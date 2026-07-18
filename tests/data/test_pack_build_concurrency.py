#!/usr/bin/env python3
"""Phase 24D follow-up 2 - cross-process single-writer concurrency.

Review finding: the journaled transaction fixed the split-write failure, but a
journal-presence check is not a lock. Two processes could both read the journal
path, both see nothing, both read the same ledger, both allocate the same ids,
both write into the same staging directory, and then race to create the journal
-- publishing one transaction's staged bytes under another's record.

Everything here uses REAL subprocesses and REAL kernel locks on real temporary
filesystems. Nothing is mocked, because an in-process mock cannot demonstrate
the one property that matters: that the OS releases ownership when a process
dies.
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

CLI = os.path.join(ROOT, "scripts", "build_content_pack.py")

EXIT_OK, EXIT_FATAL, EXIT_USAGE = 0, 1, 2
EXIT_DRIFT, EXIT_NONDET, EXIT_RECOVERY, EXIT_LOCKED = 3, 4, 5, 6

ARTIFACTS = ("demo-content-pack.js", "demo-cards.js", "demo-source.csi.json",
             "qa-report.json", "qa-report.md", "registry-handoff.json")

# A child that takes the pack lock, announces itself, and then waits to be told
# to stop -- or to be killed outright.
HOLDER = '''
import os, sys, time
sys.path.insert(0, %(scripts)r)
from contentpack.locking import PackLock
lock = PackLock(%(out)r, %(pack)r)
lock.acquire()
open(%(ready)r, "w").write("held")
while not os.path.exists(%(release)r):
    time.sleep(0.02)
lock.release()
'''

# A child that crashes abruptly after the durable commit point, so recovery has
# something real to roll forward.
CRASHER = '''
import os, sys
sys.path.insert(0, %(scripts)r)
from contentpack.pipeline import Options, build

class Boom(Exception):
    pass

def fault(label):
    if label == %(label)r:
        raise Boom(label)

try:
    build(Options(pack_id=%(pack)r, source=%(src)r, output=%(out)r, fault=fault),
          %(root)r)
except BaseException:
    pass
os._exit(9)
'''

# A child that plants a foreign journal at the moment ours would be created,
# proving the O_EXCL guard refuses to overwrite another transaction.
JOURNAL_SQUATTER = '''
import json, os, sys
sys.path.insert(0, %(scripts)r)
from contentpack import emit
from contentpack.pipeline import Options, build

def fault(label):
    if label == "before_journal":
        path = emit.journal_path(%(out)r, %(pack)r)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"journalVersion": 1, "txid": "foreign"}, fh)

res = build(Options(pack_id=%(pack)r, source=%(src)r, output=%(out)r, fault=fault),
            %(root)r)
codes = sorted({f.code for f in res.findings})
print(json.dumps(codes))
'''


def run_cli(args, cwd=ROOT):
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run([sys.executable, CLI] + args, cwd=cwd, env=env,
                          capture_output=True, text=True, encoding="utf-8")
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


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
    """Byte snapshot of a tree, excluding live lock infrastructure.

    The lock file is deliberately skipped: while a competitor holds it the OS
    refuses to read it, and its bytes carry no state anyway. Its absence after
    a successful build is asserted separately by residue().
    """
    out = {}
    if not os.path.isdir(root):
        return out
    for base, _dirs, files in os.walk(root):
        for name in files:
            if name.startswith(".lock-"):
                continue
            full = os.path.join(base, name)
            with open(full, "rb") as fh:
                out[os.path.relpath(full, root).replace("\\", "/")] = fh.read()
    return out


def ledger_ids(path):
    with open(path, encoding="utf-8") as fh:
        return {k: v["cardId"] for k, v in json.load(fh)["entries"].items()}


def residue(parent, pack_id):
    """Lock, journal, staging, old and txn state that must not survive."""
    found = []
    for name in (".lock-%s" % pack_id, ".txn-%s.json" % pack_id):
        if os.path.exists(os.path.join(parent, name)):
            found.append(name)
    for name in (".staging-%s" % pack_id, ".old-%s" % pack_id):
        if os.path.isdir(os.path.join(parent, name)):
            found.append(name)
    for base, _dirs, files in os.walk(parent):
        for name in files:
            if name.endswith(".tmp") or name.endswith(".txn"):
                found.append(os.path.join(base, name))
    return found


def main():
    fails = []

    def check(name, cond):
        if not cond:
            fails.append(name)

    # A path containing a space, exercised for the whole suite rather than as a
    # single afterthought case.
    tmp = tempfile.mkdtemp(prefix="cpconc_")
    workspace = os.path.join(tmp, "work space")
    os.makedirs(workspace)

    def new_pack(name, pack_id="demo"):
        case = os.path.join(workspace, name)
        src = packlib.copy_csv_source("demo", os.path.join(case, "src"))
        if pack_id != "demo":
            packlib.edit_manifest(src, {"packId": pack_id, "courseId": pack_id})
        parent = os.path.join(case, "build")
        os.makedirs(parent, exist_ok=True)
        return src, os.path.join(parent, pack_id), parent

    try:
        # ================================================================
        # 1. A competitor fails fast with BUILD_LOCKED and writes nothing
        # ================================================================
        src, out, parent = new_pack("locked")
        rc, _ = run_cli(["--pack", "demo", "--source", src, "--output", out,
                         "--init-ledger"])
        check("baseline build succeeds", rc == EXIT_OK)
        ledger = os.path.join(src, "demo-id-ledger.json")
        gen1_artifacts = snapshot(out)
        gen1_ledger = open(ledger, "rb").read()
        gen1_ids = ledger_ids(ledger)
        check("a clean build leaves no lock or transaction residue",
              residue(parent, "demo") == [])

        ready = os.path.join(workspace, "ready1")
        release = os.path.join(workspace, "release1")
        holder = spawn(write_child(
            os.path.join(workspace, "holder1.py"), HOLDER,
            scripts=os.path.join(ROOT, "scripts"), out=out, pack="demo",
            ready=ready, release=release))
        try:
            check("holder child acquired the lock", wait_for(ready))
            before_tree = snapshot(os.path.dirname(parent))

            rc, text = run_cli(["--pack", "demo", "--source", src,
                                "--output", out])
            check("a competing build exits BUILD_LOCKED", rc == EXIT_LOCKED)
            check("the competitor names the condition", "BUILD_LOCKED" in text)
            check("the competitor's output is ascii-safe",
                  all(ord(c) < 128 for c in text))

            # 8. Nothing the competitor touched may have changed.
            check("a refused competitor changed nothing at all",
                  snapshot(os.path.dirname(parent)) == before_tree)
            check("a refused competitor wrote no journal",
                  not os.path.exists(os.path.join(parent, ".txn-demo.json")))
            check("a refused competitor wrote no staging",
                  not os.path.isdir(os.path.join(parent, ".staging-demo")))
            check("a refused competitor did not touch the ledger",
                  open(ledger, "rb").read() == gen1_ledger)
            check("a refused competitor consumed no id",
                  ledger_ids(ledger) == gen1_ids)

            # 4. --recover must refuse against a live lock holder.
            rc, text = run_cli(["--pack", "demo", "--source", src,
                                "--output", out, "--recover"])
            check("--recover is refused while the pack is locked",
                  rc == EXIT_LOCKED)
            check("--recover names the condition", "BUILD_LOCKED" in text)
            check("--recover changed nothing while refused",
                  snapshot(os.path.dirname(parent)) == before_tree)

            # --check is read-only and deliberately lock-free: it must still
            # work, and must still write nothing, during a concurrent hold.
            rc, _ = run_cli(["--pack", "demo", "--source", src,
                             "--output", out, "--check"])
            check("--check runs without the lock", rc == EXIT_OK)
            check("--check wrote nothing during a concurrent hold",
                  snapshot(os.path.dirname(parent)) == before_tree)
        finally:
            open(release, "w").write("go")
            holder.wait(timeout=30)

        # ================================================================
        # 2. After the holder exits, a retry succeeds and is byte-identical
        # ================================================================
        rc, _ = run_cli(["--pack", "demo", "--source", src, "--output", out])
        check("retry after the lock is released succeeds", rc == EXIT_OK)
        check("retry is byte-identical", snapshot(out) == gen1_artifacts)
        check("retry preserves every id", ledger_ids(ledger) == gen1_ids)
        check("retry leaves no residue", residue(parent, "demo") == [])

        # ================================================================
        # 5. Killing the holder releases kernel ownership
        # ================================================================
        ready = os.path.join(workspace, "ready2")
        release = os.path.join(workspace, "release2")
        holder = spawn(write_child(
            os.path.join(workspace, "holder2.py"), HOLDER,
            scripts=os.path.join(ROOT, "scripts"), out=out, pack="demo",
            ready=ready, release=release))
        check("second holder acquired the lock", wait_for(ready))
        rc, _ = run_cli(["--pack", "demo", "--source", src, "--output", out])
        check("build is locked out while the holder lives", rc == EXIT_LOCKED)
        holder.kill()
        holder.wait(timeout=30)
        rc, _ = run_cli(["--pack", "demo", "--source", src, "--output", out])
        check("killing the holder releases the lock", rc == EXIT_OK)
        check("no id was consumed across the lockout",
              ledger_ids(ledger) == gen1_ids)
        check("output survives the lockout byte-identically",
              snapshot(out) == gen1_artifacts)

        # ================================================================
        # 3. Different pack ids do not block each other
        # ================================================================
        src_a, out_a, parent_a = new_pack("packA", "demo")
        rc, _ = run_cli(["--pack", "demo", "--source", src_a, "--output", out_a,
                         "--init-ledger"])
        check("pack A baseline succeeds", rc == EXIT_OK)

        # demo2 shares the same output parent, so only the pack-scoped lock
        # name keeps them apart.
        src_b = packlib.copy_csv_source("demo", os.path.join(
            workspace, "packB_src"))
        packlib.edit_manifest(src_b, {"packId": "demo2", "courseId": "demo2"})
        out_b = os.path.join(parent_a, "demo2")

        ready = os.path.join(workspace, "ready3")
        release = os.path.join(workspace, "release3")
        holder = spawn(write_child(
            os.path.join(workspace, "holder3.py"), HOLDER,
            scripts=os.path.join(ROOT, "scripts"), out=out_a, pack="demo",
            ready=ready, release=release))
        try:
            check("pack A holder acquired the lock", wait_for(ready))
            rc, _ = run_cli(["--pack", "demo2", "--source", src_b,
                             "--output", out_b, "--init-ledger"])
            check("a different pack id builds while pack A is locked",
                  rc == EXIT_OK)
            check("the other pack produced its own artifacts",
                  os.path.isfile(os.path.join(out_b, "demo2-cards.js")))
            rc, _ = run_cli(["--pack", "demo", "--source", src_a,
                             "--output", out_a])
            check("the same pack id is still locked out", rc == EXIT_LOCKED)
        finally:
            open(release, "w").write("go")
            holder.wait(timeout=30)
        check("no cross-pack residue remains", residue(parent_a, "demo2") == [])

        # ================================================================
        # 6. Recovery after a terminated post-journal process, no id burn
        # ================================================================
        src_c, out_c, parent_c = new_pack("crashed")
        rc, _ = run_cli(["--pack", "demo", "--source", src_c, "--output", out_c,
                         "--init-ledger"])
        check("crash-case baseline succeeds", rc == EXIT_OK)
        ledger_c = os.path.join(src_c, "demo-id-ledger.json")
        base_ids = ledger_ids(ledger_c)
        base_artifacts = snapshot(out_c)
        packlib.edit_cards(src_c, lambda rows: rows + [
            ["d-300", "L1", "after crash", "added before the crash",
             "", "", "", "", ""]])

        crasher = spawn(write_child(
            os.path.join(workspace, "crasher.py"), CRASHER,
            scripts=os.path.join(ROOT, "scripts"), pack="demo", src=src_c,
            out=out_c, root=ROOT, label="after_journal"))
        crasher.wait(timeout=120)
        check("the crashing child exited abnormally", crasher.returncode == 9)
        check("the crash left a journal behind",
              os.path.isfile(os.path.join(parent_c, ".txn-demo.json")))
        check("the dead process released its lock",
              not _lock_held(out_c, "demo"))

        rc, text = run_cli(["--pack", "demo", "--source", src_c,
                            "--output", out_c])
        check("a build after the crash demands recovery", rc == EXIT_RECOVERY)
        check("the demand is actionable", "--recover" in text)

        rc, _ = run_cli(["--pack", "demo", "--source", src_c, "--output", out_c,
                         "--recover"])
        check("recovery after the crash succeeds", rc == EXIT_OK)
        check("recovery leaves no residue", residue(parent_c, "demo") == [])
        after_ids = ledger_ids(ledger_c)
        check("recovery preserved every pre-existing id",
              all(after_ids[k] == v for k, v in base_ids.items()))
        check("exactly one new id was allocated, none burned",
              max(after_ids.values()) == max(base_ids.values()) + 1)
        check("recovery produced the full artifact set",
              sorted(snapshot(out_c)) == sorted(ARTIFACTS))
        check("recovery changed the generation",
              snapshot(out_c) != base_artifacts)

        rc, _ = run_cli(["--pack", "demo", "--source", src_c, "--output", out_c])
        check("a normal build works again after recovery", rc == EXIT_OK)
        check("ids remain stable after recovery", ledger_ids(ledger_c) == after_ids)

        # ================================================================
        # 7. An existing journal is never overwritten
        # ================================================================
        src_d, out_d, parent_d = new_pack("squat")
        rc, _ = run_cli(["--pack", "demo", "--source", src_d, "--output", out_d,
                         "--init-ledger"])
        check("squat-case baseline succeeds", rc == EXIT_OK)
        ledger_d = os.path.join(src_d, "demo-id-ledger.json")
        d_ledger_before = open(ledger_d, "rb").read()
        d_artifacts_before = snapshot(out_d)
        packlib.edit_cards(src_d, lambda rows: rows + [
            ["d-400", "L1", "squat", "added for the squatter case",
             "", "", "", "", ""]])

        proc = subprocess.run(
            [sys.executable, write_child(
                os.path.join(workspace, "squatter.py"), JOURNAL_SQUATTER,
                scripts=os.path.join(ROOT, "scripts"), pack="demo", src=src_d,
                out=out_d, root=ROOT)],
            capture_output=True, text=True, encoding="utf-8")
        emitted = (proc.stdout or "").strip().splitlines()
        codes = json.loads(emitted[-1]) if emitted else []
        check("a foreign journal blocks the commit",
              "JOURNAL_EXISTS" in codes)
        check("the foreign journal was not overwritten",
              json.load(open(os.path.join(parent_d, ".txn-demo.json"),
                             encoding="utf-8")).get("txid") == "foreign")
        check("the blocked transaction discarded its own staging",
              not os.path.isdir(os.path.join(parent_d, ".staging-demo")))
        check("the blocked transaction did not touch the ledger",
              open(ledger_d, "rb").read() == d_ledger_before)
        check("the blocked transaction did not touch the artifacts",
              snapshot(out_d) == d_artifacts_before)

        # ================================================================
        # A genuine simultaneous race: launch two real CLI builds at once
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
        rcs = [p.wait(timeout=180) for p in procs]
        for p in procs:
            p.stdout.close()
            p.stderr.close()
        check("no racing build produced an unexpected exit code",
              all(code in (EXIT_OK, EXIT_LOCKED, EXIT_RECOVERY) for code in rcs))
        check("at least one racing build succeeded", EXIT_OK in rcs)
        # Whether they serialized or one was refused, the outcome must be a
        # single consistent generation with exactly one new id.
        if EXIT_RECOVERY in rcs:
            run_cli(["--pack", "demo", "--source", src_e, "--output", out_e,
                     "--recover"])
        final_ids = ledger_ids(ledger_e)
        check("the race preserved every pre-existing id",
              all(final_ids[k] == v for k, v in e_ids.items()))
        check("the race allocated exactly one new id",
              max(final_ids.values()) == max(e_ids.values()) + 1)
        check("the race left a complete artifact set",
              sorted(snapshot(out_e)) == sorted(ARTIFACTS))
        check("the race left no residue", residue(parent_e, "demo") == [])

        rc, _ = run_cli(["--pack", "demo", "--source", src_e, "--output", out_e])
        check("a build after the race succeeds", rc == EXIT_OK)
        after_race = snapshot(out_e)
        rc, _ = run_cli(["--pack", "demo", "--source", src_e, "--output", out_e])
        check("rebuild after the race is byte-identical",
              snapshot(out_e) == after_race)

        # ================================================================
        # 10. --qa-only still takes the lock and preserves the data artifacts
        # ================================================================
        rc, _ = run_cli(["--pack", "demo", "--source", src_e, "--output", out_e,
                         "--qa-only"])
        check("qa-only succeeds under the lock", rc == EXIT_OK)
        qa_tree = snapshot(out_e)
        check("qa-only preserved the data artifacts",
              all(qa_tree[n] == after_race[n] for n in
                  ("demo-cards.js", "demo-content-pack.js",
                   "demo-source.csi.json")))
        check("qa-only left no residue", residue(parent_e, "demo") == [])

        # ================================================================
        # 12. Source hygiene
        # ================================================================
        lock_src = os.path.join(ROOT, "scripts", "contentpack", "locking.py")
        with open(lock_src, encoding="utf-8") as fh:
            text = fh.read()
        for banned in ("shell=True", "import urllib", "import requests",
                       "import socket", "eval(", "exec("):
            if banned in text:
                fails.append("locking.py contains %r" % banned)
        check("locking.py uses a kernel primitive on this platform",
              ("msvcrt" in text and "fcntl" in text))

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    return emit_result("pack_build_concurrency", fails)


def _lock_held(output_dir, pack_id):
    """True if some live process still owns the lock."""
    from contentpack.locking import LockBusy, PackLock
    probe = PackLock(output_dir, pack_id)
    try:
        probe.acquire()
    except LockBusy:
        return True
    probe.release()
    return False


if __name__ == "__main__":
    sys.exit(main())
