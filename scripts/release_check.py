#!/usr/bin/env python3
"""FlashEdu web-release verification — READ-ONLY.

    python scripts/release_check.py

Verifies that the current checkout is safe to deploy via the owner's MANUAL Render
workflow, and prints (but never runs) the deploy steps. It only READS: it never
fetches/pulls/merges/rebases/resets/checkouts/tags/pushes/deploys, never touches user
progress/settings/auth storage, and never contacts Supabase.

Gates (all must pass; exit 0 only when every gate passes, non-zero otherwise):
  1. inside a git work tree
  2. current branch is `main`
  3. working tree is completely clean (staged + unstaged + untracked)
  4. local `main` == local `origin/main`
  5. service-worker cache version is present (reported exactly)
  6. required web runtime assets exist
  7. full regression (`tests/run_regression.py`) passes, run with THIS interpreter

There is intentionally NO flag to skip the dirty-tree, branch, sync, or regression gates.
"""
import os
import re
import subprocess
import sys

# Windows-safe UTF-8 output.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# scripts/ lives directly under the repo root; abspath handles spaces in the path.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "hsk_flashcard_app")

REQUIRED_ASSETS = [
    "index.html", "app.js", "styles.css", "sw.js", "data.js", "manifest.webmanifest",
    "auth.js", "sync.js", "metadata.js", "insights.js", "test.js",
    "core/platform/platform.js",
]

_gates = []  # (name, ok)


def out(s=""):
    try:
        print(s)
    except UnicodeEncodeError:
        print(str(s).encode("ascii", "replace").decode())


def git(*args):
    # READ-ONLY git only. cwd=ROOT so it works regardless of the caller's directory.
    return subprocess.run(["git"] + list(args), cwd=ROOT,
                          capture_output=True, text=True, encoding="utf-8")


def gate(name, ok, detail=""):
    _gates.append((name, bool(ok)))
    out(("PASS" if ok else "FAIL") + "  " + name + (("  ->  " + detail) if detail else ""))
    return bool(ok)


def sw_version():
    sw = os.path.join(APP, "sw.js")
    if not os.path.isfile(sw):
        return None
    try:
        m = re.search(r"const\s+CACHE\s*=\s*'([^']+)'", open(sw, encoding="utf-8").read())
        return m.group(1) if m else None
    except Exception:
        return None


def manual_steps(commit, swver):
    out("")
    out("OWNER-ONLY MANUAL RELEASE STEPS (this tool does NOT perform them):")
    out("  1. Confirm the verified commit: " + commit)
    out("  2. Render dashboard -> the FlashEdu Static Site -> Manual Deploy -> Deploy latest commit.")
    out("  3. Wait until the deploy status shows Live.")
    out("  4. Hard-refresh, or open a fresh/incognito browser context, so the new")
    out("     service worker (" + (swver or "?") + ") activates and old caches purge.")
    out("  5. Run docs/release/PRODUCTION_SMOKE_CHECKLIST.md against the live site.")


def main():
    out("FlashEdu release verification (read-only) — nothing is pushed or deployed.")
    out("repo: " + ROOT)
    out("")

    inside = git("rev-parse", "--is-inside-work-tree")
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        gate("inside a git work tree", False, "not a git repository")
        return finish(None, None)
    gate("inside a git work tree", True)

    branch = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    gate("branch is main", branch == "main", "current branch: " + (branch or "?"))

    status = git("status", "--porcelain", "--untracked-files=all").stdout
    dirty = status.strip()
    gate("working tree clean", dirty == "",
         (str(len(dirty.splitlines())) + " uncommitted/untracked change(s)") if dirty else "")

    local_main = git("rev-parse", "main")
    origin_main = git("rev-parse", "origin/main")
    if local_main.returncode != 0 or origin_main.returncode != 0:
        gate("local main == origin/main", False, "missing 'main' or 'origin/main' ref")
    else:
        lm, om = local_main.stdout.strip(), origin_main.stdout.strip()
        gate("local main == origin/main", lm == om,
             "main=" + lm[:12] + "  origin/main=" + om[:12])

    commit = git("rev-parse", "HEAD").stdout.strip()
    swver = sw_version()
    out("")
    out("HEAD commit         : " + (commit or "?"))
    out("service-worker cache: " + (swver or "?"))
    gate("service-worker cache present", bool(swver), swver or "sw.js missing / no CACHE")

    missing = [f for f in REQUIRED_ASSETS if not os.path.isfile(os.path.join(APP, f))]
    gate("required web assets present", not missing,
         ("missing: " + ", ".join(missing)) if missing else (str(len(REQUIRED_ASSETS)) + " present"))

    # Fail fast: don't spend minutes on regression when a pre-condition already failed.
    if not all(ok for _, ok in _gates):
        out("")
        out("Pre-release gates failed; skipping regression.")
        return finish(commit, swver)

    out("")
    out("Running full regression (tests/run_regression.py) with " + os.path.basename(sys.executable) + " ...")
    reg = subprocess.run([sys.executable, os.path.join(ROOT, "tests", "run_regression.py")], cwd=ROOT)
    gate("full regression passes", reg.returncode == 0, "run_regression.py exit " + str(reg.returncode))

    return finish(commit, swver)


def finish(commit, swver):
    out("")
    passed = sum(1 for _, ok in _gates if ok)
    total = len(_gates)
    all_ok = passed == total
    out("Gates: %d/%d passed." % (passed, total))
    if all_ok:
        out("RESULT: PASS — commit is release-verified (read-only; nothing pushed or deployed).")
        manual_steps(commit, swver)
        return 0
    failed = [n for n, ok in _gates if not ok]
    out("RESULT: FAIL — failed gate(s): " + ", ".join(failed))
    out("No deployment steps are printed. Fix the above and re-run.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
