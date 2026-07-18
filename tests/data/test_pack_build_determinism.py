#!/usr/bin/env python3
"""Phase 24D - determinism and the three-checksum contract.

Three checksums answer three different questions and must not be conflated:

    sourceChecksum  - did the authored source change?   (CSI bytes)
    contentChecksum - did the card payload change?      (emitted cards only)
    generated-file  - are the artifacts on disk intact? (actual output bytes)

The CSI is what makes sourceChecksum reproducible. An .xlsx is a ZIP carrying
per-entry timestamps, so re-saving an unchanged workbook changes its bytes;
hashing those bytes would make the checksum a property of the editor rather
than of the content.
"""

import hashlib
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, os.path.join(ROOT, "tests", "support"))
sys.path.insert(0, os.path.join(ROOT, "tests", "fixtures", "packs"))

import packlib                                                     # noqa: E402
from datajs import emit                                            # noqa: E402
from contentpack.pipeline import Options, build, verify_deterministic  # noqa: E402


def artifacts_of(result):
    return {a.name: a.data for a in result.artifacts}


def sha_file(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def main():
    fails = []

    def check(name, cond):
        if not cond:
            fails.append(name)

    tmp = tempfile.mkdtemp(prefix="cpdet_")

    def fresh(name):
        dest = os.path.join(tmp, name)
        if os.path.isdir(dest):
            shutil.rmtree(dest)
        return packlib.copy_csv_source("demo", dest)

    def run(src, out, **kw):
        return build(Options(pack_id="demo", source=src, output=out, **kw), ROOT)

    try:
        src = fresh("base")
        out_a = os.path.join(tmp, "out_a")
        created = run(src, out_a, init_ledger=True)
        check("baseline build succeeds", not created.findings.has_fatal())
        check("ledger creation is recorded",
              "LEDGER_INITIALIZED" in {f.code for f in created.findings})

        # The --init-ledger run legitimately records an extra INFO finding, so
        # the steady-state baseline is the first rebuild after creation.
        first = run(src, out_a)
        check("steady-state build succeeds", not first.findings.has_fatal())

        # --- repeated build is byte-identical -----------------------------
        second = run(src, out_a)
        check("repeated build is byte-identical",
              artifacts_of(first) == artifacts_of(second))

        on_disk_1 = {name: sha_file(os.path.join(out_a, name))
                     for name in sorted(os.listdir(out_a))}
        run(src, out_a)
        on_disk_2 = {name: sha_file(os.path.join(out_a, name))
                     for name in sorted(os.listdir(out_a))}
        check("files on disk are byte-identical after a rebuild",
              on_disk_1 == on_disk_2)

        # --- the tool's own determinism check agrees ----------------------
        verified, differences = verify_deterministic(
            Options(pack_id="demo", source=src, output=out_a), ROOT)
        check("verify-deterministic finds no differences", differences == [])
        check("verify-deterministic run is clean",
              not verified.findings.has_fatal())

        # --- a different output root changes nothing ----------------------
        deep = os.path.join(tmp, "a different root", "nested", "out")
        other = run(src, deep)
        check("output path does not affect artifacts",
              artifacts_of(first) == artifacts_of(other))
        check("output path does not affect checksums",
              (first.source_checksum, first.content_checksum) ==
              (other.source_checksum, other.content_checksum))

        # --- checksum format ----------------------------------------------
        check("sourceChecksum is a prefixed sha256",
              first.source_checksum.startswith("sha256:")
              and len(first.source_checksum) == 71)
        check("contentChecksum is a prefixed sha256",
              first.content_checksum.startswith("sha256:")
              and len(first.content_checksum) == 71)
        check("generated file checksums are prefixed sha256",
              all(entry["sha256"].startswith("sha256:")
                  for entry in first.inventory))
        check("inventory covers exactly the three data artifacts",
              sorted(e["path"] for e in first.inventory) ==
              ["demo-cards.js", "demo-content-pack.js", "demo-source.csi.json"])

        # --- xlsx byte churn must not move sourceChecksum -----------------
        xlsx_a = packlib.make_xlsx(src, os.path.join(tmp, "a.xlsx"))
        ledger = os.path.join(src, "demo-id-ledger.json")
        res_a = run(xlsx_a, os.path.join(tmp, "out_x1"), ledger_path=ledger)
        xlsx_b = packlib.make_xlsx(src, os.path.join(tmp, "b.xlsx"))
        res_b = run(xlsx_b, os.path.join(tmp, "out_x2"), ledger_path=ledger)
        check("independently written workbooks share a sourceChecksum",
              res_a.source_checksum == res_b.source_checksum)
        check("workbook sourceChecksum equals the csv sourceChecksum",
              res_a.source_checksum == first.source_checksum)
        check("workbook artifacts equal the csv artifacts",
              {a.name: a.data for a in res_a.data_artifacts} ==
              {a.name: a.data for a in first.data_artifacts})

        # --- generatedAt never reaches content identity -------------------
        stamped = run(src, os.path.join(tmp, "out_stamp"),
                      generated_at="2026-07-18T00:00:00Z")
        check("generatedAt does not change sourceChecksum",
              stamped.source_checksum == first.source_checksum)
        check("generatedAt does not change contentChecksum",
              stamped.content_checksum == first.content_checksum)
        stamped_data = {a.name: a.data for a in stamped.data_artifacts}
        check("generatedAt does not change any runtime artifact",
              stamped_data == {a.name: a.data for a in first.data_artifacts})
        check("generatedAt is recorded in the QA report",
              stamped.report["build"].get("generatedAt") == "2026-07-18T00:00:00Z")
        check("generatedAt is absent by default",
              "generatedAt" not in first.report["build"])

        cards_js = stamped_data["demo-cards.js"].decode("utf-8")
        pack_js = stamped_data["demo-content-pack.js"].decode("utf-8")
        check("no timestamp leaks into the cards artifact",
              "2026-07-18" not in cards_js)
        check("no timestamp leaks into the manifest artifact",
              "2026-07-18" not in pack_js)
        check("no generatedAt key in the emitted manifest",
              "generatedAt" not in pack_js)
        check("build tool version is absent from runtime artifacts",
              "buildToolVersion" not in pack_js and "buildToolVersion" not in cards_js)

        # --- what each checksum actually responds to ----------------------
        src_content = fresh("content_changed")
        shutil.copyfile(ledger, os.path.join(src_content, "demo-id-ledger.json"))
        packlib.edit_cards(src_content, lambda rows: rows[:1] + [
            rows[1][:3] + ["a different meaning"] + rows[1][4:]] + rows[2:])
        changed = run(src_content, os.path.join(tmp, "out_c"))
        check("content edit moves contentChecksum",
              changed.content_checksum != first.content_checksum)
        check("content edit moves sourceChecksum",
              changed.source_checksum != first.source_checksum)

        src_manifest = fresh("manifest_changed")
        shutil.copyfile(ledger, os.path.join(src_manifest, "demo-id-ledger.json"))
        packlib.edit_manifest(src_manifest, {"description": "reworded blurb"})
        manifest_only = run(src_manifest, os.path.join(tmp, "out_m"))
        check("manifest-only edit moves sourceChecksum",
              manifest_only.source_checksum != first.source_checksum)
        check("manifest-only edit leaves contentChecksum alone",
              manifest_only.content_checksum == first.content_checksum)

        # --- ledger serialization is deterministic ------------------------
        check("ledger bytes are stable across rebuilds",
              first.ledger.to_json_bytes() == second.ledger.to_json_bytes())
        check("ledger is LF-terminated utf-8",
              first.ledger.to_json_bytes().endswith(b"\n")
              and b"\r\n" not in first.ledger.to_json_bytes())

        # --- artifacts are LF-only and BOM-free ---------------------------
        for name, data in artifacts_of(first).items():
            if b"\r\n" in data:
                fails.append("artifact %s contains CRLF" % name)
            if data.startswith(b"\xef\xbb\xbf"):
                fails.append("artifact %s starts with a BOM" % name)

        # --- QA report determinism ----------------------------------------
        check("qa report json is byte-stable",
              artifacts_of(first)["qa-report.json"] ==
              artifacts_of(second)["qa-report.json"])
        check("qa report markdown is byte-stable",
              artifacts_of(first)["qa-report.md"] ==
              artifacts_of(second)["qa-report.md"])
        check("registry handoff is byte-stable",
              artifacts_of(first)["registry-handoff.json"] ==
              artifacts_of(second)["registry-handoff.json"])

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    return emit("pack_build_determinism", fails)


if __name__ == "__main__":
    sys.exit(main())
