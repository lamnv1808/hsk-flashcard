"""Source contract: manifest allowlist, card roles, reserved id ranges.

Everything here is reconciled against the strict ContentPack v1 contract in
hsk_flashcard_app/core/content/content-pack.js (Phase 24C). Where that file
defines a vocabulary, this module mirrors it rather than inventing one.

Two identity concepts are deliberately kept apart:

    sourceKey  - author-owned, build-time only, ASCII, never reaches the
                 runtime card. It is what the ID ledger is keyed on.
    stableId   - the ContentPack v1 role naming the runtime integer id field.
                 Always emitted as "id". Tool-computed, never author-supplied.

Keeping them separate is what lets authors use readable string identity while
the runtime id stays an integer, which the Supabase schema requires
(card_progress.card_id is int, and sync_push_progress casts to int).
"""

import re

# --- mirrored from content-pack.js -----------------------------------------

# content-pack.js:60-65
KNOWN_ROLES = (
    "stableId", "deck", "primaryPrompt", "pronunciation", "definition",
    "exampleText", "examplePronunciation", "exampleTranslation",
    "tags", "searchFields", "audioTextFields", "sourceRowRef",
)

# content-pack.js:69
IDENT_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,30}[a-z0-9])?$")

# content-pack.js:66-68 (conservative BCP-47 structural check, not a registry)
BCP47_RE = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z]{4})?(-(?:[A-Za-z]{2}|[0-9]{3}))?$")

# content-pack.js:53-54
STATUS_VALUES = ("draft", "beta", "launch")
READINESS_VALUES = ("internal", "beta", "launch")
COURSE_TYPES = ("exam", "general")
DIRECTIONS = ("ltr", "rtl")

SCRIPT_RE = re.compile(r"^[A-Z][a-z]{3}$")          # ISO-15924 shape
MAX_CARD_ID = 2147483647                             # int4 ceiling

# --- source-side card roles -------------------------------------------------

# Author-owned build-time identity. Not a ContentPack role.
SOURCE_KEY_COLUMN = "sourceKey"
SOURCE_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")

# Required content roles in every generic source.
REQUIRED_CARD_ROLES = ("deck", "primaryPrompt", "definition")

# Optional content roles a pack may declare by simply including the column.
# Note: pronunciation is NOT required. IELTS and TOEIC vocabulary have no
# pinyin, and assuming otherwise would hardcode HSK semantics.
OPTIONAL_CARD_ROLES = (
    "pronunciation", "exampleText", "examplePronunciation",
    "exampleTranslation", "tags",
)

# Source-only authoring column. Deliberately NOT a ContentPack role and never
# emitted into the runtime payload: declaring it as a fieldRole would fail
# strict v1 validation, which rejects unknown roles. Coverage is reported in QA.
NOTES_COLUMN = "notes"

ALL_CARD_COLUMNS = (
    (SOURCE_KEY_COLUMN,) + REQUIRED_CARD_ROLES + OPTIONAL_CARD_ROLES + (NOTES_COLUMN,)
)

# Emitted card field name for the integer id (the stableId role target).
ID_FIELD = "id"

# Canonical emitted-field order. Roles use their own names, so the payload is
# product-neutral: no "word"/"pinyin"/"meaning" HSK vocabulary leaks in.
EMITTED_FIELD_ORDER = (ID_FIELD,) + REQUIRED_CARD_ROLES + OPTIONAL_CARD_ROLES

# --- levels sheet -----------------------------------------------------------

LEVELS_REQUIRED_COLUMNS = ("deckId", "order")
LEVELS_OPTIONAL_COLUMNS = ("title", "description")
ALL_LEVEL_COLUMNS = LEVELS_REQUIRED_COLUMNS + LEVELS_OPTIONAL_COLUMNS

# --- manifest ---------------------------------------------------------------

# Author-supplied manifest keys, dotted. Strict allowlist: an unknown key is
# FATAL. ContentPack v1 itself silently ignores unknown top-level keys, so the
# pipeline is the only layer that can catch a typo like "licence" or "packid".
MANIFEST_REQUIRED = (
    "schemaVersion",
    "packId",
    "version",
    "status",
    "title",
    "courseId",
    "courseType",
    "languageProfile.target",
    "idRange.min",
    "idRange.max",
)

MANIFEST_OPTIONAL = (
    "shortTitle",
    "description",
    "publisher",
    "source.origin",
    "source.license",
    "source.url",
    "source.acquiredAt",
    "minAppVersion",
    "languageProfile.translation",
    "languageProfile.instruction",
    "languageProfile.script",
    "languageProfile.direction",
    "audio.locale",
    "audio.fallbackLocales",
    "audio.readFields",
    "framework.name",
    "framework.version",
    "launch.visible",
    "launch.readiness",
    "search.fields",
    "search.normalizer",
    "presentation.frontRoles",
    "presentation.backRoles",
    "capabilities",
    "categories",
)

MANIFEST_ALLOWED = frozenset(MANIFEST_REQUIRED) | frozenset(MANIFEST_OPTIONAL)

# Computed by the tool. Author-supplied values for these are FATAL: allowing
# them would let a hand-written number silently disagree with reality.
MANIFEST_TOOL_COMPUTED = frozenset((
    "sourceChecksum",
    "contentChecksum",
    "generatedAt",
    "cardCount",
    "fieldRoles",
    "levels",
))

# Manifest keys whose value is a comma-separated list in the flat source form.
MANIFEST_LIST_KEYS = frozenset((
    "audio.fallbackLocales",
    "audio.readFields",
    "search.fields",
    "presentation.frontRoles",
    "presentation.backRoles",
    "capabilities",
    "categories",
))

MANIFEST_BOOL_KEYS = frozenset(("launch.visible",))
MANIFEST_INT_KEYS = frozenset(("schemaVersion", "idRange.min", "idRange.max"))

# Manifest keys whose values must be drawn from KNOWN_ROLES.
MANIFEST_ROLE_LIST_KEYS = frozenset((
    "audio.readFields",
    "search.fields",
    "presentation.frontRoles",
    "presentation.backRoles",
))

# Provenance required before a pack may claim launch readiness. Never invented,
# never defaulted: unknown provenance stays unknown and blocks certification.
PROVENANCE_REQUIRED = (
    "publisher",
    "source.origin",
    "source.license",
    "source.url",
)

# --- reserved integer id ranges (frozen, Phase 24C) -------------------------

RESERVED_RANGES = {
    "hsk":   (1, 999999),
    "ielts": (1000000, 1999999),
    "toeic": (2000000, 2999999),
    "jlpt":  (3000000, 3999999),
    "topik": (4000000, 4999999),
}

# --- limits -----------------------------------------------------------------

MAX_SOURCE_ROWS = 20000
MAX_SOURCE_BYTES = 64 * 1024 * 1024
MAX_FIELD_CHARS = 4000


def reserved_range_for(course_id):
    """Reserved block for a known course, or None if unregistered."""
    return RESERVED_RANGES.get(course_id)


def split_list(raw):
    """Parse a comma-separated manifest list value deterministically."""
    if raw is None:
        return []
    return [part.strip() for part in raw.split(",") if part.strip()]


def parse_bool(raw):
    """Strict boolean parsing. Returns None when unrecognized."""
    if raw is None:
        return None
    low = raw.strip().lower()
    if low in ("true", "yes", "1"):
        return True
    if low in ("false", "no", "0"):
        return False
    return None


def parse_int(raw):
    """Strict integer parsing. Returns None when unrecognized."""
    if raw is None:
        return None
    text = raw.strip()
    if not re.match(r"^-?[0-9]+$", text):
        return None
    try:
        return int(text)
    except ValueError:
        return None
