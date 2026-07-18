"""Unicode policy: display-affecting vs comparison-only transforms.

Display-affecting transforms alter stored, learner-visible text. They run once,
at read time, and are the ONLY transforms that change what a learner sees:

    1. line endings CRLF / CR -> LF
    2. strip U+200B (ZWSP) and U+FEFF (ZWNBSP/BOM) unconditionally
    3. NFC normalization  (never NFKC)
    4. trim leading/trailing spreadsheet whitespace, including U+00A0 and U+3000

Comparison-only transforms NEVER alter stored text. They exist solely for
duplicate and near-duplicate detection.

Deliberate non-transforms, each of which would destroy real content:
    - NFKC is never applied: it folds full-width CJK punctuation, ligatures and
      IPA modifier letters that are meaningful learner content.
    - Chinese characters, Vietnamese diacritics, pinyin tone marks, IPA, kana,
      kanji, Hangul and full-width punctuation are preserved exactly.
    - U+200C (ZWNJ) and U+200D (ZWJ) are NOT stripped: they are meaningful in
      several scripts. Their presence is fatal with a coordinate rather than
      silently removed, so a human decides.
    - Malformed Unicode and lone surrogates are fatal. Never U+FFFD.

Every non-ASCII code point in this module is written as an explicit \\uXXXX
escape so the policy stays reviewable in a diff.
"""

import re
import unicodedata

# U+200B zero-width space, U+FEFF zero-width no-break space / BOM.
# Neither carries script semantics in learner text, so both are stripped.
ZERO_WIDTH_STRIPPED = "\u200b\ufeff"

# U+200C zero-width non-joiner, U+200D zero-width joiner.
# Script-semantic. Never silently removed; presence is fatal.
ZERO_WIDTH_JOINERS = "\u200c\u200d"

# Whitespace a spreadsheet realistically produces at cell edges.
TRIM_CHARS = (
    " \t\r\n\v\f"
    "\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007"
    "\u2008\u2009\u200a\u202f\u205f\u3000"
)

_WS_RUN = re.compile(r"\s+", re.UNICODE)

# C0 and C1 control characters. After line-ending normalization a card cell
# must contain no control characters at all.
_CONTROL = re.compile(r"[\x00-\x08\x0a-\x1f\x7f-\x9f]")


class NormalizationError(Exception):
    """Raised for input that must fail closed rather than be cleaned."""

    def __init__(self, code, message):
        Exception.__init__(self, message)
        self.code = code
        self.message = message


def has_lone_surrogate(text):
    """True if the string contains an unpaired surrogate code point.

    Python strings can carry lone surrogates (e.g. via surrogateescape or a
    malformed source). They cannot be encoded to UTF-8 and must be rejected
    rather than replaced with U+FFFD.
    """
    for ch in text:
        if 0xD800 <= ord(ch) <= 0xDFFF:
            return True
    return False


def normalize_display(text, allow_newlines=False):
    """Apply the display-affecting policy. Raises NormalizationError.

    This is the only function that changes stored learner-visible text.
    """
    if text is None:
        return ""
    if not isinstance(text, str):
        raise NormalizationError("UNSUPPORTED_CELL_TYPE",
                                 "expected text, got %s" % type(text).__name__)

    if has_lone_surrogate(text):
        raise NormalizationError("MALFORMED_UNICODE",
                                 "contains an unpaired surrogate code point")

    # 1. line endings
    out = text.replace("\r\n", "\n").replace("\r", "\n")

    # 2. unconditional zero-width strip
    for ch in ZERO_WIDTH_STRIPPED:
        out = out.replace(ch, "")

    # Script-semantic joiners fail closed rather than being removed.
    for ch in ZERO_WIDTH_JOINERS:
        if ch in out:
            raise NormalizationError(
                "ZERO_WIDTH_JOINER",
                "contains U+%04X (zero-width joiner/non-joiner); it is not "
                "silently removed because it may carry script semantics"
                % ord(ch))

    # 3. NFC (never NFKC)
    out = unicodedata.normalize("NFC", out)

    # 4. trim edges
    out = out.strip(TRIM_CHARS)

    # Remaining control characters are rejected, not stripped.
    probe = out.replace("\n", "") if allow_newlines else out
    found = _CONTROL.search(probe)
    if found:
        raise NormalizationError(
            "CONTROL_CHARACTER",
            "contains control character U+%04X" % ord(found.group(0)))

    return out


def normalize_compare(text):
    """Comparison-only form. Never stored, never emitted.

    NFC + internal whitespace collapse + casefold. Used exclusively for
    duplicate and near-duplicate detection.
    """
    if not text:
        return ""
    out = unicodedata.normalize("NFC", text)
    out = _WS_RUN.sub(" ", out).strip()
    return out.casefold()


# ASCII and full-width sentence punctuation, for near-duplicate detection only.
_TRAILING_PUNCT = re.compile(
    "[\\s\\.,!\\?;:\u3002\uff0c\uff01\uff1f\uff1b\uff1a]+$")


def normalize_near(text):
    """Looser comparison form for near-duplicate detection only."""
    return _TRAILING_PUNCT.sub("", normalize_compare(text))


def is_injection_prefixed(text):
    """True if text begins with a spreadsheet-sensitive character.

    Reported as INFO only. Learner content legitimately begins with '-' (the
    suffix "-ing"), '+' or '@'. Rejecting or rewriting it would corrupt real
    content, so this never blocks and never modifies. Generated artifacts are
    JS/JSON data and Markdown, never spreadsheet output, so the actual
    injection vector does not exist in this pipeline's outputs.
    """
    if not text:
        return False
    return text[0] in "=+-@\t\r"
