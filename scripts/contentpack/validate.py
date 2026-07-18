"""Fail-closed validation and normalization of a parsed source.

Produces a ValidatedPack: a normalized manifest plus normalized cards, with all
findings accumulated rather than aborting on the first problem.

Structural validation is NOT linguistic, pedagogical, translation or licensing
certification. Content-quality acceptance is owned by Phase 24F.
"""

from . import schema
from .findings import Findings
from .normalize import (
    NormalizationError, normalize_display, normalize_compare, normalize_near,
    is_injection_prefixed,
)


class ValidatedPack(object):
    def __init__(self):
        self.manifest = {}        # flat dotted key -> parsed value
        self.cards = []           # list of dicts: {"sourceKey":..., role: text}
        self.levels = []          # list of dicts: {"deckId","order","title"?,...}
        self.levels_authored = False  # True only when a levels sheet/file exists
        self.declared_roles = []  # optional roles declared by column presence
        self.field_roles = {}     # role -> emitted card field name


# --------------------------------------------------------------------------
# manifest
# --------------------------------------------------------------------------

def validate_manifest(raw_manifest, findings):
    """Strict allowlist parse of the key/value manifest."""
    parsed = {}
    seen = {}

    for key, value, source, coord in raw_manifest:
        if key in schema.MANIFEST_TOOL_COMPUTED:
            findings.fatal(
                "TOOL_COMPUTED_FIELD",
                "'%s' is computed by the build tool and must not be authored"
                % key, source=source, coord=coord)
            continue
        if key not in schema.MANIFEST_ALLOWED:
            findings.fatal(
                "UNKNOWN_MANIFEST_KEY",
                "unknown manifest key '%s'" % key, source=source, coord=coord)
            continue
        if key in seen:
            findings.fatal(
                "DUPLICATE_MANIFEST_KEY",
                "manifest key '%s' appears more than once" % key,
                source=source, coord=coord)
            continue
        seen[key] = coord

        try:
            text = normalize_display(value) if value is not None else ""
        except NormalizationError as exc:
            findings.fatal(exc.code, "manifest '%s': %s" % (key, exc.message),
                           source=source, coord=coord)
            continue
        parsed[key] = text

    for key in schema.MANIFEST_REQUIRED:
        if key not in parsed or parsed[key] == "":
            findings.fatal(
                "MISSING_MANIFEST_KEY",
                "required manifest key '%s' is missing or empty" % key)

    if findings.has_fatal():
        return {}

    out = {}

    # typed conversions -----------------------------------------------------
    for key, raw in sorted(parsed.items()):
        if key in schema.MANIFEST_INT_KEYS:
            num = schema.parse_int(raw)
            if num is None:
                findings.fatal("INVALID_MANIFEST_VALUE",
                               "'%s' must be an integer" % key,
                               coord=seen.get(key))
                continue
            out[key] = num
        elif key in schema.MANIFEST_BOOL_KEYS:
            flag = schema.parse_bool(raw)
            if flag is None:
                findings.fatal("INVALID_MANIFEST_VALUE",
                               "'%s' must be true or false" % key,
                               coord=seen.get(key))
                continue
            out[key] = flag
        elif key in schema.MANIFEST_LIST_KEYS:
            out[key] = schema.split_list(raw)
        else:
            out[key] = raw

    if findings.has_fatal():
        return {}

    _validate_manifest_values(out, seen, findings)
    _validate_provenance(out, findings)
    return out


def _validate_manifest_values(m, coords, findings):
    def bad(key, message):
        findings.fatal("INVALID_MANIFEST_VALUE",
                       "'%s' %s" % (key, message), coord=coords.get(key))

    if m.get("schemaVersion") != 1:
        bad("schemaVersion", "must be exactly the integer 1")

    for key in ("packId", "courseId"):
        if not schema.IDENT_RE.match(m.get(key, "")):
            bad(key, "must match %s" % schema.IDENT_RE.pattern)

    if m.get("status") not in schema.STATUS_VALUES:
        bad("status", "must be one of: %s" % ", ".join(schema.STATUS_VALUES))
    if m.get("courseType") not in schema.COURSE_TYPES:
        bad("courseType", "must be one of: %s" % ", ".join(schema.COURSE_TYPES))

    for key in ("languageProfile.target", "languageProfile.translation",
                "languageProfile.instruction", "audio.locale"):
        val = m.get(key)
        if val and not schema.BCP47_RE.match(val):
            bad(key, "must be a BCP-47 tag of the form lang[-Script][-REGION]")

    for tag in m.get("audio.fallbackLocales", []):
        if not schema.BCP47_RE.match(tag):
            bad("audio.fallbackLocales", "contains an invalid BCP-47 tag")
            break

    script = m.get("languageProfile.script")
    if script and not schema.SCRIPT_RE.match(script):
        bad("languageProfile.script", "must be an ISO-15924 code such as Hans")

    direction = m.get("languageProfile.direction")
    if direction and direction not in schema.DIRECTIONS:
        bad("languageProfile.direction", "must be ltr or rtl")

    readiness = m.get("launch.readiness")
    if readiness and readiness not in schema.READINESS_VALUES:
        bad("launch.readiness",
            "must be one of: %s" % ", ".join(schema.READINESS_VALUES))

    for key in sorted(schema.MANIFEST_ROLE_LIST_KEYS):
        for role in m.get(key, []):
            if role not in schema.KNOWN_ROLES:
                bad(key, "references unknown role '%s'" % role)
                break

    # id range ---------------------------------------------------------------
    lo, hi = m.get("idRange.min"), m.get("idRange.max")
    if isinstance(lo, int) and isinstance(hi, int):
        if lo <= 0:
            bad("idRange.min", "must be greater than 0")
        if hi < lo:
            bad("idRange.max", "must be >= idRange.min")
        if hi > schema.MAX_CARD_ID:
            bad("idRange.max",
                "must stay within the database integer ceiling (%d)"
                % schema.MAX_CARD_ID)

        reserved = schema.reserved_range_for(m.get("courseId", ""))
        if reserved is None:
            findings.info(
                "UNREGISTERED_COURSE_RANGE",
                "courseId '%s' has no frozen reserved range; cross-pack "
                "overlap enforcement is owned by the Phase 24E registry"
                % m.get("courseId", ""))
        elif (lo, hi) != reserved:
            findings.fatal(
                "RESERVED_RANGE_MISMATCH",
                "courseId '%s' is reserved %d-%d; the manifest declares %d-%d"
                % (m.get("courseId", ""), reserved[0], reserved[1], lo, hi),
                coord=coords.get("idRange.min"))


def _validate_provenance(m, findings):
    """Provenance is required only for launch certification, never invented."""
    claims_launch = (
        m.get("status") == "launch"
        or m.get("launch.readiness") == "launch"
        or m.get("launch.visible") is True
    )
    if not claims_launch:
        return
    missing = [k for k in schema.PROVENANCE_REQUIRED if not m.get(k)]
    if missing:
        findings.launch_blocking(
            "PROVENANCE_INCOMPLETE",
            "pack claims launch readiness but provenance is incomplete; "
            "missing: %s. These values are never inferred or defaulted."
            % ", ".join(missing))


# --------------------------------------------------------------------------
# levels
# --------------------------------------------------------------------------

def validate_levels(raw_levels, findings):
    if raw_levels is None:
        return None

    out = []
    seen = {}
    for row in raw_levels:
        coord = row.coord("deckId")
        try:
            deck_id = normalize_display(row.values.get("deckId"))
        except NormalizationError as exc:
            findings.fatal(exc.code, "levels deckId: %s" % exc.message,
                           source=row.source, coord=coord)
            continue
        if not deck_id:
            findings.fatal("EMPTY_REQUIRED_FIELD",
                           "levels row has an empty deckId",
                           source=row.source, coord=coord)
            continue
        if deck_id in seen:
            findings.fatal("DUPLICATE_DECK",
                           "deck '%s' is declared more than once" % deck_id,
                           source=row.source, coord=coord)
            continue
        seen[deck_id] = True

        order = schema.parse_int(row.values.get("order"))
        if order is None:
            findings.fatal("INVALID_LEVEL_ORDER",
                           "deck '%s' has a non-integer order" % deck_id,
                           source=row.source, coord=row.coord("order"))
            continue

        entry = {"deckId": deck_id, "order": order}
        for optional in schema.LEVELS_OPTIONAL_COLUMNS:
            raw = row.values.get(optional)
            if raw is None:
                continue
            try:
                text = normalize_display(raw)
            except NormalizationError as exc:
                findings.fatal(exc.code, "levels %s: %s" % (optional, exc.message),
                               source=row.source, coord=row.coord(optional))
                continue
            if text:
                entry[optional] = text
        out.append(entry)

    out.sort(key=lambda e: (e["order"], e["deckId"]))
    return out


# --------------------------------------------------------------------------
# cards
# --------------------------------------------------------------------------

def validate_cards(raw_cards, manifest, levels, findings):
    """Normalize and validate card rows. Returns cards sorted by sourceKey."""
    if not raw_cards:
        findings.fatal("NO_CARDS", "the source contains no card rows")
        return [], []

    present_columns = set()
    for row in raw_cards:
        present_columns.update(row.values.keys())
    declared_roles = [r for r in schema.OPTIONAL_CARD_ROLES if r in present_columns]

    cards = []
    by_key = {}
    by_key_ci = {}

    for row in raw_cards:
        card = _validate_card_row(row, declared_roles, findings)
        if card is None:
            continue

        key = card["sourceKey"]
        if key in by_key:
            findings.fatal(
                "DUPLICATE_SOURCE_KEY",
                "sourceKey '%s' is used more than once (first at %s)"
                % (key, by_key[key]),
                source=row.source, coord=row.coord(schema.SOURCE_KEY_COLUMN),
                source_key=key)
            continue
        folded = key.lower()
        if folded in by_key_ci and by_key_ci[folded] != key:
            findings.fatal(
                "SOURCE_KEY_CASE_COLLISION",
                "sourceKey '%s' collides case-insensitively with '%s'; "
                "keys are case-sensitive, so this ambiguity is rejected"
                % (key, by_key_ci[folded]),
                source=row.source, coord=row.coord(schema.SOURCE_KEY_COLUMN),
                source_key=key)
            continue

        by_key[key] = "%s!%s" % (row.source, row.coord(schema.SOURCE_KEY_COLUMN))
        by_key_ci[folded] = key
        cards.append(card)

    if levels is not None:
        declared_decks = {entry["deckId"] for entry in levels}
        for card in cards:
            if card["deck"] not in declared_decks:
                findings.fatal(
                    "UNDECLARED_DECK",
                    "card references deck '%s', which is not declared in the "
                    "levels sheet" % card["deck"],
                    source_key=card["sourceKey"])

    for role in declared_roles:
        if not any(card.get(role) for card in cards):
            findings.warning(
                "EMPTY_DECLARED_ROLE",
                "column '%s' is present but every value is empty" % role)

    _detect_duplicates(cards, findings)

    # Deterministic, machine-independent order: sourceKey ascending. This is
    # what makes id allocation independent of row order.
    cards.sort(key=lambda c: c["sourceKey"])
    return cards, declared_roles


def _validate_card_row(row, declared_roles, findings):
    coord = row.coord(schema.SOURCE_KEY_COLUMN)
    raw_key = row.values.get(schema.SOURCE_KEY_COLUMN)

    try:
        key = normalize_display(raw_key)
    except NormalizationError as exc:
        findings.fatal(exc.code, "sourceKey: %s" % exc.message,
                       source=row.source, coord=coord)
        return None

    if not key:
        findings.fatal("EMPTY_REQUIRED_FIELD", "sourceKey is empty",
                       source=row.source, coord=coord)
        return None
    if not schema.SOURCE_KEY_RE.match(key):
        findings.fatal(
            "INVALID_SOURCE_KEY",
            "sourceKey must match %s (ASCII only, so normalization is "
            "unambiguous)" % schema.SOURCE_KEY_RE.pattern,
            source=row.source, coord=coord, source_key=key)
        return None

    card = {"sourceKey": key}
    ok = True

    for role in schema.REQUIRED_CARD_ROLES:
        rc = row.coord(role)
        try:
            text = normalize_display(row.values.get(role))
        except NormalizationError as exc:
            findings.fatal(exc.code, "%s: %s" % (role, exc.message),
                           source=row.source, coord=rc, source_key=key)
            ok = False
            continue
        if not text:
            findings.fatal("EMPTY_REQUIRED_FIELD",
                           "required field '%s' is empty" % role,
                           source=row.source, coord=rc, source_key=key)
            ok = False
            continue
        card[role] = text

    for role in declared_roles:
        rc = row.coord(role)
        try:
            text = normalize_display(row.values.get(role))
        except NormalizationError as exc:
            findings.fatal(exc.code, "%s: %s" % (role, exc.message),
                           source=row.source, coord=rc, source_key=key)
            ok = False
            continue
        card[role] = text

    notes = row.values.get(schema.NOTES_COLUMN)
    if notes is not None and notes.strip():
        card["_hasNotes"] = True

    if not ok:
        return None

    for role, text in sorted(card.items()):
        if role.startswith("_") or role == "sourceKey" or not text:
            continue
        if len(text) > schema.MAX_FIELD_CHARS:
            findings.warning(
                "FIELD_TOO_LONG",
                "field '%s' is %d characters, above the %d character soft cap"
                % (role, len(text), schema.MAX_FIELD_CHARS),
                source=row.source, coord=row.coord(role), source_key=key)
        if is_injection_prefixed(text):
            findings.info(
                "INJECTION_PREFIX",
                "field '%s' begins with a spreadsheet-sensitive character; "
                "content is preserved unmodified because it may be legitimate"
                % role,
                source=row.source, coord=row.coord(role), source_key=key)

    return card


def _detect_duplicates(cards, findings):
    """Duplicate taxonomy. Legitimate polysemy must never be fatal."""
    identical = {}
    same_deck = {}
    near = {}
    across = {}
    examples = {}

    for card in cards:
        content = tuple(
            (role, card.get(role, ""))
            for role in sorted(k for k in card if not k.startswith("_") and k != "sourceKey")
        )
        identical.setdefault(content, []).append(card["sourceKey"])

        prompt = normalize_compare(card.get("primaryPrompt", ""))
        definition = normalize_compare(card.get("definition", ""))
        deck = card.get("deck", "")

        same_deck.setdefault((deck, prompt), []).append((card["sourceKey"], definition))
        near.setdefault((deck, normalize_near(card.get("primaryPrompt", ""))), []).append(
            card["sourceKey"])
        across.setdefault(prompt, set()).add(deck)

        example = normalize_compare(card.get("exampleText", ""))
        if example:
            examples.setdefault(example, []).append(card["sourceKey"])

    for keys in sorted(identical.values()):
        if len(keys) > 1:
            findings.fatal(
                "IDENTICAL_ROWS",
                "these sourceKeys carry byte-identical content with no "
                "distinguishing field: %s" % ", ".join(sorted(keys)),
                source_key=sorted(keys)[0])

    for (deck, prompt), entries in sorted(same_deck.items()):
        if len(entries) < 2 or not prompt:
            continue
        keys = sorted(k for k, _ in entries)
        definitions = {d for _, d in entries}
        if len(definitions) == 1:
            findings.launch_blocking(
                "DUPLICATE_PROMPT_SAME_DEFINITION",
                "deck '%s' repeats the same prompt with the same definition "
                "(%s)" % (deck, ", ".join(keys)),
                source_key=keys[0])
        else:
            findings.warning(
                "DUPLICATE_PROMPT_DIFFERENT_DEFINITION",
                "deck '%s' repeats a prompt with different definitions; this "
                "is legitimate polysemy and does not block the build (%s)"
                % (deck, ", ".join(keys)),
                source_key=keys[0])

    for (deck, prompt), keys in sorted(near.items()):
        if len(keys) < 2 or not prompt:
            continue
        exact = same_deck.get((deck, prompt))
        if exact is not None and len(exact) == len(keys):
            continue  # already reported as an exact duplicate above
        findings.warning(
            "NEAR_DUPLICATE_PROMPT",
            "deck '%s' contains prompts that differ only by case, spacing or "
            "trailing punctuation (%s)" % (deck, ", ".join(sorted(keys))),
            source_key=sorted(keys)[0])

    for prompt, decks in sorted(across.items()):
        if len(decks) > 1 and prompt:
            findings.info(
                "PROMPT_ACROSS_DECKS",
                "a prompt appears in %d decks (%s); cross-deck overlap is "
                "expected and is not a defect" % (len(decks), ", ".join(sorted(decks))))

    for example, keys in sorted(examples.items()):
        if len(keys) > 1:
            findings.info(
                "REPEATED_EXAMPLE",
                "an example sentence is shared by %d cards" % len(keys),
                source_key=sorted(keys)[0])


# --------------------------------------------------------------------------

def build_field_roles(declared_roles):
    """Generated fieldRoles map. Never author-supplied."""
    roles = {"stableId": schema.ID_FIELD}
    for role in schema.REQUIRED_CARD_ROLES:
        roles[role] = role
    for role in declared_roles:
        roles[role] = role
    return roles


def validate_source(raw_source, findings):
    """Full validation pass. Returns a ValidatedPack (possibly incomplete)."""
    pack = ValidatedPack()
    pack.manifest = validate_manifest(raw_source.manifest, findings)
    if findings.has_fatal():
        return pack

    levels = validate_levels(raw_source.levels, findings)
    pack.levels_authored = levels is not None
    pack.levels = levels if levels is not None else []

    cards, declared = validate_cards(raw_source.cards, pack.manifest, levels, findings)
    pack.cards = cards
    pack.declared_roles = declared
    pack.field_roles = build_field_roles(declared)

    if levels is None and cards:
        decks = sorted({c["deck"] for c in cards})
        pack.levels = [{"deckId": d, "order": i + 1} for i, d in enumerate(decks)]

    return pack
