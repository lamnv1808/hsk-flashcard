# Regression / characterization tests

**Non-runtime.** These files are never served to users, never referenced by
`index.html`, and never cached by the service worker. They exercise the app through a
real headless browser (Playwright + Chromium) to lock current behavior before any
refactor (Phase 0 safety foundation).

## Safety
- Suites that need the account gate **mock Supabase via request interception**
  (`route('**/supabase-config.js', …)` + `route('.../functions/...')`). **No real
  Supabase project is contacted; production data is never touched.**
- Local-mode suites force `SUPABASE_CONFIG` blank, so they run entirely offline.

## Prerequisites
```bash
python -m pip install playwright
python -m playwright install chromium
```

## Run
1. Serve the app (either):
   - `run.bat`  → http://localhost:8000/hsk_flashcard_app/  (default the tests expect)
   - or any static server; then set `HSK_BASE_URL`, e.g.
     `HSK_BASE_URL=http://localhost:8123 python tests/regression/regression.py`
2. Run a suite (each prints a JSON result with `"pass": true/false`):
```bash
python tests/regression/p0_test.py        # P0 next-card answer-leak (grade/click/swipe/rapid)
python tests/regression/regression.py     # Study: flip/keyboard/audio/auto-read/Read-All/SRS/dark
python tests/regression/features_test.py  # Weak Words, Smart Review, chart, Bookmarks, Notes
python tests/regression/test_mode.py      # Test Mode: all 6 types, scoring, isolation
python tests/regression/auth_test.py      # Accounts (mocked): register/login/isolation/lockout/migration
python tests/regression/offline_test.py   # Offline queue + reconnect flush (mocked sync)
python tests/regression/qa2.py            # Adversarial: view-overlap, note edge cases, chart fill
```
On Windows also set `PYTHONIOENCODING=utf-8` (Chinese/Vietnamese in output).

## Coverage → see `docs/REGRESSION_BASELINE.md`
Each suite maps to items in the regression baseline. Where automation is impractical
(PWA install, service-worker update flow), the baseline gives exact manual steps.
