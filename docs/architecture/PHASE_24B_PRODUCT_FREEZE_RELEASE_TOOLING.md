# Phase 24B — Product Freeze + Release Tooling

## Objective & non-goals
Freeze the Milestone 1 product scope and add a safe, **read-only** web-release verification helper.
Tooling + documentation only. **No production behavior/UI/learning-logic/runtime-asset/storage/sync/
auth/service-worker/Supabase change.** The service worker remains exactly `hsk-flashcards-v35` because
no runtime asset changes. If any production/runtime change appears necessary, stop and report — do not
expand scope.

## Milestone 1 DoD
FlashEdu approved and publicly available on **both** the Apple App Store and Google Play. See
[MILESTONE_1_PRODUCT_FREEZE.md](../release/MILESTONE_1_PRODUCT_FREEZE.md) for the frozen scope,
permitted native degradation, and Milestone 2 deferrals.

## Release helper — `scripts/release_check.py`
`python scripts/release_check.py` — **read-only**. Resolves the repo root from its own path (spaces
supported), runs only read-only git (`rev-parse`, `status`), and enforces these gates:
1. inside a git work tree
2. current branch is `main`
3. working tree completely clean (staged + unstaged + untracked)
4. local `main` == local `origin/main`
5. service-worker cache version present (reported exactly)
6. required web runtime assets exist
7. full regression (`tests/run_regression.py`, run with the current interpreter) passes

It **never** fetches/pulls/merges/rebases/resets/checkouts/tags/pushes/deploys, never reads or mutates
user progress/settings/auth storage, never contacts Supabase. It fails fast (skips regression) when a
pre-condition gate fails. There is **no** flag to bypass the dirty-tree, branch, sync, or regression
gates.

**Exit-code / failure model:** exit `0` **only** when every gate passes; non-zero on any failed gate.
On success it reports the exact HEAD commit + SW cache version and prints (but never executes) the
owner's manual Render deploy steps. On failure it prints the failed gates and **no** deploy steps.

## Manual Render workflow (printed by the helper on success; owner performs it)
1. Confirm the reported commit. 2. Render → the FlashEdu Static Site → Manual Deploy → Deploy latest
commit. 3. Wait until Live. 4. Hard-refresh / fresh browser context so SW `v35` activates. 5. Run
[PRODUCTION_SMOKE_CHECKLIST.md](../release/PRODUCTION_SMOKE_CHECKLIST.md).

## Tests — `tests/tooling/test_release_check.py` (registered → 35/35)
Isolated temporary git repos + a **stubbed** `tests/run_regression.py` (no browser/network): clean
`main == origin/main` + passing regression → exit 0 with manual steps; dirty tracked file, staged
change, untracked file, wrong branch, detached HEAD, and diverged `main`/`origin/main` each → non-zero
with no manual steps; regression failure propagates non-zero; success returns zero; repo paths with
spaces work; the reported commit + SW version are exact; the helper leaves the temp repo unmodified
(HEAD + refs unchanged); static scan proves it makes no mutating git calls, imports no network
libraries, spawns only `git`/the regression runner, and has no bypass flags.

## Security & privacy prerequisites; owner decisions; native entry criteria
See [STORE_RELEASE_DECISIONS.md](../release/STORE_RELEASE_DECISIONS.md) (all `REQUIRED`, no fake
values) and the Phase 25 entry gates in the product-freeze doc.

## Files changed (allowlist)
Added: `scripts/release_check.py`, `tests/tooling/test_release_check.py`,
`docs/release/{MILESTONE_1_PRODUCT_FREEZE,STORE_RELEASE_DECISIONS,PRODUCTION_SMOKE_CHECKLIST}.md`,
`docs/architecture/PHASE_24B_PRODUCT_FREEZE_RELEASE_TOOLING.md`. Modified: `tests/run_regression.py`
(register the new suite only). **No `hsk_flashcard_app/**` / `core/**` / Supabase / manifest / native
file changed.** Production runtime is byte-unchanged.

## Rollback
Independently reversible: `git revert` the single Phase 24B commit removes only tooling/docs/tests and
returns the suite to 34/34. No runtime or user-data migration exists.
