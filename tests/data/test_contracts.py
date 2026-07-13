"""Progress & settings contract characterization (Phase 1). Pure Python.

Freezes the documented shapes/defaults (docs/architecture/DATA_CONTRACTS.md) without
touching runtime code. Covers: safe defaults for absent fields, old-user loadability,
additive metadata not corrupting existing data, account-namespace isolation (no key
collision), serialization round-trip, and the "only dirty cards are pushed" invariant.

The tiny default/normalize/namespace functions below MIRROR the documented runtime
contract; if runtime ever diverges, the browser characterization suites catch it.
"""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "support"))
from datajs import emit, repo_root

FIX = os.path.join(repo_root(), "tests", "fixtures")

# ---- mirrors of documented contract behavior (NOT imported from runtime) ----
def default_card_state(today="2026-07-12"):
    return {"due": today, "interval": 0, "reps": 0, "correct": 0, "attempts": 0}

def setting(settings, key, fallback):
    return settings.get(key, fallback)

def show_front_pinyin(settings):        # undefined => true
    return settings.get("showFrontPinyin", True) is not False

def norm_speech_rate(v):                # allowed set else 1
    try: v = float(v)
    except (TypeError, ValueError): return 1
    return v if v in (0.5, 0.75, 1, 1.25, 1.5) else 1

def ns(base, uid):                      # namespaced storage key
    return f"{base}::{uid}"

PROG_BASE, SET_BASE = "hsk_flashcard_progress_v2", "hsk_flashcard_settings_v2"
SYNC_KEYS = ["hsk_sync_dirty", "hsk_sync_meta", "hsk_sync_lastpull", "hsk_sync_settime", "hsk_import_done"]

def main():
    fails = []

    # 1) default card state shape/values
    d = default_card_state()
    if list(d.keys()) != ["due", "interval", "reps", "correct", "attempts"]:
        fails.append("default card-state key set/order drifted")
    if (d["interval"], d["reps"], d["correct"], d["attempts"]) != (0, 0, 0, 0):
        fails.append("default card-state numeric defaults changed")

    # 2) old-user settings load safely; NEW metadata defaults without error
    old = json.load(open(os.path.join(FIX, "legacy_settings_old_user.json"), encoding="utf-8"))
    if setting(old, "bookmarks", []) != []: fails.append("bookmarks default not []")
    if setting(old, "notes", {}) != {}: fails.append("notes default not {}")
    if setting(old, "dailyCounts", {}) != {}: fails.append("dailyCounts default not {}")
    if show_front_pinyin(old) is not True: fails.append("showFrontPinyin (present true) misread")
    if show_front_pinyin({}) is not True: fails.append("showFrontPinyin (absent) should default true")
    if norm_speech_rate(0.85) != 1 or norm_speech_rate(1.25) != 1.25:
        fails.append("speechRate normalization drifted")

    # 3) additive metadata does NOT corrupt existing keys (merge preserves everything)
    before_keys = set(old.keys())
    merged = dict(old)
    merged["bookmarks"] = [1, 150]
    merged["notes"] = {"1": "ghi chú"}
    merged["dailyCounts"] = {"2026-07-12": 3}
    if not before_keys.issubset(set(merged.keys())):
        fails.append("adding metadata dropped existing settings keys")
    if any(merged[k] != old[k] for k in old):
        fails.append("adding metadata mutated existing settings values")

    # 4) account-namespace isolation: two users never share keys
    ua, ub = "user-A", "user-B"
    keys_a = {ns(PROG_BASE, ua), ns(SET_BASE, ua)} | {ns(k, ua) for k in SYNC_KEYS}
    keys_b = {ns(PROG_BASE, ub), ns(SET_BASE, ub)} | {ns(k, ub) for k in SYNC_KEYS}
    if keys_a & keys_b:
        fails.append("namespaced keys collide across accounts")
    if ns(PROG_BASE, ua) == PROG_BASE:
        fails.append("namespaced key equals base key")
    # base (local-only) keys are distinct from any namespaced key
    if PROG_BASE in keys_a or SET_BASE in keys_a:
        fails.append("base key collides with a namespaced key")

    # 5) serialization round-trip preserves values incl. unicode + line breaks
    blob = {"notes": {"1": "dòng 1\ndòng 2 — 你好", "150": "café"}, "bookmarks": [1, 2, 3],
            "dailyCounts": {"2026-07-12": 5}, "speechRate": 0.75, "dark": True}
    rt = json.loads(json.dumps(blob, ensure_ascii=False))
    if rt != blob:
        fails.append("settings JSON round-trip changed values")

    # 6) "untouched cards do not create cloud rows": push payload = only dirty ids
    progress = json.load(open(os.path.join(FIX, "legacy_progress.json"), encoding="utf-8"))
    dirty = [150]  # only one card changed
    push_rows = [{"card_id": int(i), **progress[str(i)]} for i in dirty if str(i) in progress]
    if len(push_rows) != 1 or push_rows[0]["card_id"] != 150:
        fails.append("push payload should contain only dirty cards")
    if any(str(cid) for cid in [1, 1194] if str(cid) in {str(r['card_id']) for r in push_rows}):
        fails.append("untouched card appeared in push payload")

    return emit("contracts", fails, {"checks": 6})

if __name__ == "__main__":
    sys.exit(main())
