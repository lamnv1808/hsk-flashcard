"""Pipeline orchestration.

    source -> parse -> validate -> normalize -> resolve stable ids
           -> ContentPack v1 artifacts -> checksums -> QA reports
           -> registry handoff -> atomic publish

Artifact generation is a pure function of (source, ledger). Nothing is written
until every stage has succeeded, so a failure at any point leaves the previous
output byte-unchanged. In --check mode nothing is written at all, including
staging files.
"""

import os

from . import emit, identity, qa, sources, validate
from .findings import Findings

CONTENT_PACK_JS = "%s-content-pack.js"
CARDS_JS = "%s-cards.js"
CSI_JSON = "%s-source.csi.json"
QA_JSON = "qa-report.json"
QA_MD = "qa-report.md"
HANDOFF_JSON = "registry-handoff.json"

# The QA report and the handoff describe the data artifacts, so the inventory
# they carry covers exactly these three. Including the report's own checksum
# inside the report would be self-referential.
DATA_ARTIFACTS = (CONTENT_PACK_JS, CARDS_JS, CSI_JSON)


class BuildResult(object):
    def __init__(self):
        self.findings = Findings()
        self.pack = None
        self.artifacts = []          # list of emit.Artifact (all six)
        self.data_artifacts = []     # the three inventoried data artifacts
        self.inventory = []
        self.stats = {}
        self.source_checksum = None
        self.content_checksum = None
        self.ledger = None
        self.ledger_path = None
        self.report = None
        self.drift = []              # populated by --check
        self.plan = None             # journal document for this generation
        self.published = []          # every file the transaction committed


class Options(object):
    def __init__(self, pack_id, source, output, ledger_path=None,
                 check=False, qa_only=False, force=False, allow_removals=False,
                 init_ledger=False, generated_at=None, fault=None):
        self.pack_id = pack_id
        self.source = source
        self.output = output
        self.ledger_path = ledger_path
        self.check = check
        self.qa_only = qa_only
        self.force = force
        self.allow_removals = allow_removals
        self.init_ledger = init_ledger
        self.generated_at = generated_at
        # Test-only hook: called with a checkpoint label at every boundary
        # between durable filesystem operations, so failure injection exercises
        # real files rather than mocks.
        self.fault = fault


def _generate(options, findings, deterministic_note):
    """Pure generation stage: source + ledger -> artifacts. No writes."""
    result = BuildResult()
    result.findings = findings

    raw = sources.read_source(options.source, findings)
    if raw is None or findings.has_fatal():
        return result

    pack = validate.validate_source(raw, findings)
    result.pack = pack
    if findings.has_fatal():
        return result

    declared_pack_id = pack.manifest.get("packId")
    if declared_pack_id != options.pack_id:
        findings.fatal(
            "PACK_ID_MISMATCH",
            "--pack is '%s' but the manifest declares packId '%s'"
            % (options.pack_id, declared_pack_id))
        return result

    id_range = (pack.manifest["idRange.min"], pack.manifest["idRange.max"])
    ledger_path = options.ledger_path or identity.default_ledger_path(
        options.source, options.pack_id)
    result.ledger_path = ledger_path

    ledger = identity.load_ledger(
        ledger_path, options.pack_id, id_range, options.init_ledger, findings)
    if ledger is None or findings.has_fatal():
        return result

    updated, stats, assigned = identity.resolve_ids(
        ledger, pack.cards, options.allow_removals, findings)
    if updated is None or findings.has_fatal():
        return result
    result.ledger = updated
    result.stats = stats

    csi_bytes = emit.build_csi(pack)
    source_checksum = emit.sha256_of(csi_bytes)

    emitted_cards = emit.build_emitted_cards(pack, assigned)
    content_bytes = emit.build_content_bytes(emitted_cards)
    content_checksum = emit.sha256_of(content_bytes)

    result.source_checksum = source_checksum
    result.content_checksum = content_checksum

    manifest = emit.build_emitted_manifest(
        pack, stats, source_checksum, content_checksum)
    version = pack.manifest.get("version")

    data_artifacts = [
        emit.Artifact(CONTENT_PACK_JS % options.pack_id,
                      emit.render_content_pack_js(
                          options.pack_id, version, source_checksum, manifest)),
        emit.Artifact(CARDS_JS % options.pack_id,
                      emit.render_cards_js(
                          options.pack_id, version, content_checksum, emitted_cards)),
        emit.Artifact(CSI_JSON % options.pack_id, csi_bytes),
    ]
    result.data_artifacts = data_artifacts
    result.inventory = emit.inventory_only(data_artifacts)

    report = qa.build_report(
        pack, raw.files, stats, source_checksum, content_checksum,
        result.inventory, findings, deterministic_note, options.generated_at)
    result.report = report

    qa_artifacts = [
        emit.Artifact(QA_JSON, qa.render_report_json(report)),
        emit.Artifact(QA_MD, qa.render_report_md(report)),
        emit.Artifact(HANDOFF_JSON, qa.build_handoff(
            pack, stats, source_checksum, content_checksum,
            result.inventory, findings, options.generated_at)),
    ]

    if options.qa_only:
        result.artifacts = qa_artifacts[:2]
    else:
        result.artifacts = data_artifacts + qa_artifacts
    return result


def build(options, repo_root):
    """Full build. Writes only after every stage has succeeded."""
    findings = Findings()

    try:
        output_dir = emit.assert_output_root(repo_root, options.output)
    except ValueError as exc:
        findings.fatal("OUTPUT_PATH_ESCAPE", str(exc))
        result = BuildResult()
        result.findings = findings
        return result

    # A journal means a previous run committed but did not finish. Never build
    # from ambiguous state: block until --recover completes it deterministically.
    try:
        pending = emit.read_journal(output_dir, options.pack_id)
    except ValueError as exc:
        findings.fatal("TRANSACTION_JOURNAL_CORRUPT", str(exc))
        result = BuildResult()
        result.findings = findings
        return result
    if pending is not None:
        findings.fatal(
            "RECOVERY_REQUIRED",
            "an incomplete publication transaction (%s) is present for pack "
            "'%s'. Run: python scripts/build_content_pack.py --pack %s "
            "--output <dir> --recover"
            % (pending.get("txid", "?")[:12], options.pack_id, options.pack_id))
        result = BuildResult()
        result.findings = findings
        return result

    result = _generate(options, findings, deterministic_note="not verified")
    if findings.has_fatal():
        return result

    if options.check:
        result.drift = _detect_drift(output_dir, result.artifacts)
        return result

    # No journal exists, so no transaction step ever ran; any staging/.old here
    # is debris from a pre-commit failure and is safe to discard.
    emit.discard_precommit_debris(output_dir, options.pack_id, findings)

    for art in result.artifacts:
        if not emit.is_contained(output_dir, art.name):
            findings.fatal(
                "OUTPUT_PATH_ESCAPE",
                "generated artifact '%s' does not resolve inside the output "
                "directory" % art.name)
    if findings.has_fatal():
        return result

    if emit.looks_foreign(output_dir, options.pack_id) and not options.force:
        findings.fatal(
            "FOREIGN_OUTPUT",
            "output directory contains files this pipeline did not produce; "
            "pass --force only after inspecting them")
        return result

    if options.qa_only:
        findings.info(
            "QA_ONLY",
            "--qa-only: no runtime artifacts and no ledger update were written; "
            "the id allocations in this report are provisional")

    ledger_path = None if options.qa_only else result.ledger_path
    ledger_bytes = None if options.qa_only else result.ledger.to_json_bytes()

    if ledger_path:
        parent = os.path.dirname(os.path.abspath(ledger_path))
        if parent and not os.path.isdir(parent):
            os.makedirs(parent)

    plan = emit.build_plan(output_dir, options.pack_id, result.artifacts,
                           ledger_path, ledger_bytes,
                           preserve_existing=options.qa_only)
    result.plan = plan

    obsolete = sorted(
        set(e["path"] for e in _existing_files(output_dir))
        - set(e["path"] for e in plan["artifacts"]))
    for name in obsolete:
        findings.info("STALE_OUTPUT_REMOVED",
                      "obsolete generated file '%s' is not carried into the new "
                      "generation" % name)

    fault = options.fault or emit._noop_fault
    try:
        emit.prepare(plan, result.artifacts, ledger_bytes, output_dir, fault)
        # result.inventory stays the three data artifacts that the QA report and
        # the registry handoff describe. The committed set (which also includes
        # the QA and handoff files) is recorded separately.
        result.published = emit.commit(plan, fault)
    except BaseException:
        # The journal becoming durable is the commit point. If it never got
        # there, nothing observable changed and the staged state is discardable.
        # If it did, leave everything in place for --recover to roll forward.
        if not os.path.isfile(emit.journal_path(output_dir, options.pack_id)):
            emit.abort(plan)
        raise

    return result


def _existing_files(directory):
    if not os.path.isdir(directory):
        return []
    return [{"path": name} for name in sorted(os.listdir(directory))
            if os.path.isfile(os.path.join(directory, name))]


def recover(options, repo_root):
    """Complete an interrupted publication. Deterministic, idempotent."""
    findings = Findings()
    result = BuildResult()
    result.findings = findings

    try:
        output_dir = emit.assert_output_root(repo_root, options.output)
    except ValueError as exc:
        findings.fatal("OUTPUT_PATH_ESCAPE", str(exc))
        return result

    try:
        plan = emit.read_journal(output_dir, options.pack_id)
    except ValueError as exc:
        findings.fatal("TRANSACTION_JOURNAL_CORRUPT", str(exc))
        return result

    if plan is None:
        emit.discard_precommit_debris(output_dir, options.pack_id, findings)
        findings.info("NOTHING_TO_RECOVER",
                      "no transaction journal is present; the pack directory is "
                      "not in a recovery state")
        return result

    result.plan = plan
    try:
        result.inventory = emit.roll_forward(plan, options.fault or emit._noop_fault)
    except (OSError, RuntimeError) as exc:
        findings.fatal("RECOVERY_FAILED", str(exc))
        return result

    findings.info("RECOVERED",
                  "completed transaction %s; the pack now holds one complete "
                  "generation" % plan["txid"][:12])
    return result


def _detect_drift(output_dir, artifacts):
    """Compare generated bytes against what is on disk. Writes nothing."""
    drift = []
    for art in artifacts:
        target = os.path.join(output_dir, art.name)
        if not os.path.isfile(target):
            drift.append({"path": art.name, "reason": "missing"})
            continue
        with open(target, "rb") as fh:
            existing = fh.read()
        if existing != art.data:
            drift.append({"path": art.name, "reason": "content differs"})
    return drift


def verify_deterministic(options, repo_root):
    """Run generation twice and compare every artifact byte-for-byte.

    Two independent full passes (parse, validate, normalize, allocate, emit)
    catch ordering nondeterminism anywhere in the chain, not just in the
    serializer.
    """
    first = _generate(options, Findings(), deterministic_note="verified")
    if first.findings.has_fatal():
        return first, []
    second = _generate(options, Findings(), deterministic_note="verified")
    if second.findings.has_fatal():
        return second, []

    differences = []
    left = {a.name: a.data for a in first.artifacts}
    right = {a.name: a.data for a in second.artifacts}
    for name in sorted(set(left) | set(right)):
        if left.get(name) != right.get(name):
            differences.append(name)
    return first, differences
