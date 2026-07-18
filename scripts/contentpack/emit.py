"""Canonical Source Intermediate, checksums, generated artifacts, atomic publish.

Two ideas carry most of the weight here.

1. The CSI. Both frontends project into one Canonical Source Intermediate, and
   the CSI bytes -- never the raw .xlsx bytes -- are the sourceChecksum basis.
   An .xlsx is a ZIP with per-entry timestamps, so re-saving an unchanged
   workbook changes its bytes; hashing that would make the checksum a property
   of the editor rather than of the content. Hashing the CSI instead makes an
   Excel source and an equivalent CSV source produce byte-identical checksums.

2. The wrapper is tool-owned. No spreadsheet value ever reaches a code position
   -- not an identifier, not a property expression, not a namespace. Author data
   lands only inside JSON value positions, and the JSON is additionally hardened
   against the three sequences that are valid JSON but break a classic <script>
   context: "</script", U+2028 and U+2029.
"""

import hashlib
import json
import os
import shutil  # noqa: F401  (used by the transaction protocol below)

from . import CSI_VERSION, BUILD_TOOL_VERSION
from . import schema


# --------------------------------------------------------------------------
# deterministic serialization
# --------------------------------------------------------------------------

def canonical_json_bytes(obj):
    """The one canonical JSON form used for every checksum basis."""
    text = json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))
    return (text + "\n").encode("utf-8")


def sha256_of(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


def build_csi(pack):
    """Canonical Source Intermediate.

    Deliberately excludes: generated ids, generatedAt, build-tool version,
    filesystem paths, timestamps and any machine-specific value. What remains
    is exactly the authored content, so the checksum answers "did the source
    change?" and nothing else.
    """
    cards = []
    for card in pack.cards:
        record = {"sourceKey": card["sourceKey"]}
        for role in schema.REQUIRED_CARD_ROLES:
            record[role] = card.get(role, "")
        for role in pack.declared_roles:
            record[role] = card.get(role, "")
        cards.append(record)
    cards.sort(key=lambda c: c["sourceKey"])

    doc = {
        "csiVersion": CSI_VERSION,
        "manifest": dict(pack.manifest),
        "cards": cards,
        "levels": pack.levels if pack.levels_authored else None,
    }
    return canonical_json_bytes(doc)


def build_content_bytes(emitted_cards):
    """contentChecksum basis: the emitted card payload only, no manifest."""
    return canonical_json_bytes(emitted_cards)


# --------------------------------------------------------------------------
# emitted card payload
# --------------------------------------------------------------------------

def build_emitted_cards(pack, assigned):
    """Runtime card objects, sorted ascending by cardId."""
    out = []
    for card in pack.cards:
        record = {schema.ID_FIELD: assigned[card["sourceKey"]]}
        for role in schema.REQUIRED_CARD_ROLES:
            record[role] = card.get(role, "")
        for role in pack.declared_roles:
            record[role] = card.get(role, "")
        out.append(record)
    out.sort(key=lambda c: c[schema.ID_FIELD])
    return out


def unflatten(manifest):
    """Flat dotted keys -> the nested object ContentPack v1 expects."""
    nested = {}
    for key in sorted(manifest):
        parts = key.split(".")
        cursor = nested
        for part in parts[:-1]:
            cursor = cursor.setdefault(part, {})
        cursor[parts[-1]] = manifest[key]
    return nested


def build_emitted_manifest(pack, stats, source_checksum, content_checksum):
    """Author manifest plus the tool-computed fields.

    generatedAt is deliberately absent: it would make otherwise identical
    builds differ, and it belongs in QA/handoff metadata, not in a runtime
    asset that participates in content identity.
    """
    nested = unflatten(pack.manifest)
    nested["fieldRoles"] = dict(pack.field_roles)
    nested["levels"] = [dict(entry) for entry in pack.levels]
    nested["cardCount"] = stats["count"]
    nested["sourceChecksum"] = source_checksum
    nested["contentChecksum"] = content_checksum
    return nested


# --------------------------------------------------------------------------
# generated JavaScript (data only, trusted wrapper)
# --------------------------------------------------------------------------

def js_json(obj):
    """JSON hardened for embedding inside a classic <script> element."""
    text = json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))
    # "</script" (and any "</") would terminate the element early.
    text = text.replace("</", "<\\/")
    # Valid JSON, but raw line terminators in JavaScript source.
    text = text.replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    return text


_HEADER = (
    "// Generated by scripts/build_content_pack.py -- DO NOT EDIT MANUALLY.\n"
    "// pack: %s  version: %s\n"
    "// %s: %s\n"
)


def _assert_safe_pack_id(pack_id):
    """Re-validate at the emit boundary; never trust an upstream check alone."""
    if not schema.IDENT_RE.match(pack_id or ""):
        raise ValueError("unsafe packId at emit boundary: %r" % (pack_id,))
    return pack_id


def render_cards_js(pack_id, version, content_checksum, emitted_cards):
    pack_id = _assert_safe_pack_id(pack_id)
    body = _HEADER % (pack_id, version, "contentChecksum", content_checksum)
    body += 'window.FLASHEDU_PACKS = window.FLASHEDU_PACKS || {};\n'
    body += 'window.FLASHEDU_PACKS["%s"] = window.FLASHEDU_PACKS["%s"] || {};\n' % (
        pack_id, pack_id)
    body += 'window.FLASHEDU_PACKS["%s"].cards = %s;\n' % (
        pack_id, js_json(emitted_cards))
    return body.encode("utf-8")


def render_content_pack_js(pack_id, version, source_checksum, manifest):
    pack_id = _assert_safe_pack_id(pack_id)
    body = _HEADER % (pack_id, version, "sourceChecksum", source_checksum)
    body += 'window.FLASHEDU_PACKS = window.FLASHEDU_PACKS || {};\n'
    body += 'window.FLASHEDU_PACKS["%s"] = window.FLASHEDU_PACKS["%s"] || {};\n' % (
        pack_id, pack_id)
    body += 'window.FLASHEDU_PACKS["%s"].manifest = %s;\n' % (
        pack_id, js_json(manifest))
    return body.encode("utf-8")


# --------------------------------------------------------------------------
# path containment
# --------------------------------------------------------------------------

def is_contained(root, candidate):
    """True only if candidate resolves strictly inside root.

    Mirrors the containment rules already proven in scripts/release_check.py:
    reject URLs, protocol-relative and UNC paths, drive-absolute and absolute
    paths, and any '..' segment on either separator; then confirm with a
    realpath/commonpath check so symlinks cannot escape either.
    """
    if not candidate:
        return False
    if "://" in candidate or candidate.startswith("//"):
        return False
    if candidate.startswith("\\\\"):
        return False
    if len(candidate) >= 2 and candidate[1] == ":" and candidate[0].isalpha():
        return False
    if os.path.isabs(candidate):
        return False
    for sep in ("/", "\\"):
        if ".." in candidate.split(sep):
            return False
    real_root = os.path.realpath(root)
    real_cand = os.path.realpath(os.path.join(root, candidate))
    try:
        return os.path.commonpath([real_root, real_cand]) == real_root
    except ValueError:
        return False


def assert_output_root(repo_root, output_dir):
    """The output root must never resolve inside the runtime app directory.

    The output root is an explicit operator choice (--output), so it may live
    outside the repository -- a temp directory or a CI scratch path is
    legitimate. What must never happen is a write inside hsk_flashcard_app/,
    because that would add a runtime asset and drag the service worker,
    index.html and the release checker into a build-time-only phase.

    Traversal is prevented separately and unconditionally: every individual
    artifact name is containment-checked against this root by is_contained().
    """
    real_repo = os.path.realpath(repo_root)
    real_out = os.path.realpath(output_dir)

    app_dir = os.path.realpath(os.path.join(real_repo, "hsk_flashcard_app"))
    try:
        inside_app = os.path.commonpath([app_dir, real_out]) == app_dir
    except ValueError:
        inside_app = False
    if inside_app:
        raise ValueError(
            "Phase 24D must not write inside hsk_flashcard_app/; promotion "
            "into the runtime is owned by Phase 24E")
    return real_out


# --------------------------------------------------------------------------
# atomic publish
# --------------------------------------------------------------------------

class Artifact(object):
    __slots__ = ("name", "data")

    def __init__(self, name, data):
        self.name = name
        self.data = data


def _fsync_write(path, data):
    with open(path, "wb") as fh:
        fh.write(data)
        fh.flush()
        try:
            os.fsync(fh.fileno())
        except (OSError, AttributeError):
            # Best effort: some filesystems do not support fsync on files.
            pass


def looks_foreign(target_dir, pack_id):
    """True if target_dir holds files that this pipeline did not produce."""
    if not os.path.isdir(target_dir):
        return False
    existing = os.listdir(target_dir)
    if not existing:
        return False
    return "%s-content-pack.js" % pack_id not in existing


# --------------------------------------------------------------------------
# transactional publication
# --------------------------------------------------------------------------
#
# The ledger and the artifact directory are two separate durable resources, in
# different parent directories and possibly on different volumes, so no single
# atomic rename can cover both. Correctness therefore comes from a write-ahead
# journal plus idempotent roll-forward recovery.
#
#   prepare : stage artifacts (fsync) -> stage ledger to <ledger>.txn (fsync)
#   COMMIT  : write journal (fsync)          <-- the durable commit point
#   step 1  : rename O -> O.old        (atomic; skipped when O is absent)
#   step 2  : rename staging -> O      (atomic)
#   step 3  : os.replace(L.txn, L)     (atomic; skipped for --qa-only)
#   step 4  : rmtree O.old; remove journal
#
# Before the journal is durable nothing has been replaced, so recovery is a
# discard. After it, every input a later step needs is consumed only by that
# step, so roll-forward is always possible and never needs the old bytes.
#
# Windows notes, measured on NTFS rather than assumed:
#   - os.replace(dir -> EXISTING dir) raises PermissionError, so the directory
#     swap needs the two-rename dance above rather than one call.
#   - os.replace(dir -> ABSENT target) is atomic.
#   - os.replace(file -> EXISTING file) is atomic.
#   - a directory rename fails while any file inside it is open.

JOURNAL_VERSION = 1
LEDGER_STAGE_SUFFIX = ".txn"


def _noop_fault(_label):
    """Default fault hook. Tests replace it to inject failures."""
    return None


def journal_path(output_dir, pack_id):
    """Journal lives beside the pack directory, on the artifact volume."""
    parent = os.path.dirname(os.path.abspath(output_dir))
    return os.path.join(parent, ".txn-%s.json" % pack_id)


def staging_path(output_dir, pack_id):
    parent = os.path.dirname(os.path.abspath(output_dir))
    return os.path.join(parent, ".staging-%s" % pack_id)


def old_path(output_dir, pack_id):
    parent = os.path.dirname(os.path.abspath(output_dir))
    return os.path.join(parent, ".old-%s" % pack_id)


def read_journal(output_dir, pack_id):
    """Return the journal document, or None. A corrupt journal raises."""
    path = journal_path(output_dir, pack_id)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ValueError("transaction journal is unreadable or corrupt: %s" % exc)
    if not isinstance(doc, dict) or doc.get("journalVersion") != JOURNAL_VERSION:
        raise ValueError("transaction journal has an unsupported shape")
    return doc


def _fsync_dir(path):
    """Best effort. Windows cannot fsync a directory handle."""
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except (OSError, ValueError):
        pass
    finally:
        os.close(fd)


def _sha256_path(path):
    with open(path, "rb") as fh:
        return sha256_of(fh.read())


def dir_matches(directory, entries):
    """True when directory holds exactly `entries` with matching checksums."""
    if not os.path.isdir(directory):
        return False
    present = sorted(name for name in os.listdir(directory)
                     if os.path.isfile(os.path.join(directory, name)))
    if present != sorted(e["path"] for e in entries):
        return False
    for entry in entries:
        if _sha256_path(os.path.join(directory, entry["path"])) != entry["sha256"]:
            return False
    return True


def build_plan(output_dir, pack_id, artifacts, ledger_path, ledger_bytes,
               preserve_existing):
    """The deterministic journal document for one generation."""
    entries = [{"path": a.name, "bytes": len(a.data), "sha256": sha256_of(a.data)}
               for a in artifacts]
    carried = []
    if preserve_existing and os.path.isdir(output_dir):
        expected = {a.name for a in artifacts}
        for name in sorted(os.listdir(output_dir)):
            full = os.path.join(output_dir, name)
            if name not in expected and os.path.isfile(full):
                carried.append({"path": name,
                                "bytes": os.path.getsize(full),
                                "sha256": _sha256_path(full)})

    # txid is the generation hash: deterministic, never random, so a retry after
    # a failure reproduces the same transaction identity.
    digest = hashlib.sha256()
    for entry in sorted(entries + carried, key=lambda e: e["path"]):
        digest.update(entry["path"].encode("utf-8"))
        digest.update(entry["sha256"].encode("utf-8"))
    if ledger_bytes is not None:
        digest.update(sha256_of(ledger_bytes).encode("utf-8"))

    return {
        "journalVersion": JOURNAL_VERSION,
        "txid": digest.hexdigest(),
        "packId": pack_id,
        "outputDir": os.path.abspath(output_dir),
        "stagingDir": staging_path(output_dir, pack_id),
        "oldDir": old_path(output_dir, pack_id),
        "ledgerPath": os.path.abspath(ledger_path) if ledger_path else None,
        "ledgerStagePath": (os.path.abspath(ledger_path) + LEDGER_STAGE_SUFFIX
                            if ledger_path else None),
        "ledgerSha256": sha256_of(ledger_bytes) if ledger_bytes is not None else None,
        "artifacts": sorted(entries + carried, key=lambda e: e["path"]),
        "generated": sorted(entries, key=lambda e: e["path"]),
    }


def prepare(plan, artifacts, ledger_bytes, carried_from, fault=_noop_fault):
    """Stage everything durably. Nothing observable changes yet."""
    staging = plan["stagingDir"]
    fault("before_staging")

    if os.path.isdir(staging):
        shutil.rmtree(staging)
    os.makedirs(staging)

    for art in artifacts:
        fault("artifact_write:%s" % art.name)
        _fsync_write(os.path.join(staging, art.name), art.data)

    # --qa-only publishes a partial set, so the untouched files are carried
    # forward into staging. Without this the directory swap would delete the
    # data artifacts that this invocation deliberately did not regenerate.
    generated = {a.name for a in artifacts}
    for entry in plan["artifacts"]:
        if entry["path"] in generated:
            continue
        shutil.copyfile(os.path.join(carried_from, entry["path"]),
                        os.path.join(staging, entry["path"]))

    _fsync_dir(staging)

    fault("before_ledger_stage")
    if plan["ledgerStagePath"] is not None:
        fault("ledger_stage")
        _fsync_write(plan["ledgerStagePath"], ledger_bytes)

    fault("after_fsync")


def commit(plan, fault=_noop_fault):
    """Make the journal durable, then run the roll-forward steps."""
    path = journal_path(plan["outputDir"], plan["packId"])
    fault("before_journal")
    _fsync_write(path, canonical_json_bytes(plan))
    _fsync_dir(os.path.dirname(path))
    fault("after_journal")
    return roll_forward(plan, fault)


def roll_forward(plan, fault=_noop_fault):
    """Idempotent completion. Used by commit AND by recovery, unchanged.

    Sharing one implementation is deliberate: a recovery path that differs from
    the commit path is a recovery path nobody has really tested.
    """
    output_dir = plan["outputDir"]
    staging = plan["stagingDir"]
    old_dir = plan["oldDir"]

    # steps 1 + 2 -- install the artifact directory
    if not dir_matches(output_dir, plan["artifacts"]):
        if not os.path.isdir(staging):
            raise RuntimeError(
                "cannot complete transaction %s: staging directory is gone and "
                "the output directory does not hold the new generation"
                % plan["txid"][:12])
        # Staging must be complete and byte-correct before it is allowed to
        # become the live generation. Without this, a crash midway through the
        # staging writes would let recovery promote a half-written pack.
        if not dir_matches(staging, plan["artifacts"]):
            raise RuntimeError(
                "cannot complete transaction %s: the staging directory is "
                "incomplete or does not match the journal checksums"
                % plan["txid"][:12])
        fault("before_dir_swap")
        if os.path.isdir(output_dir):
            if os.path.isdir(old_dir):
                shutil.rmtree(old_dir)
            os.replace(output_dir, old_dir)
            fault("after_dir_swap_old")
        os.replace(staging, output_dir)
        fault("after_dir_swap_new")

    # step 3 -- install the ledger
    ledger = plan["ledgerPath"]
    if ledger is not None:
        needed = plan["ledgerSha256"]
        current = _sha256_path(ledger) if os.path.isfile(ledger) else None
        if current != needed:
            stage = plan["ledgerStagePath"]
            if not os.path.isfile(stage):
                raise RuntimeError(
                    "cannot complete transaction %s: the staged ledger is gone "
                    "and the live ledger is not the new generation"
                    % plan["txid"][:12])
            fault("before_ledger_replace")
            os.replace(stage, ledger)
            fault("after_ledger_replace")

    # step 4 -- cleanup; a successful build leaves no marker behind
    fault("during_cleanup")
    cleanup(plan)
    return plan["generated"]


def cleanup(plan):
    """Remove every transaction remnant. Safe to call repeatedly."""
    if os.path.isdir(plan["oldDir"]):
        shutil.rmtree(plan["oldDir"], ignore_errors=True)
    if os.path.isdir(plan["stagingDir"]):
        shutil.rmtree(plan["stagingDir"], ignore_errors=True)
    stage = plan["ledgerStagePath"]
    if stage and os.path.isfile(stage):
        try:
            os.remove(stage)
        except OSError:
            pass
    path = journal_path(plan["outputDir"], plan["packId"])
    if os.path.isfile(path):
        try:
            os.remove(path)
        except OSError:
            pass


def abort(plan):
    """Pre-commit rollback: discard staging, leave the prior generation alone."""
    if os.path.isdir(plan["stagingDir"]):
        shutil.rmtree(plan["stagingDir"], ignore_errors=True)
    stage = plan["ledgerStagePath"]
    if stage and os.path.isfile(stage):
        try:
            os.remove(stage)
        except OSError:
            pass


def discard_precommit_debris(output_dir, pack_id, findings):
    """Remove staging/.old left by a failure that never reached the journal.

    Only ever called when no journal exists, which means no step ever ran, so
    this cannot destroy a committed generation.
    """
    for path in (staging_path(output_dir, pack_id), old_path(output_dir, pack_id)):
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
            findings.info(
                "PRECOMMIT_DEBRIS_REMOVED",
                "removed '%s' left by an earlier failure that never reached the "
                "commit point" % os.path.basename(path))


def inventory_only(artifacts):
    """Checksums without touching the filesystem (used by --check)."""
    return [
        {"path": art.name, "bytes": len(art.data), "sha256": sha256_of(art.data)}
        for art in artifacts
    ]
