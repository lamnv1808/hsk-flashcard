#!/usr/bin/env python3
"""Phase 24D - HSK conformance: the generic pipeline reproduces real identity.

This is a READ-ONLY conformance check against the hardest real dataset in the
repository. It proves the generic pipeline can reproduce all 5,002 HSK card ids,
their order and all eight fields, without writing anything to production.

Explicitly NOT modified: source_data/HSK1-HSK6.xlsx, hsk_flashcard_app/data.js,
scripts/import_hsk_excel.py, packs/hsk/hsk-content-pack.js. The HSK build path
is untouched by Phase 24D.

The temporary ledger is seeded from the committed data.js using the legacy
(level, word) anchor, hashed into an ASCII sourceKey. That bridge exists ONLY to
prove reproduction. It is NOT an accepted generic authoring identity policy:
real packs carry an author-owned sourceKey precisely because a derived anchor
breaks when a typo is fixed or a card moves between levels.
"""

import hashlib
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
from datajs import emit, load_cards, data_js_path, EXPECTED_TOTAL  # noqa: E402
from contentpack import LEDGER_VERSION            # noqa: E402
from contentpack.normalize import normalize_display  # noqa: E402
from contentpack.pipeline import Options, build   # noqa: E402

# legacy field -> generic role
ROLE_MAP = (
    ("level", "deck"),
    ("word", "primaryPrompt"),
    ("meaning", "definition"),
    ("pinyin", "pronunciation"),
    ("example", "exampleText"),
    ("examplePinyin", "examplePronunciation"),
    ("translation", "exampleTranslation"),
)

CARD_COLUMNS = ["sourceKey"] + [role for _, role in ROLE_MAP]

# U+200C ZERO WIDTH NON-JOINER. Present on exactly one shipped HSK card.
ZWNJ = "\u200c"

# The single known content defect in the shipped dataset, quantified rather
# than hidden. Owned by Phase 24F content QA; Phase 24D does not edit data.js.
KNOWN_ZWNJ_CARD_ID = 1303
KNOWN_ZWNJ_LEVEL = "HSK5"
KNOWN_ZWNJ_WORD = "成人"
KNOWN_ZWNJ_FIELDS = ("example", "examplePinyin", "translation")
# Exact occurrence count, per field. Any additional card, field or invisible
# character anywhere in the dataset must fail this suite rather than widen the
# exception silently.
KNOWN_ZWNJ_COUNTS = {"example": 2, "examplePinyin": 2, "translation": 1}
KNOWN_ZWNJ_TOTAL = 5

# Every invisible character the pipeline treats specially.
INVISIBLES = "\u200b\u200c\u200d\ufeff"


def bridge_key(card):
    """Legacy (level, word) anchor, hashed into the ASCII sourceKey charset."""
    anchor = "%s|%s" % (card["level"], card["word"])
    digest = hashlib.sha1(anchor.encode("utf-8")).hexdigest()[:16]
    return "hsk-%s" % digest


def sha256_file(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


MANIFEST_ROWS = [
    ["key", "value"],
    ["schemaVersion", "1"],
    ["packId", "hsk"],
    ["version", "1.0.0"],
    ["status", "draft"],
    ["title", "HSK conformance fixture"],
    ["courseId", "hsk"],
    ["courseType", "exam"],
    ["languageProfile.target", "zh-CN"],
    ["languageProfile.translation", "vi"],
    ["languageProfile.script", "Hans"],
    ["languageProfile.direction", "ltr"],
    ["idRange.min", "1"],
    ["idRange.max", "999999"],
]


def main():
    fails = []

    def check(name, cond):
        if not cond:
            fails.append(name)

    data_js = data_js_path()
    before_hash = sha256_file(data_js)
    workbook = os.path.join(ROOT, "source_data", "HSK1-HSK6.xlsx")
    workbook_hash = sha256_file(workbook) if os.path.isfile(workbook) else None
    importer = os.path.join(ROOT, "scripts", "import_hsk_excel.py")
    importer_hash = sha256_file(importer)

    cards = load_cards()
    check("committed data.js still holds the audited card count",
          len(cards) == EXPECTED_TOTAL)

    # --- pin the known production exception exactly ----------------------
    # Scan every card for every invisible character the pipeline treats
    # specially. The result must be EXACTLY the one documented card, the three
    # documented fields, and the documented occurrence counts. A new stray
    # character anywhere else fails here rather than being absorbed silently.
    observed = {}
    for card in cards:
        for field, value in card.items():
            if not isinstance(value, str):
                continue
            hits = sum(1 for ch in value if ch in INVISIBLES)
            if hits:
                observed[(card["id"], field)] = hits
    expected_map = {(KNOWN_ZWNJ_CARD_ID, f): n
                    for f, n in KNOWN_ZWNJ_COUNTS.items()}
    check("exactly one card in data.js carries invisible characters",
          {cid for cid, _ in observed} == {KNOWN_ZWNJ_CARD_ID})
    check("exactly the three documented fields are affected",
          {f for _, f in observed} == set(KNOWN_ZWNJ_FIELDS))
    check("the per-field invisible-character counts are exactly as documented",
          observed == expected_map)
    check("the total invisible-character count is exactly as documented",
          sum(observed.values()) == KNOWN_ZWNJ_TOTAL)
    if observed != expected_map:
        fails.append("invisible-character map changed: %s"
                     % sorted(set(observed.items()) ^ set(expected_map.items())))

    known_card = {c["id"]: c for c in cards}.get(KNOWN_ZWNJ_CARD_ID, {})
    check("the exception card is still HSK5",
          known_card.get("level") == KNOWN_ZWNJ_LEVEL)
    check("the exception card is still the documented word",
          known_card.get("word") == KNOWN_ZWNJ_WORD)
    check("only U+200C is involved, not other invisibles",
          all(ch == ZWNJ for f in KNOWN_ZWNJ_FIELDS
              for ch in known_card.get(f, "") if ch in INVISIBLES))

    tmp = tempfile.mkdtemp(prefix="cphsk_")
    try:
        src = os.path.join(tmp, "src")
        os.makedirs(src)

        # --- project data.js into a generic source ------------------------
        rows = [CARD_COLUMNS]
        entries = {}
        for card in cards:
            key = bridge_key(card)
            if key in entries:
                fails.append("legacy anchor collision for id %s" % card["id"])
                continue
            entries[key] = {"cardId": card["id"], "state": "active"}
            rows.append([key] + [card[legacy] for legacy, _ in ROLE_MAP])
        packlib.write_rows(os.path.join(src, "cards.csv"), rows)
        packlib.write_rows(os.path.join(src, "manifest.csv"), MANIFEST_ROWS)

        check("bridge produced one key per card", len(entries) == EXPECTED_TOTAL)

        # --- fail-closed policy, exercised against the REAL dataset --------
        # The shipped HSK data contains stray U+200C zero-width non-joiners on
        # card 1303 (HSK5). They are editing artifacts and carry no semantics in
        # Chinese or Vietnamese, but the policy refuses to strip them silently.
        # This is a real, pre-existing content defect, recorded for Phase 24F
        # content QA. Phase 24D does not modify data.js to "fix" it.
        raw_ledger = os.path.join(src, "hsk-id-ledger.json")
        with open(raw_ledger, "w", encoding="utf-8") as fh:
            json.dump({
                "ledgerVersion": LEDGER_VERSION,
                "packId": "hsk",
                "idRange": {"min": 1, "max": 999999},
                "entries": entries,
            }, fh, ensure_ascii=False, sort_keys=True)
        unclean = build(Options(pack_id="hsk", source=src,
                                output=os.path.join(tmp, "out_raw"),
                                ledger_path=raw_ledger), ROOT)
        unclean_codes = {f.code for f in unclean.findings}
        check("pipeline detects zero-width joiners in the real HSK data",
              "ZERO_WIDTH_JOINER" in unclean_codes)
        check("that detection is fatal, not a silent strip",
              unclean.findings.has_fatal())
        zwnj = [f for f in unclean.findings if f.code == "ZERO_WIDTH_JOINER"]
        check("exactly the three known fields are flagged", len(zwnj) == 3)
        check("all flagged fields belong to one card",
              len({f.source_key for f in zwnj}) == 1)

        # --- bridge-only cleanup, so reproduction can be proven ------------
        # Removing U+200C here is a property of THIS BRIDGE, not of the
        # pipeline. It lets the test quantify the single known difference
        # instead of hiding it.
        rows = [rows[0]] + [
            [cell.replace(ZWNJ, "") if isinstance(cell, str) else cell
             for cell in row]
            for row in rows[1:]]
        packlib.write_rows(os.path.join(src, "cards.csv"), rows)

        ledger_path = os.path.join(src, "hsk-id-ledger.json")
        with open(ledger_path, "w", encoding="utf-8") as fh:
            json.dump({
                "ledgerVersion": LEDGER_VERSION,
                "packId": "hsk",
                "idRange": {"min": 1, "max": 999999},
                "entries": entries,
            }, fh, ensure_ascii=False, sort_keys=True)

        # --- run the generic pipeline --------------------------------------
        out = os.path.join(tmp, "out")
        result = build(Options(pack_id="hsk", source=src, output=out,
                               ledger_path=ledger_path), ROOT)
        check("hsk conformance build succeeds", not result.findings.has_fatal())
        if result.findings.has_fatal():
            for finding in result.findings.of_severity("FATAL")[:5]:
                fails.append("fatal: " + finding.to_line())
            return emit("pack_build_hsk_conformance", fails)

        check("no id was newly allocated", result.stats["allocated"] == 0)
        check("every id came from the ledger",
              result.stats["reused"] == EXPECTED_TOTAL)
        check("nothing was retired", result.stats["retired"] == 0)

        # --- compare the emitted payload against data.js --------------------
        with open(os.path.join(out, "hsk-cards.js"), encoding="utf-8") as fh:
            text = fh.read()
        # Parse the assignment explicitly rather than slicing between the first
        # '[' and the last ']'. That shortcut is what the legacy importer uses
        # (scripts/import_hsk_excel.py:69) and it breaks the moment the wrapper
        # contains a bracket, which this one does: window.FLASHEDU_PACKS["hsk"].
        marker = '.cards = '
        payload = text[text.index(marker) + len(marker):].strip()
        if payload.endswith(";"):
            payload = payload[:-1]
        emitted = json.loads(payload)

        check("emitted card count matches data.js", len(emitted) == EXPECTED_TOTAL)
        check("emitted ids are exactly 1..5002",
              [c["id"] for c in emitted] == list(range(1, EXPECTED_TOTAL + 1)))
        check("emitted payload is sorted ascending by id",
              all(emitted[i]["id"] < emitted[i + 1]["id"]
                  for i in range(len(emitted) - 1)))

        by_id = {c["id"]: c for c in emitted}
        mismatched_ids = []
        mismatched_fields = []
        for card in cards:
            produced = by_id.get(card["id"])
            if produced is None:
                mismatched_ids.append(card["id"])
                continue
            for legacy, role in ROLE_MAP:
                if produced.get(role) != card[legacy]:
                    mismatched_fields.append((card["id"], legacy))
        check("every data.js id is present in the emitted payload",
              not mismatched_ids)

        # The only permitted differences are the stray zero-width joiners on the
        # one known card, and each must differ by exactly that removal.
        expected = [(KNOWN_ZWNJ_CARD_ID, f) for f in KNOWN_ZWNJ_FIELDS]
        check("the only field differences are the known zero-width artifacts",
              sorted(mismatched_fields) == sorted(expected))
        if sorted(mismatched_fields) != sorted(expected):
            fails.append("unexpected field mismatches: %s"
                         % (sorted(set(mismatched_fields) - set(expected))[:5],))

        legacy_1303 = {c["id"]: c for c in cards}[KNOWN_ZWNJ_CARD_ID]
        produced_1303 = by_id[KNOWN_ZWNJ_CARD_ID]
        # Each difference is exactly: drop the stray U+200C, then apply the
        # documented display policy. On `translation` the removal exposes a
        # trailing space, which the edge-trim rule then removes -- so the two
        # transforms compose rather than the test asserting a bare replace.
        check("each known difference is exactly U+200C removal plus edge trim",
              all(produced_1303[role]
                  == normalize_display(legacy_1303[legacy].replace(ZWNJ, ""))
                  for legacy, role in ROLE_MAP))
        check("the trailing-space case is genuinely exercised",
              legacy_1303["translation"].replace(ZWNJ, "")
              != produced_1303["exampleTranslation"])
        check("5001 of 5002 cards reproduce byte-for-byte on every field",
              len({cid for cid, _ in mismatched_fields}) == 1)

        check("ids never left the reserved HSK range",
              all(1 <= c["id"] <= 999999 for c in emitted))
        check("decks reproduce the six HSK levels",
              sorted({c["deck"] for c in emitted}) ==
              ["HSK1", "HSK2", "HSK3", "HSK4", "HSK5", "HSK6"])

        counts = {}
        for card in emitted:
            counts[card["deck"]] = counts.get(card["deck"], 0) + 1
        check("per-level counts match the audited baseline",
              counts == {"HSK1": 149, "HSK2": 150, "HSK3": 295,
                         "HSK4": 600, "HSK5": 1295, "HSK6": 2513})

        # --- rebuild remains stable at real scale ----------------------------
        again = build(Options(pack_id="hsk", source=src,
                              output=os.path.join(tmp, "out2"),
                              ledger_path=ledger_path), ROOT)
        check("hsk rebuild is byte-identical",
              {a.name: a.data for a in again.data_artifacts} ==
              {a.name: a.data for a in result.data_artifacts})
        check("hsk contentChecksum is stable",
              again.content_checksum == result.content_checksum)

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # --- production must be untouched ---------------------------------------
    check("data.js is byte-unchanged", sha256_file(data_js) == before_hash)
    check("the HSK workbook is byte-unchanged",
          workbook_hash is None or sha256_file(workbook) == workbook_hash)
    check("the legacy HSK importer is byte-unchanged",
          sha256_file(importer) == importer_hash)
    check("no pack output was written into the runtime app",
          not os.path.exists(os.path.join(ROOT, "hsk_flashcard_app", "packs", "hsk",
                                          "hsk-cards.js")))

    return emit("pack_build_hsk_conformance", fails,
                {"cards": EXPECTED_TOTAL, "dataJsSha256": before_hash})


if __name__ == "__main__":
    sys.exit(main())
