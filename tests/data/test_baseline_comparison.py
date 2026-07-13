"""Production-baseline comparison (Phase 1). Pure Python; no browser, no network.

Compares current generated card data against `production-baseline-v1`:
- HSK1-HSK4 must be byte-for-byte stable (all fields).
- No existing card may be renumbered (baseline (level,word) -> id must hold).
- HSK5/HSK6 deterministic IDs must remain stable.
- No duplicate ids.
Emits a compact machine-readable stability report to tests/reports/ (best-effort).
"""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "support"))
from datajs import load_cards, load_cards_from_git, emit, CARD_FIELDS, BASELINE_TAG, repo_root

def main():
    fails = []
    try:
        cur = load_cards()
        base = load_cards_from_git(BASELINE_TAG)
    except Exception as e:
        return emit("baseline_comparison", [f"load failed: {e}"])

    cur_by_id = {c["id"]: c for c in cur}
    cur_by_lw = {(c["level"], c["word"]): c["id"] for c in cur}

    renumbered = 0
    missing = 0
    hsk14_content_diffs = 0
    hsk56_id_diffs = 0

    for b in base:
        bid = b["id"]; lvl = b["level"]; key = (lvl, b["word"])
        # identity stability: baseline (level,word) must still map to the SAME id
        if cur_by_lw.get(key) != bid:
            renumbered += 1
            continue
        cur_c = cur_by_id.get(bid)
        if cur_c is None:
            missing += 1
            continue
        if lvl in ("HSK1", "HSK2", "HSK3", "HSK4"):
            if any(str(cur_c.get(f)) != str(b.get(f)) for f in CARD_FIELDS):
                hsk14_content_diffs += 1
        else:  # HSK5/HSK6: id must be stable (content identity via level+word already checked)
            if cur_c.get("level") != lvl or cur_c.get("word") != b.get("word"):
                hsk56_id_diffs += 1

    ids = [c["id"] for c in cur]
    dupes = len(ids) - len(set(ids))

    if renumbered: fails.append(f"{renumbered} baseline card(s) renumbered ((level,word)->id changed)")
    if missing: fails.append(f"{missing} baseline id(s) missing from current data")
    if hsk14_content_diffs: fails.append(f"{hsk14_content_diffs} HSK1-4 card(s) content changed vs baseline")
    if hsk56_id_diffs: fails.append(f"{hsk56_id_diffs} HSK5/6 id(s) no longer map to the same card")
    if dupes: fails.append(f"{dupes} duplicate id(s)")

    report = {
        "suite": "baseline_comparison", "baseline": BASELINE_TAG,
        "baselineCards": len(base), "currentCards": len(cur),
        "renumbered": renumbered, "missing": missing,
        "hsk14ContentDiffs": hsk14_content_diffs, "hsk56IdDiffs": hsk56_id_diffs,
        "duplicateIds": dupes,
        "hsk14ByteStable": hsk14_content_diffs == 0 and renumbered == 0 and missing == 0,
    }
    try:
        rd = os.path.join(repo_root(), "tests", "reports"); os.makedirs(rd, exist_ok=True)
        with open(os.path.join(rd, "stability.json"), "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return emit("baseline_comparison", fails, report)

if __name__ == "__main__":
    sys.exit(main())
