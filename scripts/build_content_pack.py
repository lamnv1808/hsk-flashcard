#!/usr/bin/env python3
"""Deterministic Excel/CSV -> ContentPack v1 build pipeline (Phase 24D).

Build-time tooling. It writes NOTHING inside hsk_flashcard_app/, adds no runtime
asset, and does not touch the service worker. Promotion of a generated pack into
the runtime, the pack registry and the SW cache bump are owned by Phase 24E.

Usage:
    python scripts/build_content_pack.py --pack <packId> [options]

Exit codes:
    0  success
    1  fatal validation failure (no output written)
    2  usage / environment / dependency failure
    3  --check found drift between the source and the committed output
    4  --verify-deterministic found a byte difference between two builds
    5  an incomplete publication transaction is present; run --recover
    6  another process holds this pack's single-writer lock (BUILD_LOCKED)

Console output is ASCII-only so a Windows cp1252 console cannot crash a build.
Non-ASCII content appears only inside the UTF-8 artifacts.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from contentpack import schema                      # noqa: E402
from contentpack.findings import (                  # noqa: E402
    FATAL, LAUNCH_BLOCKING, WARNING, INFO, ascii_safe,
)
from contentpack.pipeline import (                # noqa: E402
    Options, build, recover, verify_deterministic,
)

EXIT_OK = 0
EXIT_FATAL = 1
EXIT_USAGE = 2
EXIT_DRIFT = 3
EXIT_NONDETERMINISTIC = 4
EXIT_RECOVERY_REQUIRED = 5
EXIT_LOCKED = 6

# Codes that mean "the tool could not run", as opposed to "the content is wrong".
ENVIRONMENT_CODES = frozenset((
    "MISSING_DEPENDENCY",
    "SOURCE_NOT_FOUND",
    "UNSUPPORTED_SOURCE",
    "OUTPUT_PATH_ESCAPE",
))

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def out(line=""):
    sys.stdout.write(ascii_safe(line) + "\n")


def err(line=""):
    sys.stderr.write(ascii_safe(line) + "\n")


def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog="build_content_pack.py",
        description="Deterministic Excel/CSV -> ContentPack v1 pipeline.")
    parser.add_argument("--pack", required=True,
                        help="pack id (lower-case identifier)")
    parser.add_argument("--source",
                        help="a .xlsx workbook, or a directory containing "
                             "manifest.csv / cards.csv / optional levels.csv "
                             "(default: source_data/<packId>)")
    parser.add_argument("--output",
                        help="output directory "
                             "(default: build/content-packs/<packId>)")
    parser.add_argument("--ledger",
                        help="identity ledger path "
                             "(default: <source dir>/<packId>-id-ledger.json)")
    parser.add_argument("--check", action="store_true",
                        help="no-write mode: build in memory and report drift")
    parser.add_argument("--verify-deterministic", action="store_true",
                        help="build twice and compare every artifact byte-wise")
    parser.add_argument("--qa-only", action="store_true",
                        help="emit only the QA report; no runtime artifacts, "
                             "no ledger update")
    parser.add_argument("--force", action="store_true",
                        help="overwrite an output directory holding files this "
                             "pipeline did not produce")
    parser.add_argument("--allow-removals", action="store_true",
                        help="retire ledger entries whose cards are gone from "
                             "the source (their ids are never reused)")
    parser.add_argument("--init-ledger", action="store_true",
                        help="create a new ledger; only for a genuinely new "
                             "pack, never to recover from a lost one")
    parser.add_argument("--recover", action="store_true",
                        help="complete an interrupted publication. Idempotent "
                             "and deterministic; leaves exactly one complete "
                             "generation and no transaction state.")
    parser.add_argument("--generated-at",
                        help="release tooling only: ISO-8601 stamp recorded in "
                             "QA/handoff metadata. Never enters a runtime asset "
                             "or any content-identity checksum.")
    return parser.parse_args(argv)


def print_findings(findings):
    items = findings.sorted_items()
    if not items:
        return
    for severity in (FATAL, LAUNCH_BLOCKING, WARNING, INFO):
        block = [f for f in items if f.severity == severity]
        if not block:
            continue
        err("")
        err("-- %s (%d) --" % (severity, len(block)))
        for finding in block:
            err("  " + finding.to_line())


def summarize(result, options):
    counts = result.findings.counts()
    out("")
    out("pack            : %s" % options.pack_id)
    if result.source_checksum:
        out("sourceChecksum  : %s" % result.source_checksum)
        out("contentChecksum : %s" % result.content_checksum)
    if result.stats:
        out("cards           : %d" % result.stats.get("count", 0))
        out("id range        : %s-%s  allocated %s-%s"
            % (result.stats.get("rangeMin"), result.stats.get("rangeMax"),
               result.stats.get("minId"), result.stats.get("maxId")))
        out("ids new/reused  : %d / %d"
            % (result.stats.get("allocated", 0), result.stats.get("reused", 0)))
        if result.stats.get("retired"):
            out("ids retired     : %d (never reused)" % result.stats["retired"])
    out("findings        : %d fatal, %d launch-blocking, %d warning, %d info"
        % (counts[FATAL], counts[LAUNCH_BLOCKING], counts[WARNING], counts[INFO]))
    if result.report:
        launch = result.report["launch"]
        out("launchEligible  : %s" % ("yes" if launch["launchEligible"] else "no"))


def main(argv=None):
    args = parse_args(argv if argv is not None else sys.argv[1:])

    if not schema.IDENT_RE.match(args.pack or ""):
        err("ERROR: --pack must match %s" % schema.IDENT_RE.pattern)
        return EXIT_USAGE

    source = args.source or os.path.join(REPO_ROOT, "source_data", args.pack)
    output = args.output or os.path.join(
        REPO_ROOT, "build", "content-packs", args.pack)

    options = Options(
        pack_id=args.pack,
        source=source,
        output=output,
        ledger_path=args.ledger,
        check=args.check,
        qa_only=args.qa_only,
        force=args.force,
        allow_removals=args.allow_removals,
        init_ledger=args.init_ledger,
        generated_at=args.generated_at,
    )

    out("FlashEdu content pack build (Phase 24D, build-time only).")
    out("source: %s" % os.path.relpath(source, REPO_ROOT))
    out("output: %s" % os.path.relpath(output, REPO_ROOT))
    if args.check:
        out("mode  : --check (no files are written)")

    if args.recover:
        result = recover(options, REPO_ROOT)
        print_findings(result.findings)
        if result.findings.has_fatal():
            err("")
            err("RESULT: RECOVERY FAILED - the pack directory still needs "
                "manual inspection.")
            return _fatal_exit_code(result)
        out("")
        out("RESULT: OK - exactly one complete generation is present and no "
            "transaction state remains.")
        return EXIT_OK

    if args.verify_deterministic:
        result, differences = verify_deterministic(options, REPO_ROOT)
        print_findings(result.findings)
        summarize(result, options)
        if result.findings.has_fatal():
            code = _fatal_exit_code(result)
            err("")
            err("RESULT: FATAL - no output written.")
            return code
        if differences:
            err("")
            err("RESULT: NON-DETERMINISTIC - artifacts differ between builds:")
            for name in differences:
                err("  " + name)
            return EXIT_NONDETERMINISTIC
        out("")
        out("RESULT: DETERMINISTIC - two independent builds are byte-identical.")
        return EXIT_OK

    result = build(options, REPO_ROOT)
    print_findings(result.findings)
    summarize(result, options)

    if result.findings.has_fatal():
        err("")
        err("RESULT: FATAL - no output written.")
        return _fatal_exit_code(result)

    if args.check:
        if result.drift:
            err("")
            err("RESULT: DRIFT - committed output does not match the source:")
            for entry in result.drift:
                err("  %s (%s)" % (entry["path"], entry["reason"]))
            return EXIT_DRIFT
        out("")
        out("RESULT: UP TO DATE - committed output matches the source. "
            "Nothing was written.")
        return EXIT_OK

    out("")
    out("Generated:")
    for art in result.artifacts:
        out("  %s (%d bytes)" % (art.name, len(art.data)))
    if not args.qa_only:
        out("ledger: %s" % os.path.relpath(result.ledger_path, REPO_ROOT))
    out("")
    out("RESULT: OK - structural build succeeded.")
    out("NOTE: structural validation is not content-quality certification; "
        "Phase 24F owns that.")
    out("NOTE: nothing was added to hsk_flashcard_app/ and the service worker "
        "was not touched. Runtime promotion is Phase 24E.")
    return EXIT_OK


def _fatal_exit_code(result):
    codes = {f.code for f in result.findings if f.severity == FATAL}
    # Contention is machine-distinct from every other outcome: the right
    # response is "retry later", not "fix the source" or "run recovery".
    if "BUILD_LOCKED" in codes:
        return EXIT_LOCKED
    # An unfinished transaction is not a content problem; it needs --recover,
    # so CI can tell it apart from "the source is wrong".
    if codes & {"RECOVERY_REQUIRED", "TRANSACTION_JOURNAL_CORRUPT",
                "JOURNAL_EXISTS"}:
        return EXIT_RECOVERY_REQUIRED
    if codes & ENVIRONMENT_CODES:
        return EXIT_USAGE
    return EXIT_FATAL


if __name__ == "__main__":
    sys.exit(main())
