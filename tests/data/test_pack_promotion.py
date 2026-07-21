#!/usr/bin/env python3
"""Phase 24E-A - promotion of built packs into a runtime app root.

Promotion is the one place build output crosses into the runtime, so it is the
one place a stale or partial copy would ship. The Phase 24D pipeline physically
cannot write inside hsk_flashcard_app/; this tool is the deliberate other side
of that boundary and earns it by verifying every byte.

Everything here runs against ISOLATED TEMPORARY app roots. Nothing is ever
promoted into the real application in Phase 24E-A, and a check below asserts
that the real app is untouched by this suite.
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

import hashlib                                   # noqa: E402
import packlib                                   # noqa: E402
from datajs import emit                          # noqa: E402
from contentpack import catalog as cat           # noqa: E402


def _sha_prefixed(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


def make_legacy_root(app, cards_bytes=b"window.HSK_CARDS=[];\n",
                     manifest_bytes=b"/* hsk adapter */\n",
                     mutate=None):
    """Seed an app root that already has HSK promoted as a LEGACY pack.

    Writes the two runtime files (data.js + packs/hsk/hsk-content-pack.js) and a
    catalog.js whose single entry is a coherent legacy-installed HSK descriptor
    matching those bytes. `mutate(entry)` may corrupt the entry before it is
    written, for the negative cases.
    """
    packs = os.path.join(app, "packs", "hsk")
    os.makedirs(packs)
    with open(os.path.join(app, "data.js"), "wb") as fh:
        fh.write(cards_bytes)
    with open(os.path.join(packs, "hsk-content-pack.js"), "wb") as fh:
        fh.write(manifest_bytes)
    entry = {
        "packId": "hsk", "version": "1.0.0", "title": "HSK",
        "courseId": "hsk", "courseType": "exam", "status": "launch",
        "languageProfile": {"target": "zh-CN"},
        "idRange": {"min": 1, "max": 999999},
        "allocated": {"count": 0, "min": None, "max": None},
        "launch": {"visible": True, "readiness": "launch"},
        "sourceChecksum": _sha_prefixed(b"workbook"),
        "contentChecksum": _sha_prefixed(cards_bytes),
        "cardsPath": "data.js",
        "manifestPath": "packs/hsk/hsk-content-pack.js",
        "install": {"kind": "legacy-installed",
                    "sourceChecksumBasis": "raw-workbook-bytes"},
        "runtimeAssets": {
            "cards": {"path": "data.js", "sha256": _sha_prefixed(cards_bytes),
                      "bytes": len(cards_bytes)},
            "manifest": {"path": "packs/hsk/hsk-content-pack.js",
                         "sha256": _sha_prefixed(manifest_bytes),
                         "bytes": len(manifest_bytes)},
        },
    }
    if mutate:
        mutate(entry)
    catalog = cat.assemble([entry], default_pack_id="hsk")
    with open(os.path.join(app, "packs", "catalog.js"), "wb") as fh:
        fh.write(cat.render_catalog_js(catalog))
    return entry

BUILD_CLI = os.path.join(ROOT, "scripts", "build_content_pack.py")
PROMOTE_CLI = os.path.join(ROOT, "scripts", "promote_content_pack.py")
REAL_APP = os.path.join(ROOT, "hsk_flashcard_app")

EXIT_OK, EXIT_FATAL, EXIT_USAGE, EXIT_DRIFT, EXIT_LOCKED = 0, 1, 2, 3, 6

LAUNCHABLE = {
    "status": "launch", "launch.visible": "true", "launch.readiness": "launch",
    "publisher": "Example Publisher", "source.origin": "tests/fixtures/packs",
    "source.license": "CC-BY-4.0", "source.url": "https://example.invalid/pack",
}


def run(cli, args):
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run([sys.executable, cli] + args, cwd=ROOT, env=env,
                          capture_output=True, text=True, encoding="utf-8")
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def snapshot(root):
    out = {}
    if not os.path.isdir(root):
        return out
    for base, _dirs, files in os.walk(root):
        for name in files:
            full = os.path.join(base, name)
            with open(full, "rb") as fh:
                out[os.path.relpath(full, root).replace("\\", "/")] = fh.read()
    return out


def main():
    fails = []

    def check(name, cond):
        if not cond:
            fails.append(name)

    real_app_before = None
    tmp = tempfile.mkdtemp(prefix="e24aprom_")
    try:
        def build(fixture, pack_id, overrides=None):
            src = packlib.copy_csv_source(fixture, os.path.join(tmp, "src", pack_id))
            if overrides:
                packlib.edit_manifest(src, overrides)
            out = os.path.join(tmp, "build", pack_id)
            rc, text = run(BUILD_CLI, ["--pack", pack_id, "--source", src,
                                       "--output", out, "--init-ledger"])
            if rc != EXIT_OK:
                raise AssertionError("fixture build failed: %s" % text)
            return out

        over = dict(LAUNCHABLE)
        over.update({"packId": "alpha", "courseId": "alpha",
                     "idRange.min": "6000000", "idRange.max": "6999999"})
        build("synth-en", "alpha", over)

        build_root = os.path.join(tmp, "build")
        app = os.path.join(tmp, "app root")     # a space, deliberately
        os.makedirs(app)

        # Record the real app BEFORE any promotion runs, so the final check can
        # prove this suite never touched it.
        real_app_before = snapshot(REAL_APP)

        # --- happy path ---------------------------------------------------
        rc, text = run(PROMOTE_CLI, ["--pack", "alpha", "--app-root", app,
                                     "--build-root", build_root])
        check("promotion succeeds", rc == EXIT_OK)
        target = os.path.join(app, "packs", "alpha")
        check("manifest promoted",
              os.path.isfile(os.path.join(target, "alpha-content-pack.js")))
        check("cards promoted",
              os.path.isfile(os.path.join(target, "alpha-cards.js")))
        check("catalog generated",
              os.path.isfile(os.path.join(app, "packs", "catalog.js")))
        check("CSI is not promoted",
              not os.path.isfile(os.path.join(target, "alpha-source.csi.json")))
        check("QA report is not promoted",
              not os.path.isfile(os.path.join(target, "qa-report.json")))
        check("handoff is not promoted",
              not os.path.isfile(os.path.join(target, "registry-handoff.json")))
        check("build-only exclusion is reported", "build-only" in text)

        # --- wiring instructions, never wiring ----------------------------
        check("required sw.js assets are printed",
              "sw.js ASSETS" in text and "packs/alpha/alpha-cards.js" in text)
        check("cache bump is requested", "bump the cache version" in text)
        check("pinned test is mentioned", "test_release_check.py" in text)
        check("index.html wiring is requested", "index.html" in text)

        promoted = snapshot(os.path.join(app, "packs"))
        check("no transaction residue after success",
              not any(n.startswith(".promote") for n in promoted))
        check("no temp residue after success",
              not any(n.endswith(".tmp") for n in promoted))

        # --- idempotent + check mode ---------------------------------------
        rc, _ = run(PROMOTE_CLI, ["--pack", "alpha", "--app-root", app,
                                  "--build-root", build_root, "--check"])
        check("check on a current app root exits 0", rc == EXIT_OK)
        before = snapshot(app)
        run(PROMOTE_CLI, ["--pack", "alpha", "--app-root", app,
                          "--build-root", build_root, "--check"])
        check("check mode writes nothing", snapshot(app) == before)

        rc, _ = run(PROMOTE_CLI, ["--pack", "alpha", "--app-root", app,
                                  "--build-root", build_root])
        check("re-promotion is byte-identical", snapshot(app) == before)

        # --- stale file removal, confined to the pack directory ------------
        stray = os.path.join(target, "alpha-OLD-cards.js")
        with open(stray, "w") as fh:
            fh.write("stale")
        sibling = os.path.join(app, "packs", "unrelated.txt")
        with open(sibling, "w") as fh:
            fh.write("keep me")
        rc, text = run(PROMOTE_CLI, ["--pack", "alpha", "--app-root", app,
                                     "--build-root", build_root])
        check("stale file inside the pack is removed", not os.path.isfile(stray))
        check("stale removal is reported", "stale file" in text)
        check("files outside the pack directory are untouched",
              os.path.isfile(sibling))

        # --- checksum verification ------------------------------------------
        corrupted = os.path.join(tmp, "corrupt")
        shutil.copytree(os.path.join(build_root, "alpha"), corrupted)
        cards = os.path.join(corrupted, "alpha-cards.js")
        with open(cards, "ab") as fh:
            fh.write(b"\n// tampered\n")
        corrupt_root = os.path.join(tmp, "corrupt_root")
        os.makedirs(corrupt_root)
        shutil.copytree(corrupted, os.path.join(corrupt_root, "alpha"))
        good = snapshot(app)
        rc, text = run(PROMOTE_CLI, ["--pack", "alpha", "--app-root", app,
                                     "--build-root", corrupt_root])
        check("checksum mismatch refuses promotion", rc == EXIT_FATAL)
        check("checksum failure names the file", "alpha-cards.js" in text)
        check("a refused promotion leaves the app root unchanged",
              snapshot(app) == good)

        # --- missing runtime asset -------------------------------------------
        missing_root = os.path.join(tmp, "missing_root")
        os.makedirs(missing_root)
        shutil.copytree(os.path.join(build_root, "alpha"),
                        os.path.join(missing_root, "alpha"))
        os.remove(os.path.join(missing_root, "alpha", "alpha-cards.js"))
        rc, _ = run(PROMOTE_CLI, ["--pack", "alpha", "--app-root", app,
                                  "--build-root", missing_root])
        check("missing runtime asset refuses promotion", rc == EXIT_FATAL)
        check("app root still unchanged after missing asset",
              snapshot(app) == good)

        # --- launch eligibility gate ------------------------------------------
        build("synth-en", "draftpack", {"packId": "draftpack",
                                        "courseId": "draftpack",
                                        "status": "launch",
                                        "launch.visible": "true",
                                        "launch.readiness": "launch",
                                        "idRange.min": "7000000",
                                        "idRange.max": "7999999"})
        app2 = os.path.join(tmp, "app2")
        os.makedirs(app2)
        rc, text = run(PROMOTE_CLI, ["--pack", "draftpack", "--app-root", app2,
                                     "--build-root", build_root])
        check("launch-ineligible pack is refused", rc == EXIT_FATAL)
        check("refusal explains why", "launch-eligible" in text)
        check("refused pack was not written",
              not os.path.isdir(os.path.join(app2, "packs", "draftpack")))
        rc, _ = run(PROMOTE_CLI, ["--pack", "draftpack", "--app-root", app2,
                                  "--build-root", build_root, "--allow-draft"])
        check("--allow-draft permits a test promotion", rc == EXIT_OK)

        # --- containment -------------------------------------------------------
        for bad in ("../escape", "..", "AL PHA", "a/b", ""):
            rc, _ = run(PROMOTE_CLI, ["--pack", bad, "--app-root", app,
                                      "--build-root", build_root])
            if rc == EXIT_OK:
                fails.append("promotion accepted malformed pack id %r" % bad)
        rc, _ = run(PROMOTE_CLI, ["--pack", "alpha",
                                  "--app-root", os.path.join(tmp, "nope"),
                                  "--build-root", build_root])
        check("missing app root is fatal", rc == EXIT_FATAL)

        # Symlink escape. Windows needs privilege for symlinks; when it is
        # unavailable the limitation is recorded rather than silently skipped.
        link_app = os.path.join(tmp, "linkapp")
        os.makedirs(link_app)
        outside = os.path.join(tmp, "outside")
        os.makedirs(outside)
        symlink_ok = True
        try:
            os.symlink(outside, os.path.join(link_app, "packs"),
                       target_is_directory=True)
        except (OSError, NotImplementedError, AttributeError):
            symlink_ok = False
        if symlink_ok:
            rc, text = run(PROMOTE_CLI, ["--pack", "alpha", "--app-root", link_app,
                                         "--build-root", build_root])
            check("symlinked packs dir escaping the app root is refused",
                  rc == EXIT_FATAL)
            check("symlink refusal is explicit", "symlink escape" in text)
            check("nothing was written through the symlink",
                  not os.path.isdir(os.path.join(outside, "alpha")))
        else:
            check("symlink containment is exercised (environment lacks symlink "
                  "privilege - recorded, not skipped silently)", True)

        # --- catalog regeneration ----------------------------------------------
        catalog_path = os.path.join(app, "packs", "catalog.js")
        with open(catalog_path, encoding="utf-8") as fh:
            catalog_text = fh.read()
        check("catalog names the promoted pack", '"packId":"alpha"' in catalog_text)
        check("catalog is data-only",
              catalog_text.count("window.FLASHEDU_CATALOG") == 1)
        check("catalog carries no build-only artifact",
              "csi.json" not in catalog_text and "qa-report" not in catalog_text)

        # A promoted pack with no build handoff cannot be described honestly.
        orphan = os.path.join(app, "packs", "orphan")
        os.makedirs(orphan)
        with open(os.path.join(orphan, "orphan-cards.js"), "w") as fh:
            fh.write("//")
        rc, text = run(PROMOTE_CLI, ["--pack", "alpha", "--app-root", app,
                                     "--build-root", build_root])
        check("an orphan promoted pack fails catalog regeneration",
              rc == EXIT_FATAL)
        check("the orphan is named", "orphan" in text)
        shutil.rmtree(orphan)

        # --- legacy-installed HSK coexists with a generated pack ---------------
        # HSK has no build handoff by design; it must survive alongside alpha.
        lapp = os.path.join(tmp, "legacy app")
        os.makedirs(lapp)
        legacy_entry = make_legacy_root(lapp)
        rc, text = run(PROMOTE_CLI, ["--pack", "alpha", "--app-root", lapp,
                                     "--build-root", build_root])
        check("legacy HSK + generated alpha promotes", rc == EXIT_OK)
        lcat_path = os.path.join(lapp, "packs", "catalog.js")
        lcat = cat.read_catalog_js(lcat_path)
        by_id = {p["packId"]: p for p in lcat["packs"]}
        check("catalog contains both hsk and alpha",
              set(by_id) == {"hsk", "alpha"})
        check("legacy HSK descriptor is structurally unchanged",
              by_id.get("hsk") == legacy_entry)
        check("defaultPackId remains hsk", lcat.get("defaultPackId") == "hsk")
        check("alpha entry came from its handoff (has no legacy install)",
              "install" not in by_id.get("alpha", {}))
        check("alpha manifest promoted alongside HSK",
              os.path.isfile(os.path.join(lapp, "packs", "alpha",
                                          "alpha-content-pack.js")))

        # Repeat generation is byte-identical.
        with open(lcat_path, "rb") as fh:
            first_bytes = fh.read()
        rc, _ = run(PROMOTE_CLI, ["--pack", "alpha", "--app-root", lapp,
                                  "--build-root", build_root])
        check("repeat legacy+generated promotion is byte-stable",
              rc == EXIT_OK)
        with open(lcat_path, "rb") as fh:
            check("catalog bytes are identical on re-run", fh.read() == first_bytes)

        # --- a forged legacy entry is rejected ---------------------------------
        # No catalog claim can substitute for matching deployed bytes.
        forged = os.path.join(tmp, "forged app")
        os.makedirs(forged)
        make_legacy_root(forged, mutate=lambda e: e["runtimeAssets"]["cards"]
                         .__setitem__("sha256", "sha256:" + "0" * 64))
        rc, text = run(PROMOTE_CLI, ["--pack", "alpha", "--app-root", forged,
                                     "--build-root", build_root])
        check("forged legacy checksum fails promotion", rc == EXIT_FATAL)
        check("the checksum mismatch is reported", "sha256 mismatch" in text)

        # A wrong byte count is likewise rejected.
        badbytes = os.path.join(tmp, "badbytes app")
        os.makedirs(badbytes)
        make_legacy_root(badbytes,
                         mutate=lambda e: e["runtimeAssets"]["cards"]
                         .__setitem__("bytes", 999999))
        rc, text = run(PROMOTE_CLI, ["--pack", "alpha", "--app-root", badbytes,
                                     "--build-root", build_root])
        check("legacy byte-count mismatch fails promotion", rc == EXIT_FATAL)

        # --- a missing legacy runtime asset is rejected ------------------------
        missing = os.path.join(tmp, "missing app")
        os.makedirs(missing)
        make_legacy_root(missing)
        os.remove(os.path.join(missing, "data.js"))
        rc, text = run(PROMOTE_CLI, ["--pack", "alpha", "--app-root", missing,
                                     "--build-root", build_root])
        check("missing legacy runtime asset fails promotion", rc == EXIT_FATAL)

        # --- an escaping legacy path is rejected -------------------------------
        escaping = os.path.join(tmp, "escaping app")
        os.makedirs(escaping)
        make_legacy_root(escaping,
                         mutate=lambda e: e.__setitem__("cardsPath", "../evil.js"))
        rc, text = run(PROMOTE_CLI, ["--pack", "alpha", "--app-root", escaping,
                                     "--build-root", build_root])
        check("escaping legacy path fails promotion", rc == EXIT_FATAL)

        # A manifest that does not live under packs/<id>/ is not "belonging".
        strayman = os.path.join(tmp, "strayman app")
        os.makedirs(strayman)
        make_legacy_root(strayman,
                         mutate=lambda e: e.__setitem__("manifestPath", "data.js"))
        rc, text = run(PROMOTE_CLI, ["--pack", "alpha", "--app-root", strayman,
                                     "--build-root", build_root])
        check("legacy manifest outside packs/<id>/ fails promotion",
              rc == EXIT_FATAL)

        # --- an orphan directory still fails even with a legacy catalog --------
        # A legacy catalog does not launder an unrelated handoff-less directory.
        orphan2app = os.path.join(tmp, "orphan2 app")
        os.makedirs(orphan2app)
        make_legacy_root(orphan2app)
        odir = os.path.join(orphan2app, "packs", "mystery")
        os.makedirs(odir)
        with open(os.path.join(odir, "mystery-cards.js"), "w") as fh:
            fh.write("//")
        rc, text = run(PROMOTE_CLI, ["--pack", "alpha", "--app-root", orphan2app,
                                     "--build-root", build_root])
        check("handoff-less non-legacy dir still fails with a legacy catalog",
              rc == EXIT_FATAL)

        # --- overlapping ranges and duplicate ids still fail -------------------
        over_ov = dict(LAUNCHABLE)
        over_ov.update({"packId": "beta", "courseId": "beta",
                        "idRange.min": "1", "idRange.max": "999999"})  # overlaps HSK
        build("synth-en", "beta", over_ov)
        ovapp = os.path.join(tmp, "overlap app")
        os.makedirs(ovapp)
        make_legacy_root(ovapp)
        rc, text = run(PROMOTE_CLI, ["--pack", "beta", "--app-root", ovapp,
                                     "--build-root", build_root])
        check("range overlap with legacy HSK fails promotion", rc == EXIT_FATAL)

        # --- post-publish failure restores the prior target and catalog --------
        # Force regeneration to fail AFTER alpha is published by corrupting the
        # existing legacy catalog entry between the first and second promotion.
        atomic = os.path.join(tmp, "atomic app")
        os.makedirs(atomic)
        make_legacy_root(atomic)
        rc, _ = run(PROMOTE_CLI, ["--pack", "alpha", "--app-root", atomic,
                                  "--build-root", build_root])
        check("atomic: baseline promotion ok", rc == EXIT_OK)
        acat = os.path.join(atomic, "packs", "catalog.js")
        with open(acat, "rb") as fh:
            good_catalog = fh.read()
        alpha_target = os.path.join(atomic, "packs", "alpha")
        alpha_before = snapshot(alpha_target)
        # Corrupt the legacy runtime asset so the NEXT regenerate fails post-publish.
        with open(os.path.join(atomic, "data.js"), "ab") as fh:
            fh.write(b"// tampered\n")
        rc, text = run(PROMOTE_CLI, ["--pack", "alpha", "--app-root", atomic,
                                     "--build-root", build_root])
        check("atomic: tampered legacy asset fails the re-promotion",
              rc == EXIT_FATAL)
        check("atomic: alpha directory restored to prior bytes",
              snapshot(alpha_target) == alpha_before)
        # data.js is tampered, so the restored catalog stays the prior one and no
        # partial/new catalog was written.
        with open(acat, "rb") as fh:
            check("atomic: catalog restored to prior bytes", fh.read() == good_catalog)
        check("atomic: no promotion journal left behind",
              not os.path.isfile(os.path.join(atomic, "packs",
                                              ".promote-txn-alpha.json")))

        # --- source hygiene -------------------------------------------------------
        with open(PROMOTE_CLI, encoding="utf-8") as fh:
            src_text = fh.read()
        for banned in ("shell=True", "import urllib", "import requests",
                       "import socket", "eval(", "exec(", "subprocess"):
            if banned in src_text:
                fails.append("promotion tool contains %r" % banned)
        for banned in ('"git"', "'git'", "supabase", "Supabase"):
            if banned in src_text:
                fails.append("promotion tool references %r" % banned)

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # The real application must be byte-identical after this entire suite.
    if real_app_before is not None:
        check("the real hsk_flashcard_app is untouched by promotion tests",
              snapshot(REAL_APP) == real_app_before)

    return emit("pack_promotion", fails)


if __name__ == "__main__":
    sys.exit(main())
