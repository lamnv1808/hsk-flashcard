#!/usr/bin/env python3
"""Promote a built content pack into a runtime app root.

Phase 24E-A foundation. This is the ONLY sanctioned way to move Phase 24D build
output into the runtime. Manual copying is not acceptable: it bypasses every
checksum the pipeline computed, cannot detect a partial or stale promotion, and
silently breaks the release checker's clean-tree gate until someone remembers to
commit. A dedicated command makes those failures loud.

The Phase 24D pipeline physically cannot write inside hsk_flashcard_app/
(`emit.assert_output_root`). This tool is the deliberate other side of that
boundary, and it earns that by verifying every byte it copies.

Usage:
    python scripts/promote_content_pack.py --pack <packId> --app-root <dir>
                                           [--build-root <dir>] [--catalog <path>]
                                           [--allow-draft] [--check]

Exit codes:
    0  success (or --check found no drift)
    1  verification / validation failure (nothing changed)
    2  usage / environment failure
    3  --check found drift
    6  another process holds this pack's canonical lock

It never edits index.html, never edits sw.js, never edits the pinned
service-worker test, never runs git, and never pushes, merges or deploys.
"""

import argparse
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from contentpack import catalog as cat                      # noqa: E402
from contentpack import emit                                # noqa: E402
from contentpack.findings import ascii_safe                 # noqa: E402
from contentpack.locking import LockBusy, PackLock          # noqa: E402

EXIT_OK = 0
EXIT_FATAL = 1
EXIT_USAGE = 2
EXIT_DRIFT = 3
EXIT_LOCKED = 6

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_BUILD_ROOT = os.path.join(REPO_ROOT, "build", "content-packs")
PACKS_DIRNAME = "packs"


class PromotionError(Exception):
    """A promotion that must not proceed."""


def out(line=""):
    sys.stdout.write(ascii_safe(line) + "\n")


def err(line=""):
    sys.stderr.write(ascii_safe(line) + "\n")


# --------------------------------------------------------------------------
# containment
# --------------------------------------------------------------------------

def resolve_target_dir(app_root, pack_id):
    """<app-root>/packs/<packId>, containment- and symlink-checked.

    realpath is applied to both sides before the decision, so a symlinked
    packs/ directory pointing outside the app cannot be used to write anywhere
    else. The pack id is validated first, so it can never contribute a path
    segment like '..'.
    """
    if not cat.IDENT_RE.match(pack_id or ""):
        raise PromotionError("pack id %r is not a valid identifier" % (pack_id,))

    real_app = os.path.realpath(app_root)
    if not os.path.isdir(real_app):
        raise PromotionError("app root does not exist: %s" % app_root)

    packs_root = os.path.join(real_app, PACKS_DIRNAME)
    target = os.path.join(packs_root, pack_id)

    # Check against whichever ancestor already exists, so a not-yet-created
    # target still gets a real containment decision.
    probe = target
    while not os.path.exists(probe):
        parent = os.path.dirname(probe)
        if parent == probe:
            break
        probe = parent
    real_probe = os.path.realpath(probe)
    try:
        contained = os.path.commonpath([real_app, real_probe]) == real_app
    except ValueError:
        contained = False
    if not contained:
        raise PromotionError(
            "target directory for '%s' resolves outside the app root "
            "(symlink escape refused)" % pack_id)
    return packs_root, target


# --------------------------------------------------------------------------
# verification
# --------------------------------------------------------------------------

def load_pack(build_root, pack_id):
    """Read and verify one built pack. Returns (handoff, {name: bytes})."""
    source = os.path.join(build_root, pack_id)
    if not os.path.isdir(source):
        raise PromotionError("no build output for '%s' in %s"
                             % (pack_id, os.path.basename(build_root)))
    handoff_path = os.path.join(source, cat.HANDOFF_NAME)
    if not os.path.isfile(handoff_path):
        raise PromotionError("no %s for '%s'" % (cat.HANDOFF_NAME, pack_id))

    try:
        handoff = cat.read_handoff(handoff_path)
    except cat.CatalogError as exc:
        raise PromotionError(str(exc))
    if handoff["packId"] != pack_id:
        raise PromotionError("handoff declares '%s' but --pack is '%s'"
                             % (handoff["packId"], pack_id))

    wanted, present, build_only = cat.runtime_asset_names(handoff)
    payload = {}
    for name in sorted(wanted.values()):
        path = os.path.join(source, name)
        if not os.path.isfile(path):
            raise PromotionError("build output is missing '%s'" % name)
        with open(path, "rb") as fh:
            data = fh.read()
        expected = present[name]["sha256"]
        actual = emit.sha256_of(data)
        if actual != expected:
            raise PromotionError(
                "'%s' does not match its recorded checksum; the build output is "
                "stale or corrupt (expected %s, found %s)"
                % (name, expected[:19] + "...", actual[:19] + "..."))
        if len(data) != present[name]["bytes"]:
            raise PromotionError("'%s' has an unexpected size" % name)
        payload[name] = data
    return handoff, payload, build_only


def check_target_foreign(target, expected_names):
    """Files already in the target that this promotion will not produce."""
    if not os.path.isdir(target):
        return []
    return sorted(n for n in os.listdir(target)
                  if n not in expected_names
                  and os.path.isfile(os.path.join(target, n)))


# --------------------------------------------------------------------------
# atomic publish
# --------------------------------------------------------------------------

def publish(target, payload, journal_dir, pack_id):
    """Stage completely, then swap the directory. Same protocol as Phase 24D.

    Two atomic renames rather than one, because os.replace(dir -> existing dir)
    raises on Windows. A journal makes the window between them recoverable.
    """
    staging = os.path.join(journal_dir, ".promote-staging-%s" % pack_id)
    old_dir = os.path.join(journal_dir, ".promote-old-%s" % pack_id)
    journal = os.path.join(journal_dir, ".promote-txn-%s.json" % pack_id)

    if os.path.isfile(journal):
        raise PromotionError(
            "an incomplete promotion is present for '%s'; inspect %s before "
            "retrying" % (pack_id, os.path.basename(journal)))

    inventory = [{"path": n, "bytes": len(d), "sha256": emit.sha256_of(d)}
                 for n, d in sorted(payload.items())]

    try:
        if os.path.isdir(staging):
            shutil.rmtree(staging)
        os.makedirs(staging)
        for name, data in sorted(payload.items()):
            emit._fsync_write(os.path.join(staging, name), data)

        emit._fsync_write(journal, emit.canonical_json_bytes({
            "promotionVersion": 1, "packId": pack_id,
            "target": target, "files": inventory,
        }))

        if os.path.isdir(target):
            if os.path.isdir(old_dir):
                shutil.rmtree(old_dir)
            os.replace(target, old_dir)
        parent = os.path.dirname(target)
        if not os.path.isdir(parent):
            os.makedirs(parent)
        os.replace(staging, target)
    finally:
        # Pre-commit debris only. The journal is removed last, below, so an
        # interrupted run leaves it behind as the recovery marker.
        if os.path.isdir(staging):
            shutil.rmtree(staging, ignore_errors=True)

    if os.path.isdir(old_dir):
        shutil.rmtree(old_dir, ignore_errors=True)
    if os.path.isfile(journal):
        os.remove(journal)
    return inventory


def rollback_target(target, old_dir):
    """Restore the previous generation after a failed swap."""
    if os.path.isdir(old_dir) and not os.path.isdir(target):
        os.replace(old_dir, target)


# --------------------------------------------------------------------------
# catalog regeneration
# --------------------------------------------------------------------------

def regenerate_catalog(app_root, build_root, catalog_path, default_pack,
                       app_version, allow_hidden):
    """Rebuild the catalog from every pack currently promoted into app_root.

    Deliberately driven by what is PROMOTED, not by what happens to be built:
    a catalog that advertises a pack the runtime does not have is exactly the
    stale-state failure this tooling exists to prevent. Each promoted file is
    re-verified against its handoff on the way through.
    """
    packs_root = os.path.join(os.path.realpath(app_root), PACKS_DIRNAME)
    entries = []
    if os.path.isdir(packs_root):
        for pack_id in sorted(os.listdir(packs_root)):
            promoted = os.path.join(packs_root, pack_id)
            if not os.path.isdir(promoted) or not cat.IDENT_RE.match(pack_id):
                continue
            handoff_path = os.path.join(build_root, pack_id, cat.HANDOFF_NAME)
            if not os.path.isfile(handoff_path):
                raise PromotionError(
                    "pack '%s' is promoted but has no build handoff; the "
                    "catalog cannot describe it honestly" % pack_id)
            handoff = cat.read_handoff(handoff_path)
            wanted, present, _ = cat.runtime_asset_names(handoff)
            for name in sorted(wanted.values()):
                path = os.path.join(promoted, name)
                if not os.path.isfile(path):
                    raise PromotionError(
                        "promoted pack '%s' is missing '%s'" % (pack_id, name))
                with open(path, "rb") as fh:
                    if emit.sha256_of(fh.read()) != present[name]["sha256"]:
                        raise PromotionError(
                            "promoted '%s/%s' does not match its handoff "
                            "checksum" % (pack_id, name))
            manifest = cat.read_manifest_js(
                os.path.join(promoted, wanted["manifest"]))
            entries.append(cat.build_entry(
                handoff, manifest, "%s/%s" % (PACKS_DIRNAME, pack_id)))

    if not entries:
        raise PromotionError("no promoted packs found; nothing to catalogue")

    catalog = cat.assemble(entries, default_pack_id=default_pack,
                           app_version=app_version)
    visible = [p["packId"] for p in catalog["packs"] if p["launch"]["visible"]]
    if not visible and not allow_hidden:
        raise PromotionError(
            "no promoted pack is launch-visible; refusing to write a catalog "
            "with no usable study option (use --allow-draft for a test root)")
    return catalog, cat.render_catalog_js(catalog)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog="promote_content_pack.py",
        description="Promote a built content pack into a runtime app root.")
    parser.add_argument("--pack", required=True)
    parser.add_argument("--app-root", required=True,
                        help="the runtime app directory (e.g. hsk_flashcard_app)")
    parser.add_argument("--build-root", default=DEFAULT_BUILD_ROOT)
    parser.add_argument("--catalog",
                        help="catalog.js path (default: <app-root>/packs/catalog.js)")
    parser.add_argument("--default-pack",
                        help="explicit default pack id for the catalog")
    parser.add_argument("--app-version")
    parser.add_argument("--allow-draft", action="store_true",
                        help="promote a launch-ineligible pack; test and "
                             "staging roots only, never a production launch")
    parser.add_argument("--check", action="store_true",
                        help="no-write mode: verify and report drift")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv if argv is not None else sys.argv[1:])

    out("FlashEdu pack promotion (build-time only).")
    out("pack    : %s" % args.pack)
    if args.check:
        out("mode    : --check (no files are written)")

    try:
        packs_root, target = resolve_target_dir(args.app_root, args.pack)
    except PromotionError as exc:
        err("")
        err("FATAL: " + str(exc))
        return EXIT_FATAL

    catalog_path = args.catalog or os.path.join(packs_root, "catalog.js")

    try:
        with PackLock(args.pack):
            return _run(args, packs_root, target, catalog_path)
    except LockBusy as exc:
        err("")
        err("BUILD_LOCKED: %s. Nothing was verified or written." % exc)
        return EXIT_LOCKED
    except PromotionError as exc:
        err("")
        err("FATAL: " + str(exc))
        err("RESULT: FATAL - the app root was not modified.")
        return EXIT_FATAL
    except cat.CatalogError as exc:
        err("")
        err("FATAL: " + str(exc))
        return EXIT_FATAL
    except OSError as exc:
        err("")
        err("ERROR: " + str(exc))
        return EXIT_USAGE


def _run(args, packs_root, target, catalog_path):
    handoff, payload, build_only = load_pack(args.build_root, args.pack)

    out("version : %s" % handoff["version"])
    out("status  : %s  launchEligible: %s"
        % (handoff["status"], handoff["launchEligible"]))
    for name in build_only:
        out("  note: '%s' is build-only and is NOT promoted" % name)

    if not handoff["launchEligible"] and not args.allow_draft:
        raise PromotionError(
            "pack '%s' is not launch-eligible (%s). Promoting it would put "
            "uncertified content in the runtime; pass --allow-draft only for a "
            "test or staging app root."
            % (args.pack, ", ".join(handoff.get("launchBlockers") or ["unspecified"])))

    expected_names = set(payload)
    foreign = check_target_foreign(target, expected_names)
    for name in foreign:
        out("  note: stale file '%s' will be removed from the pack directory"
            % name)

    for name in sorted(payload):
        if not emit.is_contained(target, name):
            raise PromotionError("generated name '%s' escapes the pack directory"
                                 % name)

    if args.check:
        drift = []
        for name, data in sorted(payload.items()):
            path = os.path.join(target, name)
            if not os.path.isfile(path):
                drift.append("%s (missing)" % name)
                continue
            with open(path, "rb") as fh:
                if fh.read() != data:
                    drift.append("%s (differs)" % name)
        drift.extend("%s (stale)" % n for n in foreign)
        if not os.path.isfile(catalog_path):
            drift.append("catalog.js (missing)")
        if drift:
            err("")
            err("RESULT: DRIFT - the app root does not match the build output:")
            for item in drift:
                err("  " + item)
            return EXIT_DRIFT
        out("")
        out("RESULT: UP TO DATE - nothing was written.")
        return EXIT_OK

    old_dir = os.path.join(packs_root, ".promote-old-%s" % args.pack)
    try:
        inventory = publish(target, payload, packs_root, args.pack)
    except BaseException:
        rollback_target(target, old_dir)
        raise

    catalog, catalog_bytes = regenerate_catalog(
        args.app_root, args.build_root, catalog_path,
        args.default_pack, args.app_version, args.allow_draft)

    parent = os.path.dirname(os.path.abspath(catalog_path))
    if parent and not os.path.isdir(parent):
        os.makedirs(parent)
    tmp = catalog_path + ".tmp"
    try:
        emit._fsync_write(tmp, catalog_bytes)
        os.replace(tmp, catalog_path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass

    out("")
    out("Promoted:")
    for entry in inventory:
        out("  packs/%s/%s (%d bytes)" % (args.pack, entry["path"], entry["bytes"]))
    out("  %s (%d bytes)" % (os.path.basename(catalog_path), len(catalog_bytes)))

    _print_required_wiring(args.pack, inventory, catalog_path, packs_root, catalog)
    out("")
    out("RESULT: OK - promotion complete.")
    return EXIT_OK


def _print_required_wiring(pack_id, inventory, catalog_path, packs_root, catalog):
    """Tell the owner exactly what to change. Never change it automatically.

    index.html and sw.js are runtime files with a mandatory single cache bump
    and a pinned release-tooling assertion. Editing them from a build tool would
    make an unreviewed runtime change look like a content update.
    """
    rel_catalog = os.path.relpath(catalog_path, os.path.dirname(packs_root))
    rel_catalog = rel_catalog.replace("\\", "/")
    out("")
    out("REQUIRED MANUAL WIRING (this tool does NOT perform it) -- Phase 24E-B:")
    out("  1. sw.js ASSETS: add")
    out("       '%s'" % rel_catalog)
    for entry in inventory:
        out("       '%s/%s/%s'" % (PACKS_DIRNAME, pack_id, entry["path"]))
    out("  2. sw.js: bump the cache version exactly once.")
    out("  3. tests/tooling/test_release_check.py: update the pinned cache literal.")
    out("  4. index.html: load the catalog and the boot shim; the pack payload "
        "is inserted at parse time from the validated catalog only.")
    out("  5. Re-run: python scripts/release_check.py")
    out("")
    out("Catalog launch-visible packs: %s"
        % (", ".join(p["packId"] for p in catalog["packs"]
                     if p["launch"]["visible"]) or "(none)"))


if __name__ == "__main__":
    sys.exit(main())
