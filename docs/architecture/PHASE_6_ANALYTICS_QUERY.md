# Phase 6 — Read-only Analytics Query / Dashboard Read-Model Seam

Fourth read-only boundary for **FlashEdu** (HSK is content pack #1). A single
`AnalyticsQuery` now owns the existing **display computations** — home/dashboard
summary, per-level summary, Weak Words ranking, Smart Review model, daily-learning
series — extracted verbatim from `app.js renderHome` and `insights.js`, with **zero
write side-effects**. **This centralizes reads only** — app.js and insights.js keep
all DOM/SVG rendering; no metric definition, formula, ordering, or UI output changed
(full suite 19/19; cards/IDs/importer/baseline/SRS/CardRepository/SettingsRepository/
StudySessionQuery all identical to `production-baseline-v1`; the existing
Weak/Smart/chart/bookmark UI regression suites `features_test`/`qa2` stay green).

- Phase 5 anchor (rollback): `f4476c0`
- Phase 6 = the commit introducing this document.

## Module
`hsk_flashcard_app/core/analytics/analytics-query.js` — classic script, no
bundler/ESM/TS. Mirrors prior `core/*` phases; extends `window.HSKUtil`.
- `HSKUtil.createAnalyticsQuery({cardRepository, progressProvider, settingsRepository, dailyCountsProvider, dateProvider})`.
- `HSKUtil.analytics` — shared instance for consumers outside app.js (insights.js).

Load order (`index.html`): … `core/sessions/study-session-query.js` →
**`core/analytics/analytics-query.js`** → `supabase-config.js` → … → `app.js` → … →
`insights.js`. Depends on the Phase 3 repo + Phase 4 settings repo + injected providers.

## Read-only contract
No writes of any kind. The query never mutates progress/settings/cards/source arrays,
never updates streak or daily counts, never creates a progress row for an untouched
card, never marks dirty / writes localStorage / enqueues sync / calls Supabase /
grades / changes SRS. No DOM, no audio, no network. It returns plain data (card refs
may be live source refs, treated read-only); arrays are fresh.

## Dependency inputs (injected)
| Dep | Purpose | Default |
|---|---|---|
| `cardRepository` | Phase 3 repo — `getAll/getById/getByLevel/getLevels/count` | — |
| `progressProvider` | `() => live progress map` — re-read every call | `{}` |
| `settingsRepository` | Phase 4 repo — `getStreak()` | — |
| `dailyCountsProvider` | `() => live dailyCounts map` (LOCAL-day keys) | `{}` |
| `dateProvider` | `() => Date "now"` | `() => new Date()` |

### Progress-provider lifecycle
`progress` is a `let` reassigned by `reloadState()` after a cloud pull; account
switch/login/logout `location.reload()`. The query captures `() => progress` (or, for
the shared instance, `() => HSK_APP.getProgress()`) and re-reads it on every call — so
account switches and cloud pulls are observed with **no stale progress and no
cross-account leakage**. Two instances exist by design: app.js uses a private one over
its live `progress` binding (works during the first `renderHome()` before `HSK_APP`
exists); `HSKUtil.analytics` (used by insights.js, which loads after app.js/metadata.js)
reads through `HSK_APP.getProgress()` / `HSKMeta.dailyCounts()`. Both read the same
underlying live data.

## Read models & formulas (frozen from current runtime)
`state(id) = progress[id] || {due:today, interval:0, reps:0, correct:0, attempts:0}`.
Date semantics preserved exactly: **`isoDay` (UTC day)** for due comparisons,
**`localDay` (LOCAL day)** for daily counts (see `core/util/date.js`).

### `getHomeSummary(levels)` → `{total, learned, attempts, correct, retentionPct, retentionText, dueCount}`
- `total = cardRepository.count()`.
- `learned` = cards with `reps > 0` (over **all** cards).
- `attempts`/`correct` = Σ over **progress rows** of `.attempts`/`.correct`.
- `retentionText = attempts ? round(correct/attempts*100)+"%" : "0%"`; `retentionPct` the int (0 when no attempts).
- `dueCount` = cards in `levels` with `state.due <= today` (untouched ⇒ due today ⇒ counted).

### `getLevelSummary(levels)` → `[{level,total,learned,due,pct}]`
Per level (given order): `total = getByLevel(level).length`; `learned` = those with `reps>0`;
`due` = those with `due<=today`; `pct = round(learned/total*100)` (matches renderHome; `total 0` ⇒ `NaN`, unreachable for real levels).

### `getWeakWords(levelFilter)` → ranked `[{card,st,score,failures,attempts,last}]`
Identical to `insights.weakCards`. `weakness(st)`: `attempts<=0`→null (excluded);
`failures = attempts-correct`; `failures<=0`→0 (excluded); `sfr=(failures+1)/(attempts+2)`;
`rec=1/(1+daysSince/14)`; `score = failures·sfr·rec`. `daysSince = last ? max(0,round((now−last)/day)) : 30`;
`last = date(due) − interval days`. Iterates `Object.keys(progress)`, resolves via repo,
applies `level` filter (`"all"`/falsy = none), sorts **score desc, then failures desc**.

### `getSmartReviewModel()` → `{hasData, levelRetention:{weakest,strongest}|null, weakCount, recentStruggles, today, last7, last30, streak}`
`hasData = Object.keys(progress).length>0`. Level retention over rows with `attempts>0`,
levels with `att>=10`, `ret=cor/att`, sorted asc → `weakest[0]` / `strongest[last]` as
`{level, pct=round(ret*100)}`, else `null`. `weakCount = getWeakWords("all").length`;
`recentStruggles` = weak items with `last && daysSince(last)<=7`; `today/last7/last30`
from `dailyCounts` via `localDay`; `streak` from settings. Presentation strings stay in
insights.js.

### `getDailySeries(days)` → `{labels:Date[], values:int[], total, max, average}`
For `i=days−1..0`: `label = now − i·day` (oldest→newest), `value = dailyCounts[localDay(label)]||0`.
`total=Σ`, `max=Math.max(1, max(values))`, `average = total/days`. SVG building stays in insights.js.

## Migrated read computations
| File | Was | Now |
|---|---|---|
| `app.js` decl | — | `const analytics = HSKUtil.createAnalyticsQuery({...})` |
| `app.js renderHome` per-level loop | inline `levelCards`/`getCardState`/`dueCards` counts | `analytics.getLevelSummary(LEVELS)` |
| `app.js renderHome` global | inline `learned`/`attempts`/`correct`/`retention`/`dueCount` | `analytics.getHomeSummary(LEVELS)` |
| `insights.js renderWeak` | `weakCards(level)` | `ANALYTICS.getWeakWords(level)` |
| `insights.js renderInsights` | inline retention/weak/daily/streak rows | `ANALYTICS.getSmartReviewModel()` |
| `insights.js renderChart` | inline series/total/max/avg | `ANALYTICS.getDailySeries(chartDays)` |

The inline `weakness/lastGradedDate/daysSince/weakCards/sumDays/P()` helpers moved into
`AnalyticsQuery` and were removed from `insights.js` (no duplicate logic).

## Deferred (documented, unchanged)
- **All analytics WRITES**: `updateStreak` (app.js), `metadata.js` `recordDailyLearn`/
  `pruneDaily` (daily-count writes), grading/SRS writes, `save()`, sync, Test Mode
  history. Untouched.
- **DOM/SVG rendering** stays in app.js/insights.js (query returns data only).
- **Bookmarks page** (`bookmarkCards`, `renderBookmarks` filter/search) — bookmark
  *display*, not analytics; left as-is (still uses `CardRepository.getManyByIds`).
- `app.js` `dueCards()`/`levelCards()` are now unused by the migrated `renderHome` but
  left in place (dead but harmless) to keep the diff minimal and reversible.

## Why AnalyticsRepository write paths are deferred
Streak increment, daily-count recording (dedup + prune), and rating history are
mutable-state + settings/sync writes. Wrapping them changes behavior-critical write
code and must be characterized separately (a future write-capable repository), not
mixed into this read-only read-model seam.

## Performance
- Query object built **once** per module load (app.js instance + shared instance); no
  per-render or per-card rebuild.
- Reuses the Phase 3 `CardRepository` indexes (not rebuilt). Home/level summaries do
  bounded single scans of the source array / per-level arrays — the same work the
  inline code did. Weak/smart iterate `Object.keys(progress)` (touched rows only).
- Computations run **only when the relevant screen renders** (home, Weak, Insights,
  chart) — nothing added to the hot card-render path. No caching (recompute on render),
  so account switches can't produce stale results. No network, no storage, no clone.

## Service worker
Bumped **once**: `v13 → v14`; added `core/analytics/analytics-query.js` to the precache
`ASSETS`. **Strategy unchanged** (cache-first; existing `activate` removes old caches).

## Characterization
`tests/browser/test_analytics_query.py` re-implements each **original inline**
computation (`__oldHome`/`__oldLevel`/`__oldWeak`/`__oldSeries`) and compares it to the
query over identical fixtures + a fixed injected `now` — asserting equal values, order
and counts for home summary, per-level, Weak Words (incl. tie-break), Smart Review
values, and daily series (7/30, zero days, ordering, local-midnight keys), plus
retention edges, account isolation (A→B→A provider swap), and no source/progress/daily
mutation. The existing UI suites `features_test`/`qa2` continue to validate the rendered
Weak/Smart/chart/bookmark screens end-to-end.

## Rollback
Phase 6 is independently reversible.
1. `git revert <phase-6-commit>` on `architecture-v2` — restores the inline renderHome
   counts and insights.js computations, removes the query `<script>` tag and the
   `analytics` decl, and reverts `sw.js` to `v13`.
2. Or manual: `git checkout f4476c0 -- hsk_flashcard_app/app.js hsk_flashcard_app/insights.js hsk_flashcard_app/index.html hsk_flashcard_app/sw.js tests/run_regression.py`,
   then delete `hsk_flashcard_app/core/analytics/` and `tests/browser/test_analytics_query.py`.
3. Re-run `python tests/run_regression.py` — expect **18/18** after full rollback
   (Phase 6 suite removed).
4. Phase 1–5 fixtures, baselines, and the `production-baseline-v1` tag are preserved.

## Recommended Phase 7 scope (do not begin)
**Read-only `BookmarkQuery` / `NoteQuery` read seam** — extract the remaining read-only
metadata *reads* still inline in `metadata.js`/`insights.js` (bookmark id lists,
`isBookmarked`, note existence/text lookups, the Bookmarks-page filter/search resolution
via `CardRepository`) behind one deterministic, side-effect-free query. Continue
deferring **all** writes: `toggleBookmark`/`removeBookmark`/`setNote`/`recordDailyLearn`/
`updateStreak`, grading/SRS, `sync.js`, Test Mode, and content-pack/DeckRepository work.
The first write-capable repository (ProgressRepository) remains a later, separately
characterized phase.
