# Phase 8 — Read-only ProgressRepository Seam

Sixth repository boundary for **FlashEdu** (HSK is content pack #1), and the first over
the **highest-risk domain: per-card learning progress**. A single read-only
`ProgressRepository` now freezes and centralizes the exact progress read + default-state
contract that was duplicated inline as `app.js getCardState()` and the
`StudySessionQuery`/`AnalyticsQuery` `stateOf()` helpers. **This is a read boundary only**
— grading, SRS, `save()`, dirty tracking and cloud sync are untouched; every output is
unchanged (full suite 21/21; SRS goldens `srs_characterization`/`p0_test`/`regression`
green; cards/IDs/importer/baseline and every prior repo/query identical to
`production-baseline-v1`).

- Phase 7 anchor (rollback): `f977a2d`
- Phase 8 = the commit introducing this document.

## Why read-only first
Progress drives grading, SRS, due dates, learned status, analytics, Weak Words, session
selection, dirty tracking, cloud sync and the offline queue. Read abstraction and write
ownership must not land in one phase. Phase 8 **freezes every read contract**; a
write-capable `ProgressRepository` is a later, separately characterized phase.

## Module
`hsk_flashcard_app/core/progress/progress-repository.js` — classic script, no
bundler/ESM/TS. `core/progress/` matches the `core/<domain>/` convention of Phases 3–7.
Extends `window.HSKUtil`.
- `HSKUtil.createProgressRepository({progressProvider})`.
- `HSKUtil.progress` — shared instance over the app bridge (symmetry/tests; app.js
  injects its own instance into the queries).

Load order (`index.html`): … `core/settings/settings-repository.js` →
**`core/progress/progress-repository.js`** → `core/sessions/study-session-query.js` →
`core/analytics/analytics-query.js` → … (loaded **before** the queries that consume it).

## Read-only contract
No writes of any kind. The repository never creates a progress row, never assigns or
mutates `progress[cardId]` or any field (`due`/`interval`/`reps`/`attempts`/`correct`),
never grades/schedules, updates streak/daily counts, marks dirty, writes localStorage,
enqueues sync, calls Supabase, or mutates cards/settings/metadata/DOM. **Reading an
untouched card creates no stored row** (verified). It owns **only** per-card learning
progress reads — not bookmarks, notes, settings, dailyCounts, streak, cards, Test Mode,
auth or sync transport (no god-repository).

## Progress schema (frozen — DATA_CONTRACTS §2)
`localStorage[stateKey] = { "<cardId>": { due, interval, reps, correct, attempts } }`.
Only those five fields — no last-rating/ease/legacy/per-card-timestamp fields (sync
timestamps live separately in `hsk_sync_meta::uid`, outside progress).

## Default-state contract (frozen)
`getOrDefault(id, todayKey)` returns, for a **touched** card, the **live stored row**
(same reference — read-only by contract); for an **untouched** card, a **freshly
allocated** `{ due: todayKey, interval: 0, reps: 0, correct: 0, attempts: 0 }`. This is a
byte-for-byte mirror of `app.js getCardState()` and the queries' `stateOf()`. The `due`
default is the **caller's** today key (`StudySessionQuery` passes `now`, `AnalyticsQuery`
passes `isoDay(now)`) — the repository does not own a date source. Reading a default
never writes it back.

## Provider lifecycle
`progress` is a `let` reassigned by `reloadState()` (cloud pull), and rebuilt on account
switch/logout via `location.reload()`; sync merges mutate the stored blob then
`reloadState()`. The repository captures `() => progress` and re-reads it on every call —
so cloud pulls, reconnect merges and account switches are observed with **no stale
progress and no cross-account leakage** (same pattern as Phases 4–7).

## API (all read-only)
| Method | Rule |
|---|---|
| `has(id)` / `isTouched(id)` | `hasOwnProperty(progress, id)` (numeric id → string key; prototype-safe) |
| `getStored(id)` | `progress[id]` — live row or `undefined` |
| `getOrDefault(id, todayKey)` | `progress[id] || {due:todayKey,interval:0,reps:0,correct:0,attempts:0}` |
| `getCardIds()` | `Object.keys(progress)` (string keys, enumeration order) |
| `getEntries()` | `[[id, row], …]` |
| `count()` | `Object.keys(progress).length` |
| `isLearned(id)` | `!!(progress[id] && progress[id].reps > 0)` |
| `isDue(id, todayKey)` | `getOrDefault(id,todayKey).due <= todayKey` |

No `set/save/update/patch/grade/schedule/delete/reset/markDirty/sync`.

## ID / key & reference policy
IDs 1–5002 resolve unchanged; `getStored`/`getOrDefault` use `progress[id]` (number→string
key coercion, exactly as before); `getCardIds()` returns string keys (consumers that need
numbers already `Number(id)` them, e.g. `getWeakWords`). No renumbering, cleanup, or
key-format rewrite. `getStored`/`getOrDefault` expose the **live row reference** for
touched cards (required so nothing changes) — **read-only by contract**; only genuinely
read-only consumers were migrated. No dataset-wide cloning.

## Migrated read sites (dependency direction: ProgressRepository → StudySessionQuery / AnalyticsQuery)
Both queries now take an optional `progressRepository` dependency (falling back to
building one from their existing `progressProvider`, so their standalone tests are
unchanged). `app.js` creates one shared `progressRepo` over the live `progress` binding
and injects it into both.

| File | Was | Now |
|---|---|---|
| `app.js` | `progressProvider: () => progress` (×2) | `const progressRepo = createProgressRepository({progressProvider:()=>progress})`; `progressRepository: progressRepo` (×2) |
| `study-session-query.js` | `stateOf(prog,id,now)` in `selectStandardSession`/`classifyCards` | `progressRepo.getOrDefault(id, now)` |
| `analytics-query.js` `getHomeSummary` | `stateOf(...)`, `Object.keys(prog)`, `prog[id]` | `getOrDefault`, `getCardIds`, `getStored` |
| `analytics-query.js` `getLevelSummary` | `stateOf(...)` | `getOrDefault` |
| `analytics-query.js` `getWeakWords` | `Object.keys(prog)`, `prog[id]` | `getCardIds`, `getStored` |
| `analytics-query.js` `getSmartReviewModel` | `Object.keys(prog)`, `prog[id]` | `getCardIds`, `getStored` |

The queries' public APIs and outputs are unchanged (their existing suites pass via the
`progressProvider` fallback path).

## Deferred (write / SRS / sync — unchanged)
`gradeCard` (read-modify-write via `getCardState` → `progress[c.id]=s; save()`), `save()`,
the snapshot/undo clone, `resetBtn` (`progress={}`), `getCardState`/`dueCards` (left as-is,
shared by the write path), `sync.js` push/pull/merge, `auth.js` progress export, Test
Mode. **`getCardState` is intentionally NOT routed through the repository** — it feeds
`gradeCard`, which mutates the returned row, so the write path stays byte-identical.

## Why write capability is deferred
Grading a card is a read-modify-write that also drives SRS scheduling, due dates,
learned status, daily analytics, dirty marking and cloud push. Wrapping the write path
changes behavior-critical, sync-coupled code and must be characterized separately against
the frozen SRS goldens — not mixed into this read seam.

## Performance
- One shared repository instance (app.js), built once; the queries build at most one
  internal fallback instance at factory time — never per card or per render.
- No clone of progress rows; `getStored`/`getOrDefault`/`has`/`isLearned`/`isDue` are
  O(1); `getCardIds`/`count` are one `Object.keys` (same as the prior inline reads).
  Reuses the live provider; no caching (no stale on account switch), no network, no
  storage. Study session selection and dashboard scans are unchanged in cost.

## Characterization
`tests/browser/test_progress_repository.py` re-implements the **original inline**
`getCardState`/`stateOf` (`__oldState`) and raw `Object.keys`/`prog[id]` reads and
compares to the repository over identical fixtures (touched/untouched/missing/
numeric-string ids, empty/null source) — asserting equal values, ids, ordering, live-row
identity, default fields, **no row created by reads**, provider replacement (account
isolation A→B→A), existing-write visibility, and source unmutated. The migrated queries'
own suites (`session_query`, `analytics_query`) and the SRS goldens
(`srs_characterization`, `p0_test`, `regression`) continue to validate end-to-end
equivalence.

## Service worker
Bumped **once**: `v15 → v16`; added `core/progress/progress-repository.js` to the precache
`ASSETS`. **Strategy unchanged** (cache-first; existing `activate` removes old caches).

## Rollback
Phase 8 is independently reversible.
1. `git revert <phase-8-commit>` on `architecture-v2` — restores the inline `stateOf`
   reads in both queries and the `progressProvider` wiring in app.js, removes the query
   `<script>` tag, and reverts `sw.js` to `v15`.
2. Or manual: `git checkout f977a2d -- hsk_flashcard_app/app.js hsk_flashcard_app/core/sessions/study-session-query.js hsk_flashcard_app/core/analytics/analytics-query.js hsk_flashcard_app/index.html hsk_flashcard_app/sw.js tests/run_regression.py`,
   then delete `hsk_flashcard_app/core/progress/` and `tests/browser/test_progress_repository.py`.
3. Re-run `python tests/run_regression.py` — expect **20/20** after full rollback
   (Phase 8 suite removed).
4. Phase 1–7 fixtures, baselines, and the `production-baseline-v1` tag are preserved.

## Recommended Phase 9 scope (do not begin)
With every read domain now behind a seam (Cards, Settings, Progress, Session, Analytics,
User-Metadata), the next step is the **first write-capable boundary: a
`ProgressWriter`/write-capable `ProgressRepository` for SRS grading persistence** — wrap
`gradeCard`'s read-modify-write (`getCardState` → apply SRS → `progress[id]=…` → `save()`
→ `HSKSync.onSettingsChanged`/dirty) behind one repository method (e.g. `applyGrade` /
`commit`), characterized against the frozen SRS goldens and dirty/push behavior, **without**
changing SRS formulas, due-date math, storage keys or cloud payloads. This is a larger,
sync-coupled write phase needing its own characterization budget; a lower-risk
intermediate alternative is a read-only **`TestModeQuery`** seam over Test Mode
history/results. Defer `BookmarkRepository`/`NoteRepository` writes, sync ownership, and
content-pack/DeckRepository work.
