"""Importer determinism (Phase 1). Pure Python; no browser, no network.

Verifies that regenerating hsk_flashcard_app/data.js from the unchanged Excel source
produces byte-identical output on repeated runs AND matches the currently committed
data.js (idempotent). SAFETY: the current data.js bytes are backed up and ALWAYS
restored, so this test never leaves the working tree changed regardless of outcome.
Skips gracefully if the importer prerequisites (openpyxl / source xlsx) are absent.
"""
import sys, os, subprocess, hashlib
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "support"))
from datajs import repo_root, data_js_path, emit

def sha(b): return hashlib.sha256(b).hexdigest()

def main():
    root = repo_root()
    importer = os.path.join(root, "scripts", "import_hsk_excel.py")
    xlsx = os.path.join(root, "source_data", "HSK1-HSK6.xlsx")
    if not os.path.exists(importer) or not os.path.exists(xlsx):
        return emit("importer_determinism", [], {"skipped": "importer or source xlsx missing"})
    try:
        import openpyxl  # noqa: F401
    except Exception:
        return emit("importer_determinism", [], {"skipped": "openpyxl not installed"})

    path = data_js_path()
    with open(path, "rb") as f:
        original = f.read()
    orig_hash = sha(original)

    fails = []
    run1_hash = run2_hash = None
    try:
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        r1 = subprocess.run([sys.executable, importer], cwd=root, capture_output=True, text=True, env=env)
        if r1.returncode != 0:
            fails.append(f"importer run1 failed: {r1.stderr.strip()[-200:]}")
        else:
            with open(path, "rb") as f: run1_hash = sha(f.read())
        r2 = subprocess.run([sys.executable, importer], cwd=root, capture_output=True, text=True, env=env)
        if r2.returncode != 0:
            fails.append(f"importer run2 failed: {r2.stderr.strip()[-200:]}")
        else:
            with open(path, "rb") as f: run2_hash = sha(f.read())
    finally:
        # ALWAYS restore the original committed bytes — tree must be unchanged.
        with open(path, "wb") as f:
            f.write(original)

    if run1_hash and run2_hash and run1_hash != run2_hash:
        fails.append("importer output differs between runs (non-deterministic)")
    if run1_hash and run1_hash != orig_hash:
        fails.append("importer output differs from committed data.js (source unchanged)")
    # confirm restore succeeded
    with open(path, "rb") as f:
        restored_hash = sha(f.read())
    if restored_hash != orig_hash:
        fails.append("SAFETY: failed to restore original data.js")

    return emit("importer_determinism", fails, {
        "deterministic": bool(run1_hash and run2_hash and run1_hash == run2_hash),
        "matchesCommitted": bool(run1_hash and run1_hash == orig_hash),
        "restoredClean": restored_hash == orig_hash,
    })

if __name__ == "__main__":
    sys.exit(main())
