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


class Options(object):
    def __init__(self, pack_id, source, output, ledger_path=None,
                 check=False, qa_only=False, force=False, allow_removals=False,
                 init_ledger=False, generated_at=None):
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

    result = _generate(options, findings, deterministic_note="not verified")
    if findings.has_fatal():
        return result

    if options.check:
        result.drift = _detect_drift(output_dir, result.artifacts)
        return result

    if options.qa_only:
        findings.info(
            "QA_ONLY",
            "--qa-only: no runtime artifacts and no ledger update were written; "
            "the id allocations in this report are provisional")
    else:
        # The ledger is written BEFORE the artifacts on purpose. If the artifact
        # write failed after a ledger write, the next run reuses the same ids and
        # converges. The reverse order could hand out different ids on the next
        # run, which is the failure mode this whole module exists to prevent.
        _write_ledger(result.ledger, result.ledger_path)

    if not os.path.isdir(output_dir):
        os.makedirs(output_dir)
    inventory = emit.publish(
        output_dir, options.pack_id, result.artifacts, options.force, findings)
    if inventory is None:
        return result
    return result


def _write_ledger(ledger, path):
    data = ledger.to_json_bytes()
    parent = os.path.dirname(os.path.abspath(path))
    if parent and not os.path.isdir(parent):
        os.makedirs(parent)
    tmp = path + ".tmp"
    try:
        with open(tmp, "wb") as fh:
            fh.write(data)
            fh.flush()
            try:
                os.fsync(fh.fileno())
            except (OSError, AttributeError):
                pass
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


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
