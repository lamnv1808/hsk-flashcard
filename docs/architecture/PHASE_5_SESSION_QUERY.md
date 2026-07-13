# Phase 5 — Read-only Study Session Query / Card-Selection Seam

Third read-only boundary for **FlashEdu** (HSK is content pack #1). A single
`StudySessionQuery` now owns the logic that **selects which cards enter a Study
session** — extracted verbatim from `app.js`'s inline `startStudy`/`startSession`
selection, with **zero write side-effects**. **This is query extraction, not a
session engine** — app.js still owns all mutable session state, grading, navigation,
audio, completion, progress writes and sync (full suite 18/18; cards/IDs/importer/
baseline/SRS/CardRepository/SettingsRepository all identical to
`production-baseline-v1`).

- Phase 4 anchor (rollback): `a2ca4ed`
- Phase 5 = the commit introducing this document.

## Module
`hsk_flashcard_app/core/sessions/study-session-query.js` — classic script, no
bundler/ESM/TS. Path mirrors `core/cards/`, `core/settings/`. Extends `window.HSKUtil`.
- `HSKUtil.createStudySessionQuery({cardRepository, progressProvider, dateProvider, randomProvider})`.

Load order (`index.html`): `data.js` → `core/util/*` → `core/cards/card-repository.js`
→ `core/settings/settings-repository.js` → **`core/sessions/study-session-query.js`**
→ `supabase-config.js` → `auth.js` → `app.js` → … . Depends only on the Phase 3
repo + injected providers.

## Read-only contract
No writes of any kind. `selectStandardSession`/`selectExplicitCardSession`/
`classifyCards` never mutate cards, progress, settings, or source arrays; never write
localStorage, mark dirty, or enqueue sync; never grade, change SRS/due fields, or
**create a progress row for an untouched card** (selecting a card does not touch its
progress). No DOM, no audio, no network. `getAll()` is read via the repo (live source
array) and only `.filter()`/`.slice()` copies are sorted — the source is never sorted
in place.

## Dependency inputs (injected)
| Dep | Purpose | Default |
|---|---|---|
| `cardRepository` | Phase 3 repo — `getAll()` (source order, indexes built once), `getById()` | — |
| `progressProvider` | `() => live progress map` — re-read every call | `{}` |
| `dateProvider` | `() => "YYYY-MM-DD"` today (matches app.js `today()`) | `new Date().toISOString().slice(0,10)` |
| `randomProvider` | `() => [0,1)` for the fallback shuffle | `Math.random` |

### Progress-provider lifecycle
`progress` in app.js is a `let` **reassigned** by `reloadState()` after a cloud pull;
login/logout/account-switch/delete all `location.reload()`. The query captures
`() => progress` (closure over the live binding) and re-reads it on every call — so
account switches and cloud pulls are observed with **no stale/captured progress and no
cross-account leakage**. Same account-safe pattern as SettingsRepository.

## API
- `selectStandardSession({levels, limit})` → `Card[]` — normal Study session.
  `limit` is a Number or the string `"all"`.
- `selectExplicitCardSession(ids)` → `Card[]` — Weak Words / Bookmarks sessions.
- `classifyCards({levels})` → `{due:number[], fresh:number[]}` — read-only helper for
  characterization/tests; does not select or truncate.

No `next/previous/grade/flip/finish/save/resume` — those belong to later phases.

## Classification rules (frozen from current runtime)
`state(id) = progress[id] || {due: today, interval:0, reps:0, correct:0, attempts:0}`.
Selection reads only `.due` and `.reps`.
- **due**: in selected levels AND `state.due <= today` (string compare). An **untouched**
  card has `due === today` ⇒ it **is** due.
- **fresh**: in selected levels AND `state.reps === 0`. An untouched card **is** fresh.
- A card can be in **both** due and fresh (every untouched card is).
- **fallback**: all in-level cards, used only when the primary selection is empty.
- (`learned`, used only by the renderHome *display* counters, = `reps > 0` — **not**
  part of session selection; deferred, see below.)

## Priority / composition (exact)
1. `due` (source order, no shuffle).
2. `fresh` **not already in due** (deduped by id) appended after due.
3. `merged = due ++ fresh'`; take `slice(0, limit)` (`"all"` ⇒ whole pool).
4. **Only if the result is empty** (nothing due or fresh in the selected levels →
   everything studied and scheduled in the future): shuffle **all in-level cards** and
   take `slice(0, limit)`.

Duplicates cannot enter twice (dedup by id). When fewer cards exist than requested, the
whole pool is returned. `limit` uses `Number(sizeSetting)` exactly as before (edge
values like `0` yield an empty session → immediate completion, unchanged).

## Randomization
The primary path is **deterministic source order — no shuffle**. Only the fallback
shuffles, preserving the **exact original algorithm** `pool.sort(() => rnd() - 0.5)`
(deliberately **not** the Phase 2 Fisher–Yates, which has a different distribution —
see `core/util/shuffle.js` note). `rnd` is injectable (default `Math.random`) so tests
are deterministic; production is byte-identical to before. The shuffle runs on a
**copy** (`all.filter(inLevel).slice()`), so the source array is never reordered.

## Explicit-card sessions (Weak Words / Bookmarks)
`selectExplicitCardSession(ids)` resolves each id via `cardRepository.getById` in
**requested order**, **dedups** by resolved id, **skips missing**, does **not** shuffle,
and creates **no progress**. This is exactly the pre-Phase-5 `startSession` inline loop.
It is **not** merged with due/fresh selection (current behavior never did). Callers
(`insights.js studyIds` ← Weak Words weakness-ordered ids / Bookmarks filtered ids) are
unchanged and still call `HSK_APP.startSession(ids)`.

## Migrated selection call sites (2)
| File | Was | Now |
|---|---|---|
| `app.js` decl | — | `const sessionQuery = HSKUtil.createStudySessionQuery({...})` |
| `app.js startStudy` | inline `due/fresh/merged/slice/fallback` (10 lines) | `session = sessionQuery.selectStandardSession({levels, limit})` |
| `app.js HSK_APP.startSession` | inline `getById`+`seen` loop | `const list = sessionQuery.selectExplicitCardSession(ids)` |

The write/lifecycle lines around them are **unchanged**: `saveSettings()`,
`updateStreak()`, `session=`, `current=0`, `showView`, `renderCard()`, view reset.

## Deferred (documented, unchanged)
- **All mutation / session state**: `startStudy`/`startSession` writes (settings save,
  streak, `session`, `current`, `snapshots`, view, first render), grading, Next/prev,
  flip/animation, answer-leak protection, audio, completion stats, `save()`, SRS
  scheduling. (Belong to a later StudySessionEngine phase.)
- **renderHome display counters** — `dueCards(levels)` and the `learned`
  (`reps>0`) filters used to render deck/due/learned **counts**. These are analytics
  *display*, not session construction; migrating them belongs to a future
  read-only AnalyticsQuery (Phase 6 candidate). `dueCards()` remains in app.js.
- **Test Mode** question/distractor construction and state — out of scope.
- **`metadata.js`** (bookmark/note/daily writes) and **`sync.js`** — untouched.

## Why the full StudySessionEngine is deferred
Grading, `current` index, flip/animation, the P0 answer-leak reflow, audio lifecycle,
completion, progress mutation and dirty tracking are **write-path + mutable-state**
concerns intertwined with SRS scheduling. Wrapping them changes behavior-critical code
and must be characterized separately, not mixed into this read-only selection seam.

## Performance
- Query object built **once** per module load (app.js instance); no per-session rebuild.
- Reuses the Phase 3 `CardRepository` — its `byId`/`byLevel`/`levels` indexes are **not**
  rebuilt; selection does `getAll().filter(...)` (same O(n) source scan the inline code
  did) and small `.slice()`/`.sort()` on copies. No full-card clone, no progress
  normalization, no network, no storage. Session-start cost is unchanged.

## Service worker
Bumped **once**: `v12 → v13`; added `core/sessions/study-session-query.js` to the
precache `ASSETS`. **Strategy unchanged** (cache-first; existing `activate` removes old
caches).

## Characterization
`tests/browser/test_session_query.py` includes a direct comparison: a faithful copy of
the **original inline** `startStudy` selection (`__oldStandard`) vs
`selectStandardSession` over identical fixtures (empty / mixed / all-future progress),
identical injected date, and identical seeded `rnd` — asserting equal **ids, order, and
count** across standard and fallback paths, plus source/progress left unmutated.

## Rollback
Phase 5 is independently reversible.
1. `git revert <phase-5-commit>` on `architecture-v2` — restores the inline
   `startStudy`/`startSession` selection, removes the `sessionQuery` decl and the repo
   `<script>` tag, and reverts `sw.js` to `v12`.
2. Or manual: `git checkout a2ca4ed -- hsk_flashcard_app/app.js hsk_flashcard_app/index.html hsk_flashcard_app/sw.js tests/run_regression.py`,
   then delete `hsk_flashcard_app/core/sessions/` and `tests/browser/test_session_query.py`.
3. Re-run `python tests/run_regression.py` — expect **17/17** after full rollback
   (Phase 5 suite removed).
4. Phase 1–4 fixtures, baselines, and the `production-baseline-v1` tag are preserved.

## Recommended Phase 6 scope (do not begin)
**Read-only `AnalyticsQuery` / dashboard-read seam.** Extract the remaining read-only
*display* computations that Phase 5 deliberately left inline — `renderHome`'s
`dueCards`/`learned`/retention counters and `insights.js`'s weakness model, daily-count
sums and streak/retention reads — behind one deterministic, side-effect-free query over
`CardRepository` + `SettingsRepository` + a live progress provider. Still defer: all
progress/SRS **writes**, the StudySessionEngine, grading, `metadata.js` write paths,
`sync.js`, Test Mode, and content-pack/DeckRepository work.
