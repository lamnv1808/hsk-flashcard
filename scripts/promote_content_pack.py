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

def publish(target, payload, journal_dir, pack_id, finalize=True):
    """Stage completely, then swap the directory. Same protocol as Phase 24D.

    Two atomic renames rather than one, because os.replace(dir -> existing dir)
    raises on Windows. A journal makes the window between them recoverable.

    finalize=False DEFERS dropping the saved old directory and the journal, so
    the caller can still restore the prior pack if a LATER step (catalog
    regeneration/write) fails. The caller then calls finalize_publish() on
    success or rollback_published() on failure.
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

    had_prior = os.path.isdir(target)
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

    if finalize:
        finalize_publish(old_dir, journal)
        return inventory
    return inventory, old_dir, journal, had_prior


def finalize_publish(old_dir, journal):
    """Commit a deferred publish: drop the saved old directory and journal."""
    if os.path.isdir(old_dir):
        shutil.rmtree(old_dir, ignore_errors=True)
    if os.path.isfile(journal):
        os.remove(journal)


def rollback_published(target, old_dir, journal, had_prior):
    """Undo a committed swap when a later step fails.

    Restores the prior pack directory (or removes the freshly published one when
    there was no prior), then clears the journal, leaving the runtime in exactly
    its pre-promotion state.
    """
    if os.path.isdir(target):
        shutil.rmtree(target, ignore_errors=True)
    if had_prior and os.path.isdir(old_dir):
        os.replace(old_dir, target)
    if os.path.isfile(journal):
        os.remove(journal)


def rollback_target(target, old_dir):
    """Restore the previous generation after a failed swap."""
    if os.path.isdir(old_dir) and not os.path.isdir(target):
        os.replace(old_dir, target)


# --------------------------------------------------------------------------
# catalog regeneration
# --------------------------------------------------------------------------

def _canonical_runtime_bytes(abs_path):
    """Bytes as the repository canonically stores a TEXT runtime asset (LF).

    The legacy catalog records checksums over the LF-normalised form (see
    tests/data/test_pack_catalog_legacy.py), because a CRLF checkout of a
    committed-LF file must still verify. Runtime assets are always .js, so this
    matches how those checksums were computed and is stable across platforms.
    """
    with open(abs_path, "rb") as fh:
        return fh.read().replace(b"\r\n", b"\n")


def _resolve_inside(app_real, rel_path, field):
    """Resolve an app-root-relative path, rejecting traversal and symlink escape."""
    if not isinstance(rel_path, str) or not rel_path:
        raise PromotionError("%s must be a non-empty relative path" % field)
    if rel_path.startswith("/") or (len(rel_path) > 1 and rel_path[1] == ":") \
            or "\\" in rel_path or "://" in rel_path:
        raise PromotionError("%s is not a plain relative path: %r" % (field, rel_path))
    if ".." in rel_path.split("/"):
        raise PromotionError("%s contains a '..' segment: %r" % (field, rel_path))
    target = os.path.realpath(os.path.join(app_real, rel_path))
    if not (target == app_real or target.startswith(app_real + os.sep)):
        raise PromotionError("%s escapes the app root: %r" % (field, rel_path))
    return target


def _validate_legacy_entry(app_real, pack_id, packs_root, entry):
    """Verify a legacy-installed descriptor against the bytes on disk.

    A legacy pack (HSK) has no build handoff -- its payload is the hand-installed
    data.js and its adapter lives under packs/<id>/. This never SYNTHESISES a
    handoff or provenance; it only proves the existing descriptor still matches
    exactly what is deployed, then preserves it structurally unchanged.
    """
    where = "legacy entry '%s'" % pack_id
    if not isinstance(entry, dict):
        raise PromotionError("%s must be an object" % where)
    if entry.get("packId") != pack_id:
        raise PromotionError(
            "%s: packId %r does not match its directory" % (where, entry.get("packId")))
    install = entry.get("install")
    if not isinstance(install, dict) or install.get("kind") != "legacy-installed":
        raise PromotionError("%s: install.kind must be 'legacy-installed'" % where)

    manifest_rel = entry.get("manifestPath")
    cards_rel = entry.get("cardsPath")
    manifest_abs = _resolve_inside(app_real, manifest_rel, "%s.manifestPath" % where)
    _resolve_inside(app_real, cards_rel, "%s.cardsPath" % where)

    # The manifest must BELONG to this pack: it lives under packs/<pack_id>/.
    pack_dir_real = os.path.realpath(os.path.join(packs_root, pack_id))
    if not manifest_abs.startswith(pack_dir_real + os.sep):
        raise PromotionError(
            "%s.manifestPath does not live under packs/%s/" % (where, pack_id))

    runtime = entry.get("runtimeAssets")
    if not isinstance(runtime, dict) or "cards" not in runtime or "manifest" not in runtime:
        raise PromotionError("%s: runtimeAssets.cards and .manifest are required" % where)

    cards_sha = None
    for role in ("cards", "manifest"):
        asset = runtime[role]
        if not isinstance(asset, dict):
            raise PromotionError("%s.runtimeAssets.%s must be an object" % (where, role))
        abs_path = _resolve_inside(app_real, asset.get("path"),
                                   "%s.runtimeAssets.%s.path" % (where, role))
        if not os.path.isfile(abs_path):
            raise PromotionError(
                "%s: runtime asset '%s' does not exist" % (where, asset.get("path")))
        data = _canonical_runtime_bytes(abs_path)
        recorded = asset.get("sha256")
        actual = emit.sha256_of(data)          # already 'sha256:'-prefixed
        if recorded != actual:
            raise PromotionError(
                "%s: runtime asset '%s' sha256 mismatch (recorded %r, actual %r)"
                % (where, asset.get("path"), recorded, actual))
        if asset.get("bytes") != len(data):
            raise PromotionError(
                "%s: runtime asset '%s' byte count mismatch (recorded %r, actual %d)"
                % (where, asset.get("path"), asset.get("bytes"), len(data)))
        if role == "cards":
            cards_sha = actual

    # contentChecksum is, by contract, the sha256 of the cards runtime asset.
    if entry.get("contentChecksum") != cards_sha:
        raise PromotionError(
            "%s: contentChecksum %r disagrees with the cards runtime asset %r"
            % (where, entry.get("contentChecksum"), cards_sha))
    return entry


def regenerate_catalog(app_root, build_root, catalog_path, default_pack,
                       app_version, allow_hidden):
    """Rebuild the catalog from every pack currently promoted into app_root.

    Deliberately driven by what is PROMOTED, not by what happens to be built:
    a catalog that advertises a pack the runtime does not have is exactly the
    stale-state failure this tooling exists to prevent.

    A generated pack is re-verified against its build handoff. A LEGACY-installed
    pack (HSK) has no handoff by design; it is accepted only when the EXISTING
    catalog already describes it as legacy-installed, and only after that
    descriptor is re-verified against the deployed bytes. An unknown directory
    with neither a handoff nor a valid legacy entry is still fatal.
    """
    app_real = os.path.realpath(app_root)
    packs_root = os.path.join(app_real, PACKS_DIRNAME)

    # Read the existing catalog once (fail-closed if present but malformed). It
    # is the only sanctioned source of a legacy descriptor and of the default/
    # appVersion to preserve when the CLI does not override them.
    existing = None
    legacy_by_id = {}
    if os.path.isfile(catalog_path):
        existing = cat.read_catalog_js(catalog_path)
        for e in existing["packs"]:
            inst = e.get("install")
            if isinstance(inst, dict) and inst.get("kind") == "legacy-installed":
                pid = e.get("packId")
                if pid in legacy_by_id:
                    raise PromotionError(
                        "existing catalog declares legacy pack '%s' more than once" % pid)
                legacy_by_id[pid] = e

    entries = []
    if os.path.isdir(packs_root):
        for pack_id in sorted(os.listdir(packs_root)):
            promoted = os.path.join(packs_root, pack_id)
            if not os.path.isdir(promoted) or not cat.IDENT_RE.match(pack_id):
                continue
            handoff_path = os.path.join(build_root, pack_id, cat.HANDOFF_NAME)
            if not os.path.isfile(handoff_path):
                # No handoff: only a re-verified legacy descriptor is acceptable.
                legacy = legacy_by_id.get(pack_id)
                if legacy is None:
                    raise PromotionError(
                        "pack '%s' is promoted but has no build handoff and no "
                        "'legacy-installed' entry in the existing catalog; the "
                        "catalog cannot describe it honestly" % pack_id)
                entries.append(_validate_legacy_entry(
                    app_real, pack_id, packs_root, legacy))
                continue
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

    # Explicit CLI values are authoritative; otherwise preserve what the existing
    # catalog declared.
    effective_default = default_pack if default_pack is not None \
        else (existing or {}).get("defaultPackId")
    effective_appver = app_version if app_version is not None \
        else (existing or {}).get("appVersion")

    catalog = cat.assemble(entries, default_pack_id=effective_default,
                           app_version=effective_appver)
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

    # The prior catalog bytes are retained so a post-publish failure can restore
    # them exactly (or remove a catalog this run created).
    prior_catalog_bytes = None
    if os.path.isfile(catalog_path):
        with open(catalog_path, "rb") as fh:
            prior_catalog_bytes = fh.read()

    # Deferred publish: the saved old directory and journal survive until the
    # catalog is regenerated AND written, so a catalog/legacy validation failure
    # rolls the candidate pack back rather than leaving it half-promoted.
    inventory, old_dir, journal, had_prior = publish(
        target, payload, packs_root, args.pack, finalize=False)

    try:
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
    except BaseException:
        # Restore the prior pack directory and the prior catalog exactly.
        rollback_published(target, old_dir, journal, had_prior)
        try:
            if prior_catalog_bytes is None:
                if os.path.isfile(catalog_path):
                    os.remove(catalog_path)
            else:
                with open(catalog_path, "wb") as fh:
                    fh.write(prior_catalog_bytes)
        except OSError:
            pass
        raise

    finalize_publish(old_dir, journal)

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
