"""Stable card identity: the committed ID ledger is the sole authority.

The existing HSK importer recovers ids by parsing its own generated data.js and
silently falls back to an empty map when that parse fails
(scripts/import_hsk_excel.py:64-71). The consequence is a successful, exit-0
reallocation of every card id from 1, which destroys the join key for all local
and cloud progress. This module inverts that behavior deliberately.

Rules:
  - identity is keyed on the author-owned sourceKey, never on row order, never
    on current card text, never on generated output
  - a ledger that is expected but missing, unreadable, malformed or conflicting
    is FATAL; there is no empty-ledger fallback
  - ids are allocated monotonically inside the pack's reserved range
  - retired ids are never recycled; a retired key that reappears keeps its
    original id, so a delete/restore round-trip preserves SRS history
"""

import json
import os

from . import LEDGER_VERSION
from . import schema

ACTIVE = "active"
RETIRED = "retired"


class Ledger(object):
    def __init__(self, pack_id, id_range, entries=None):
        self.pack_id = pack_id
        self.id_range = id_range          # (min, max)
        self.entries = entries or {}      # sourceKey -> {"cardId": int, "state": str}

    def active_ids(self):
        return {e["cardId"] for e in self.entries.values() if e["state"] == ACTIVE}

    def all_ids(self):
        return {e["cardId"] for e in self.entries.values()}

    def to_json_bytes(self):
        """Deterministic, diff-friendly serialization. This file is committed."""
        doc = {
            "ledgerVersion": LEDGER_VERSION,
            "packId": self.pack_id,
            "idRange": {"min": self.id_range[0], "max": self.id_range[1]},
            "entries": {
                key: {"cardId": val["cardId"], "state": val["state"]}
                for key, val in self.entries.items()
            },
        }
        text = json.dumps(doc, ensure_ascii=False, sort_keys=True, indent=2)
        return (text + "\n").encode("utf-8")


def default_ledger_path(source_path, pack_id):
    """Ledger lives beside the source, because it is authored identity state."""
    base = source_path if os.path.isdir(source_path) else os.path.dirname(source_path)
    return os.path.join(base, "%s-id-ledger.json" % pack_id)


def load_ledger(path, pack_id, id_range, init_allowed, findings):
    """Load and cross-check the ledger. Returns None on any fatal problem."""
    if not os.path.exists(path):
        if init_allowed:
            findings.info(
                "LEDGER_INITIALIZED",
                "no ledger found; creating a new one because --init-ledger was "
                "given. Every card id in this pack will be allocated fresh.")
            return Ledger(pack_id, id_range)
        findings.fatal(
            "LEDGER_MISSING",
            "identity ledger '%s' is missing. Refusing to fall back to an "
            "empty ledger, which would silently reallocate every card id. "
            "Pass --init-ledger only for a genuinely new pack."
            % os.path.basename(path))
        return None

    try:
        with open(path, "r", encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, UnicodeDecodeError) as exc:
        findings.fatal("LEDGER_UNREADABLE",
                       "identity ledger cannot be read: %s" % exc)
        return None
    except ValueError as exc:
        findings.fatal("LEDGER_MALFORMED",
                       "identity ledger is not valid JSON: %s" % exc)
        return None

    if not isinstance(doc, dict):
        findings.fatal("LEDGER_MALFORMED", "identity ledger must be a JSON object")
        return None

    if doc.get("ledgerVersion") != LEDGER_VERSION:
        findings.fatal(
            "LEDGER_VERSION_MISMATCH",
            "identity ledger declares ledgerVersion %r, expected %d"
            % (doc.get("ledgerVersion"), LEDGER_VERSION))
        return None

    if doc.get("packId") != pack_id:
        findings.fatal(
            "LEDGER_PACK_MISMATCH",
            "identity ledger belongs to pack '%s' but this build is for '%s'"
            % (doc.get("packId"), pack_id))
        return None

    declared = doc.get("idRange")
    if not isinstance(declared, dict) or \
            declared.get("min") != id_range[0] or declared.get("max") != id_range[1]:
        findings.fatal(
            "LEDGER_RANGE_MISMATCH",
            "identity ledger declares a different idRange than the manifest; "
            "renumbering an existing pack is never done implicitly")
        return None

    raw_entries = doc.get("entries")
    if not isinstance(raw_entries, dict):
        findings.fatal("LEDGER_MALFORMED", "identity ledger 'entries' must be an object")
        return None

    entries = {}
    seen_ids = {}
    for key in sorted(raw_entries):
        value = raw_entries[key]
        if not isinstance(value, dict):
            findings.fatal("LEDGER_MALFORMED",
                           "ledger entry '%s' is not an object" % key, source_key=key)
            continue
        card_id = value.get("cardId")
        state = value.get("state")
        if not isinstance(card_id, int) or isinstance(card_id, bool):
            findings.fatal("LEDGER_INVALID_ID",
                           "ledger entry '%s' has a non-integer cardId" % key,
                           source_key=key)
            continue
        if state not in (ACTIVE, RETIRED):
            findings.fatal("LEDGER_INVALID_STATE",
                           "ledger entry '%s' has an unknown state %r" % (key, state),
                           source_key=key)
            continue
        if not schema.SOURCE_KEY_RE.match(key):
            findings.fatal("LEDGER_INVALID_KEY",
                           "ledger key '%s' is not a valid sourceKey" % key,
                           source_key=key)
            continue
        if card_id < id_range[0] or card_id > id_range[1]:
            findings.fatal(
                "LEDGER_ID_OUT_OF_RANGE",
                "ledger entry '%s' has cardId %d, outside the declared range "
                "%d-%d" % (key, card_id, id_range[0], id_range[1]),
                source_key=key)
            continue
        if card_id in seen_ids:
            findings.fatal(
                "LEDGER_DUPLICATE_ID",
                "cardId %d is assigned to both '%s' and '%s'"
                % (card_id, seen_ids[card_id], key), source_key=key)
            continue
        seen_ids[card_id] = key
        entries[key] = {"cardId": card_id, "state": state}

    if findings.has_fatal():
        return None
    return Ledger(pack_id, id_range, entries)


def resolve_ids(ledger, cards, allow_removals, findings):
    """Assign a stable integer id to every card.

    Returns (updated_ledger, stats, assigned); all three are None/empty when a
    fatal finding was recorded.

    Allocation is deterministic and machine-independent: new keys are processed
    in ascending sourceKey order and receive the next free id above the current
    high-water mark. Gaps left by retirement are never filled.
    """
    entries = dict((k, dict(v)) for k, v in ledger.entries.items())
    lo, hi = ledger.id_range

    source_keys = [c["sourceKey"] for c in cards]
    present = set(source_keys)

    # Retirement: a ledger key that no longer appears in the source.
    retiring = sorted(
        key for key, val in entries.items()
        if val["state"] == ACTIVE and key not in present)
    if retiring and not allow_removals:
        findings.fatal(
            "CARDS_REMOVED",
            "%d card(s) present in the ledger are absent from the source: %s. "
            "Pass --allow-removals to retire them. Their ids are never reused."
            % (len(retiring), ", ".join(retiring[:10]) + (" ..." if len(retiring) > 10 else "")))
        return None, {}, {}
    for key in retiring:
        entries[key]["state"] = RETIRED

    # Reactivation: a retired key that reappears keeps its original id.
    reactivated = []
    for key in source_keys:
        if key in entries and entries[key]["state"] == RETIRED:
            entries[key]["state"] = ACTIVE
            reactivated.append(key)

    # Allocation: monotonic above the high-water mark, never recycling.
    used = {v["cardId"] for v in entries.values()}
    high_water = max(used) if used else (lo - 1)
    new_keys = sorted(k for k in present if k not in entries)
    allocated = []
    for key in new_keys:
        high_water += 1
        if high_water > hi:
            findings.fatal(
                "RANGE_EXHAUSTED",
                "the reserved id range %d-%d is exhausted; %d new card(s) "
                "could not be allocated" % (lo, hi, len(new_keys) - len(allocated)))
            return None, {}, {}
        entries[key] = {"cardId": high_water, "state": ACTIVE}
        allocated.append(key)

    # Post-assignment drift assertion. The existing importer has the same idea
    # (scripts/import_hsk_excel.py:160-164) and it is worth keeping: prove the
    # anchor actually held rather than assuming it did.
    for key, before in ledger.entries.items():
        after = entries.get(key)
        if after is not None and after["cardId"] != before["cardId"]:
            findings.fatal(
                "ID_DRIFT",
                "cardId for '%s' changed from %d to %d; existing ids are "
                "immutable" % (key, before["cardId"], after["cardId"]),
                source_key=key)

    assigned = {}
    for key in source_keys:
        assigned[key] = entries[key]["cardId"]

    seen = {}
    for key, card_id in sorted(assigned.items()):
        if card_id in seen:
            findings.fatal(
                "DUPLICATE_CARD_ID",
                "cardId %d is assigned to both '%s' and '%s'"
                % (card_id, seen[card_id], key), source_key=key)
        seen[card_id] = key
        if card_id < lo or card_id > hi:
            findings.fatal(
                "ID_OUT_OF_RANGE",
                "cardId %d for '%s' is outside the reserved range %d-%d"
                % (card_id, key, lo, hi), source_key=key)

    if findings.has_fatal():
        return None, {}, {}

    active_ids = sorted(assigned.values())
    stats = {
        "allocated": len(allocated),
        "reused": len(source_keys) - len(allocated),
        "reactivated": len(reactivated),
        "retired": len(retiring),
        "retiredTotal": sum(1 for v in entries.values() if v["state"] == RETIRED),
        "minId": active_ids[0] if active_ids else None,
        "maxId": active_ids[-1] if active_ids else None,
        "count": len(active_ids),
        "gaps": (active_ids[-1] - active_ids[0] + 1 - len(active_ids)) if active_ids else 0,
        "rangeMin": lo,
        "rangeMax": hi,
        "rangeCapacity": hi - lo + 1,
        "rangeUtilization": round(len(entries) / float(hi - lo + 1), 9),
    }

    updated = Ledger(ledger.pack_id, ledger.id_range, entries)
    return updated, stats, assigned
