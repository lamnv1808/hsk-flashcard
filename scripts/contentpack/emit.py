"""Canonical Source Intermediate, checksums, generated artifacts, atomic publish.

Two ideas carry most of the weight here.

1. The CSI. Both frontends project into one Canonical Source Intermediate, and
   the CSI bytes -- never the raw .xlsx bytes -- are the sourceChecksum basis.
   An .xlsx is a ZIP with per-entry timestamps, so re-saving an unchanged
   workbook changes its bytes; hashing that would make the checksum a property
   of the editor rather than of the content. Hashing the CSI instead makes an
   Excel source and an equivalent CSV source produce byte-identical checksums.

2. The wrapper is tool-owned. No spreadsheet value ever reaches a code position
   -- not an identifier, not a property expression, not a namespace. Author data
   lands only inside JSON value positions, and the JSON is additionally hardened
   against the three sequences that are valid JSON but break a classic <script>
   context: "</script", U+2028 and U+2029.
"""

import hashlib
import json
import os
import shutil

from . import CSI_VERSION, BUILD_TOOL_VERSION
from . import schema


# --------------------------------------------------------------------------
# deterministic serialization
# --------------------------------------------------------------------------

def canonical_json_bytes(obj):
    """The one canonical JSON form used for every checksum basis."""
    text = json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))
    return (text + "\n").encode("utf-8")


def sha256_of(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


def build_csi(pack):
    """Canonical Source Intermediate.

    Deliberately excludes: generated ids, generatedAt, build-tool version,
    filesystem paths, timestamps and any machine-specific value. What remains
    is exactly the authored content, so the checksum answers "did the source
    change?" and nothing else.
    """
    cards = []
    for card in pack.cards:
        record = {"sourceKey": card["sourceKey"]}
        for role in schema.REQUIRED_CARD_ROLES:
            record[role] = card.get(role, "")
        for role in pack.declared_roles:
            record[role] = card.get(role, "")
        cards.append(record)
    cards.sort(key=lambda c: c["sourceKey"])

    doc = {
        "csiVersion": CSI_VERSION,
        "manifest": dict(pack.manifest),
        "cards": cards,
        "levels": pack.levels if pack.levels_authored else None,
    }
    return canonical_json_bytes(doc)


def build_content_bytes(emitted_cards):
    """contentChecksum basis: the emitted card payload only, no manifest."""
    return canonical_json_bytes(emitted_cards)


# --------------------------------------------------------------------------
# emitted card payload
# --------------------------------------------------------------------------

def build_emitted_cards(pack, assigned):
    """Runtime card objects, sorted ascending by cardId."""
    out = []
    for card in pack.cards:
        record = {schema.ID_FIELD: assigned[card["sourceKey"]]}
        for role in schema.REQUIRED_CARD_ROLES:
            record[role] = card.get(role, "")
        for role in pack.declared_roles:
            record[role] = card.get(role, "")
        out.append(record)
    out.sort(key=lambda c: c[schema.ID_FIELD])
    return out


def unflatten(manifest):
    """Flat dotted keys -> the nested object ContentPack v1 expects."""
    nested = {}
    for key in sorted(manifest):
        parts = key.split(".")
        cursor = nested
        for part in parts[:-1]:
            cursor = cursor.setdefault(part, {})
        cursor[parts[-1]] = manifest[key]
    return nested


def build_emitted_manifest(pack, stats, source_checksum, content_checksum):
    """Author manifest plus the tool-computed fields.

    generatedAt is deliberately absent: it would make otherwise identical
    builds differ, and it belongs in QA/handoff metadata, not in a runtime
    asset that participates in content identity.
    """
    nested = unflatten(pack.manifest)
    nested["fieldRoles"] = dict(pack.field_roles)
    nested["levels"] = [dict(entry) for entry in pack.levels]
    nested["cardCount"] = stats["count"]
    nested["sourceChecksum"] = source_checksum
    nested["contentChecksum"] = content_checksum
    return nested


# --------------------------------------------------------------------------
# generated JavaScript (data only, trusted wrapper)
# --------------------------------------------------------------------------

def js_json(obj):
    """JSON hardened for embedding inside a classic <script> element."""
    text = json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))
    # "</script" (and any "</") would terminate the element early.
    text = text.replace("</", "<\\/")
    # Valid JSON, but raw line terminators in JavaScript source.
    text = text.replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    return text


_HEADER = (
    "// Generated by scripts/build_content_pack.py -- DO NOT EDIT MANUALLY.\n"
    "// pack: %s  version: %s\n"
    "// %s: %s\n"
)


def _assert_safe_pack_id(pack_id):
    """Re-validate at the emit boundary; never trust an upstream check alone."""
    if not schema.IDENT_RE.match(pack_id or ""):
        raise ValueError("unsafe packId at emit boundary: %r" % (pack_id,))
    return pack_id


def render_cards_js(pack_id, version, content_checksum, emitted_cards):
    pack_id = _assert_safe_pack_id(pack_id)
    body = _HEADER % (pack_id, version, "contentChecksum", content_checksum)
    body += 'window.FLASHEDU_PACKS = window.FLASHEDU_PACKS || {};\n'
    body += 'window.FLASHEDU_PACKS["%s"] = window.FLASHEDU_PACKS["%s"] || {};\n' % (
        pack_id, pack_id)
    body += 'window.FLASHEDU_PACKS["%s"].cards = %s;\n' % (
        pack_id, js_json(emitted_cards))
    return body.encode("utf-8")


def render_content_pack_js(pack_id, version, source_checksum, manifest):
    pack_id = _assert_safe_pack_id(pack_id)
    body = _HEADER % (pack_id, version, "sourceChecksum", source_checksum)
    body += 'window.FLASHEDU_PACKS = window.FLASHEDU_PACKS || {};\n'
    body += 'window.FLASHEDU_PACKS["%s"] = window.FLASHEDU_PACKS["%s"] || {};\n' % (
        pack_id, pack_id)
    body += 'window.FLASHEDU_PACKS["%s"].manifest = %s;\n' % (
        pack_id, js_json(manifest))
    return body.encode("utf-8")


# --------------------------------------------------------------------------
# path containment
# --------------------------------------------------------------------------

def is_contained(root, candidate):
    """True only if candidate resolves strictly inside root.

    Mirrors the containment rules already proven in scripts/release_check.py:
    reject URLs, protocol-relative and UNC paths, drive-absolute and absolute
    paths, and any '..' segment on either separator; then confirm with a
    realpath/commonpath check so symlinks cannot escape either.
    """
    if not candidate:
        return False
    if "://" in candidate or candidate.startswith("//"):
        return False
    if candidate.startswith("\\\\"):
        return False
    if len(candidate) >= 2 and candidate[1] == ":" and candidate[0].isalpha():
        return False
    if os.path.isabs(candidate):
        return False
    for sep in ("/", "\\"):
        if ".." in candidate.split(sep):
            return False
    real_root = os.path.realpath(root)
    real_cand = os.path.realpath(os.path.join(root, candidate))
    try:
        return os.path.commonpath([real_root, real_cand]) == real_root
    except ValueError:
        return False


def assert_output_root(repo_root, output_dir):
    """The output root must never resolve inside the runtime app directory.

    The output root is an explicit operator choice (--output), so it may live
    outside the repository -- a temp directory or a CI scratch path is
    legitimate. What must never happen is a write inside hsk_flashcard_app/,
    because that would add a runtime asset and drag the service worker,
    index.html and the release checker into a build-time-only phase.

    Traversal is prevented separately and unconditionally: every individual
    artifact name is containment-checked against this root by is_contained().
    """
    real_repo = os.path.realpath(repo_root)
    real_out = os.path.realpath(output_dir)

    app_dir = os.path.realpath(os.path.join(real_repo, "hsk_flashcard_app"))
    try:
        inside_app = os.path.commonpath([app_dir, real_out]) == app_dir
    except ValueError:
        inside_app = False
    if inside_app:
        raise ValueError(
            "Phase 24D must not write inside hsk_flashcard_app/; promotion "
            "into the runtime is owned by Phase 24E")
    return real_out


# --------------------------------------------------------------------------
# atomic publish
# --------------------------------------------------------------------------

class Artifact(object):
    __slots__ = ("name", "data")

    def __init__(self, name, data):
        self.name = name
        self.data = data


def _fsync_write(path, data):
    with open(path, "wb") as fh:
        fh.write(data)
        fh.flush()
        try:
            os.fsync(fh.fileno())
        except (OSError, AttributeError):
            # Best effort: some filesystems do not support fsync on files.
            pass


def looks_foreign(target_dir, pack_id):
    """True if target_dir holds files that this pipeline did not produce."""
    if not os.path.isdir(target_dir):
        return False
    existing = os.listdir(target_dir)
    if not existing:
        return False
    return "%s-content-pack.js" % pack_id not in existing


def publish(output_dir, pack_id, artifacts, force, findings):
    """Validate, stage completely, then promote. Never partial.

    Every artifact is written and flushed into a staging directory before any
    promotion happens, so a failure at any earlier point leaves the previous
    output byte-unchanged.
    """
    parent = os.path.dirname(os.path.abspath(output_dir))
    staging = os.path.join(parent, ".staging-%s" % pack_id)

    for art in artifacts:
        if not is_contained(output_dir, art.name):
            findings.fatal(
                "OUTPUT_PATH_ESCAPE",
                "generated artifact '%s' does not resolve inside the output "
                "directory" % art.name)
    if findings.has_fatal():
        return None

    if looks_foreign(output_dir, pack_id) and not force:
        findings.fatal(
            "FOREIGN_OUTPUT",
            "output directory contains files this pipeline did not produce; "
            "pass --force only after inspecting them")
        return None

    inventory = []
    try:
        if os.path.isdir(staging):
            shutil.rmtree(staging)
        os.makedirs(staging)

        for art in artifacts:
            _fsync_write(os.path.join(staging, art.name), art.data)

        if not os.path.isdir(output_dir):
            os.makedirs(output_dir)

        expected = {art.name for art in artifacts}
        obsolete = sorted(
            name for name in os.listdir(output_dir)
            if name not in expected and os.path.isfile(os.path.join(output_dir, name)))

        for art in artifacts:
            os.replace(os.path.join(staging, art.name),
                       os.path.join(output_dir, art.name))
            inventory.append({
                "path": art.name,
                "bytes": len(art.data),
                "sha256": sha256_of(art.data),
            })

        # Cleanup is confined to the pack's own directory and never recursive.
        for name in obsolete:
            victim = os.path.join(output_dir, name)
            if is_contained(output_dir, name) and os.path.isfile(victim):
                os.remove(victim)
                findings.info("STALE_OUTPUT_REMOVED",
                              "removed obsolete generated file '%s'" % name)
    finally:
        if os.path.isdir(staging):
            shutil.rmtree(staging, ignore_errors=True)

    return inventory


def inventory_only(artifacts):
    """Checksums without touching the filesystem (used by --check)."""
    return [
        {"path": art.name, "bytes": len(art.data), "sha256": sha256_of(art.data)}
        for art in artifacts
    ]
