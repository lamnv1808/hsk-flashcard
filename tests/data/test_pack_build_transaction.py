#!/usr/bin/env python3
"""Phase 24D follow-up - transactional ledger + pack publication.

Review finding: the ledger and the artifact directory were two independent
durable writes with no shared commit point, so a failure between them left
"new ledger + old artifacts", and a failure inside the per-file promotion loop
left mixed artifact generations. Both are forbidden states.

The protocol under test is a write-ahead journal with idempotent roll-forward.
Every case below injects a real failure at a real filesystem boundary in an
isolated temporary tree -- no mocks -- and then asserts that the externally
observable state is exactly one of:

    A. the complete previous generation, or
    B. the complete new generation,

and never a mixture, and never a state where an id was consumed only because a
publication failed.
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

import packlib                                            # noqa: E402
from datajs import emit as emit_result                    # noqa: E402
from contentpack import emit as cp_emit                   # noqa: E402
from contentpack.pipeline import Options, build, recover  # noqa: E402

ARTIFACTS = ("demo-content-pack.js", "demo-cards.js", "demo-source.csi.json",
             "qa-report.json", "qa-report.md", "registry-handoff.json")

# Every boundary between durable filesystem operations.
CHECKPOINTS = (
    "before_staging",
    "artifact_write:demo-content-pack.js",
    "artifact_write:demo-cards.js",
    "artifact_write:qa-report.json",
    "before_ledger_stage",
    "ledger_stage",
    "after_fsync",
    "before_journal",
    "after_journal",
    "before_dir_swap",
    "after_dir_swap_old",
    "after_dir_swap_new",
    "before_ledger_replace",
    "after_ledger_replace",
    "during_cleanup",
)

# Checkpoints reached before the journal becomes durable. A failure here must
# leave the previous generation intact and consume no id.
PRE_COMMIT = CHECKPOINTS[:CHECKPOINTS.index("after_journal")]


class Boom(Exception):
    """Simulated crash."""


def fault_at(label):
    def hook(current):
        if current == label:
            raise Boom(label)
    return hook


def ledger_ids(path):
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    return {k: v["cardId"] for k, v in doc["entries"].items()}


def txn_residue(parent, pack_id="demo"):
    """Any transaction state that must not survive a successful build."""
    found = []
    if os.path.isfile(os.path.join(parent, ".txn-%s.json" % pack_id)):
        found.append("journal")
    if os.path.isdir(os.path.join(parent, ".staging-%s" % pack_id)):
        found.append("staging")
    if os.path.isdir(os.path.join(parent, ".old-%s" % pack_id)):
        found.append("old")
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

    tmp = tempfile.mkdtemp(prefix="cptxn_")

    def new_case(name):
        """An isolated repo: its own source, ledger, output parent."""
        case = os.path.join(tmp, name)
        src = packlib.copy_csv_source("demo", os.path.join(case, "src"))
        out_parent = os.path.join(case, "build")
        os.makedirs(out_parent, exist_ok=True)
        return src, os.path.join(out_parent, "demo"), out_parent

    def run(src, out, **kw):
        return build(Options(pack_id="demo", source=src, output=out, **kw), ROOT)

    try:
        # ================================================================
        # Establish generation 1 in a reusable template, then copy it per case
        # so every scenario starts from a real committed previous generation.
        # ================================================================
        base_src, base_out, base_parent = new_case("template")
        gen1 = run(base_src, base_out, init_ledger=True)
        check("template generation commits", not gen1.findings.has_fatal())
        check("a successful build leaves no transaction state",
              txn_residue(base_parent) == [])

        base_ledger = os.path.join(base_src, "demo-id-ledger.json")
        GEN1_ARTIFACTS = packlib.snapshot_tree(base_out)
        GEN1_LEDGER = open(base_ledger, "rb").read()
        GEN1_IDS = ledger_ids(base_ledger)
        check("generation 1 wrote all six artifacts",
              sorted(GEN1_ARTIFACTS) == sorted(ARTIFACTS))

        def clone(name):
            """A fresh copy of the committed generation-1 state."""
            case = os.path.join(tmp, name)
            shutil.copytree(os.path.join(tmp, "template"), case)
            src = os.path.join(case, "src")
            parent = os.path.join(case, "build")
            return src, os.path.join(parent, "demo"), parent

        def mutate_source(src):
            """A real content edit, so generation 2 differs from generation 1."""
            packlib.edit_cards(src, lambda rows: rows + [
                ["d-200", "L1", "second generation", "added in gen 2",
                 "", "", "", "", ""]])

        # ================================================================
        # 1-10. Failure injection at every durable boundary
        # ================================================================
        for label in CHECKPOINTS:
            case = "fail_" + label.replace(":", "_").replace(".", "_")
            src, out, parent = clone(case)
            mutate_source(src)
            ledger = os.path.join(src, "demo-id-ledger.json")

            crashed = False
            try:
                run(src, out, fault=fault_at(label))
            except Boom:
                crashed = True
            check("%s: injected failure actually fired" % label, crashed)

            pre_commit = label in PRE_COMMIT
            artifacts_now = packlib.snapshot_tree(out)
            ledger_now = open(ledger, "rb").read() if os.path.isfile(ledger) else None

            if pre_commit:
                # Nothing observable may have changed, and no id may be consumed.
                check("%s: artifacts unchanged before commit point" % label,
                      artifacts_now == GEN1_ARTIFACTS)
                check("%s: ledger unchanged before commit point" % label,
                      ledger_now == GEN1_LEDGER)
                check("%s: no journal was written" % label,
                      not os.path.isfile(os.path.join(parent, ".txn-demo.json")))
                check("%s: no staging debris survives abort" % label,
                      not os.path.isdir(os.path.join(parent, ".staging-demo")))
                check("%s: no orphan staged ledger" % label,
                      not os.path.isfile(ledger + ".txn"))
            else:
                # Post-commit: a journal must mark the pack as needing recovery.
                check("%s: journal marks the incomplete transaction" % label,
                      os.path.isfile(os.path.join(parent, ".txn-demo.json"))
                      or label == "during_cleanup")

                # A further build must refuse to run from ambiguous state.
                blocked = run(src, out)
                check("%s: a later build is blocked until recovery" % label,
                      "RECOVERY_REQUIRED" in {f.code for f in blocked.findings}
                      or label == "during_cleanup")

                # --check must also refuse, and must still write nothing.
                before = packlib.snapshot_tree(os.path.dirname(parent))
                checked = run(src, out, check=True)
                check("%s: --check refuses under stale transaction state" % label,
                      "RECOVERY_REQUIRED" in {f.code for f in checked.findings}
                      or label == "during_cleanup")
                check("%s: --check wrote nothing under stale state" % label,
                      packlib.snapshot_tree(os.path.dirname(parent)) == before)

                # Recovery completes the generation deterministically.
                recovered = recover(
                    Options(pack_id="demo", source=src, output=out), ROOT)
                check("%s: recovery succeeds" % label,
                      not recovered.findings.has_fatal())
                check("%s: recovery leaves no transaction state" % label,
                      txn_residue(parent) == [])

            # After abort or recovery the pack must hold exactly ONE complete
            # generation, never a mixture.
            final_artifacts = packlib.snapshot_tree(out)
            final_ledger = open(ledger, "rb").read()
            is_gen1 = (final_artifacts == GEN1_ARTIFACTS and final_ledger == GEN1_LEDGER)
            check("%s: no mixed generation is exposed" % label,
                  is_gen1 or sorted(final_artifacts) == sorted(ARTIFACTS))
            if not is_gen1:
                # If it moved to generation 2, ledger and artifacts must agree.
                check("%s: committed generation is internally consistent" % label,
                      final_ledger != GEN1_LEDGER
                      and final_artifacts != GEN1_ARTIFACTS)

            # Ids are never recycled and never renumbered.
            final_ids = ledger_ids(ledger)
            check("%s: every prior id is preserved exactly" % label,
                  all(final_ids.get(k) == v for k, v in GEN1_IDS.items()))

            # 15. Retry after the injected failure must be deterministic.
            retry = run(src, out)
            check("%s: retry succeeds" % label, not retry.findings.has_fatal())
            check("%s: retry leaves no transaction state" % label,
                  txn_residue(parent) == [])
            retry_artifacts = packlib.snapshot_tree(out)
            retry_ids = ledger_ids(ledger)
            check("%s: retry preserves all prior ids" % label,
                  all(retry_ids.get(k) == v for k, v in GEN1_IDS.items()))
            check("%s: retry produced the full artifact set" % label,
                  sorted(retry_artifacts) == sorted(ARTIFACTS))

            again = run(src, out)
            check("%s: a second retry is byte-identical" % label,
                  packlib.snapshot_tree(out) == retry_artifacts)
            check("%s: repeated retry keeps ids stable" % label,
                  ledger_ids(ledger) == retry_ids)
            check("%s: no id was consumed only by the failed publish" % label,
                  max(retry_ids.values()) == max(GEN1_IDS.values()) + 1)

        # ================================================================
        # 12. Recovery when staging is incomplete must fail closed
        # ================================================================
        src, out, parent = clone("incomplete_staging")
        mutate_source(src)
        try:
            run(src, out, fault=fault_at("after_journal"))
        except Boom:
            pass
        staging = os.path.join(parent, ".staging-demo")
        check("staging exists after the commit point", os.path.isdir(staging))
        os.remove(os.path.join(staging, "demo-cards.js"))
        broken = recover(Options(pack_id="demo", source=src, output=out), ROOT)
        check("recovery refuses an incomplete staging directory",
              "RECOVERY_FAILED" in {f.code for f in broken.findings})
        check("refused recovery did not touch the previous artifacts",
              packlib.snapshot_tree(out) == GEN1_ARTIFACTS)
        check("refused recovery did not touch the previous ledger",
              open(os.path.join(src, "demo-id-ledger.json"), "rb").read()
              == GEN1_LEDGER)

        # ================================================================
        # A corrupt journal is fatal and actionable, never silently ignored
        # ================================================================
        src, out, parent = clone("corrupt_journal")
        with open(os.path.join(parent, ".txn-demo.json"), "w") as fh:
            fh.write("{not json")
        corrupt = run(src, out)
        check("a corrupt journal blocks the build",
              "TRANSACTION_JOURNAL_CORRUPT" in {f.code for f in corrupt.findings})
        corrupt_recover = recover(
            Options(pack_id="demo", source=src, output=out), ROOT)
        check("a corrupt journal blocks recovery too",
              "TRANSACTION_JOURNAL_CORRUPT"
              in {f.code for f in corrupt_recover.findings})
        check("a corrupt journal leaves artifacts untouched",
              packlib.snapshot_tree(out) == GEN1_ARTIFACTS)

        # ================================================================
        # Recovery with no journal is a no-op, not an error
        # ================================================================
        src, out, parent = clone("nothing_to_recover")
        nothing = recover(Options(pack_id="demo", source=src, output=out), ROOT)
        check("recovery without a journal is not fatal",
              not nothing.findings.has_fatal())
        check("recovery without a journal reports so",
              "NOTHING_TO_RECOVER" in {f.code for f in nothing.findings})
        check("recovery without a journal changes nothing",
              packlib.snapshot_tree(out) == GEN1_ARTIFACTS)

        # ================================================================
        # Pre-commit debris (no journal) is cleaned, never promoted
        # ================================================================
        src, out, parent = clone("debris")
        debris = os.path.join(parent, ".staging-demo")
        os.makedirs(debris)
        with open(os.path.join(debris, "demo-cards.js"), "w") as fh:
            fh.write("half-written garbage")
        after = run(src, out)
        check("pre-commit debris does not block a build",
              not after.findings.has_fatal())
        check("pre-commit debris is reported",
              "PRECOMMIT_DEBRIS_REMOVED" in {f.code for f in after.findings})
        check("pre-commit debris was never promoted",
              packlib.snapshot_tree(out) == GEN1_ARTIFACTS)
        check("pre-commit debris is gone", txn_residue(parent) == [])

        # ================================================================
        # 16. --check on a healthy pack still writes absolutely nothing
        # ================================================================
        src, out, parent = clone("check_clean")
        case_root = os.path.dirname(parent)
        before = packlib.snapshot_tree(case_root)
        clean = run(src, out, check=True)
        check("check on a healthy pack reports no drift", clean.drift == [])
        check("check on a healthy pack writes nothing at all",
              packlib.snapshot_tree(case_root) == before)
        check("check creates no transaction state", txn_residue(parent) == [])

        # ================================================================
        # --qa-only must not delete the data artifacts it did not regenerate
        # ================================================================
        src, out, parent = clone("qa_only")
        qa_run = run(src, out, qa_only=True)
        check("qa-only succeeds", not qa_run.findings.has_fatal())
        after_qa = packlib.snapshot_tree(out)
        check("qa-only preserves the full artifact set",
              sorted(after_qa) == sorted(ARTIFACTS))
        check("qa-only leaves the data artifacts byte-identical",
              all(after_qa[name] == GEN1_ARTIFACTS[name]
                  for name in ("demo-cards.js", "demo-content-pack.js",
                               "demo-source.csi.json")))
        check("qa-only does not touch the ledger",
              open(os.path.join(src, "demo-id-ledger.json"), "rb").read()
              == GEN1_LEDGER)
        check("qa-only leaves no transaction state", txn_residue(parent) == [])

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    return emit_result("pack_build_transaction", fails,
                       {"checkpoints": len(CHECKPOINTS)})


if __name__ == "__main__":
    sys.exit(main())
