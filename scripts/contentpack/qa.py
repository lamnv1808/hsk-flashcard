"""QA report (machine + human) and the Phase 24E registry handoff.

Both artifacts are deterministic: identical inputs produce byte-identical
reports. generatedAt is omitted unless release tooling supplies it explicitly,
and even then it lives only here and in the handoff -- never in a runtime asset
and never inside a content-identity checksum.
"""

import json

from . import BUILD_TOOL_VERSION
from . import schema
from .findings import FATAL, LAUNCH_BLOCKING, WARNING, INFO

DISCLAIMER = (
    "Structural validation only. A passing report does NOT certify linguistic, "
    "pedagogical or translation quality, nor content licensing. Content-quality "
    "acceptance is owned by Phase 24F."
)

# Notices about HOW a build was invoked, not about the pack. They are printed on
# the console but excluded from the report and the handoff, so those artifacts
# stay a function of the content alone and --check compares like with like.
BUILD_EVENT_CODES = frozenset((
    "LEDGER_INITIALIZED",
    "QA_ONLY",
    "STALE_OUTPUT_REMOVED",
))


def _coverage(cards, role):
    if not cards:
        return {"present": 0, "total": 0, "percent": 0.0}
    present = sum(1 for c in cards if c.get(role))
    total = len(cards)
    return {
        "present": present,
        "total": total,
        "percent": round(100.0 * present / total, 4),
    }


def _counts_by(cards, key):
    out = {}
    for card in cards:
        out[card.get(key, "")] = out.get(card.get(key, ""), 0) + 1
    return dict(sorted(out.items()))


def launch_assessment(pack, findings):
    """launchEligible plus the explicit reasons it is false."""
    reasons = []
    for finding in findings.sorted_items():
        if finding.severity == LAUNCH_BLOCKING:
            reasons.append({"code": finding.code, "message": finding.message})
        elif finding.severity == FATAL:
            reasons.append({"code": finding.code, "message": finding.message})

    claims_launch = (
        pack.manifest.get("status") == "launch"
        or pack.manifest.get("launch.readiness") == "launch"
        or pack.manifest.get("launch.visible") is True
    )
    missing_provenance = [
        k for k in schema.PROVENANCE_REQUIRED if not pack.manifest.get(k)]

    eligible = not reasons
    return {
        "launchEligible": eligible,
        "claimsLaunchReadiness": claims_launch,
        "missingProvenanceFields": missing_provenance,
        "reasons": reasons,
    }


def build_report(pack, source_files, stats, source_checksum, content_checksum,
                 output_inventory, findings, deterministic_note, generated_at=None):
    """Machine-readable QA report."""
    findings = findings.without_codes(BUILD_EVENT_CODES)
    cards = pack.cards
    role_coverage = {}
    for role in schema.REQUIRED_CARD_ROLES:
        role_coverage[role] = _coverage(cards, role)
    optional_coverage = {}
    for role in schema.OPTIONAL_CARD_ROLES:
        if role in pack.declared_roles:
            optional_coverage[role] = _coverage(cards, role)
        else:
            optional_coverage[role] = {"present": 0, "total": len(cards),
                                       "percent": 0.0, "declared": False}
    notes_present = sum(1 for c in cards if c.get("_hasNotes"))

    counts = findings.counts()
    report = {
        "reportVersion": 1,
        "disclaimer": DISCLAIMER,
        "pack": {
            "packId": pack.manifest.get("packId"),
            "version": pack.manifest.get("version"),
            "status": pack.manifest.get("status"),
            "courseId": pack.manifest.get("courseId"),
            "courseType": pack.manifest.get("courseType"),
            "title": pack.manifest.get("title"),
        },
        "build": {
            "buildToolVersion": BUILD_TOOL_VERSION,
            "deterministic": deterministic_note,
        },
        "source": {
            "files": sorted(source_files, key=lambda f: f["name"]),
            "sourceChecksum": source_checksum,
        },
        "content": {
            "contentChecksum": content_checksum,
            "cardTotal": len(cards),
            "countsByDeck": _counts_by(cards, "deck"),
            "declaredOptionalRoles": sorted(pack.declared_roles),
            "fieldRoles": dict(pack.field_roles),
            "levels": [dict(entry) for entry in pack.levels],
            "levelsAuthored": pack.levels_authored,
            "categories": pack.manifest.get("categories", []),
        },
        "completeness": {
            "required": role_coverage,
            "optional": optional_coverage,
            "authoringNotesPresent": notes_present,
        },
        # Pack STATE only. Per-invocation deltas (how many ids this particular
        # run allocated, reused or retired) are printed on the console but kept
        # out of the report, so the report stays a pure function of
        # (source, ledger) and --check compares like with like.
        "identity": {
            "idRange": {"min": stats.get("rangeMin"), "max": stats.get("rangeMax")},
            "allocated": {
                "min": stats.get("minId"),
                "max": stats.get("maxId"),
                "count": stats.get("count"),
                "gaps": stats.get("gaps"),
            },
            "retiredTotal": stats.get("retiredTotal"),
            "rangeCapacity": stats.get("rangeCapacity"),
            "rangeUtilization": stats.get("rangeUtilization"),
        },
        "findings": {
            "counts": {
                "fatal": counts[FATAL],
                "launchBlocking": counts[LAUNCH_BLOCKING],
                "warning": counts[WARNING],
                "info": counts[INFO],
            },
            "codes": findings.codes(),
            "items": findings.to_list(),
        },
        "launch": launch_assessment(pack, findings),
        "output": {"files": sorted(output_inventory, key=lambda f: f["path"])},
    }
    if generated_at:
        report["build"]["generatedAt"] = generated_at
    return report


def render_report_json(report):
    text = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2)
    return (text + "\n").encode("utf-8")


def render_report_md(report):
    """Human-readable form. Markdown, never CSV.

    Emitting Markdown rather than CSV is what designs the spreadsheet-injection
    problem out of the output side entirely: nothing here is ever re-interpreted
    by a spreadsheet application.
    """
    pack = report["pack"]
    out = []
    add = out.append

    add("# Content Pack QA Report -- %s %s" % (pack["packId"], pack["version"]))
    add("")
    add("> %s" % report["disclaimer"])
    add("")
    add("## Pack")
    add("")
    add("| Field | Value |")
    add("|---|---|")
    for key in ("packId", "version", "status", "courseId", "courseType", "title"):
        add("| %s | %s |" % (key, pack.get(key)))
    add("| buildToolVersion | %s |" % report["build"]["buildToolVersion"])
    if "generatedAt" in report["build"]:
        add("| generatedAt | %s |" % report["build"]["generatedAt"])
    add("")

    add("## Checksums")
    add("")
    add("| Kind | Value |")
    add("|---|---|")
    add("| sourceChecksum (CSI bytes) | `%s` |" % report["source"]["sourceChecksum"])
    add("| contentChecksum (card payload) | `%s` |" % report["content"]["contentChecksum"])
    add("")

    add("## Source files")
    add("")
    add("| File | Bytes | SHA-256 |")
    add("|---|---:|---|")
    for entry in report["source"]["files"]:
        add("| %s | %d | `%s` |" % (entry["name"], entry["bytes"], entry["sha256"]))
    add("")

    add("## Content")
    add("")
    add("- Cards: **%d**" % report["content"]["cardTotal"])
    add("- Declared optional roles: %s"
        % (", ".join(report["content"]["declaredOptionalRoles"]) or "(none)"))
    add("")
    add("| Deck | Cards |")
    add("|---|---:|")
    for deck, count in report["content"]["countsByDeck"].items():
        add("| %s | %d |" % (deck, count))
    add("")

    add("## Field completeness")
    add("")
    add("| Role | Kind | Present | Total | % |")
    add("|---|---|---:|---:|---:|")
    for role, cov in sorted(report["completeness"]["required"].items()):
        add("| %s | required | %d | %d | %.2f |"
            % (role, cov["present"], cov["total"], cov["percent"]))
    for role, cov in sorted(report["completeness"]["optional"].items()):
        kind = "optional" if cov.get("declared", True) else "not declared"
        add("| %s | %s | %d | %d | %.2f |"
            % (role, kind, cov["present"], cov["total"], cov["percent"]))
    add("")

    ident = report["identity"]
    add("## Identity")
    add("")
    add("| Metric | Value |")
    add("|---|---|")
    add("| Reserved range | %s - %s |" % (ident["idRange"]["min"], ident["idRange"]["max"]))
    add("| Allocated min / max | %s / %s |"
        % (ident["allocated"]["min"], ident["allocated"]["max"]))
    add("| Active cards | %s |" % ident["allocated"]["count"])
    add("| Gaps inside allocated span | %s |" % ident["allocated"]["gaps"])
    add("| Retired total (ids never reused) | %s |" % ident["retiredTotal"])
    add("| Range utilization | %s |" % ident["rangeUtilization"])
    add("")

    counts = report["findings"]["counts"]
    add("## Findings")
    add("")
    add("| Severity | Count |")
    add("|---|---:|")
    add("| FATAL | %d |" % counts["fatal"])
    add("| LAUNCH-BLOCKING | %d |" % counts["launchBlocking"])
    add("| WARNING | %d |" % counts["warning"])
    add("| INFO | %d |" % counts["info"])
    add("")
    if report["findings"]["items"]:
        add("| Severity | Code | Location | sourceKey | Message |")
        add("|---|---|---|---|---|")
        for item in report["findings"]["items"]:
            loc = "!".join(x for x in (item.get("source"), item.get("coord")) if x)
            add("| %s | %s | %s | %s | %s |"
                % (item["severity"], item["code"], loc or "-",
                   item.get("sourceKey", "-"), item["message"]))
        add("")

    launch = report["launch"]
    add("## Launch readiness")
    add("")
    add("- launchEligible: **%s**" % ("yes" if launch["launchEligible"] else "no"))
    add("- Pack claims launch readiness: %s"
        % ("yes" if launch["claimsLaunchReadiness"] else "no"))
    if launch["missingProvenanceFields"]:
        add("- Missing provenance fields: %s"
            % ", ".join(launch["missingProvenanceFields"]))
        add("- These values are never inferred, defaulted or invented. Unknown "
            "provenance stays unknown and blocks launch certification.")
    if launch["reasons"]:
        add("")
        add("Reasons launchEligible is false:")
        add("")
        for reason in launch["reasons"]:
            add("- `%s` -- %s" % (reason["code"], reason["message"]))
    add("")

    add("## Generated output")
    add("")
    add("| File | Bytes | SHA-256 |")
    add("|---|---:|---|")
    for entry in report["output"]["files"]:
        add("| %s | %d | `%s` |" % (entry["path"], entry["bytes"], entry["sha256"]))
    add("")

    return ("\n".join(out)).encode("utf-8")


def build_handoff(pack, stats, source_checksum, content_checksum,
                  output_inventory, findings, generated_at=None):
    """Phase 24E registry input. Data only -- no registry is implemented here.

    'allocated' (not merely the declared range) is the field that lets Phase 24E
    perform an exact cross-pack overlap check without reading card payloads.
    """
    findings = findings.without_codes(BUILD_EVENT_CODES)
    launch = launch_assessment(pack, findings)
    doc = {
        "handoffVersion": 1,
        "packId": pack.manifest.get("packId"),
        "version": pack.manifest.get("version"),
        "status": pack.manifest.get("status"),
        "courseId": pack.manifest.get("courseId"),
        "courseType": pack.manifest.get("courseType"),
        "launch": {
            "visible": pack.manifest.get("launch.visible"),
            "readiness": pack.manifest.get("launch.readiness"),
        },
        "idRange": {"min": stats.get("rangeMin"), "max": stats.get("rangeMax")},
        "allocated": {
            "min": stats.get("minId"),
            "max": stats.get("maxId"),
            "count": stats.get("count"),
            "gaps": stats.get("gaps"),
        },
        "sourceChecksum": source_checksum,
        "contentChecksum": content_checksum,
        "generatedFiles": sorted(output_inventory, key=lambda f: f["path"]),
        "provenanceComplete": not launch["missingProvenanceFields"],
        "missingProvenanceFields": launch["missingProvenanceFields"],
        "launchEligible": launch["launchEligible"],
        "launchBlockers": [r["code"] for r in launch["reasons"]],
    }
    if generated_at:
        doc["generatedAt"] = generated_at
    text = json.dumps(doc, ensure_ascii=False, sort_keys=True, indent=2)
    return (text + "\n").encode("utf-8")
