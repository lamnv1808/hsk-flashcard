"""Focused tests for scripts/release_check.py (read-only, fail-closed web-release verifier).

Each case builds an ISOLATED temporary git repo with a copy of release_check.py, a STUBBED
tests/run_regression.py, and a sw.js whose ASSETS precache array lists the created files. Then it
runs the helper and asserts exit code + output. No network, no real user data, no Supabase, and the
helper must not mutate the temp repo.

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

# The temp repo's sw.js precache inventory (the release helper's single source of truth).
SW_ASSETS = ["./", "index.html", "app.js", "styles.css", "data.js", "sw.js", "core/platform/platform.js"]
SW_FILES = ["index.html", "app.js", "styles.css", "data.js", "core/platform/platform.js"]  # sw.js written separately

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

def sw_js(assets):
    return "const CACHE='hsk-flashcards-v35';\nconst ASSETS=[\n  " + ",".join("'%s'" % a for a in assets) + "\n];\n"

def stub_regression(reg_pass=True, mutation=None):
    body = "import sys, subprocess, os\nprint('{\"pass\": %s}')\n" % ("true" if reg_pass else "false")
    if mutation == "modify":
        body += "open(os.path.join('hsk_flashcard_app','app.js'),'a',encoding='utf-8').write('// reg edit\\n')\n"
    elif mutation == "untracked":
        body += "open('reg_untracked.txt','w',encoding='utf-8').write('x')\n"
    elif mutation == "stage":
        body += ("open(os.path.join('hsk_flashcard_app','app.js'),'a',encoding='utf-8').write('// reg edit\\n')\n"
                 "subprocess.run(['git','add','hsk_flashcard_app/app.js'])\n")
    elif mutation == "commit":
        body += ("open('reg_new.txt','w',encoding='utf-8').write('x')\n"
                 "subprocess.run(['git','add','-A'])\n"
                 "subprocess.run(['git','-c','user.email=a@a','-c','user.name=a','-c','commit.gpgsign=false','commit','-q','-m','regmut'])\n")
    body += "sys.exit(%d)\n" % (0 if reg_pass else 1)
    return body

def scaffold(repo, reg_pass=True, mutation=None, sw_override=None, drop_asset=None):
    os.makedirs(os.path.join(repo, "scripts"), exist_ok=True)
    shutil.copy(SRC, os.path.join(repo, "scripts", "release_check.py"))
    write(os.path.join(repo, "tests", "run_regression.py"), stub_regression(reg_pass, mutation))
    for f in SW_FILES:
        write(os.path.join(repo, "hsk_flashcard_app", f), "// stub\n")
    write(os.path.join(repo, "hsk_flashcard_app", "sw.js"),
          sw_override if sw_override is not None else sw_js(SW_ASSETS))
    if drop_asset:  # remove a file that IS listed in ASSETS (to trigger a missing-precache failure)
        os.remove(os.path.join(repo, "hsk_flashcard_app", drop_asset))
    run_git(repo, "init", "-q")
    run_git(repo, "config", "user.email", "t@t.test")
    run_git(repo, "config", "user.name", "t")
    run_git(repo, "config", "commit.gpgsign", "false")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", "init")
    run_git(repo, "branch", "-M", "main")
    head = run_git(repo, "rev-parse", "HEAD").stdout.strip()
    run_git(repo, "update-ref", "refs/remotes/origin/main", head)
    return head

def run_check(repo):
    r = subprocess.run([sys.executable, os.path.join(repo, "scripts", "release_check.py")],
                       cwd=repo, capture_output=True, text=True, encoding="utf-8")
    return r.returncode, (r.stdout or "") + (r.stderr or "")

def main():
    base = tempfile.mkdtemp(prefix="relchk_")
    srctext = open(SRC, encoding="utf-8").read()
    try:
        # 1) clean main == origin/main + regression passes -> exit 0, exact reporting, manual steps
        r1 = os.path.join(base, "clean"); head = scaffold(r1)
        code, out = run_check(r1)
        check("clean passes (exit 0)", code == 0)
        check("clean: reports exact commit", head in out)
        check("clean: reports SW v35", "hsk-flashcards-v35" in out)
        check("clean: precache inventory verified", "precache assets verified" in out)
        check("clean: RESULT PASS", "RESULT: PASS" in out)
        check("clean: prints manual Render steps on success", "Manual Deploy" in out)
        check("clean: post-regression invariants gate PASS", "PASS  repository unchanged by regression" in out)
        st = run_git(r1, "status", "--porcelain", "--untracked-files=all").stdout.strip()
        check("clean: helper leaves repo unmodified", st == "")
        check("clean: HEAD unchanged", run_git(r1, "rev-parse", "HEAD").stdout.strip() == head)
        check("clean: origin/main unchanged", run_git(r1, "rev-parse", "origin/main").stdout.strip() == head)
        check("clean: ASCII-only CLI output", all(ord(ch) < 128 for ch in out))

        # 2-4) dirty / staged / untracked -> non-zero, no manual steps
        r2 = os.path.join(base, "dirty"); scaffold(r2)
        with open(os.path.join(r2, "hsk_flashcard_app", "app.js"), "a", encoding="utf-8") as f: f.write("// e\n")
        code, out = run_check(r2)
        check("dirty fails", code != 0); check("dirty: clean gate FAIL", "FAIL  working tree clean" in out)
        check("dirty: no manual steps", "Manual Deploy" not in out)
        r3 = os.path.join(base, "staged"); scaffold(r3)
        with open(os.path.join(r3, "hsk_flashcard_app", "app.js"), "a", encoding="utf-8") as f: f.write("// e\n")
        run_git(r3, "add", "hsk_flashcard_app/app.js")
        code, out = run_check(r3)
        check("staged fails", code != 0); check("staged: no manual steps", "Manual Deploy" not in out)
        r4 = os.path.join(base, "untracked"); scaffold(r4); write(os.path.join(r4, "newfile.txt"), "x")
        code, out = run_check(r4)
        check("untracked fails", code != 0); check("untracked: clean gate FAIL", "FAIL  working tree clean" in out)

        # 5-6) wrong branch / detached HEAD -> non-zero
        r5 = os.path.join(base, "branch"); scaffold(r5); run_git(r5, "checkout", "-q", "-b", "feature")
        code, out = run_check(r5)
        check("wrong branch fails", code != 0); check("wrong branch: gate FAIL", "FAIL  branch is main" in out)
        r6 = os.path.join(base, "detached"); h6 = scaffold(r6); run_git(r6, "checkout", "-q", h6)
        code, out = run_check(r6)
        check("detached HEAD fails", code != 0); check("detached: branch gate FAIL", "FAIL  branch is main" in out)

        # 7) diverged main / origin/main -> non-zero
        r7 = os.path.join(base, "diverged"); scaffold(r7)
        write(os.path.join(r7, "extra.txt"), "y"); run_git(r7, "add", "-A"); run_git(r7, "commit", "-q", "-m", "second")
        code, out = run_check(r7)
        check("diverged fails", code != 0); check("diverged: sync gate FAIL", "FAIL  local main == origin/main" in out)

        # 8) regression failure propagates non-zero
        r8 = os.path.join(base, "regfail"); scaffold(r8, reg_pass=False)
        code, out = run_check(r8)
        check("regression failure -> non-zero", code != 0)
        check("regfail: regression gate FAIL", "FAIL  full regression passes" in out)
        check("regfail: no manual steps", "Manual Deploy" not in out)

        # === Finding 1: passing regression that MUTATES the repo -> helper fails, no deploy steps ===
        for mut, label in [("modify", "modifies a tracked file"), ("untracked", "creates an untracked file"),
                           ("stage", "stages a file"), ("commit", "changes HEAD/refs")]:
            rr = os.path.join(base, "mut_" + mut); scaffold(rr, reg_pass=True, mutation=mut)
            code, out = run_check(rr)
            check("passing regression that %s -> helper fails" % label, code != 0)
            check("mut %s: post-regression gate FAIL" % mut, "FAIL  repository unchanged by regression" in out)
            check("mut %s: no manual steps" % mut, "Manual Deploy" not in out)

        # === Finding 2: precache inventory ===
        # missing a listed SW asset -> fail
        r9 = os.path.join(base, "missing_asset"); scaffold(r9, drop_asset="styles.css")
        code, out = run_check(r9)
        check("missing precache asset -> fail", code != 0)
        check("missing asset: precache gate FAIL", "FAIL  sw.js precache inventory verified" in out)
        check("missing asset: no manual steps", "Manual Deploy" not in out)
        # malformed ASSETS array -> fail closed
        r10 = os.path.join(base, "bad_assets"); scaffold(r10, sw_override="const CACHE='hsk-flashcards-v35';\nconst ASSETS=[ oops \n")
        code, out = run_check(r10)
        check("malformed ASSETS -> fail closed", code != 0)
        # missing ASSETS array entirely -> fail closed
        r11 = os.path.join(base, "no_assets"); scaffold(r11, sw_override="const CACHE='hsk-flashcards-v35';\n")
        code, out = run_check(r11)
        check("missing ASSETS array -> fail closed", code != 0)
        check("no ASSETS: precache gate FAIL", "FAIL  sw.js precache inventory verified" in out)

        # === Finding 2 (hardened): strict ASSETS parsing + path containment ===
        def sw_case(name, assets_line, external=None):
            repo = os.path.join(base, name)
            scaffold(repo, sw_override="const CACHE='hsk-flashcards-v35';\n" + assets_line + "\n")
            if external:  # create a file OUTSIDE hsk_flashcard_app that a traversal would resolve to
                write(os.path.join(repo, external), "external\n")
                run_git(repo, "add", "-A"); run_git(repo, "commit", "-q", "-m", "ext")
                h = run_git(repo, "rev-parse", "HEAD").stdout.strip()
                run_git(repo, "update-ref", "refs/remotes/origin/main", h)
            return repo, run_check(repo)

        fail_cases = [
            ("mixed_broken", "const ASSETS=['index.html', BROKEN_TOKEN];", None, "mixed valid + BROKEN_TOKEN"),
            ("expr_entry", "const ASSETS=['index.html', 'a' + '.js'];", None, "expression entry"),
            ("func_entry", "const ASSETS=['index.html', foo()];", None, "function-call entry"),
            ("nonstr_entry", "const ASSETS=['index.html', 123];", None, "non-string entry"),
            ("bslash_trav", "const ASSETS=['index.html','..\\\\outside.txt'];", "outside.txt", "backslash traversal (external exists)"),
            ("fslash_trav", "const ASSETS=['index.html','../outside.txt'];", "outside.txt", "forward-slash traversal"),
            ("abs_path", "const ASSETS=['index.html','/etc/passwd'];", None, "absolute path"),
            ("drive_path", "const ASSETS=['index.html','C:/Windows/win.ini'];", None, "windows drive path"),
            ("url_entry", "const ASSETS=['index.html','https://evil.example/x.js'];", None, "url entry"),
            ("proto_rel", "const ASSETS=['index.html','//evil.example/x.js'];", None, "protocol-relative entry"),
            ("missing_bracket", "const ASSETS=['index.html', 'app.js'", None, "missing closing bracket"),
            ("dup_exact", "const ASSETS=['index.html','index.html'];", None, "exact duplicate"),
            ("dup_relalias", "const ASSETS=['index.html','./index.html'];", None, "relative-alias duplicate"),
            ("dup_rootalias", "const ASSETS=['./','.'];", None, "root-alias (canonical) duplicate"),
        ]
        for name, line, ext, label in fail_cases:
            repo, (code, out) = sw_case(name, line, ext)
            check("ASSETS %s -> non-zero" % label, code != 0)
            check("ASSETS %s -> precache gate FAIL" % label, "FAIL  sw.js precache inventory verified" in out)
            check("ASSETS %s -> no manual steps" % label, "Manual Deploy" not in out)
            st = run_git(repo, "status", "--porcelain", "--untracked-files=all").stdout.strip()
            check("ASSETS %s -> repo unchanged" % label, st == "")
        # containment reason surfaced for a traversal case (rejected as unsafe, not merely missing)
        _, (_, tout) = sw_case("bslash_reason", "const ASSETS=['index.html','..\\\\outside.txt'];", "outside.txt")
        check("backslash traversal rejected as unsafe (containment, not missing)", "traversal" in tout)
        # duplicate reason clearly surfaced (raw dup and relative alias)
        _, (_, dout1) = sw_case("dup_reason1", "const ASSETS=['index.html','index.html'];")
        check("exact-duplicate reason visible", "duplicate" in dout1)
        _, (_, dout2) = sw_case("dup_reason2", "const ASSETS=['index.html','./index.html'];")
        check("relative-alias duplicate reason visible", "duplicate" in dout2)
        # current formatting with a trailing comma still passes
        _, (code, out) = sw_case("trailing_comma",
                                 "const ASSETS=['./','index.html','app.js','styles.css','data.js','sw.js','core/platform/platform.js',];")
        check("trailing-comma ASSETS passes (exit 0)", code == 0)
        check("trailing-comma: precache verified", "precache assets verified" in out)
        # the REAL production sw.js (all 36 entries) passes the actual helper's parser
        import importlib.util
        spec = importlib.util.spec_from_file_location("relcheck_mod", SRC)
        relmod = importlib.util.module_from_spec(spec); spec.loader.exec_module(relmod)
        r_swver, r_ok, r_detail, r_count = relmod.sw_inventory()
        check("real sw.js precache verified", r_ok is True)
        check("real sw.js has exactly 36 precache assets", r_count == 36)
        check("real sw.js cache is v35", r_swver == "hsk-flashcards-v35")

        # === Finding 3: git command failures fail closed ===
        # not a git work tree
        ng = os.path.join(base, "not_git"); os.makedirs(os.path.join(ng, "scripts"), exist_ok=True)
        shutil.copy(SRC, os.path.join(ng, "scripts", "release_check.py"))
        write(os.path.join(ng, "tests", "run_regression.py"), stub_regression(True))
        write(os.path.join(ng, "hsk_flashcard_app", "sw.js"), sw_js(SW_ASSETS))
        code, out = run_check(ng)
        check("non-git dir -> fail closed", code != 0)
        check("non-git: work-tree gate FAIL", "FAIL  inside a git work tree" in out)
        check("non-git: no manual steps", "Manual Deploy" not in out)
        # empty repo (no commit -> HEAD read fails) -> fail closed, never treated as clean
        er = os.path.join(base, "empty_repo"); os.makedirs(os.path.join(er, "scripts"), exist_ok=True)
        shutil.copy(SRC, os.path.join(er, "scripts", "release_check.py"))
        write(os.path.join(er, "tests", "run_regression.py"), stub_regression(True))
        write(os.path.join(er, "hsk_flashcard_app", "sw.js"), sw_js(SW_ASSETS))
        for f in SW_FILES: write(os.path.join(er, "hsk_flashcard_app", f), "// s\n")
        run_git(er, "init", "-q"); run_git(er, "branch", "-M", "main")
        code, out = run_check(er)
        check("empty repo (no HEAD) -> fail closed", code != 0)
        check("empty repo: no manual steps", "Manual Deploy" not in out)
        # source proof: clean is fail-closed (requires clean is True; status rc is checked)
        check("source: clean gate requires clean is True", 'inv.get("clean") is True' in srctext)
        check("source: git status failure is handled (rc-gated)", '"git status failed"' in srctext and "returncode != 0" in srctext)

        # 10) path with spaces still works
        rs = os.path.join(base, "dir with space", "the repo"); scaffold(rs)
        code, out = run_check(rs)
        check("path with spaces: exit 0", code == 0)
        check("path with spaces: RESULT PASS", "RESULT: PASS" in out)

        # 11) helper source performs no mutating/deploy operation, no network, no bypass
        bad = re.findall(r'git\(\s*["\'](push|fetch|pull|merge|rebase|reset|checkout|tag|clean|commit|apply|update-ref|branch)["\']', srctext)
        check("helper makes no mutating git calls", bad == [])
        check("helper imports no network libraries",
              not re.search(r'^\s*(import|from)\s+(urllib|requests|http|socket|ftplib|smtplib)\b', srctext, re.M))
        subcalls = re.findall(r'subprocess\.run\(\s*(\[[^\]]*\])', srctext)
        check("helper only spawns git or the regression runner", len(subcalls) >= 1 and
              all(('"git"' in s or "'git'" in s or "sys.executable" in s) for s in subcalls))
        check("no bypass flags", not any(x in srctext for x in ("skip-regression", "no-regression", "allow-dirty", "--force")))

    finally:
        shutil.rmtree(base, ignore_errors=True)

    print(json.dumps({"suite": "release_check", "pass": len(fails) == 0, "fails": fails}, ensure_ascii=False))
    return 0 if not fails else 1

if __name__ == "__main__":
    sys.exit(main())
