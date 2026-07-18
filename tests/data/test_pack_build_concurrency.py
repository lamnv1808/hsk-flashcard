#!/usr/bin/env python3
"""Phase 24D follow-up - canonical persistent per-pack single-writer locking.

Two review findings drive this suite.

FINDING 1 -- unlinking the lock file permits POSIX split-brain:
    A unlocks; B opens and locks the same inode (its identity check passes,
    because the pathname still resolves to that inode); A unlinks the pathname;
    C creates a new file there and locks the new inode. B and C both own the
    pack. No acquire-side check closes that window, so the lock file must be
    PERSISTENT and must never be unlinked.

FINDING 2 -- output-relative lock paths do not protect pack identity:
    the same packId under two --output roots took two different locks while
    still mutating the same ledger. Lock identity must be canonical.

Everything here uses REAL subprocesses and REAL kernel locks on real temporary
filesystems, under a path containing a space. Nothing is mocked, because an
in-process mock cannot demonstrate the property that matters most: that the OS
releases ownership when a process dies.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, os.path.join(ROOT, "tests", "support"))
sys.path.insert(0, os.path.join(ROOT, "tests", "fixtures", "packs"))

import packlib                                    # noqa: E402
from datajs import emit as emit_result            # noqa: E402
from contentpack.locking import (                 # noqa: E402
    LockPathRejected, PackLock, canonical_lock_path, lock_root, repo_root,
)

CLI = os.path.join(ROOT, "scripts", "build_content_pack.py")
SCRIPTS = os.path.join(ROOT, "scripts")

EXIT_OK, EXIT_FATAL, EXIT_USAGE = 0, 1, 2
EXIT_DRIFT, EXIT_NONDET, EXIT_RECOVERY, EXIT_LOCKED = 3, 4, 5, 6

ARTIFACTS = ("demo-content-pack.js", "demo-cards.js", "demo-source.csi.json",
             "qa-report.json", "qa-report.md", "registry-handoff.json")

# Holds the canonical pack lock until told to stop, or until killed.
HOLDER = '''
import os, sys, time
sys.path.insert(0, %(scripts)r)
from contentpack.locking import PackLock
lock = PackLock(%(pack)r)
lock.acquire()
open(%(ready)r, "w").write(lock.path)
while not os.path.exists(%(release)r):
    time.sleep(0.02)
lock.release()
'''

# Crashes abruptly after the durable commit point.
CRASHER = '''
import os, sys
sys.path.insert(0, %(scripts)r)
from contentpack.pipeline import Options, build

def fault(label):
    if label == %(label)r:
        raise RuntimeError(label)

try:
    build(Options(pack_id=%(pack)r, source=%(src)r, output=%(out)r, fault=fault),
          %(root)r)
except BaseException:
    pass
os._exit(9)
'''

# Plants a foreign journal exactly where ours would be created.
JOURNAL_SQUATTER = '''
import json, os, sys
sys.path.insert(0, %(scripts)r)
from contentpack import emit
from contentpack.pipeline import Options, build

def fault(label):
    if label == "before_journal":
        with open(emit.journal_path(%(out)r, %(pack)r), "w", encoding="utf-8") as fh:
            json.dump({"journalVersion": 1, "txid": "foreign"}, fh)

res = build(Options(pack_id=%(pack)r, source=%(src)r, output=%(out)r, fault=fault),
            %(root)r)
print(json.dumps(sorted({f.code for f in res.findings})))
'''

# Reports the canonical lock path plus the file's identity, from a separate
# process, so persistence across processes is observed rather than assumed.
PROBE = '''
import json, os, sys
sys.path.insert(0, %(scripts)r)
from contentpack.locking import PackLock, canonical_lock_path
path = canonical_lock_path(%(pack)r)
lock = PackLock(%(pack)r)
lock.acquire()
st = os.stat(path)
lock.release()
print(json.dumps({"path": path,
                  "exists_after_release": os.path.exists(path),
                  "ino": st.st_ino, "dev": st.st_dev}))
'''


def run_cli(args, cwd=ROOT):
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run([sys.executable, CLI] + args, cwd=cwd, env=env,
                          capture_output=True, text=True, encoding="utf-8")
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def run_child(script, cwd=None):
    proc = subprocess.run([sys.executable, script], cwd=cwd,
                          capture_output=True, text=True, encoding="utf-8")
    return proc.returncode, (proc.stdout or "").strip(), (proc.stderr or "")


def write_child(path, template, **kw):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(template % kw)
    return path


def spawn(script):
    return subprocess.Popen([sys.executable, script],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def wait_for(path, timeout=30.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if os.path.exists(path):
            return True
        time.sleep(0.02)
    return False


def snapshot(root):
    """Byte snapshot of a tree. The canonical lock lives outside every case."""
    out = {}
    if not os.path.isdir(root):
        return out
    for base, _dirs, files in os.walk(root):
        for name in files:
            full = os.path.join(base, name)
            with open(full, "rb") as fh:
                out[os.path.relpath(full, root).replace("\\", "/")] = fh.read()
    return out


def ledger_ids(path):
    with open(path, encoding="utf-8") as fh:
        return {k: v["cardId"] for k, v in json.load(fh)["entries"].items()}


def residue(parent, pack_id):
    """Transaction state that must not survive. The lock is NOT included: it is
    persistent by design and lives in the canonical root, not here."""
    found = []
    if os.path.exists(os.path.join(parent, ".txn-%s.json" % pack_id)):
        found.append("journal")
    for name in (".staging-%s" % pack_id, ".old-%s" % pack_id):
        if os.path.isdir(os.path.join(parent, name)):
            found.append(name)
    for base, _dirs, files in os.walk(parent):
        for name in files:
            if name.endswith(".tmp") or name.endswith(".txn"):
                found.append(os.path.join(base, name))
    return found


def stray_locks(root):
    """Any lock file created outside the canonical namespace is a defect."""
    found = []
    for base, _dirs, files in os.walk(root):
        for name in files:
            if name.startswith(".lock-") or name.endswith(".lock"):
                found.append(os.path.join(base, name))
    return found


def main():
    fails = []

    def check(name, cond):
        if not cond:
            fails.append(name)

    tmp = tempfile.mkdtemp(prefix="cpconc_")
    workspace = os.path.join(tmp, "work space")   # 14. path containing a space
    os.makedirs(workspace)

    def new_pack(name, pack_id="demo"):
        case = os.path.join(workspace, name)
        src = packlib.copy_csv_source("demo", os.path.join(case, "src"))
        if pack_id != "demo":
            packlib.edit_manifest(src, {"packId": pack_id, "courseId": pack_id})
        parent = os.path.join(case, "build")
        os.makedirs(parent, exist_ok=True)
        return src, os.path.join(parent, pack_id), parent

    def holder_for(pack_id, tag):
        ready = os.path.join(workspace, "ready_" + tag)
        release = os.path.join(workspace, "release_" + tag)
        proc = spawn(write_child(
            os.path.join(workspace, "holder_%s.py" % tag), HOLDER,
            scripts=SCRIPTS, pack=pack_id, ready=ready, release=release))
        return proc, ready, release

    try:
        # ================================================================
        # 17. Canonical path derivation and containment
        # ================================================================
        check("repo root is derived from the module location, not the CWD",
              os.path.realpath(repo_root()) == os.path.realpath(ROOT))
        check("lock root is the canonical build namespace",
              os.path.realpath(lock_root()) == os.path.realpath(
                  os.path.join(ROOT, "build", "content-packs", ".locks")))
        check("the same pack id always resolves to the same path",
              canonical_lock_path("demo") == canonical_lock_path("demo"))
        check("different pack ids resolve to different files",
              canonical_lock_path("demo") != canonical_lock_path("demo2"))
        check("lock path sits directly inside the canonical root",
              os.path.dirname(os.path.realpath(canonical_lock_path("demo")))
              == os.path.realpath(lock_root()))

        for bad in ("../escape", "..", "/abs", "C:\\abs", "a/b", "a\\b",
                    "Demo", "de mo", "", "de.mo", "-lead", "trail-",
                    "x" * 64, None, 17):
            try:
                canonical_lock_path(bad)
                fails.append("lock path accepted a malformed pack id %r" % (bad,))
            except LockPathRejected:
                pass

        # ================================================================
        # 6 + 9. The lock file is persistent and the same path is reused
        # ================================================================
        probe = write_child(os.path.join(workspace, "probe.py"), PROBE,
                            scripts=SCRIPTS, pack="demo")
        rc1, out1, _ = run_child(probe)
        rc2, out2, _ = run_child(probe, cwd=workspace)   # different CWD
        check("probe process 1 succeeded", rc1 == 0)
        check("probe process 2 succeeded", rc2 == 0)
        a, b = json.loads(out1), json.loads(out2)
        check("the lock file survives release", a["exists_after_release"] is True)
        check("the second process also leaves it in place",
              b["exists_after_release"] is True)
        check("the canonical path is identical across processes",
              a["path"] == b["path"] == canonical_lock_path("demo"))
        check("the canonical path does not depend on the CWD",
              a["path"] == b["path"])
        # 9. The SAME inode is reused; nothing recreated it, so nothing unlinked it.
        check("the same inode is reused across acquire/release cycles",
              (a["ino"], a["dev"]) == (b["ino"], b["dev"]))

        # 9. Static proof: production locking code contains no unlink path.
        with open(os.path.join(SCRIPTS, "contentpack", "locking.py"),
                  encoding="utf-8") as fh:
            lock_src = fh.read()
        for banned in ("os.remove", "os.unlink", "shutil.rmtree", "shell=True",
                       "import urllib", "import socket", "eval(", "exec("):
            if banned in lock_src:
                fails.append("locking.py contains %r" % banned)
        check("locking.py uses kernel primitives on both platforms",
              "msvcrt" in lock_src and "fcntl" in lock_src)
        check("release is documented as never unlinking",
              "NEVER unlink" in lock_src)

        # 8. A pre-existing but unlocked lock file must not block anything.
        src, out, parent = new_pack("preexisting")
        check("a lock file already exists from the probes",
              os.path.isfile(canonical_lock_path("demo")))
        rc, _ = run_cli(["--pack", "demo", "--source", src, "--output", out,
                         "--init-ledger"])
        check("an existing unlocked lock file does not block a build",
              rc == EXIT_OK)
        ledger = os.path.join(src, "demo-id-ledger.json")
        gen1_artifacts = snapshot(out)
        gen1_ledger = open(ledger, "rb").read()
        gen1_ids = ledger_ids(ledger)
        check("a clean build leaves no transaction residue",
              residue(parent, "demo") == [])
        check("no stray lock namespace was created next to the output",
              stray_locks(os.path.dirname(parent)) == [])

        # ================================================================
        # 1. Competitor gets BUILD_LOCKED and changes nothing
        # ================================================================
        holder, ready, release = holder_for("demo", "same")
        try:
            check("holder acquired the canonical lock", wait_for(ready))
            check("holder reported the canonical path",
                  open(ready).read().strip() == canonical_lock_path("demo"))
            before = snapshot(os.path.dirname(parent))

            rc, text = run_cli(["--pack", "demo", "--source", src, "--output", out])
            check("a competing build exits BUILD_LOCKED", rc == EXIT_LOCKED)
            check("the competitor names the condition", "BUILD_LOCKED" in text)
            check("the competitor's output stays ascii-safe",
                  all(ord(c) < 128 for c in text))
            check("a refused competitor changed nothing",
                  snapshot(os.path.dirname(parent)) == before)
            check("a refused competitor wrote no journal or staging",
                  residue(parent, "demo") == [])
            check("a refused competitor consumed no id",
                  ledger_ids(ledger) == gen1_ids)

            # 2. Same pack, DIFFERENT output root -> still contends.
            other_out = os.path.join(workspace, "other build", "demo")
            rc, text = run_cli(["--pack", "demo", "--source", src,
                                "--output", other_out])
            check("same pack under a different output root still contends",
                  rc == EXIT_LOCKED)
            check("no output was created under the alternative root",
                  not os.path.exists(other_out))
            check("no alternative lock namespace appeared",
                  stray_locks(workspace) == [])

            # 3. Same pack, DIFFERENT source path -> still contends.
            other_src = packlib.copy_csv_source(
                "demo", os.path.join(workspace, "other source"))
            rc, _ = run_cli(["--pack", "demo", "--source", other_src,
                             "--output", out])
            check("same pack from a different source still contends",
                  rc == EXIT_LOCKED)

            # 4. Same pack with a ledger override -> still contends, and no
            #    alternative lock namespace is created beside the ledger.
            alt_ledger = os.path.join(workspace, "alt ledger",
                                      "demo-id-ledger.json")
            os.makedirs(os.path.dirname(alt_ledger), exist_ok=True)
            shutil.copyfile(ledger, alt_ledger)
            rc, _ = run_cli(["--pack", "demo", "--source", src, "--output", out,
                             "--ledger", alt_ledger])
            check("a ledger override does not escape the canonical lock",
                  rc == EXIT_LOCKED)
            check("no lock namespace was created beside the override ledger",
                  stray_locks(os.path.dirname(alt_ledger)) == [])

            # 10. --recover must contend on the same canonical lock.
            rc, text = run_cli(["--pack", "demo", "--source", src,
                                "--output", out, "--recover"])
            check("--recover is refused while the pack is locked",
                  rc == EXIT_LOCKED)
            check("--recover changed nothing while refused",
                  snapshot(os.path.dirname(parent)) == before)

            # 16. --check now takes the same lock, and reports it honestly.
            rc, text = run_cli(["--pack", "demo", "--source", src,
                                "--output", out, "--check"])
            check("--check contends on the canonical lock", rc == EXIT_LOCKED)
            check("--check mutated no content state while refused",
                  snapshot(os.path.dirname(parent)) == before)
        finally:
            open(release, "w").write("go")
            holder.wait(timeout=30)

        # 6. The lock file is still there after the holder released it.
        check("the lock file persists after normal release",
              os.path.isfile(canonical_lock_path("demo")))

        # 16. --check with no competitor: no content-state mutation.
        before_case = snapshot(os.path.dirname(parent))
        rc, _ = run_cli(["--pack", "demo", "--source", src, "--output", out,
                         "--check"])
        check("--check succeeds once the lock is free", rc == EXIT_OK)
        check("--check mutated no ledger, artifact, report or source",
              snapshot(os.path.dirname(parent)) == before_case)

        # 2 (continued). Retry after release is byte-identical.
        rc, _ = run_cli(["--pack", "demo", "--source", src, "--output", out])
        check("retry after release succeeds", rc == EXIT_OK)
        check("retry is byte-identical", snapshot(out) == gen1_artifacts)
        check("retry preserves every id", ledger_ids(ledger) == gen1_ids)

        # ================================================================
        # 7. Crash release: kill the holder, file persists, no id burned
        # ================================================================
        holder, ready, release = holder_for("demo", "kill")
        check("kill-case holder acquired the lock", wait_for(ready))
        rc, _ = run_cli(["--pack", "demo", "--source", src, "--output", out])
        check("build is locked out while the holder lives", rc == EXIT_LOCKED)
        holder.kill()
        holder.wait(timeout=30)
        check("the lock file survives an abrupt kill",
              os.path.isfile(canonical_lock_path("demo")))
        rc, _ = run_cli(["--pack", "demo", "--source", src, "--output", out])
        check("killing the holder releases kernel ownership", rc == EXIT_OK)
        check("no id was consumed across the lockout",
              ledger_ids(ledger) == gen1_ids)
        check("output survives the lockout byte-identically",
              snapshot(out) == gen1_artifacts)

        # ================================================================
        # 5. Different pack ids proceed concurrently
        # ================================================================
        src_b = packlib.copy_csv_source("demo", os.path.join(workspace, "packB"))
        packlib.edit_manifest(src_b, {"packId": "demo2", "courseId": "demo2"})
        out_b = os.path.join(parent, "..", "demo2")

        holder, ready, release = holder_for("demo", "cross")
        try:
            check("cross-pack holder acquired the demo lock", wait_for(ready))
            rc, _ = run_cli(["--pack", "demo2", "--source", src_b,
                             "--output", out_b, "--init-ledger"])
            check("a different pack id builds while demo is locked",
                  rc == EXIT_OK)
            check("the other pack produced its own artifacts",
                  os.path.isfile(os.path.join(out_b, "demo2-cards.js")))
            rc, _ = run_cli(["--pack", "demo", "--source", src, "--output", out])
            check("the same pack id remains locked out", rc == EXIT_LOCKED)
        finally:
            open(release, "w").write("go")
            holder.wait(timeout=30)
        check("both canonical locks now exist side by side",
              os.path.isfile(canonical_lock_path("demo"))
              and os.path.isfile(canonical_lock_path("demo2")))

        # ================================================================
        # 11. Recovery after a terminated post-journal process
        # ================================================================
        src_c, out_c, parent_c = new_pack("crashed")
        rc, _ = run_cli(["--pack", "demo", "--source", src_c, "--output", out_c,
                         "--init-ledger"])
        check("crash-case baseline succeeds", rc == EXIT_OK)
        ledger_c = os.path.join(src_c, "demo-id-ledger.json")
        base_ids = ledger_ids(ledger_c)
        packlib.edit_cards(src_c, lambda rows: rows + [
            ["d-300", "L1", "after crash", "added before the crash",
             "", "", "", "", ""]])

        crasher = spawn(write_child(
            os.path.join(workspace, "crasher.py"), CRASHER, scripts=SCRIPTS,
            pack="demo", src=src_c, out=out_c, root=ROOT, label="after_journal"))
        crasher.wait(timeout=180)
        check("the crashing child exited abnormally", crasher.returncode == 9)
        check("the crash left a journal behind",
              os.path.isfile(os.path.join(parent_c, ".txn-demo.json")))
        check("the dead process released the kernel lock", not _held("demo"))

        rc, text = run_cli(["--pack", "demo", "--source", src_c, "--output", out_c])
        check("a build after the crash demands recovery", rc == EXIT_RECOVERY)
        check("the demand is actionable", "--recover" in text)
        rc, _ = run_cli(["--pack", "demo", "--source", src_c, "--output", out_c,
                         "--recover"])
        check("recovery after the crash succeeds", rc == EXIT_OK)
        check("recovery leaves no transaction residue",
              residue(parent_c, "demo") == [])
        after_ids = ledger_ids(ledger_c)
        check("recovery preserved every prior id",
              all(after_ids[k] == v for k, v in base_ids.items()))
        check("exactly one new id was allocated, none burned",
              max(after_ids.values()) == max(base_ids.values()) + 1)
        check("recovery produced one complete generation",
              sorted(snapshot(out_c)) == sorted(ARTIFACTS))

        # ================================================================
        # 12. Foreign journal is never overwritten
        # ================================================================
        src_d, out_d, parent_d = new_pack("squat")
        rc, _ = run_cli(["--pack", "demo", "--source", src_d, "--output", out_d,
                         "--init-ledger"])
        check("squat-case baseline succeeds", rc == EXIT_OK)
        ledger_d = os.path.join(src_d, "demo-id-ledger.json")
        d_ledger = open(ledger_d, "rb").read()
        d_artifacts = snapshot(out_d)
        packlib.edit_cards(src_d, lambda rows: rows + [
            ["d-400", "L1", "squat", "added for the squatter", "", "", "", "", ""]])

        rc, stdout, _ = run_child(write_child(
            os.path.join(workspace, "squatter.py"), JOURNAL_SQUATTER,
            scripts=SCRIPTS, pack="demo", src=src_d, out=out_d, root=ROOT))
        lines = stdout.splitlines()
        codes = json.loads(lines[-1]) if lines else []
        check("a foreign journal blocks the commit", "JOURNAL_EXISTS" in codes)
        check("the foreign journal was not overwritten",
              json.load(open(os.path.join(parent_d, ".txn-demo.json"),
                             encoding="utf-8")).get("txid") == "foreign")
        check("the blocked transaction discarded its own staging",
              not os.path.isdir(os.path.join(parent_d, ".staging-demo")))
        check("the blocked transaction did not touch the ledger",
              open(ledger_d, "rb").read() == d_ledger)
        check("the blocked transaction did not touch the artifacts",
              snapshot(out_d) == d_artifacts)

        # ================================================================
        # 13. Two simultaneous CI-style builds converge on one generation
        # ================================================================
        src_e, out_e, parent_e = new_pack("race")
        rc, _ = run_cli(["--pack", "demo", "--source", src_e, "--output", out_e,
                         "--init-ledger"])
        check("race-case baseline succeeds", rc == EXIT_OK)
        ledger_e = os.path.join(src_e, "demo-id-ledger.json")
        e_ids = ledger_ids(ledger_e)
        packlib.edit_cards(src_e, lambda rows: rows + [
            ["d-500", "L1", "raced", "added for the race", "", "", "", "", ""]])

        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        args = [sys.executable, CLI, "--pack", "demo", "--source", src_e,
                "--output", out_e]
        procs = [subprocess.Popen(args, cwd=ROOT, env=env,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                 for _ in range(2)]
        rcs = [p.wait(timeout=300) for p in procs]
        for p in procs:
            p.stdout.close()
            p.stderr.close()
        check("no racing build produced an unexpected exit code",
              all(c in (EXIT_OK, EXIT_LOCKED, EXIT_RECOVERY) for c in rcs))
        check("at least one racing build succeeded", EXIT_OK in rcs)
        if EXIT_RECOVERY in rcs:
            run_cli(["--pack", "demo", "--source", src_e, "--output", out_e,
                     "--recover"])
        final_ids = ledger_ids(ledger_e)
        check("the race preserved every prior id",
              all(final_ids[k] == v for k, v in e_ids.items()))
        check("the race allocated exactly one stable new id",
              max(final_ids.values()) == max(e_ids.values()) + 1)
        check("the race left no mixed artifact set",
              sorted(snapshot(out_e)) == sorted(ARTIFACTS))
        check("the race left no transaction residue",
              residue(parent_e, "demo") == [])

        rc, _ = run_cli(["--pack", "demo", "--source", src_e, "--output", out_e])
        check("a build after the race succeeds", rc == EXIT_OK)
        after_race = snapshot(out_e)
        rc, _ = run_cli(["--pack", "demo", "--source", src_e, "--output", out_e])
        check("rebuild after the race is byte-identical",
              snapshot(out_e) == after_race)

        # --qa-only holds the same lock and preserves the data artifacts.
        rc, _ = run_cli(["--pack", "demo", "--source", src_e, "--output", out_e,
                         "--qa-only"])
        check("qa-only succeeds under the canonical lock", rc == EXIT_OK)
        qa_tree = snapshot(out_e)
        check("qa-only preserved the data artifacts",
              all(qa_tree[n] == after_race[n] for n in
                  ("demo-cards.js", "demo-content-pack.js",
                   "demo-source.csi.json")))
        check("qa-only left no transaction residue",
              residue(parent_e, "demo") == [])

        # No invocation anywhere created a lock outside the canonical root.
        check("no stray lock file was created anywhere in the workspace",
              stray_locks(workspace) == [])

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    return emit_result("pack_build_concurrency", fails,
                       {"canonicalLockRoot": os.path.relpath(lock_root(), ROOT)
                        .replace("\\", "/")})


def _held(pack_id):
    """True if some live process still owns the canonical lock."""
    from contentpack.locking import LockBusy
    probe = PackLock(pack_id)
    try:
        probe.acquire()
    except LockBusy:
        return True
    probe.release()
    return False


if __name__ == "__main__":
    sys.exit(main())
