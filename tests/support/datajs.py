"""Shared helpers for Phase 1 pure-Python characterization tests.

Loads the generated card data (`hsk_flashcard_app/data.js`) and the production
baseline copy from git, without importing any runtime code. No network, no browser.
"""
import json, os, subprocess

# Audited production counts (Phase 0 docs/architecture/DATA_CONTRACTS.md & CURRENT_STATE.md).
EXPECTED_COUNTS = {"HSK1": 149, "HSK2": 150, "HSK3": 295, "HSK4": 600, "HSK5": 1295, "HSK6": 2513}
EXPECTED_TOTAL = 5002
CARD_FIELDS = ["id", "level", "word", "pinyin", "meaning", "example", "examplePinyin", "translation"]
BASELINE_TAG = "production-baseline-v1"

def repo_root():
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def data_js_path():
    return os.path.join(repo_root(), "hsk_flashcard_app", "data.js")

def parse_cards_from_text(text):
    """Extract the JSON array from a `window.HSK_CARDS = [...];` file (ignoring JS comments)."""
    start = text.index("[")
    end = text.rindex("]") + 1
    return json.loads(text[start:end])

def load_cards():
    with open(data_js_path(), encoding="utf-8") as f:
        return parse_cards_from_text(f.read())

def load_cards_from_git(ref):
    """Return the cards array from `<ref>:hsk_flashcard_app/data.js` (e.g. the baseline tag)."""
    out = subprocess.run(
        ["git", "show", f"{ref}:hsk_flashcard_app/data.js"],
        cwd=repo_root(), capture_output=True, text=True, encoding="utf-8",
    )
    if out.returncode != 0:
        raise RuntimeError(f"git show {ref}:data.js failed: {out.stderr.strip()}")
    return parse_cards_from_text(out.stdout)

def by_level(cards):
    d = {}
    for c in cards:
        d.setdefault(c["level"], 0)
        d[c["level"]] += 1
    return d

def emit(suite, fails, extra=None):
    """Print a standard JSON result and return an exit code (0 pass / 1 fail)."""
    res = {"suite": suite, "pass": len(fails) == 0, "fails": fails}
    if extra:
        res.update(extra)
    print(json.dumps(res, ensure_ascii=False))
    return 0 if not fails else 1
