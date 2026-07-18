#!/usr/bin/env python3
"""Phase 24E-A - deterministic catalog generation from Phase 24D handoffs.

The generator is the honesty boundary. An author can write
`launch.visible: true` in a spreadsheet while the build finds the pack
launch-ineligible; emitting that as visible would put uncertified content in
front of a learner. So visibility is DERIVED here, never copied, and every
derivation is asserted below.

Determinism matters for a different reason: the catalog is a committed runtime
asset, so a generator whose output depended on input order or dict iteration
would produce spurious diffs and make "is the committed catalog current?"
unanswerable.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, os.path.join(ROOT, "tests", "support"))
sys.path.insert(0, os.path.join(ROOT, "tests", "fixtures", "packs"))

import packlib                                   # noqa: E402
from datajs import emit                          # noqa: E402
from contentpack import catalog as cat           # noqa: E402

BUILD_CLI = os.path.join(ROOT, "scripts", "build_content_pack.py")
CATALOG_CLI = os.path.join(ROOT, "scripts", "build_pack_catalog.py")

EXIT_OK, EXIT_FATAL, EXIT_USAGE, EXIT_DRIFT = 0, 1, 2, 3


def run(cli, args):
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run([sys.executable, cli] + args, cwd=ROOT, env=env,
                          capture_output=True, text=True, encoding="utf-8")
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def build_pack(fixture, pack_id, tmp, overrides=None):
    """Build one fixture pack into <tmp>/build/<pack_id>."""
    src = packlib.copy_csv_source(fixture, os.path.join(tmp, "src", pack_id))
    if overrides:
        packlib.edit_manifest(src, overrides)
    out = os.path.join(tmp, "build", pack_id)
    rc, text = run(BUILD_CLI, ["--pack", pack_id, "--source", src,
                               "--output", out, "--init-ledger"])
    if rc != EXIT_OK:
        raise AssertionError("fixture build failed for %s: %s" % (pack_id, text))
    return out


def catalog_json(path):
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    marker = "window.FLASHEDU_CATALOG = "
    payload = text[text.index(marker) + len(marker):].strip()
    if payload.endswith(";"):
        payload = payload[:-1]
    return json.loads(payload)


def main():
    fails = []

    def check(name, cond):
        if not cond:
            fails.append(name)

    tmp = tempfile.mkdtemp(prefix="e24acat_")
    try:
        # demo occupies 1000-1999; synth-en occupies 5000000-5999999.
        demo = build_pack("demo", "demo", tmp)
        synth = build_pack("synth-en", "synth-en", tmp)

        # --- determinism --------------------------------------------------
        c1 = os.path.join(tmp, "c1.js")
        c2 = os.path.join(tmp, "c2.js")
        c3 = os.path.join(tmp, "c3.js")
        rc, _ = run(CATALOG_CLI, ["--source", demo, "--source", synth,
                                  "--output", c1, "--allow-hidden"])
        check("catalog generation succeeds", rc == EXIT_OK)
        run(CATALOG_CLI, ["--source", synth, "--source", demo,
                          "--output", c2, "--allow-hidden"])
        run(CATALOG_CLI, ["--source", demo, "--source", synth,
                          "--output", c3, "--allow-hidden"])
        a = open(c1, "rb").read()
        b = open(c2, "rb").read()
        c = open(c3, "rb").read()
        check("input order does not change the catalog", a == b)
        check("repeated generation is byte-identical", a == c)
        check("catalog is LF-only", b"\r\n" not in a)
        check("catalog has no BOM", not a.startswith(b"\xef\xbb\xbf"))

        doc = catalog_json(c1)
        check("schemaVersion is 1", doc["schemaVersion"] == 1)
        check("packs ordered by declared range start",
              [p["packId"] for p in doc["packs"]] == ["demo", "synth-en"])

        # --- catalog contract ---------------------------------------------
        entry = {p["packId"]: p for p in doc["packs"]}["synth-en"]
        for key in ("packId", "version", "title", "shortTitle", "courseId",
                    "courseType", "status", "launch", "idRange", "allocated",
                    "sourceChecksum", "contentChecksum", "manifestPath",
                    "cardsPath", "languageProfile", "audio", "capabilities",
                    "levels"):
            if key not in entry:
                fails.append("catalog entry is missing %r" % key)
        check("runtime manifest path is app-relative",
              entry["manifestPath"] == "packs/synth-en/synth-en-content-pack.js")
        check("runtime cards path is app-relative",
              entry["cardsPath"] == "packs/synth-en/synth-en-cards.js")
        check("allocated range is carried",
              entry["allocated"]["count"] == 6
              and entry["allocated"]["min"] == 5000000)
        check("checksums are carried verbatim",
              entry["contentChecksum"].startswith("sha256:")
              and len(entry["contentChecksum"]) == 71)
        check("levels are carried from the manifest",
              [lv["deckId"] for lv in entry["levels"]] == ["UNIT1", "UNIT2"])
        check("audio policy is carried", entry["audio"]["locale"] == "en-US")

        # Build-only artifacts must never appear anywhere in the catalog.
        raw = a.decode("utf-8")
        for banned in ("source.csi.json", "qa-report", "registry-handoff",
                       "id-ledger", "sourceKey", "provenance"):
            if banned in raw:
                fails.append("catalog leaks build-only artifact %r" % banned)

        # --- launch honesty -----------------------------------------------
        check("draft packs are emitted hidden",
              all(p["launch"]["visible"] is False for p in doc["packs"]))

        launchable = build_pack("demo", "gamma", tmp, {
            "packId": "gamma", "courseId": "gamma", "status": "launch",
            "launch.visible": "true", "launch.readiness": "launch",
            "publisher": "Example", "source.origin": "tests/fixtures",
            "source.license": "CC-BY-4.0", "source.url": "https://example.invalid",
            "idRange.min": "6000000", "idRange.max": "6999999"})
        c4 = os.path.join(tmp, "c4.js")
        rc, _ = run(CATALOG_CLI, ["--source", launchable, "--output", c4])
        check("a fully launch-eligible pack needs no --allow-hidden", rc == EXIT_OK)
        vis = catalog_json(c4)["packs"][0]
        check("launch-eligible pack is visible", vis["launch"]["visible"] is True)
        check("launch-eligible readiness carried",
              vis["launch"]["readiness"] == "launch")

        # Declared visible, but the build says not launch-eligible.
        dishonest = build_pack("demo", "delta", tmp, {
            "packId": "delta", "courseId": "delta", "status": "launch",
            "launch.visible": "true", "launch.readiness": "launch",
            "idRange.min": "7000000", "idRange.max": "7999999"})
        c5 = os.path.join(tmp, "c5.js")
        rc, text = run(CATALOG_CLI, ["--source", dishonest, "--output", c5,
                                     "--allow-hidden"])
        check("launch-ineligible pack still generates", rc == EXIT_OK)
        check("launch-ineligible pack is forced hidden",
              catalog_json(c5)["packs"][0]["launch"]["visible"] is False)
        check("the downgrade is reported", "HIDDEN" in text)
        rc, _ = run(CATALOG_CLI, ["--source", dishonest, "--output", c5])
        check("no visible pack without --allow-hidden is fatal", rc == EXIT_FATAL)

        # --- default pack --------------------------------------------------
        c6 = os.path.join(tmp, "c6.js")
        rc, _ = run(CATALOG_CLI, ["--source", launchable, "--output", c6,
                                  "--default-pack", "gamma"])
        check("explicit default accepted", rc == EXIT_OK)
        check("default recorded", catalog_json(c6)["defaultPackId"] == "gamma")
        rc, _ = run(CATALOG_CLI, ["--source", launchable, "--output", c6,
                                  "--default-pack", "nope"])
        check("unknown default is fatal", rc == EXIT_FATAL)
        rc, _ = run(CATALOG_CLI, ["--source", demo, "--output", c6,
                                  "--allow-hidden", "--default-pack", "demo"])
        check("hidden default is fatal", rc == EXIT_FATAL)

        # --- range overlap --------------------------------------------------
        clash = build_pack("demo", "clash", tmp, {
            "packId": "clash", "courseId": "clash",
            "idRange.min": "1500", "idRange.max": "2500"})
        rc, text = run(CATALOG_CLI, ["--source", demo, "--source", clash,
                                     "--output", os.path.join(tmp, "x.js"),
                                     "--allow-hidden"])
        check("declared-range overlap is fatal", rc == EXIT_FATAL)
        check("overlap message names both packs",
              "demo" in text and "clash" in text and "overlap" in text)

        # --- malformed handoffs fail closed ----------------------------------
        def corrupt(name, mutate):
            case = os.path.join(tmp, "bad_" + name)
            shutil.copytree(demo, case)
            path = os.path.join(case, "registry-handoff.json")
            doc2 = json.load(open(path, encoding="utf-8"))
            mutate(doc2)
            json.dump(doc2, open(path, "w", encoding="utf-8"))
            rc2, _ = run(CATALOG_CLI, ["--source", case,
                                       "--output", os.path.join(tmp, "y.js"),
                                       "--allow-hidden"])
            return rc2

        def setver(d): d["handoffVersion"] = 2
        check("unsupported handoffVersion is fatal", corrupt("ver", setver) == EXIT_FATAL)

        def badid(d): d["packId"] = "BAD ID"
        check("malformed packId is fatal", corrupt("id", badid) == EXIT_FATAL)

        def badsum(d): d["contentChecksum"] = "sha256:xyz"
        check("malformed checksum is fatal", corrupt("sum", badsum) == EXIT_FATAL)

        def badalloc(d): d["allocated"]["max"] = 999999999
        check("allocated outside declared is fatal",
              corrupt("alloc", badalloc) == EXIT_FATAL)

        def badstatus(d): d["status"] = "shipped"
        check("unknown status is fatal", corrupt("status", badstatus) == EXIT_FATAL)

        def dropfile(d):
            d["generatedFiles"] = [f for f in d["generatedFiles"]
                                   if not f["path"].endswith("-cards.js")]
        check("missing runtime asset entry is fatal",
              corrupt("files", dropfile) == EXIT_FATAL)

        def pathy(d): d["generatedFiles"][0]["path"] = "../escape.js"
        check("path escape in generatedFiles is fatal",
              corrupt("path", pathy) == EXIT_FATAL)

        broken = os.path.join(tmp, "bad_json")
        shutil.copytree(demo, broken)
        with open(os.path.join(broken, "registry-handoff.json"), "w") as fh:
            fh.write("{not json")
        rc, _ = run(CATALOG_CLI, ["--source", broken,
                                  "--output", os.path.join(tmp, "z.js"),
                                  "--allow-hidden"])
        check("unparseable handoff is fatal", rc == EXIT_FATAL)

        rc, _ = run(CATALOG_CLI, ["--source", os.path.join(tmp, "nope"),
                                  "--output", os.path.join(tmp, "z.js")])
        check("missing source directory is fatal", rc == EXIT_FATAL)

        # --- check mode ------------------------------------------------------
        rc, _ = run(CATALOG_CLI, ["--source", demo, "--source", synth,
                                  "--output", c1, "--allow-hidden", "--check"])
        check("check on a current catalog exits 0", rc == EXIT_OK)
        rc, _ = run(CATALOG_CLI, ["--source", demo, "--output", c1,
                                  "--allow-hidden", "--check"])
        check("check detects drift", rc == EXIT_DRIFT)
        before = os.path.getmtime(c1)
        run(CATALOG_CLI, ["--source", demo, "--output", c1,
                          "--allow-hidden", "--check"])
        check("check mode writes nothing", os.path.getmtime(c1) == before)

        # --- manifest reading is data-only ------------------------------------
        manifest = cat.read_manifest_js(
            os.path.join(synth, "synth-en-content-pack.js"))
        check("manifest parsed without executing JS",
              manifest["packId"] == "synth-en")
        check("manifest carries the title",
              manifest["title"] == "Synthetic English Fixture")
        # The naive first-[ to last-] slice would break on FLASHEDU_PACKS["id"].
        check("manifest parse survives brackets in the wrapper",
              isinstance(manifest.get("levels"), list))

        # --- no inference -----------------------------------------------------
        check("no licence is invented",
              "license" not in json.dumps(catalog_json(c1)).lower()
              or "license" not in raw.lower())

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    return emit("pack_catalog_build", fails)


if __name__ == "__main__":
    sys.exit(main())
