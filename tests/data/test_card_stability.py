"""Card data stability contract (Phase 1). Pure Python; no browser, no network.

Freezes the current production vocabulary contract: exact counts, unique/contiguous
IDs, deterministic ordering, non-empty Chinese, valid levels, parseable data.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "support"))
from datajs import load_cards, by_level, emit, EXPECTED_COUNTS, EXPECTED_TOTAL, CARD_FIELDS

def main():
    fails = []
    try:
        cards = load_cards()
    except Exception as e:
        return emit("card_stability", [f"data.js did not parse: {e}"])

    # total + per-level counts (exact, from Phase 0 audit)
    if len(cards) != EXPECTED_TOTAL:
        fails.append(f"total cards {len(cards)} != {EXPECTED_TOTAL}")
    counts = by_level(cards)
    for lvl, exp in EXPECTED_COUNTS.items():
        if counts.get(lvl) != exp:
            fails.append(f"{lvl} count {counts.get(lvl)} != {exp}")
    extra_levels = set(counts) - set(EXPECTED_COUNTS)
    if extra_levels:
        fails.append(f"unexpected levels present: {sorted(extra_levels)}")

    ids = [c["id"] for c in cards]
    # every id present, unique, integer
    if any(not isinstance(i, int) for i in ids):
        fails.append("some card id is not an integer")
    if len(set(ids)) != len(ids):
        fails.append(f"duplicate ids: {len(ids) - len(set(ids))} dup(s)")
    # contiguous 1..N (deterministic + stable id space)
    if sorted(ids) != list(range(1, len(ids) + 1)):
        fails.append("ids are not contiguous 1..N")
    # ordering is deterministic: array is sorted ascending by id
    if ids != sorted(ids):
        fails.append("card array is not ordered by ascending id (non-deterministic order)")

    # schema: exact field set, every field present, non-empty Chinese word, valid level
    empty_word = 0
    bad_level = 0
    bad_schema = 0
    for c in cards:
        if list(c.keys()) != CARD_FIELDS:
            bad_schema += 1
        if not str(c.get("word", "")).strip():
            empty_word += 1
        if c.get("level") not in EXPECTED_COUNTS:
            bad_level += 1
    if bad_schema:
        fails.append(f"{bad_schema} card(s) with unexpected key set/order")
    if empty_word:
        fails.append(f"{empty_word} card(s) with empty Chinese word")
    if bad_level:
        fails.append(f"{bad_level} card(s) with invalid HSK level")

    return emit("card_stability", fails, {
        "total": len(cards), "byLevel": counts,
        "idsUnique": len(set(ids)) == len(ids),
        "idsContiguous": sorted(ids) == list(range(1, len(ids) + 1)),
        "idRange": [min(ids), max(ids)] if ids else None,
    })

if __name__ == "__main__":
    sys.exit(main())
