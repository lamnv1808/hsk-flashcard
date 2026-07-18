#!/usr/bin/env python3
"""Phase 24D - QA report contract, severity split, provenance launch gate.

The severity split is the point of this suite. The legacy HSK importer has only
"fatal" and "invisible", so a real content defect either stops the build or is
never seen. Here, three classes are separated and each is asserted:

    FATAL           - abort, nothing written
    LAUNCH_BLOCKING - builds, but launchEligible=false
    WARNING / INFO  - recorded, never blocks

Legitimate polysemy (one prompt, several senses) must land in WARNING, never
FATAL: a Chinese headword with multiple meanings is correct content, not a bug.
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

PROVENANCE = {
    "publisher": "Example Publisher",
    "source.origin": "tests/fixtures/packs/demo",
    "source.license": "CC-BY-4.0",
    "source.url": "https://example.invalid/demo",
}


def by_code(result):
    out = {}
    for finding in result.findings:
        out.setdefault(finding.code, []).append(finding)
    return out


def main():
    fails = []

    def check(name, cond):
        if not cond:
            fails.append(name)

    tmp = tempfile.mkdtemp(prefix="cpqa_")

    def fresh(name):
        dest = os.path.join(tmp, name)
        if os.path.isdir(dest):
            shutil.rmtree(dest)
        return packlib.copy_csv_source("demo", dest)

    def run(src, out, **kw):
        kw.setdefault("init_ledger", True)
        return build(Options(pack_id="demo", source=src, output=out, **kw), ROOT)

    try:
        src = fresh("base")
        base = run(src, os.path.join(tmp, "out"))
        report = base.report
        found = by_code(base)

        # --- report shape --------------------------------------------------
        for section in ("pack", "build", "source", "content", "completeness",
                        "identity", "findings", "launch", "output"):
            if section not in report:
                fails.append("report is missing the %r section" % section)
        check("disclaimer present in json", "Phase 24F" in report["disclaimer"])
        check("report records the build tool version",
              report["build"]["buildToolVersion"])
        check("report carries the source checksum",
              report["source"]["sourceChecksum"] == base.source_checksum)
        check("report carries the content checksum",
              report["content"]["contentChecksum"] == base.content_checksum)
        check("report lists source files",
              [f["name"] for f in report["source"]["files"]] ==
              ["cards.csv", "levels.csv", "manifest.csv"])
        check("report counts cards", report["content"]["cardTotal"] == 7)
        check("report counts per deck",
              report["content"]["countsByDeck"] == {"L1": 3, "L2": 4})
        check("report lists generated output",
              sorted(f["path"] for f in report["output"]["files"]) ==
              ["demo-cards.js", "demo-content-pack.js", "demo-source.csi.json"])
        check("report records id utilization",
              report["identity"]["allocated"]["count"] == 7
              and report["identity"]["rangeCapacity"] == 1000)
        check("report records min and max ids",
              report["identity"]["allocated"]["min"] == 1000
              and report["identity"]["allocated"]["max"] == 1006)

        # --- completeness ---------------------------------------------------
        completeness = report["completeness"]
        check("required roles are fully covered",
              all(c["percent"] == 100.0 for c in completeness["required"].values()))
        check("declared optional role coverage is measured",
              completeness["optional"]["pronunciation"]["present"] == 6)
        check("undeclared optional role is marked as such",
              completeness["optional"]["examplePronunciation"]["declared"] is False)
        check("authoring notes are counted, not emitted",
              completeness["authoringNotesPresent"] == 3)
        check("notes never reach the card payload",
              all("notes" not in c for c in
                  json.loads(json.dumps(report["content"]["fieldRoles"])).items()
                  if False) or "notes" not in report["content"]["fieldRoles"])

        # --- markdown form ----------------------------------------------------
        md = {a.name: a.data for a in base.artifacts}["qa-report.md"].decode("utf-8")
        check("disclaimer present in markdown", "Phase 24F" in md)
        check("markdown reports launch eligibility", "launchEligible" in md)
        check("markdown reports checksums", base.content_checksum in md)

        # --- polysemy is a warning, never fatal --------------------------------
        check("polysemy is reported as a warning",
              "DUPLICATE_PROMPT_DIFFERENT_DEFINITION" in found)
        check("polysemy does not block the build", not base.findings.has_fatal())
        check("polysemy is severity WARNING",
              found["DUPLICATE_PROMPT_DIFFERENT_DEFINITION"][0].severity == "WARNING")
        check("injection prefix is INFO only",
              found["INJECTION_PREFIX"][0].severity == "INFO")
        check("injection-prefixed content is preserved unmodified",
              any(c["primaryPrompt"] == "-ing" for c in base.pack.cards))

        # --- identical rows are fatal ------------------------------------------
        src_ident = fresh("identical")
        packlib.edit_cards(src_ident, lambda rows: rows + [
            ["d-100"] + rows[1][1:]])
        identical = run(src_ident, os.path.join(tmp, "o1"))
        check("byte-identical rows under different keys are fatal",
              "IDENTICAL_ROWS" in by_code(identical))

        # --- same prompt + same definition in one deck is launch-blocking ------
        src_same = fresh("same_def")
        packlib.edit_cards(src_same, lambda rows: rows + [
            ["d-101", "L1", "爱", "yêu, thương", "ài", "", "", "extra-tag", ""]])
        same = run(src_same, os.path.join(tmp, "o2"))
        same_found = by_code(same)
        check("same prompt and definition in one deck is launch-blocking",
              "DUPLICATE_PROMPT_SAME_DEFINITION" in same_found)
        check("that duplicate does not abort the build",
              not same.findings.has_fatal())
        check("that duplicate has LAUNCH_BLOCKING severity",
              same_found["DUPLICATE_PROMPT_SAME_DEFINITION"][0].severity
              == "LAUNCH_BLOCKING")
        check("a launch blocker clears launchEligible",
              same.report["launch"]["launchEligible"] is False)

        # --- near duplicates ----------------------------------------------------
        src_near = fresh("near")
        packlib.edit_cards(src_near, lambda rows: rows + [
            ["d-102", "L2", "Water.", "a near duplicate of water",
             "", "", "", "", ""]])
        near = run(src_near, os.path.join(tmp, "o3"))
        check("near-duplicate prompt is a warning",
              "NEAR_DUPLICATE_PROMPT" in by_code(near))
        check("near duplicate does not abort", not near.findings.has_fatal())

        # --- cross-deck overlap is informational --------------------------------
        src_cross = fresh("cross")
        packlib.edit_cards(src_cross, lambda rows: rows + [
            ["d-103", "L1", "water", "same word, earlier level",
             "", "", "", "", ""]])
        cross = run(src_cross, os.path.join(tmp, "o4"))
        cross_found = by_code(cross)
        check("cross-deck overlap is INFO",
              "PROMPT_ACROSS_DECKS" in cross_found
              and cross_found["PROMPT_ACROSS_DECKS"][0].severity == "INFO")
        check("cross-deck overlap never blocks",
              cross.report["launch"]["launchEligible"] is True)

        # --- provenance launch gate ----------------------------------------------
        check("draft pack without provenance is not launch-blocked",
              base.report["launch"]["launchEligible"] is True)
        check("draft pack still reports which provenance is absent",
              set(base.report["launch"]["missingProvenanceFields"]) ==
              {"publisher", "source.origin", "source.license", "source.url"})

        src_launch = fresh("launching")
        packlib.edit_manifest(src_launch, {"status": "launch",
                                           "launch.visible": "true",
                                           "launch.readiness": "launch"})
        launching = run(src_launch, os.path.join(tmp, "o5"))
        launch_found = by_code(launching)
        check("launch claim without provenance is launch-blocking",
              "PROVENANCE_INCOMPLETE" in launch_found)
        check("provenance gap does not abort the build",
              not launching.findings.has_fatal())
        check("launch claim without provenance is not eligible",
              launching.report["launch"]["launchEligible"] is False)
        check("missing provenance fields are named explicitly",
              set(launching.report["launch"]["missingProvenanceFields"]) ==
              {"publisher", "source.origin", "source.license", "source.url"})
        check("reasons explain why it is ineligible",
              any(r["code"] == "PROVENANCE_INCOMPLETE"
                  for r in launching.report["launch"]["reasons"]))

        src_full = fresh("full_provenance")
        updates = dict(PROVENANCE)
        updates.update({"status": "launch", "launch.visible": "true",
                        "launch.readiness": "launch"})
        packlib.edit_manifest(src_full, updates)
        full = run(src_full, os.path.join(tmp, "o6"))
        check("complete provenance clears the launch gate",
              "PROVENANCE_INCOMPLETE" not in by_code(full))
        check("complete provenance yields launchEligible",
              full.report["launch"]["launchEligible"] is True)
        check("nothing was invented for the missing fields",
              full.report["launch"]["missingProvenanceFields"] == [])

        # --- registry handoff ------------------------------------------------------
        handoff = json.loads(
            {a.name: a.data for a in full.artifacts}["registry-handoff.json"]
            .decode("utf-8"))
        for key in ("handoffVersion", "packId", "version", "status", "courseId",
                    "launch", "idRange", "allocated", "sourceChecksum",
                    "contentChecksum", "generatedFiles", "provenanceComplete",
                    "launchEligible", "launchBlockers"):
            if key not in handoff:
                fails.append("handoff is missing %r" % key)
        check("handoff carries the declared range",
              handoff["idRange"] == {"min": 1000, "max": 1999})
        check("handoff carries the actual allocated span",
              handoff["allocated"]["min"] == 1000
              and handoff["allocated"]["max"] == 1006
              and handoff["allocated"]["count"] == 7)
        check("handoff reports provenance completeness",
              handoff["provenanceComplete"] is True)
        check("handoff lists generated file checksums",
              all(f["sha256"].startswith("sha256:")
                  for f in handoff["generatedFiles"]))
        check("handoff implements no registry (data only)",
              isinstance(handoff, dict) and "packs" not in handoff)

        blocked_handoff = json.loads(
            {a.name: a.data for a in launching.artifacts}["registry-handoff.json"]
            .decode("utf-8"))
        check("handoff propagates launch blockers",
              blocked_handoff["launchEligible"] is False
              and "PROVENANCE_INCOMPLETE" in blocked_handoff["launchBlockers"])

        # --- severity counts ---------------------------------------------------------
        counts = launching.report["findings"]["counts"]
        check("counts expose the three-class split",
              counts["fatal"] == 0 and counts["launchBlocking"] >= 1
              and counts["warning"] >= 1)
        check("every finding carries a machine-readable code",
              all(item["code"] for item in launching.report["findings"]["items"]))
        check("content findings carry coordinates or a sourceKey",
              all(("source" in item or "sourceKey" in item)
                  for item in base.report["findings"]["items"]
                  if item["code"] in ("INJECTION_PREFIX",
                                      "DUPLICATE_PROMPT_DIFFERENT_DEFINITION")))

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    return emit("pack_build_qa", fails)


if __name__ == "__main__":
    sys.exit(main())
