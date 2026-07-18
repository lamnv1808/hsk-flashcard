#!/usr/bin/env python3
"""Phase 24D - stable identity: sourceKey, the committed ledger, allocation.

The property under test is the one the whole phase exists to protect: a card's
integer id is the join key for local and cloud SRS progress, so it must survive
reordering, text edits and deck moves, and must never be silently reallocated.

The legacy HSK importer fails exactly here: an unparseable prior output makes it
renumber every card from 1 and exit 0 (scripts/import_hsk_excel.py:64-71). The
ledger tests below assert the inverted behavior.
"""

import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, os.path.join(ROOT, "tests", "support"))
sys.path.insert(0, os.path.join(ROOT, "tests", "fixtures", "packs"))

import packlib                                    # noqa: E402
from datajs import emit                           # noqa: E402
from contentpack.pipeline import Options, build   # noqa: E402


def codes(result):
    return {f.code for f in result.findings}


def ids_of(result):
    """sourceKey -> cardId, taken from the ledger the build resolved."""
    return {k: v["cardId"] for k, v in result.ledger.entries.items()
            if v["state"] == "active"}


def main():
    fails = []

    def check(name, cond):
        if not cond:
            fails.append(name)

    tmp = tempfile.mkdtemp(prefix="cpident_")

    def fresh(name):
        dest = os.path.join(tmp, name)
        if os.path.isdir(dest):
            shutil.rmtree(dest)
        return packlib.copy_csv_source("demo", dest)

    def run(src, out, **kw):
        return build(Options(pack_id="demo", source=src, output=out, **kw), ROOT)

    try:
        # --- initial allocation -------------------------------------------
        src = fresh("base")
        out = os.path.join(tmp, "out")
        first = run(src, out, init_ledger=True)
        check("initial build succeeds", not first.findings.has_fatal())
        base_ids = ids_of(first)
        check("all seven ids allocated", len(base_ids) == 7)
        check("ids are integers",
              all(isinstance(v, int) for v in base_ids.values()))
        check("ids inside declared range",
              all(1000 <= v <= 1999 for v in base_ids.values()))
        check("allocation is monotonic from range start",
              sorted(base_ids.values()) == list(range(1000, 1007)))
        check("allocation follows sourceKey order",
              base_ids["d-001"] < base_ids["d-007"])

        # --- rebuild is stable --------------------------------------------
        second = run(src, out)
        check("rebuild reuses every id", ids_of(second) == base_ids)
        check("rebuild allocates nothing new", second.stats["allocated"] == 0)

        # --- row reorder does not move ids --------------------------------
        src_rev = fresh("reordered")
        shutil.copyfile(os.path.join(src, "demo-id-ledger.json"),
                        os.path.join(src_rev, "demo-id-ledger.json"))
        packlib.edit_cards(src_rev,
                           lambda rows: [rows[0]] + list(reversed(rows[1:])))
        reordered = run(src_rev, os.path.join(tmp, "out_rev"))
        check("row reorder keeps every id", ids_of(reordered) == base_ids)
        check("row reorder keeps contentChecksum",
              reordered.content_checksum == first.content_checksum)

        # --- editing learner text does not move ids -----------------------
        src_edit = fresh("edited")
        shutil.copyfile(os.path.join(src, "demo-id-ledger.json"),
                        os.path.join(src_edit, "demo-id-ledger.json"))
        packlib.edit_cards(src_edit, lambda rows: rows[:1] + [
            rows[1][:3] + ["completely rewritten meaning"] + rows[1][4:]
        ] + rows[2:])
        edited = run(src_edit, os.path.join(tmp, "out_edit"))
        check("text edit keeps every id", ids_of(edited) == base_ids)
        check("text edit changes contentChecksum",
              edited.content_checksum != first.content_checksum)

        # --- moving a card between decks does not move ids ----------------
        src_move = fresh("moved")
        shutil.copyfile(os.path.join(src, "demo-id-ledger.json"),
                        os.path.join(src_move, "demo-id-ledger.json"))
        packlib.edit_cards(src_move, lambda rows: rows[:1] + [
            [rows[1][0], "L2"] + rows[1][2:]] + rows[2:])
        moved = run(src_move, os.path.join(tmp, "out_move"))
        check("deck move keeps every id", ids_of(moved) == base_ids)

        # --- a new card gets the next free id -----------------------------
        src_new = fresh("added")
        shutil.copyfile(os.path.join(src, "demo-id-ledger.json"),
                        os.path.join(src_new, "demo-id-ledger.json"))
        packlib.edit_cards(src_new, lambda rows: rows + [
            ["d-008", "L1", "new", "brand new card", "", "", "", "", ""]])
        added = run(src_new, os.path.join(tmp, "out_new"))
        added_ids = ids_of(added)
        check("existing ids untouched when adding",
              all(added_ids[k] == v for k, v in base_ids.items()))
        check("new card gets high-water + 1", added_ids["d-008"] == 1007)

        # --- removal requires an explicit flag ----------------------------
        src_del = fresh("deleted")
        shutil.copyfile(os.path.join(src, "demo-id-ledger.json"),
                        os.path.join(src_del, "demo-id-ledger.json"))
        packlib.edit_cards(src_del, lambda rows: rows[:-1])
        blocked = run(src_del, os.path.join(tmp, "out_del"))
        check("removal without --allow-removals is fatal",
              "CARDS_REMOVED" in codes(blocked))

        removed = run(src_del, os.path.join(tmp, "out_del"), allow_removals=True)
        check("removal with the flag succeeds", not removed.findings.has_fatal())
        check("removed key is retired, not deleted",
              removed.ledger.entries["d-007"]["state"] == "retired")
        check("retired id is retained in the ledger",
              removed.ledger.entries["d-007"]["cardId"] == base_ids["d-007"])
        check("retired card is absent from the payload",
              "d-007" not in ids_of(removed))

        # --- retired ids are never recycled -------------------------------
        src_recycle = fresh("recycle")
        shutil.copyfile(os.path.join(src_del, "demo-id-ledger.json"),
                        os.path.join(src_recycle, "demo-id-ledger.json"))
        packlib.edit_cards(src_recycle, lambda rows: rows[:-1] + [
            ["d-009", "L1", "later", "added after a retirement",
             "", "", "", "", ""]])
        recycled = run(src_recycle, os.path.join(tmp, "out_recycle"),
                       allow_removals=True)
        check("a retired id is never handed to a new card",
              ids_of(recycled)["d-009"] != base_ids["d-007"])
        check("new id continues above the high-water mark",
              ids_of(recycled)["d-009"] == 1007)

        # --- a retired key that returns keeps its original id -------------
        src_restore = fresh("restore")
        shutil.copyfile(os.path.join(src_recycle, "demo-id-ledger.json"),
                        os.path.join(src_restore, "demo-id-ledger.json"))
        restored = run(src_restore, os.path.join(tmp, "out_restore"),
                       allow_removals=True)
        check("restored card recovers its original id",
              ids_of(restored)["d-007"] == base_ids["d-007"])

        # --- duplicate and colliding source keys --------------------------
        src_dupkey = fresh("dupkey")
        packlib.edit_cards(src_dupkey, lambda rows: rows + [
            ["d-001", "L1", "dup", "duplicate key", "", "", "", "", ""]])
        check("duplicate sourceKey is fatal",
              "DUPLICATE_SOURCE_KEY" in codes(
                  run(src_dupkey, os.path.join(tmp, "o1"), init_ledger=True)))

        src_case = fresh("casekey")
        packlib.edit_cards(src_case, lambda rows: rows + [
            ["D-001", "L1", "dup", "case collision", "", "", "", "", ""]])
        check("case-insensitive sourceKey collision is fatal",
              "SOURCE_KEY_CASE_COLLISION" in codes(
                  run(src_case, os.path.join(tmp, "o2"), init_ledger=True)))

        src_badkey = fresh("badkey")
        packlib.edit_cards(src_badkey, lambda rows: rows[:1] + [
            ["khoa-ạ", "L1", "x", "non-ascii key"] + rows[1][4:]] + rows[2:])
        check("non-ascii sourceKey is fatal",
              "INVALID_SOURCE_KEY" in codes(
                  run(src_badkey, os.path.join(tmp, "o3"), init_ledger=True)))

        # --- ledger failure modes all fail closed -------------------------
        src_noledger = fresh("noledger")
        check("missing ledger without --init-ledger is fatal",
              "LEDGER_MISSING" in codes(run(src_noledger, os.path.join(tmp, "o4"))))

        def with_ledger(name, mutate):
            target = fresh(name)
            path = os.path.join(target, "demo-id-ledger.json")
            shutil.copyfile(os.path.join(src, "demo-id-ledger.json"), path)
            mutate(path)
            return run(target, os.path.join(tmp, "o_" + name))

        def corrupt(path):
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("{ this is not json")
        check("corrupt ledger is fatal",
              "LEDGER_MALFORMED" in codes(with_ledger("corrupt", corrupt)))

        def truncate(path):
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("")
        check("empty ledger file is fatal",
              "LEDGER_MALFORMED" in codes(with_ledger("empty", truncate)))

        def wrong_pack(path):
            doc = json.load(open(path, encoding="utf-8"))
            doc["packId"] = "other"
            json.dump(doc, open(path, "w", encoding="utf-8"))
        check("ledger for another pack is fatal",
              "LEDGER_PACK_MISMATCH" in codes(with_ledger("wrongpack", wrong_pack)))

        def wrong_range(path):
            doc = json.load(open(path, encoding="utf-8"))
            doc["idRange"] = {"min": 1, "max": 500}
            json.dump(doc, open(path, "w", encoding="utf-8"))
        check("ledger range mismatch is fatal",
              "LEDGER_RANGE_MISMATCH" in codes(with_ledger("wrongrange", wrong_range)))

        def dup_id(path):
            doc = json.load(open(path, encoding="utf-8"))
            doc["entries"]["d-002"]["cardId"] = doc["entries"]["d-001"]["cardId"]
            json.dump(doc, open(path, "w", encoding="utf-8"))
        check("duplicate id inside the ledger is fatal",
              "LEDGER_DUPLICATE_ID" in codes(with_ledger("dupid", dup_id)))

        def out_of_range(path):
            doc = json.load(open(path, encoding="utf-8"))
            doc["entries"]["d-001"]["cardId"] = 999999
            json.dump(doc, open(path, "w", encoding="utf-8"))
        check("ledger id outside the range is fatal",
              "LEDGER_ID_OUT_OF_RANGE" in codes(
                  with_ledger("outofrange", out_of_range)))

        def non_integer(path):
            doc = json.load(open(path, encoding="utf-8"))
            doc["entries"]["d-001"]["cardId"] = "1000"
            json.dump(doc, open(path, "w", encoding="utf-8"))
        check("non-integer ledger id is fatal",
              "LEDGER_INVALID_ID" in codes(with_ledger("nonint", non_integer)))

        # --- range exhaustion ---------------------------------------------
        src_small = fresh("small")
        packlib.edit_manifest(src_small, {"idRange.min": "1000",
                                          "idRange.max": "1002"})
        check("range exhaustion is fatal",
              "RANGE_EXHAUSTED" in codes(
                  run(src_small, os.path.join(tmp, "o5"), init_ledger=True)))

        # --- frozen reserved ranges are enforced --------------------------
        src_reserved = fresh("reserved")
        packlib.edit_manifest(src_reserved, {"courseId": "ielts"})
        check("declared range must match the frozen reserved block",
              "RESERVED_RANGE_MISMATCH" in codes(
                  run(src_reserved, os.path.join(tmp, "o6"), init_ledger=True)))

        src_ok = fresh("reserved_ok")
        packlib.edit_manifest(src_ok, {"courseId": "ielts",
                                       "idRange.min": "1000000",
                                       "idRange.max": "1999999"})
        reserved_ok = run(src_ok, os.path.join(tmp, "o7"), init_ledger=True)
        check("matching reserved block is accepted",
              not reserved_ok.findings.has_fatal())
        check("ids allocate from the reserved block start",
              min(ids_of(reserved_ok).values()) == 1000000)

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    return emit("pack_build_identity", fails)


if __name__ == "__main__":
    sys.exit(main())
