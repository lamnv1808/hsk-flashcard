# Phase 15 — Read-only AuthContextQuery (account identity / storage namespace)

One read-only `AuthContextQuery` now centralizes the current account identity + storage-
namespace reads. **A projection over the existing auth state, not an auth service** — it
changes no behavior (full suite 25/25; auth isolation / offline sync / metadata-sync green
through the query-derived keys; everything behaviorally identical to
`production-baseline-v1`).

```
BEFORE:  app.js/sync.js/... → direct reads of window.HSK_AUTH + inline `|| base` key logic
AFTER:   window.HSK_AUTH (live) → AuthContextQuery → read-only consumers
```

- Phase 14 anchor (rollback): `ceb96c3`
- Phase 15 = the commit introducing this document.

## Purpose & why it precedes StudySessionEngine
Phase 16 (StudySessionEngine) and future domain services must **not** read `HSK_AUTH`
internals, raw localStorage keys, username-based key construction, or local-only detection
from arbitrary places. Phase 15 creates a stable identity seam first, so those services
depend on one read model instead of scattered globals.

## Module
`hsk_flashcard_app/core/auth/auth-context-query.js` — classic script.
`HSKUtil.createAuthContextQuery(deps)` + shared `HSKUtil.authContext`.
Load order (`index.html`): … `auth.js` → **`core/auth/auth-context-query.js`** → `app.js`
→ … (after the auth module that sets `HSK_AUTH`; before the bootstrap that reads keys).

## Strict read-only contract
Never logs in/out, registers, deletes accounts, touches PINs/tokens/secrets, calls
Supabase, writes/clears localStorage, mutates auth/settings/progress, reloads, or triggers
sync/account events. Returns plain read-only data only.

## Current auth model (source of truth — `auth.js`, unchanged)
`window.HSK_AUTH` is set **synchronously** at auth.js load and is **immutable per page**
(every auth transition does `location.reload()`):
- `{ configured:false }` — Supabase not configured → **local-only**.
- `{ configured:true, needsAuth:true }` — configured but not logged in → **gated**.
- `{ configured:true, userId, username, progressKey, settingsKey }` — logged in.
`configured = !!(SUPABASE_CONFIG.url && SUPABASE_CONFIG.anonKey)`. HSK_AUTH holds **no**
token/PIN/secret (it is the namespacing object).

## Context shape (`getContext()`)
```
{ configured, requiresAuth, authenticated, localOnly,
  userId, username, displayUsername, progressKey, settingsKey, syncAvailable }
```
Derivations (exact): `configured=!!a.configured`; `requiresAuth=!!a.needsAuth`;
`authenticated=!!a.userId`; **`localOnly=!a.configured`** (NOT-configured ≠ "not logged
in"); `userId=a.userId||null`; `username=a.username||null`;
**`displayUsername=a.username||null`** (HSK_AUTH.username is already display-case; there is
no separate server `display_username` in HSK_AUTH); `progressKey=a.progressKey||base`;
`settingsKey=a.settingsKey||base`; `syncAvailable=!!(a.configured && a.userId &&
authModulePresent)` — **exactly** sync.js's gate (`A.configured && A.userId && window.HSKAuth`).

## Convenience reads
`isConfigured / requiresAuth / isAuthenticated / isLocalOnly / getUserId / getUsername /
getDisplayUsername / getProgressKey / getSettingsKey / canSync`.

## Storage-key ownership (unchanged)
Keys are still derived by `auth.js` (`nsProgress(id)="hsk_flashcard_progress_v2::"+id`,
`nsSettings(id)="hsk_flashcard_settings_v2::"+id`). The query only **reads** them, applying
the same fallback app.js used: `getProgressKey() = HSK_AUTH.progressKey ||
"hsk_flashcard_progress_v2"` (and settings likewise). The base literals live in `auth.js`
(`PROG_BASE`/`SET_BASE`) and, as the query's default fallback, here — both unchanged; no key
renamed, no migration.

## Local-only semantics
`localOnly = !configured` (Supabase URL/key absent). A **gated** (configured, not-logged-in)
state is **not** local-only — it uses the base keys transiently behind the auth gate. The
query never bypasses the gate (`requiresAuth` reflects `needsAuth`).

## Sync availability
`canSync()` / `syncAvailable` = `configured && authenticated && authModulePresent`, matching
sync.js's own guard. `configured` alone is **not** treated as "sync available". The query
does not touch sync transport.

## Security exclusions
The context exposes **only** the 10 namespacing/config fields above. It never surfaces
`hsk_session` access/refresh tokens, PINs, password-derived HMAC, the Supabase anon/service
key, or the raw session object — even if the auth object were polluted with such fields (a
test asserts none leak into any getter or `getContext()`).

## Live-provider lifecycle
`authProvider: () => window.HSK_AUTH || {}` (re-read every call) + `authModuleProvider:
() => window.HSKAuth`. HSK_AUTH is stable per page and rebuilt on reload (account switch), so
the query is always current with no stale capture. A test proves a provider swap A→gated→A is
observed with no stale value. Shared `HSKUtil.authContext` built once.

## Migrated reads
| File | Was | Now |
|---|---|---|
| `app.js` bootstrap | `const AUTH=window.HSK_AUTH||{}; stateKey=AUTH.progressKey||base; settingsKey=AUTH.settingsKey||base` | `authContext.getProgressKey()` / `getSettingsKey()` |

`AUTH` was used nowhere else in app.js. `stateKey`/`settingsKey` (and everything consuming
them) are unchanged.

## Deferred auth/sync writes (unchanged)
- **`auth.js`** — the HSK_AUTH source + all login/register/logout/delete/PIN/token/reload +
  account-UI (`buildProfile`) reads.
- **`sync.js`** — `progressKey()`/`settingsKey()` helpers, the `A.configured && A.userId &&
  HSKAuth` gate, and all transport/push/pull/merge (out of scope — "do not modify sync
  transport"; migrating would be transport-adjacent).
- **`test.js` `historyKey`** — Test-Mode history namespace (`hsk_test_history[::userId]`).
The phase's goal — one deliberate shared query with the most-duplicated bootstrap read
centralized — is met without churning auth/sync writes.

## Performance
One shared instance (built once); `getContext()` returns a small plain object; key
derivation is O(1); no network/storage on read; no per-render cloning beyond the small
context; initial load unchanged (in fact app.js no longer reads HSK_AUTH twice inline).

## Characterization / tests
`tests/browser/test_auth_context_query.py`: a faithful copy of the inline `AUTH.progressKey
|| base` key logic vs the query across all three HSK_AUTH variants (+ empty/null) — exact
equality of progress/settings keys and every context field; config/auth/local-only
semantics; user id/username; provider swap (no stale); canSync gate; **security (no PIN/
token/anon/service-role/secret leak)**; no side effects. The real `auth_test` /
`offline_test` / `metadata_sync` suites exercise the query-derived keys end-to-end (account
isolation, offline push/pull).

## Service worker
Bumped **once**: `v21 → v22`; added `core/auth/auth-context-query.js` to the precache
`ASSETS`. **Strategy unchanged**.

## Rollback
Phase 15 is independently reversible.
1. `git revert <phase-15-commit>` on `architecture-v2` — restores app.js's inline
   `AUTH.progressKey || base` bootstrap, removes the query `<script>` tag, and reverts
   `sw.js` to `v21`.
2. Or manual: `git checkout ceb96c3 -- hsk_flashcard_app/app.js hsk_flashcard_app/index.html hsk_flashcard_app/sw.js tests/run_regression.py`,
   then delete `hsk_flashcard_app/core/auth/` and `tests/browser/test_auth_context_query.py`.
3. Re-run `python tests/run_regression.py` — expect **24/24** after full rollback (Phase 15
   suite removed).
4. Phase 1–14 files, baselines, and the `production-baseline-v1` tag are preserved.

## Recommended Phase 16 scope (do not begin) — StudySessionEngine (read-only orchestration seam)
Introduce a **read-only `StudySessionEngine`** that composes the existing seams to *describe*
a study session without owning mutable UI/DOM: given the active `AuthContextQuery` context,
`ContentPack`/`CardRepository`, `ProgressRepository`, `SettingsRepository` and
`StudySessionQuery`, expose a cohesive read model — e.g. `buildSession({levels, limit})`
(delegating to `StudySessionQuery.selectStandardSession`), `describeCard(index)` (front/back
fields + flip/pinyin rules from settings), and session progress counters — **without** moving
the mutable `session`/`current`/`flipped`/`snapshots` state, grading (`ProgressWriter`),
rendering, audio, or navigation out of app.js. Characterize each read model against the
current inline computations; **defer** all mutation and DOM. This is a larger, read-only
composition phase needing its own before-coding audit. Continue deferring `auth.js`/`sync.js`
writes, sync transport ownership, `metadata`/bookmark/note writes, dynamic pack loading, and
UI branding.
