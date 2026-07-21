"""Deterministic pack-catalog generation from Phase 24D registry handoffs.

Phase 24E-A foundation. Produces `catalog.js` — a classic, static, data-only
script declaring `window.FLASHEDU_CATALOG` — from one or more built packs.

Two inputs per pack, because neither alone is sufficient:

  * `registry-handoff.json` — identity, status, launch metadata, declared and
    allocated id ranges, checksums, generated-file inventory.
  * `<packId>-content-pack.js` — the emitted manifest, which is the only place
    `title`, `languageProfile`, `audio`, `capabilities`, `levels` and
    `categories` exist. Its JSON is extracted by marker slice and parsed; the
    generated JavaScript is NEVER executed.

Honesty rules, enforced rather than documented:
  * launch visibility is never inferred. A pack is emitted visible only when the
    author declared it visible AND the build found it launch-eligible AND both
    `status` and `launch.readiness` are "launch". Anything else is emitted
    hidden, and the reason is reported.
  * provenance, licence and readiness are never synthesised.
  * build-only artifacts (CSI, QA reports, ledger, the handoff itself) never
    reach the catalog or the runtime.
"""

import json
import os
import re

from . import emit

CATALOG_SCHEMA_VERSION = 1
HANDOFF_NAME = "registry-handoff.json"

IDENT_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,30}[a-z0-9])?$")
CHECKSUM_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
VERSION_RE = re.compile(r"^[0-9]+(\.[0-9]+)*$")

MAX_CARD_ID = 2147483647

STATUS_VALUES = ("draft", "beta", "launch")
READINESS_VALUES = ("internal", "beta", "launch")
COURSE_TYPES = ("exam", "general")

# Manifest keys that are catalogue-relevant. Everything else the manifest
# carries (source provenance, checksums we take from the handoff, fieldRoles,
# cardCount) stays out of the runtime catalog.
MANIFEST_CARRIED = (
    "title", "shortTitle", "languageProfile", "audio",
    "capabilities", "categories", "levels", "minAppVersion",
)

# Suffixes that are runtime assets. Anything else a build produced is build-only.
RUNTIME_SUFFIXES = ("-content-pack.js", "-cards.js")


class CatalogError(Exception):
    """A handoff or manifest that cannot be turned into an honest catalog."""


def _fail(field, message):
    raise CatalogError("%s %s" % (field, message))


# --------------------------------------------------------------------------
# reading
# --------------------------------------------------------------------------

def read_handoff(path):
    """Load and structurally validate one registry-handoff.json."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, UnicodeDecodeError) as exc:
        _fail("handoff", "cannot be read: %s" % exc)
    except ValueError as exc:
        _fail("handoff", "is not valid JSON: %s" % exc)

    if not isinstance(doc, dict):
        _fail("handoff", "must be a JSON object")
    if doc.get("handoffVersion") != 1:
        _fail("handoff.handoffVersion",
              "must be exactly 1 (unsupported handoff versions fail closed)")

    pack_id = doc.get("packId")
    if not isinstance(pack_id, str) or not IDENT_RE.match(pack_id):
        _fail("handoff.packId", "must match %s" % IDENT_RE.pattern)

    for key in ("version", "status", "courseId", "courseType"):
        if not isinstance(doc.get(key), str) or not doc.get(key):
            _fail("handoff.%s" % key, "must be a non-empty string")
    if doc["status"] not in STATUS_VALUES:
        _fail("handoff.status", "must be one of: %s" % ", ".join(STATUS_VALUES))
    if doc["courseType"] not in COURSE_TYPES:
        _fail("handoff.courseType", "must be one of: %s" % ", ".join(COURSE_TYPES))
    if not IDENT_RE.match(doc["courseId"]):
        _fail("handoff.courseId", "must match %s" % IDENT_RE.pattern)

    launch = doc.get("launch")
    if not isinstance(launch, dict):
        _fail("handoff.launch", "must be an object")
    if launch.get("visible") not in (True, False, None):
        _fail("handoff.launch.visible", "must be a boolean or null")
    if launch.get("readiness") not in READINESS_VALUES + (None,):
        _fail("handoff.launch.readiness",
              "must be one of: %s" % ", ".join(READINESS_VALUES))

    _check_range(doc.get("idRange"), "handoff.idRange")
    _check_allocated(doc.get("allocated"), doc["idRange"], "handoff.allocated")

    for key in ("sourceChecksum", "contentChecksum"):
        value = doc.get(key)
        if not isinstance(value, str) or not CHECKSUM_RE.match(value):
            _fail("handoff.%s" % key,
                  "must be 'sha256:' followed by 64 lower-case hex digits")

    files = doc.get("generatedFiles")
    if not isinstance(files, list) or not files:
        _fail("handoff.generatedFiles", "must be a non-empty array")
    for entry in files:
        if not isinstance(entry, dict):
            _fail("handoff.generatedFiles", "entries must be objects")
        name = entry.get("path")
        if not isinstance(name, str) or not name:
            _fail("handoff.generatedFiles[].path", "must be a non-empty string")
        if os.path.basename(name) != name:
            _fail("handoff.generatedFiles[].path",
                  "must be a bare file name, not a path")
        if not isinstance(entry.get("sha256"), str) or \
                not CHECKSUM_RE.match(entry["sha256"]):
            _fail("handoff.generatedFiles[].sha256", "must be a sha256: digest")
        if not isinstance(entry.get("bytes"), int) or entry["bytes"] < 0:
            _fail("handoff.generatedFiles[].bytes",
                  "must be a non-negative integer")

    if not isinstance(doc.get("launchEligible"), bool):
        _fail("handoff.launchEligible", "must be a boolean")
    return doc


def _check_range(rng, field):
    if not isinstance(rng, dict):
        _fail(field, "must be an object")
    for key in ("min", "max"):
        value = rng.get(key)
        if not isinstance(value, int) or isinstance(value, bool):
            _fail("%s.%s" % (field, key), "must be an integer")
    if rng["min"] <= 0:
        _fail("%s.min" % field, "must be greater than 0")
    if rng["max"] < rng["min"]:
        _fail("%s.max" % field, "must be >= min")
    if rng["max"] > MAX_CARD_ID:
        _fail("%s.max" % field,
              "must stay within the database integer ceiling (%d)" % MAX_CARD_ID)


def _check_allocated(alloc, declared, field):
    if not isinstance(alloc, dict):
        _fail(field, "must be an object")
    count = alloc.get("count")
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        _fail("%s.count" % field, "must be a non-negative integer")
    if count == 0:
        if alloc.get("min") is not None or alloc.get("max") is not None:
            _fail(field, "must report null min/max when count is 0")
        return
    for key in ("min", "max"):
        value = alloc.get(key)
        if not isinstance(value, int) or isinstance(value, bool):
            _fail("%s.%s" % (field, key), "must be an integer when count > 0")
    if alloc["max"] < alloc["min"]:
        _fail("%s.max" % field, "must be >= min")
    if alloc["min"] < declared["min"] or alloc["max"] > declared["max"]:
        _fail(field, "must fall inside the declared idRange")
    if count > (alloc["max"] - alloc["min"] + 1):
        _fail("%s.count" % field, "exceeds the allocated span")


def read_manifest_js(path):
    """Extract the manifest JSON from a generated content-pack.js.

    The generated file is DATA, and it is treated as data: the JSON is sliced
    out at the assignment marker and parsed. Nothing is executed, and no JS
    engine is involved. The naive "first [ to last ]" trick is deliberately
    avoided -- the wrapper contains brackets (`FLASHEDU_PACKS["id"]`), which is
    exactly the failure mode the legacy HSK importer has.
    """
    try:
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
    except (OSError, UnicodeDecodeError) as exc:
        _fail("manifest", "cannot be read: %s" % exc)

    marker = ".manifest = "
    if marker not in text:
        _fail("manifest", "does not contain a '%s' assignment" % marker.strip())
    payload = text[text.index(marker) + len(marker):].strip()
    if payload.endswith(";"):
        payload = payload[:-1]
    try:
        doc = json.loads(payload)
    except ValueError as exc:
        _fail("manifest", "assignment is not valid JSON: %s" % exc)
    if not isinstance(doc, dict):
        _fail("manifest", "must be a JSON object")
    return doc


def read_catalog_js(path):
    """Parse the canonical `window.FLASHEDU_CATALOG = {...};` assignment as DATA.

    Never executes JavaScript. Fails closed on a malformed or AMBIGUOUS catalog:
    exactly one assignment must be present, and its value must be a JSON object
    with a `packs` array. `js_json` neutralises `</` as `<\\/` and escapes
    U+2028/U+2029 -- all valid JSON escapes -- so `json.loads` reverses them.
    """
    try:
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
    except (OSError, UnicodeDecodeError) as exc:
        _fail("catalog", "cannot be read: %s" % exc)

    marker = "window.FLASHEDU_CATALOG"
    count = text.count(marker)
    if count != 1:
        _fail("catalog",
              "must contain exactly one '%s' assignment (found %d)" % (marker, count))
    after = text[text.index(marker) + len(marker):].lstrip()
    if not after.startswith("="):
        _fail("catalog", "'%s' is not a simple assignment" % marker)
    after = after[1:].lstrip()
    if not after.startswith("{"):
        _fail("catalog", "assignment value must be a JSON object")
    # Slice the balanced object: first '{' to the last '}' before the trailing ';'.
    end = after.rfind("}")
    if end < 0:
        _fail("catalog", "assignment value is not terminated")
    try:
        doc = json.loads(after[:end + 1])
    except ValueError as exc:
        _fail("catalog", "assignment is not valid JSON: %s" % exc)
    if not isinstance(doc, dict) or not isinstance(doc.get("packs"), list):
        _fail("catalog", "must be a JSON object with a 'packs' array")
    return doc


# --------------------------------------------------------------------------
# entry construction
# --------------------------------------------------------------------------

def runtime_asset_names(handoff):
    """The two runtime files, taken from the handoff inventory.

    Anything that is not a runtime suffix -- the CSI, and by construction the QA
    reports and the handoff itself, which the pipeline never inventories -- is
    build-only and must not be promoted or catalogued.
    """
    pack_id = handoff["packId"]
    wanted = {
        "manifest": "%s-content-pack.js" % pack_id,
        "cards": "%s-cards.js" % pack_id,
    }
    present = {entry["path"]: entry for entry in handoff["generatedFiles"]}
    for role, name in sorted(wanted.items()):
        if name not in present:
            _fail("handoff.generatedFiles",
                  "is missing the required runtime asset '%s'" % name)
    build_only = sorted(
        name for name in present
        if not any(name.endswith(sfx) for sfx in RUNTIME_SUFFIXES))
    return wanted, present, build_only


def build_entry(handoff, manifest, runtime_dir):
    """One catalog entry. `runtime_dir` is app-root-relative, e.g. packs/hsk."""
    pack_id = handoff["packId"]
    wanted, present, _ = runtime_asset_names(handoff)

    if manifest.get("packId") != pack_id:
        _fail("manifest.packId",
              "is '%s' but the handoff declares '%s'"
              % (manifest.get("packId"), pack_id))
    if manifest.get("version") != handoff["version"]:
        _fail("manifest.version", "disagrees with the handoff version")

    entry = {
        "packId": pack_id,
        "version": handoff["version"],
        "courseId": handoff["courseId"],
        "courseType": handoff["courseType"],
        "status": handoff["status"],
        "idRange": dict(handoff["idRange"]),
        "allocated": dict(handoff["allocated"]),
        "sourceChecksum": handoff["sourceChecksum"],
        "contentChecksum": handoff["contentChecksum"],
        "manifestPath": _join_rel(runtime_dir, wanted["manifest"]),
        "cardsPath": _join_rel(runtime_dir, wanted["cards"]),
    }

    for key in MANIFEST_CARRIED:
        if key in manifest and manifest[key] not in (None, ""):
            entry[key] = manifest[key]

    if "title" not in entry:
        _fail("manifest.title", "is required to build a catalog entry")

    if "minAppVersion" in entry and not VERSION_RE.match(str(entry["minAppVersion"])):
        _fail("manifest.minAppVersion",
              "must be a dotted numeric version string")

    entry["launch"] = _resolve_launch(handoff)
    return entry


def _join_rel(runtime_dir, name):
    parts = [p for p in str(runtime_dir).replace("\\", "/").split("/") if p and p != "."]
    for part in parts:
        if part == "..":
            _fail("runtime directory", "must not contain a '..' segment")
    return "/".join(parts + [name])


def _resolve_launch(handoff):
    """Visibility is derived, never copied blindly.

    An author can declare `launch.visible: true` in a spreadsheet. The build may
    still have found the pack launch-ineligible (missing provenance, a
    launch-blocking duplicate). Emitting that pack as visible would put an
    uncertified study option in front of a learner, so the catalog downgrades it
    to hidden and the generator reports why.
    """
    declared_visible = handoff["launch"].get("visible") is True
    readiness = handoff["launch"].get("readiness") or "internal"
    ready = (
        declared_visible
        and handoff["launchEligible"] is True
        and handoff["status"] == "launch"
        and readiness == "launch"
    )
    return {"visible": bool(ready), "readiness": readiness}


def hidden_reason(handoff):
    """Why a pack is not launch-visible, or None when it is."""
    if handoff["launch"].get("visible") is not True:
        return "author declared launch.visible=false"
    if handoff["launchEligible"] is not True:
        blockers = ", ".join(handoff.get("launchBlockers") or []) or "unspecified"
        return "build reported launchEligible=false (%s)" % blockers
    if handoff["status"] != "launch":
        return "status is '%s', not 'launch'" % handoff["status"]
    if (handoff["launch"].get("readiness") or "internal") != "launch":
        return "launch.readiness is '%s', not 'launch'" % handoff["launch"].get("readiness")
    return None


# --------------------------------------------------------------------------
# catalog assembly
# --------------------------------------------------------------------------

def assemble(entries, default_pack_id=None, app_version=None):
    """Order deterministically and reject cross-pack defects."""
    seen = {}
    for entry in entries:
        pack_id = entry["packId"]
        if pack_id in seen:
            _fail("catalog", "declares pack id '%s' more than once" % pack_id)
        seen[pack_id] = entry

    # Deterministic order, independent of input order: by declared range start,
    # which is a total order because ranges must be disjoint.
    ordered = sorted(entries, key=lambda e: (e["idRange"]["min"], e["packId"]))

    _reject_overlap(ordered, "idRange", lambda e: (e["idRange"]["min"], e["idRange"]["max"]))
    _reject_overlap(
        ordered, "allocated",
        lambda e: (e["allocated"]["min"], e["allocated"]["max"])
        if e["allocated"]["count"] > 0 else None)

    catalog = {"schemaVersion": CATALOG_SCHEMA_VERSION, "packs": ordered}
    if default_pack_id is not None:
        if default_pack_id not in seen:
            _fail("defaultPackId",
                  "'%s' is not declared in this catalog" % default_pack_id)
        if not seen[default_pack_id]["launch"]["visible"]:
            _fail("defaultPackId",
                  "'%s' is not launch-visible" % default_pack_id)
        catalog["defaultPackId"] = default_pack_id
    if app_version is not None:
        catalog["appVersion"] = app_version
    return catalog


def _reject_overlap(entries, field, pick):
    spans = []
    for entry in entries:
        span = pick(entry)
        if span is not None:
            spans.append((span[0], span[1], entry["packId"]))
    spans.sort()
    for i in range(1, len(spans)):
        if spans[i][0] <= spans[i - 1][1]:
            _fail(field,
                  "packs '%s' (%d-%d) and '%s' (%d-%d) overlap; card ids must "
                  "be globally disjoint"
                  % (spans[i - 1][2], spans[i - 1][0], spans[i - 1][1],
                     spans[i][2], spans[i][0], spans[i][1]))


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------

_HEADER = (
    "// Generated by scripts/build_pack_catalog.py -- DO NOT EDIT MANUALLY.\n"
    "// schemaVersion: %d  packs: %d\n"
)


def render_catalog_js(catalog):
    """Data-only classic script. The wrapper is a tool-owned literal.

    No catalogued value ever reaches a code position: the whole document goes
    through the Phase 24D `js_json` hardening (`</` neutralised, U+2028/U+2029
    escaped) and lands in a single JSON value position.
    """
    body = _HEADER % (catalog["schemaVersion"], len(catalog["packs"]))
    body += "window.FLASHEDU_CATALOG = %s;\n" % emit.js_json(catalog)
    return body.encode("utf-8")
