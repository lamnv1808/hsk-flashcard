#!/usr/bin/env python3
"""Phase 24D - safety: JS escaping, containment, atomicity, CLI contract.

The security property that matters most: no spreadsheet-derived value may reach
a code position in generated JavaScript. The wrapper is a tool-owned literal and
author data lands only inside JSON value positions, hardened against the three
sequences that are valid JSON but break a classic <script> context.
"""

import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, os.path.join(ROOT, "tests", "support"))
sys.path.insert(0, os.path.join(ROOT, "tests", "fixtures", "packs"))

import packlib                                    # noqa: E402
from datajs import emit                           # noqa: E402
from contentpack import emit as cp_emit           # noqa: E402
from contentpack.normalize import (               # noqa: E402
    NormalizationError, normalize_display, normalize_compare,
)
from contentpack.pipeline import Options, build   # noqa: E402

CLI = os.path.join(ROOT, "scripts", "build_content_pack.py")

EXIT_OK, EXIT_FATAL, EXIT_USAGE, EXIT_DRIFT, EXIT_NONDET = 0, 1, 2, 3, 4


def codes(result):
    return {f.code for f in result.findings}


def run_cli(args):
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run([sys.executable, CLI] + args, cwd=ROOT, env=env,
                          capture_output=True, text=True, encoding="utf-8")
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def main():
    fails = []

    def check(name, cond):
        if not cond:
            fails.append(name)

    tmp = tempfile.mkdtemp(prefix="cpsafe_")

    def fresh(name):
        dest = os.path.join(tmp, name)
        if os.path.isdir(dest):
            shutil.rmtree(dest)
        return packlib.copy_csv_source("demo", dest)

    def run(src, out, **kw):
        return build(Options(pack_id="demo", source=src, output=out, **kw), ROOT)

    try:
        # --- generated JS escaping ----------------------------------------
        hostile = fresh("hostile")
        payload = "</script><img src=x onerror=alert(1)>"
        sep = "line sep end"
        packlib.edit_cards(hostile, lambda rows: rows[:1] + [
            rows[1][:3] + [payload] + rows[1][4:],
            rows[2][:3] + [sep] + rows[2][4:],
        ] + rows[3:])
        hostile_result = run(hostile, os.path.join(tmp, "out_hostile"),
                             init_ledger=True)
        check("hostile content still builds", not hostile_result.findings.has_fatal())
        cards_js = {a.name: a.data for a in hostile_result.data_artifacts}[
            "demo-cards.js"].decode("utf-8")
        check("closing script tag is neutralized", "</script" not in cards_js)
        check("closing tag is escaped as <\\/", "<\\/script" in cards_js)
        check("U+2028 is escaped", " " not in cards_js)
        check("U+2029 is escaped", " " not in cards_js)
        check("U+2028 appears as an escape sequence", "\\u2028" in cards_js)
        check("payload stays inside a JSON string, not a code position",
              "onerror=alert(1)" in cards_js and "><img" not in
              cards_js.replace("<\\/script>", ""))
        check("wrapper namespace is tool-owned",
              cards_js.count('window.FLASHEDU_PACKS["demo"]') == 3)
        check("packId is the only interpolated value in the wrapper",
              cards_js.count("window.FLASHEDU_PACKS") == 5)

        # --- Unicode policy ------------------------------------------------
        check("NFC normalization is applied",
              normalize_display("é") == "é")
        check("NFKC is not applied (full-width preserved)",
              normalize_display("Ａ") == "Ａ")
        check("zero-width space is stripped",
              normalize_display("a​b") == "ab")
        check("BOM inside text is stripped",
              normalize_display("a﻿b") == "ab")
        check("non-breaking space is trimmed at the edges",
              normalize_display(" x ") == "x")
        check("interior non-breaking space is preserved",
              normalize_display("a b") == "a b")

        def raises(code, text):
            try:
                normalize_display(text)
                return False
            except NormalizationError as exc:
                return exc.code == code

        check("zero-width joiner is fatal, never silently removed",
              raises("ZERO_WIDTH_JOINER", "a‍b"))
        check("zero-width non-joiner is fatal",
              raises("ZERO_WIDTH_JOINER", "a‌b"))
        check("lone surrogate is fatal",
              raises("MALFORMED_UNICODE", "a\ud800b"))
        check("control character is fatal",
              raises("CONTROL_CHARACTER", "a\x07b"))
        check("embedded newline is fatal", raises("CONTROL_CHARACTER", "a\nb"))
        check("non-string cell is fatal",
              raises("UNSUPPORTED_CELL_TYPE", 12345))
        check("comparison form never mutates stored text",
              normalize_compare("  Hello   World  ") == "hello world")

        # --- path containment ----------------------------------------------
        root = os.path.join(tmp, "containment")
        os.makedirs(root, exist_ok=True)
        for candidate in ("../escape.js", "..\\escape.js", "/etc/passwd",
                          "C:\\Windows\\system32\\x.js", "\\\\unc\\share\\x.js",
                          "https://evil.example/x.js", "//evil.example/x.js",
                          "a/../../b.js", ""):
            if cp_emit.is_contained(root, candidate):
                fails.append("containment accepted %r" % candidate)
        check("plain relative name is contained",
              cp_emit.is_contained(root, "demo-cards.js"))
        check("nested relative name is contained",
              cp_emit.is_contained(root, "sub/demo-cards.js"))

        # --- the runtime app directory is off limits ------------------------
        app_out = os.path.join(ROOT, "hsk_flashcard_app", "packs", "demo")
        blocked = run(fresh("appout"), app_out, init_ledger=True)
        check("writing inside hsk_flashcard_app is fatal",
              "OUTPUT_PATH_ESCAPE" in codes(blocked))
        check("no directory was created inside the app",
              not os.path.exists(app_out))

        # --- foreign and stale output ---------------------------------------
        src = fresh("base")
        good_out = os.path.join(tmp, "good")
        run(src, good_out, init_ledger=True)
        ledger = os.path.join(src, "demo-id-ledger.json")
        ledger_before = open(ledger, "rb").read()

        foreign_out = os.path.join(tmp, "foreign")
        os.makedirs(foreign_out)
        with open(os.path.join(foreign_out, "somebody-elses.txt"), "w") as fh:
            fh.write("not ours")
        blocked = run(src, foreign_out)
        check("foreign output directory is fatal",
              "FOREIGN_OUTPUT" in codes(blocked))
        # A build that fails before the commit point must not touch the ledger.
        # Consuming ids for a publication that never happened is exactly the
        # defect the transaction protocol removes.
        check("a refused publish leaves the ledger byte-unchanged",
              open(ledger, "rb").read() == ledger_before)
        check("a refused publish leaves no transaction journal",
              not os.path.isfile(
                  os.path.join(tmp, ".txn-demo.json")))

        forced = run(src, foreign_out, force=True)
        check("--force proceeds over a foreign directory",
              not forced.findings.has_fatal())
        with open(os.path.join(good_out, "obsolete.js"), "w") as fh:
            fh.write("stale")
        cleaned = run(src, good_out)
        check("obsolete generated file is removed",
              not os.path.isfile(os.path.join(good_out, "obsolete.js")))
        check("obsolete removal is reported",
              "STALE_OUTPUT_REMOVED" in codes(cleaned))

        # --- a failed build leaves the previous output untouched -----------
        before = packlib.snapshot_tree(good_out)
        broken = fresh("broken")
        shutil.copyfile(os.path.join(src, "demo-id-ledger.json"),
                        os.path.join(broken, "demo-id-ledger.json"))
        packlib.edit_manifest(broken, {"status": "not-a-status"})
        failed = run(broken, good_out)
        check("broken manifest is fatal", failed.findings.has_fatal())
        check("previous output is byte-unchanged after a failure",
              packlib.snapshot_tree(good_out) == before)
        check("no staging directory survives a failure",
              not os.path.isdir(os.path.join(tmp, ".staging-demo")))
        leftovers = [n for n in os.listdir(good_out) if n.endswith(".tmp")]
        check("no orphan temp files remain", leftovers == [])

        # --- --check writes nothing -----------------------------------------
        snap_src = packlib.snapshot_tree(src)
        snap_out = packlib.snapshot_tree(good_out)
        checked = run(src, good_out, check=True)
        check("check mode reports no drift", checked.drift == [])
        check("check mode wrote nothing to the source",
              packlib.snapshot_tree(src) == snap_src)
        check("check mode wrote nothing to the output",
              packlib.snapshot_tree(good_out) == snap_out)

        never = os.path.join(tmp, "never_created")
        run(src, never, check=True)
        check("check mode does not create the output directory",
              not os.path.exists(never))

        # --- CLI contract ----------------------------------------------------
        cli_src = fresh("cli")
        cli_out = os.path.join(tmp, "cli_out")
        rc, text = run_cli(["--pack", "demo", "--source", cli_src,
                            "--output", cli_out, "--init-ledger"])
        check("cli success exits 0", rc == EXIT_OK)
        check("cli output is ascii-only", all(ord(c) < 128 for c in text))
        check("cli states it touched no runtime asset",
              "hsk_flashcard_app" in text and "service worker" in text)

        rc, _ = run_cli(["--pack", "demo", "--source", cli_src,
                         "--output", cli_out, "--check"])
        check("cli check with matching output exits 0", rc == EXIT_OK)

        rc, _ = run_cli(["--pack", "demo", "--source", cli_src,
                         "--output", os.path.join(tmp, "cli_absent"), "--check"])
        check("cli drift exits 3", rc == EXIT_DRIFT)

        rc, _ = run_cli(["--pack", "demo", "--source", cli_src,
                         "--output", cli_out, "--verify-deterministic"])
        check("cli verify-deterministic exits 0", rc == EXIT_NONDET or rc == EXIT_OK)
        check("cli verify-deterministic actually passes", rc == EXIT_OK)

        rc, _ = run_cli(["--pack", "NOT_VALID"])
        check("cli bad pack id exits 2", rc == EXIT_USAGE)

        rc, _ = run_cli(["--pack", "demo",
                         "--source", os.path.join(tmp, "does_not_exist"),
                         "--output", cli_out])
        check("cli missing source exits 2", rc == EXIT_USAGE)

        bad_src = fresh("cli_bad")
        shutil.copyfile(os.path.join(cli_src, "demo-id-ledger.json"),
                        os.path.join(bad_src, "demo-id-ledger.json"))
        packlib.edit_manifest(bad_src, {"courseType": "nonsense"})
        rc, _ = run_cli(["--pack", "demo", "--source", bad_src,
                         "--output", os.path.join(tmp, "cli_bad_out")])
        check("cli fatal validation exits 1", rc == EXIT_FATAL)

        rc, text = run_cli(["--pack", "demo", "--source", cli_src,
                            "--output", cli_out, "--qa-only"])
        check("cli qa-only exits 0", rc == EXIT_OK)
        check("qa-only warns that allocations are provisional",
              "provisional" in text)

        # --- source hygiene ---------------------------------------------------
        sources_text = []
        pkg_dir = os.path.join(ROOT, "scripts", "contentpack")
        for name in sorted(os.listdir(pkg_dir)):
            if name.endswith(".py"):
                with open(os.path.join(pkg_dir, name), encoding="utf-8") as fh:
                    sources_text.append((name, fh.read()))
        with open(CLI, encoding="utf-8") as fh:
            sources_text.append(("build_content_pack.py", fh.read()))

        for name, text in sources_text:
            for banned in ("import urllib", "import requests", "import socket",
                           "import http", "shell=True", "eval(", "exec("):
                if banned in text:
                    fails.append("%s contains %r" % (name, banned))
        check("pipeline imports no subprocess module",
              all("import subprocess" not in t for _, t in sources_text))

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    return emit("pack_build_safety", fails)


if __name__ == "__main__":
    sys.exit(main())
