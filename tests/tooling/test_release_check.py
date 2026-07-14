"""Focused tests for scripts/release_check.py (the read-only web-release verifier).

Each case builds an ISOLATED temporary git repo with a copy of release_check.py and a STUBBED
tests/run_regression.py, then runs the helper and asserts exit code + output. No network, no real
user data, no Supabase, and the helper must not mutate the temp repo.

Emits a single JSON line with a "pass" key so tests/run_regression.py can score it.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(ROOT, "scripts", "release_check.py")
REQUIRED = ["index.html", "app.js", "styles.css", "sw.js", "data.js", "manifest.webmanifest",
            "auth.js", "sync.js", "metadata.js", "insights.js", "test.js", "core/platform/platform.js"]

fails = []
def check(n, c):
    if not c:
        fails.append(n)

def run_git(repo, *args):
    return subprocess.run(["git"] + list(args), cwd=repo, capture_output=True, text=True, encoding="utf-8")

def write(path, content=""):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

def scaffold(repo, reg_pass=True):
    """A clean 'main == origin/main' repo with the helper, stub regression, and required assets."""
    os.makedirs(os.path.join(repo, "scripts"), exist_ok=True)
    shutil.copy(SRC, os.path.join(repo, "scripts", "release_check.py"))
    # stub regression: prints a pass line and exits 0 (pass) or 1 (fail) — no browser/network.
    write(os.path.join(repo, "tests", "run_regression.py"),
          'import sys\nprint(\'{"pass": %s}\')\nsys.exit(%d)\n' % ("true" if reg_pass else "false", 0 if reg_pass else 1))
    for f in REQUIRED:
        p = os.path.join(repo, "hsk_flashcard_app", f)
        write(p, "const CACHE='hsk-flashcards-v35';\n" if f == "sw.js" else "// stub\n")
    run_git(repo, "init", "-q")
    run_git(repo, "config", "user.email", "t@t.test")
    run_git(repo, "config", "user.name", "t")
    run_git(repo, "config", "commit.gpgsign", "false")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", "init")
    run_git(repo, "branch", "-M", "main")
    head = run_git(repo, "rev-parse", "HEAD").stdout.strip()
    run_git(repo, "update-ref", "refs/remotes/origin/main", head)   # simulate a synced origin/main
    return head

def run_check(repo):
    r = subprocess.run([sys.executable, os.path.join(repo, "scripts", "release_check.py")],
                       cwd=repo, capture_output=True, text=True, encoding="utf-8")
    return r.returncode, (r.stdout or "") + (r.stderr or "")

def main():
    base = tempfile.mkdtemp(prefix="relchk_")
    try:
        # 1) clean main == origin/main + regression passes -> exit 0, manual steps printed
        r1 = os.path.join(base, "clean"); head = scaffold(r1, reg_pass=True)
        code, out = run_check(r1)
        check("clean main passes (exit 0)", code == 0)
        check("clean: reports exact commit", head in out)
        check("clean: reports SW v35", "hsk-flashcards-v35" in out)
        check("clean: RESULT PASS", "RESULT: PASS" in out)
        check("clean: prints manual Render steps only on success", "Manual Deploy" in out)
        # helper did not modify the repo
        st = run_git(r1, "status", "--porcelain", "--untracked-files=all").stdout.strip()
        check("clean: helper leaves repo unmodified", st == "")
        check("clean: HEAD unchanged after run", run_git(r1, "rev-parse", "HEAD").stdout.strip() == head)
        check("clean: origin/main unchanged after run", run_git(r1, "rev-parse", "origin/main").stdout.strip() == head)

        # 2) dirty tracked file (unstaged) -> non-zero, no manual steps
        r2 = os.path.join(base, "dirty"); scaffold(r2)
        with open(os.path.join(r2, "hsk_flashcard_app", "app.js"), "a", encoding="utf-8") as f: f.write("// edit\n")
        code, out = run_check(r2)
        check("dirty unstaged fails (non-zero)", code != 0)
        check("dirty: working tree clean gate FAIL", "FAIL  working tree clean" in out)
        check("dirty: no manual steps on failure", "Manual Deploy" not in out)

        # 3) staged change -> non-zero
        r3 = os.path.join(base, "staged"); scaffold(r3)
        with open(os.path.join(r3, "hsk_flashcard_app", "app.js"), "a", encoding="utf-8") as f: f.write("// edit\n")
        run_git(r3, "add", "hsk_flashcard_app/app.js")
        code, out = run_check(r3)
        check("staged change fails (non-zero)", code != 0)
        check("staged: no manual steps", "Manual Deploy" not in out)

        # 4) untracked file -> non-zero
        r4 = os.path.join(base, "untracked"); scaffold(r4)
        write(os.path.join(r4, "newfile.txt"), "x")
        code, out = run_check(r4)
        check("untracked file fails (non-zero)", code != 0)
        check("untracked: clean gate FAIL", "FAIL  working tree clean" in out)

        # 5) wrong branch -> non-zero
        r5 = os.path.join(base, "branch"); scaffold(r5)
        run_git(r5, "checkout", "-q", "-b", "feature")
        code, out = run_check(r5)
        check("wrong branch fails (non-zero)", code != 0)
        check("wrong branch: branch gate FAIL", "FAIL  branch is main" in out)

        # 6) detached HEAD -> non-zero
        r6 = os.path.join(base, "detached"); h6 = scaffold(r6)
        run_git(r6, "checkout", "-q", h6)
        code, out = run_check(r6)
        check("detached HEAD fails (non-zero)", code != 0)
        check("detached: branch gate FAIL", "FAIL  branch is main" in out)

        # 7) diverged main / origin/main -> non-zero
        r7 = os.path.join(base, "diverged"); scaffold(r7)
        with open(os.path.join(r7, "extra.txt"), "w", encoding="utf-8") as f: f.write("y")
        run_git(r7, "add", "-A"); run_git(r7, "commit", "-q", "-m", "second")  # main moves; origin/main stays
        code, out = run_check(r7)
        check("diverged main/origin fails (non-zero)", code != 0)
        check("diverged: sync gate FAIL", "FAIL  local main == origin/main" in out)
        check("diverged: no manual steps", "Manual Deploy" not in out)

        # 8) regression failure propagates non-zero
        r8 = os.path.join(base, "regfail"); scaffold(r8, reg_pass=False)
        code, out = run_check(r8)
        check("regression failure -> non-zero", code != 0)
        check("regfail: regression gate FAIL", "FAIL  full regression passes" in out)
        check("regfail: no manual steps", "Manual Deploy" not in out)

        # 9) successful regression returns zero (covered by case 1); assert regression gate PASS text
        check("success: regression gate PASS text present", "PASS  full regression passes" in run_check(r1)[1])

        # 10) repository path containing spaces works
        r10 = os.path.join(base, "dir with space", "the repo"); scaffold(r10)
        code, out = run_check(r10)
        check("path with spaces: exit 0", code == 0)
        check("path with spaces: RESULT PASS", "RESULT: PASS" in out)

        # 11) helper source performs no git-mutating / deploy operation
        srctext = open(SRC, encoding="utf-8").read()
        bad = re.findall(r'git\(\s*["\'](push|fetch|pull|merge|rebase|reset|checkout|tag|clean|commit|apply|update-ref|branch)["\']', srctext)
        check("helper makes no mutating git calls", bad == [])
        check("helper imports no network libraries",
              not re.search(r'^\s*(import|from)\s+(urllib|requests|http|socket|ftplib|smtplib)\b', srctext, re.M))
        subcalls = re.findall(r'subprocess\.run\(\s*(\[[^\]]*\])', srctext)
        check("helper only spawns git or the regression runner (no deploy tool)",
              len(subcalls) >= 1 and all(('"git"' in s or "'git'" in s or "sys.executable" in s) for s in subcalls))

        # 12) no bypass flags for the safety gates
        check("no --skip-regression bypass", "skip-regression" not in srctext and "no-regression" not in srctext)
        check("no --allow-dirty bypass", "allow-dirty" not in srctext and "--force" not in srctext)

    finally:
        shutil.rmtree(base, ignore_errors=True)

    print(json.dumps({"suite": "release_check", "pass": len(fails) == 0, "fails": fails}, ensure_ascii=False))
    return 0 if not fails else 1

if __name__ == "__main__":
    sys.exit(main())
