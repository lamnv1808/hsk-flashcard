#!/usr/bin/env python3
"""FlashEdu web-release verification - READ-ONLY, FAIL-CLOSED.

    python scripts/release_check.py

Verifies that the current checkout is safe to deploy via the owner's MANUAL Render
workflow, and prints (but never runs) the deploy steps. It only READS: it never
fetches/pulls/merges/rebases/resets/checkouts/tags/pushes/deploys, never touches user
progress/settings/auth storage, and never contacts Supabase.

Gates (all must pass; exit 0 only when every gate passes, non-zero otherwise):
  1. inside a git work tree
  2. all safety-critical git reads succeed and have the expected shape (fail-closed)
  3. current branch is `main`
  4. working tree completely clean (staged + unstaged + untracked)
  5. local `main` == local `origin/main`
  6. service-worker cache version present (reported exactly)
  7. the FULL sw.js precache inventory (its ASSETS array) is verified to exist on disk
  8. full regression (`tests/run_regression.py`) passes, run with THIS interpreter
  9. repository invariants (branch/HEAD/main/origin-main/clean) are UNCHANGED after regression

There is intentionally NO flag to skip the dirty-tree, branch, sync, precache, or regression gates.
CLI output is ASCII-only (docs may be UTF-8).
"""
import os
import re
import subprocess
import sys

# scripts/ lives directly under the repo root; abspath handles spaces in the path.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "hsk_flashcard_app")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")

_gates = []  # (name, ok)


def out(s=""):
    # ASCII-only line so Windows consoles never render punctuation as mojibake.
    try:
        print(str(s).encode("ascii", "replace").decode("ascii"))
    except Exception:
        print(s)


def git(*args):
    # READ-ONLY git only. cwd=ROOT so it works regardless of the caller's directory.
    return subprocess.run(["git"] + list(args), cwd=ROOT,
                          capture_output=True, text=True, encoding="utf-8")


def gate(name, ok, detail=""):
    _gates.append((name, bool(ok)))
    out(("PASS" if ok else "FAIL") + "  " + name + (("  -  " + detail) if detail else ""))
    return bool(ok)


def read_invariants():
    """Read every safety-critical git value FAIL-CLOSED: each must return code 0 AND the
    expected output shape. A failed `git status` (nonzero exit / empty stdout) is never
    treated as a clean tree."""
    inv = {"read_ok": True, "errors": []}

    r = git("rev-parse", "--abbrev-ref", "HEAD")
    b = r.stdout.strip()
    inv["branch"] = b if r.returncode == 0 else None
    if r.returncode != 0 or not b or any(ch.isspace() for ch in b):
        inv["read_ok"] = False; inv["errors"].append("branch read failed")

    r = git("status", "--porcelain", "--untracked-files=all")
    if r.returncode != 0:
        inv["read_ok"] = False; inv["clean"] = None; inv["errors"].append("git status failed")
    else:
        inv["clean"] = (r.stdout.strip() == "")   # only a code-0 status may declare cleanliness
        inv["status"] = r.stdout

    for key, ref in (("head", "HEAD"), ("main", "main"), ("origin_main", "origin/main")):
        r = git("rev-parse", ref)
        v = r.stdout.strip()
        if r.returncode == 0 and SHA_RE.match(v):
            inv[key] = v
        else:
            inv[key] = None; inv["read_ok"] = False; inv["errors"].append(ref + " read failed")
    return inv


def sw_inventory():
    """Parse sw.js READ-ONLY (no JS execution). Returns (cache_version, ok, detail, count).
    Fails closed if sw.js/the CACHE line/the ASSETS array cannot be found or parsed, or if any
    listed precache asset is missing on disk. The sw.js ASSETS array is the single source of
    truth - no second asset list is kept here."""
    sw = os.path.join(APP, "sw.js")
    if not os.path.isfile(sw):
        return (None, False, "hsk_flashcard_app/sw.js missing", 0)
    try:
        text = open(sw, encoding="utf-8").read()
    except Exception as e:
        return (None, False, "could not read sw.js: " + str(e), 0)

    mver = re.search(r"const\s+CACHE\s*=\s*'([^']+)'", text)
    swver = mver.group(1) if mver else None

    marr = re.search(r"\bASSETS\s*=\s*\[(.*?)\]", text, re.S)
    if not marr:
        return (swver, False, "sw.js ASSETS precache array not found (fail-closed)", 0)
    items = re.findall(r"""['"]([^'"]+)['"]""", marr.group(1))
    if not items:
        return (swver, False, "sw.js ASSETS array is empty/unparseable (fail-closed)", 0)

    missing = []
    for a in items:
        parts = a.split("/")
        if ".." in parts:
            missing.append(a + " (unsafe path)"); continue
        if a in ("./", "."):
            if not os.path.isdir(APP):
                missing.append(a)
            continue
        rel = a[2:] if a.startswith("./") else a
        if not os.path.isfile(os.path.join(APP, *rel.split("/"))):
            missing.append(a)

    if missing:
        return (swver, False, "missing precache asset(s): " + ", ".join(missing), len(items))
    return (swver, True, str(len(items)) + " precache assets verified", len(items))


def compare_invariants(before, after):
    """Return (unchanged_ok, detail). Requires: readable, still on main, still clean, and
    HEAD/main/origin-main unchanged, with main still == origin/main."""
    if not after["read_ok"]:
        return (False, "post-regression git read failed: " + "; ".join(after["errors"]))
    problems = []
    if after["branch"] != "main":
        problems.append("branch -> " + str(after["branch"]))
    if after.get("clean") is not True:
        problems.append("working tree no longer clean")
    if after["head"] != before["head"]:
        problems.append("HEAD moved")
    if after["main"] != before["main"]:
        problems.append("main moved")
    if after["origin_main"] != before["origin_main"]:
        problems.append("origin/main moved")
    if after["main"] != after["origin_main"]:
        problems.append("main != origin/main")
    return (not problems, "; ".join(problems))


def manual_steps(commit, swver):
    out("")
    out("OWNER-ONLY MANUAL RELEASE STEPS (this tool does NOT perform them):")
    out("  1. Confirm the verified commit: " + str(commit))
    out("  2. Render dashboard -> the FlashEdu Static Site -> Manual Deploy -> Deploy latest commit.")
    out("  3. Wait until the deploy status shows Live.")
    out("  4. Hard-refresh, or open a fresh/incognito browser context, so the new")
    out("     service worker (" + (swver or "?") + ") activates and old caches purge.")
    out("  5. Run docs/release/PRODUCTION_SMOKE_CHECKLIST.md against the live site.")


def main():
    out("FlashEdu release verification (read-only) - nothing is pushed or deployed.")
    out("repo: " + ROOT)
    out("")

    inside = git("rev-parse", "--is-inside-work-tree")
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        gate("inside a git work tree", False, "not a git repository or git read failed")
        return finish(None, None)
    gate("inside a git work tree", True)

    inv = read_invariants()
    gate("git invariants readable (fail-closed)", inv["read_ok"],
         "" if inv["read_ok"] else "; ".join(inv["errors"]))
    gate("branch is main", inv["read_ok"] and inv["branch"] == "main",
         "current branch: " + str(inv["branch"]))
    gate("working tree clean", inv.get("clean") is True,
         "" if inv.get("clean") is True else "not clean or git status failed")
    gate("local main == origin/main",
         inv["read_ok"] and inv["main"] is not None and inv["main"] == inv["origin_main"],
         ("main=" + (inv["main"] or "?")[:12] + "  origin/main=" + (inv["origin_main"] or "?")[:12]))

    commit = inv.get("head")
    swver, assets_ok, assets_detail, assets_count = sw_inventory()
    out("")
    out("HEAD commit         : " + str(commit))
    out("service-worker cache: " + (swver or "?"))
    gate("service-worker cache present", bool(swver), swver or "sw.js missing / no CACHE line")
    gate("sw.js precache inventory verified", assets_ok, assets_detail)

    # Fail fast: do not spend minutes on regression when a pre-condition already failed.
    if not all(ok for _, ok in _gates):
        out("")
        out("Pre-release gates failed; skipping regression.")
        return finish(commit, swver)

    # Snapshot invariants immediately BEFORE regression (Finding 1).
    before = read_invariants()

    out("")
    out("Running full regression (tests/run_regression.py) with " + os.path.basename(sys.executable) + " ...")
    reg = subprocess.run([sys.executable, os.path.join(ROOT, "tests", "run_regression.py")], cwd=ROOT)
    gate("full regression passes", reg.returncode == 0, "run_regression.py exit " + str(reg.returncode))

    # Re-validate invariants AFTER regression: regression is executable code and must not have
    # mutated the tree/branch/refs. Any mutation fails closed with no deploy steps.
    after = read_invariants()
    unchanged, why = compare_invariants(before, after)
    gate("repository unchanged by regression", unchanged, why)

    return finish(commit, swver)


def finish(commit, swver):
    out("")
    passed = sum(1 for _, ok in _gates if ok)
    total = len(_gates)
    if passed == total:
        out("Gates: %d/%d passed." % (passed, total))
        out("RESULT: PASS - commit is release-verified (read-only; nothing pushed or deployed).")
        manual_steps(commit, swver)
        return 0
    out("Gates: %d/%d passed." % (passed, total))
    out("RESULT: FAIL - failed gate(s): " + ", ".join(n for n, ok in _gates if not ok))
    out("No deployment steps are printed. Fix the above and re-run.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
