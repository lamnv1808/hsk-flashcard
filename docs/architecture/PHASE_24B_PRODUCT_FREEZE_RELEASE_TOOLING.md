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
`python scripts/release_check.py` — **read-only, fail-closed**. Resolves the repo root from its own
path (spaces supported), runs only read-only git (`rev-parse`, `status`), and enforces these gates:
1. inside a git work tree
2. all safety-critical git reads succeed **and** have the expected shape (branch is a non-blank token;
   HEAD/main/origin-main are 40-hex SHAs) — a failed `git status` (nonzero exit / empty stdout) is
   **never** treated as a clean tree
3. current branch is `main`
4. working tree completely clean (staged + unstaged + untracked)
5. local `main` == local `origin/main`
6. service-worker cache version present (reported exactly)
7. the **full `sw.js` precache inventory** (its `ASSETS` array) is parsed **strictly** and read-only —
   the array literal is isolated and parsed with `ast.literal_eval` (literals only; **never executes
   JS**), so any unparsed token, expression (`'a'+'b'`), function call (`foo()`), missing bracket, or
   non-string/empty entry **fails closed**. Every listed path must resolve **inside**
   `hsk_flashcard_app` (except the intentional `./` app-root entry): URLs/protocol-relative, absolute
   POSIX paths, Windows drive-absolute and UNC paths, and parent traversal via **both** `/` and `\\`
   are rejected (with a real-path/`commonpath` containment check as defense in depth — a traversal is
   rejected even when the external target exists). Every remaining path must exist; the count of
   verified assets is reported (the real inventory is **36**; no second asset list is kept in Python)
8. full regression (`tests/run_regression.py`, run with the current interpreter) passes
9. **post-regression revalidation:** branch/HEAD/main/origin-main and cleanliness are snapshotted
   before regression and re-checked after — since regression is executable code, any mutation
   (tracked edit, new untracked file, staged change, moved HEAD/branch/ref) fails the run

It **never** fetches/pulls/merges/rebases/resets/checkouts/tags/pushes/deploys, never reads or mutates
user progress/settings/auth storage, never contacts Supabase, and never auto-cleans/reverts anything.
It fails fast (skips regression) when a pre-condition gate fails. There is **no** flag to bypass the
dirty-tree, branch, sync, precache, or regression gates. CLI output is ASCII-only (docs stay UTF-8).

**Exit-code / failure model:** exit `0` **only** when every gate passes (including post-regression
revalidation); non-zero on any failed gate. On success it reports the exact HEAD commit + SW cache
version + verified precache-asset count and prints (but never executes) the owner's manual Render
deploy steps. On failure it prints the failed gates and **no** deploy steps.

## Release ordering — `release_check.py` is a POST-PUSH, PRE-DEPLOY gate
The helper requires `main == origin/main`, so it is designed to run on a **clean, synchronized main
after the push**, immediately **before** the manual Render deploy. The correct future runtime-release
order is:
1. Merge the phase branch locally into `main` (`git merge --no-ff`).
2. Run `python tests/run_regression.py` on local `main`.
3. **Push** `main` to origin (`git push origin main`).
4. Run `python scripts/release_check.py` on the clean, synchronized `main`.
5. Only if it passes, **manually** deploy on Render (Static Site → Manual Deploy → Deploy latest commit); wait until Live.
6. Hard-refresh / fresh browser context so SW `v35` activates; run
   [PRODUCTION_SMOKE_CHECKLIST.md](../release/PRODUCTION_SMOKE_CHECKLIST.md).

Note: running `release_check.py` **after the local merge but before the push is expected to FAIL** the
`main == origin/main` gate — that is intentional; the synchronized-main gate is not relaxed to permit
an ahead-of-origin `main`. Phase 24B itself changes only tooling/docs/tests, so it does **not** require
a Render deployment (`hsk_flashcard_app` is byte-unchanged). The step list the helper prints on success
mirrors steps 5–6.

## Tests — `tests/tooling/test_release_check.py` (registered → 35/35)
Isolated temporary git repos + a **stubbed** `tests/run_regression.py` (no browser/network) whose
`sw.js` carries a real `ASSETS` array: clean `main == origin/main` + passing regression → exit 0 with
manual steps + exact commit/SW/precache-count + post-regression gate PASS; dirty/staged/untracked/
wrong-branch/detached-HEAD/diverged each → non-zero, no manual steps; regression failure → non-zero.
**Finding 1:** a passing regression that modifies a tracked file / creates an untracked file / stages
a file / moves HEAD → the post-regression revalidation fails (non-zero, no steps). **Finding 2:**
missing a listed precache asset, and a malformed or missing `ASSETS` array, each fail closed.
**Finding 3:** a non-git directory and an empty repo (no HEAD) fail closed; a source scan confirms the
clean gate requires `clean is True` and that `git status` is return-code-gated. Plus: space-containing
paths work; the helper leaves the temp repo unmodified (HEAD + refs unchanged); ASCII-only output; and
a static scan proves no mutating git calls, no network imports, only `git`/the regression runner are
spawned, and no bypass flags.

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
