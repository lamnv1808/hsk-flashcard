#!/usr/bin/env python3
"""Generate the runtime pack catalog from Phase 24D registry handoffs.

Phase 24E-A foundation. Build-time only: it reads built packs and writes a
classic, static, data-only `catalog.js`. It never executes generated
JavaScript, never touches the network or Supabase, and never edits index.html
or sw.js.

Usage:
    python scripts/build_pack_catalog.py --source <packDir> [--source <packDir>...]
                                         --output <catalog.js>
                                         [--runtime-root packs]
                                         [--default-pack <packId>]
                                         [--app-version <x.y.z>]
                                         [--allow-hidden] [--check]

Each --source is a directory holding one built pack: registry-handoff.json plus
the generated runtime assets.

Exit codes:
    0  success (or --check found no drift)
    1  a handoff/manifest/catalog defect (nothing written)
    2  usage / environment failure
    3  --check found drift between the sources and the existing catalog

Console output is ASCII-only so a Windows cp1252 console cannot crash a build.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from contentpack import catalog as cat          # noqa: E402
from contentpack.findings import ascii_safe     # noqa: E402

EXIT_OK = 0
EXIT_FATAL = 1
EXIT_USAGE = 2
EXIT_DRIFT = 3

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def out(line=""):
    sys.stdout.write(ascii_safe(line) + "\n")


def err(line=""):
    sys.stderr.write(ascii_safe(line) + "\n")


def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog="build_pack_catalog.py",
        description="Deterministic pack catalog generation from 24D handoffs.")
    parser.add_argument("--source", action="append", required=True,
                        metavar="DIR",
                        help="a built pack directory (repeatable)")
    parser.add_argument("--output", required=True,
                        help="path to write catalog.js")
    parser.add_argument("--runtime-root", default="packs",
                        help="app-root-relative directory holding promoted "
                             "packs (default: packs)")
    parser.add_argument("--default-pack",
                        help="explicit default pack id; must be launch-visible")
    parser.add_argument("--app-version",
                        help="record the app version this catalog targets")
    parser.add_argument("--allow-hidden", action="store_true",
                        help="proceed when no pack is launch-visible "
                             "(test and staging catalogs)")
    parser.add_argument("--check", action="store_true",
                        help="no-write mode: report drift against --output")
    return parser.parse_args(argv)


def collect(sources, runtime_root):
    """Read every source directory into a validated catalog entry."""
    entries = []
    notes = []
    for source in sources:
        if not os.path.isdir(source):
            raise cat.CatalogError("source directory does not exist: %s"
                                   % os.path.basename(source))
        handoff_path = os.path.join(source, cat.HANDOFF_NAME)
        if not os.path.isfile(handoff_path):
            raise cat.CatalogError("no %s in %s"
                                   % (cat.HANDOFF_NAME, os.path.basename(source)))

        handoff = cat.read_handoff(handoff_path)
        pack_id = handoff["packId"]
        wanted, _present, build_only = cat.runtime_asset_names(handoff)

        manifest_path = os.path.join(source, wanted["manifest"])
        if not os.path.isfile(manifest_path):
            raise cat.CatalogError("missing runtime asset %s" % wanted["manifest"])
        cards_path = os.path.join(source, wanted["cards"])
        if not os.path.isfile(cards_path):
            raise cat.CatalogError("missing runtime asset %s" % wanted["cards"])

        manifest = cat.read_manifest_js(manifest_path)
        runtime_dir = "%s/%s" % (str(runtime_root).strip("/"), pack_id)
        entries.append(cat.build_entry(handoff, manifest, runtime_dir))

        reason = cat.hidden_reason(handoff)
        if reason:
            notes.append("%s is HIDDEN: %s" % (pack_id, reason))
        for name in build_only:
            notes.append("%s: '%s' is build-only and is not catalogued" % (pack_id, name))
    return entries, notes


def main(argv=None):
    args = parse_args(argv if argv is not None else sys.argv[1:])

    out("FlashEdu pack catalog generation (build-time only).")
    out("sources: %d" % len(args.source))
    if args.check:
        out("mode   : --check (no files are written)")

    try:
        entries, notes = collect(args.source, args.runtime_root)
        catalog = cat.assemble(entries,
                               default_pack_id=args.default_pack,
                               app_version=args.app_version)
    except cat.CatalogError as exc:
        err("")
        err("FATAL: " + str(exc))
        err("RESULT: FATAL - no catalog was written.")
        return EXIT_FATAL
    except OSError as exc:
        err("")
        err("ERROR: " + str(exc))
        return EXIT_USAGE

    visible = [p["packId"] for p in catalog["packs"] if p["launch"]["visible"]]
    if not visible and not args.allow_hidden:
        err("")
        err("FATAL: no pack in this catalog is launch-visible. Pass "
            "--allow-hidden for a test or staging catalog.")
        return EXIT_FATAL

    data = cat.render_catalog_js(catalog)

    for note in notes:
        out("  note: " + note)
    out("")
    out("packs          : %s" % ", ".join(p["packId"] for p in catalog["packs"]))
    out("launch-visible : %s" % (", ".join(visible) or "(none)"))
    if "defaultPackId" in catalog:
        out("default        : %s" % catalog["defaultPackId"])
    out("catalog bytes  : %d" % len(data))

    if args.check:
        if not os.path.isfile(args.output):
            err("")
            err("RESULT: DRIFT - %s does not exist." % os.path.basename(args.output))
            return EXIT_DRIFT
        with open(args.output, "rb") as fh:
            existing = fh.read()
        if existing != data:
            err("")
            err("RESULT: DRIFT - the committed catalog does not match its sources.")
            return EXIT_DRIFT
        out("")
        out("RESULT: UP TO DATE - the catalog matches its sources. Nothing written.")
        return EXIT_OK

    parent = os.path.dirname(os.path.abspath(args.output))
    if parent and not os.path.isdir(parent):
        os.makedirs(parent)
    tmp = args.output + ".tmp"
    try:
        with open(tmp, "wb") as fh:
            fh.write(data)
            fh.flush()
            try:
                os.fsync(fh.fileno())
            except (OSError, AttributeError):
                pass
        os.replace(tmp, args.output)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass

    out("")
    out("RESULT: OK - wrote %s" % os.path.basename(args.output))
    out("NOTE: this catalog is data only. Wiring it into index.html and the "
        "service worker is Phase 24E-B.")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
