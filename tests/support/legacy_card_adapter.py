"""PROTOTYPE LegacyCardAdapter (Phase 1 characterization ONLY).

This is a test-only reference implementation of the future adapter described in
docs/architecture/DATA_CONTRACTS.md §8-9. It is NOT imported by any runtime code and
does NOT change production behavior. Its sole purpose is to prove that a canonical
Card representation can round-trip back to the exact legacy shape, byte-for-byte, for
every compatibility-critical field — including when optional canonical metadata is
present.

Legacy card shape (frozen contract):
  {id, level, word, pinyin, meaning, example, examplePinyin, translation}
"""

LEGACY_FIELDS = ["id", "level", "word", "pinyin", "meaning", "example", "examplePinyin", "translation"]

def _level_order(level):
    n = "".join(ch for ch in str(level) if ch.isdigit())
    return int(n) if n else 0

def to_canonical(legacy, pack_id="hsk", audio_lang="zh-CN"):
    """Legacy dict -> canonical dict. Optional metadata (packId, levelOrder, audio,
    tags, extra) is additive and must never leak back into the legacy shape."""
    return {
        "id": legacy["id"],
        "packId": pack_id,                                  # additive
        "level": legacy["level"],
        "levelOrder": _level_order(legacy["level"]),        # additive
        "prompt": {"text": legacy["word"], "lang": "zh"},
        "reading": {"text": legacy["pinyin"], "system": "pinyin"},
        "meaning": {"text": legacy["meaning"], "lang": "vi"},
        "example": {
            "text": legacy["example"], "lang": "zh",
            "reading": {"text": legacy["examplePinyin"], "system": "pinyin"},
            "translation": {"text": legacy["translation"], "lang": "vi"},
        },
        "audio": {"lang": audio_lang},                      # additive
        "tags": [],                                          # additive
        "extra": {},                                         # additive
    }

def to_legacy(canonical):
    """Canonical dict -> legacy dict, reconstructing EXACTLY the frozen legacy shape
    (same keys, same order, same values). Additive canonical metadata is dropped."""
    ex = canonical.get("example") or {}
    return {
        "id": canonical["id"],
        "level": canonical["level"],
        "word": canonical["prompt"]["text"],
        "pinyin": canonical["reading"]["text"],
        "meaning": canonical["meaning"]["text"],
        "example": ex.get("text", ""),
        "examplePinyin": (ex.get("reading") or {}).get("text", ""),
        "translation": (ex.get("translation") or {}).get("text", ""),
    }

def round_trip(legacy):
    return to_legacy(to_canonical(legacy))
