# Phase 2 — Pure Utilities Extraction

Low-risk architectural seam test: extract four duplicated, deterministic,
side-effect-free utilities into tested modules and migrate the audited call sites.
**Runtime behavior is unchanged** (full suite 15/15; card data/IDs/importer/SRS/
Study/Test/Auth/Sync all identical to `production-baseline-v1`).

- Phase 1 commit (rollback anchor): `bfb35a4`
- Phase 2 = the commit introducing this document.

## Modules (all under `hsk_flashcard_app/core/util/`, classic scripts)

Single deliberate namespace: **`window.HSKUtil`** with four sub-namespaces. No
bundler, no ESM, no TypeScript, no npm runtime deps — consistent with ADR-001 and
the static-site/`run.bat` workflow. Loaded in `index.html` immediately after
`data.js`, before every consumer.

### `date.js` → `HSKUtil.date`
- `localDay(date?) : "YYYY-MM-DD"` — **LOCAL** calendar day from local Date
  components. Falsy/missing → now. (Was `metadata.js localDay()`.)
- `isoDay(date?) : "YYYY-MM-DD"` — **UTC** calendar day via `toISOString().slice(0,10)`.
  No arg → current UTC day; falsy → `""`; invalid Date → `""`.
- **Why two:** production has two distinct, intentional semantics — daily-learning
  analytics uses LOCAL day; SRS due-dates/history use UTC day. They are deliberately
  **not** unified (unifying would shift dates across the local/UTC midnight boundary).

### `levels.js` → `HSKUtil.levels`
- `levelOrder(level) : number` — `parseInt(digits) || 0`; unknown/empty/null → 0.
- `sortLevels(levels) : string[]` — new array, ascending by `levelOrder` (does not mutate).
- `levelsFromCards(cards) : string[]` — distinct levels, ordered. Byte-equivalent to
  `[...new Set(cards.map(c=>c.level))].sort(byNumericOrder)`. Generic (numeric suffix),
  preserves HSK1..HSK6 exactly; HSK7/HSK10 sort by number; unknowns sort first.

### `shuffle.js` → `HSKUtil.shuffle`
- `shuffleInPlace(arr, rnd=Math.random) : arr` — Fisher–Yates, mutates + returns same ref.
- `shuffledCopy(arr, rnd=Math.random) : arr` — shuffles a copy; input untouched.
- Exact algorithm preserved from `test.js`: `j = (rnd()*(i+1))|0`. `rnd` is injectable
  for deterministic tests; defaults to `Math.random` in production.

### `card-index.js` → `HSKUtil.cardIndex`
- `buildCardById(cards) : Map` — equivalent to `new Map(cards.map(c=>[c.id,c]))`
  (no id coercion, no card cloning, last-wins on dup). **Wired.**
- `getCardById(index, id)` — thin `Map.get` wrapper. Tested; not wired (runtime uses the Map directly).
- `buildCardsByLevel(cards) : {level:[cards]}` — source order preserved. Tested; **not
  wired** (reserved for Phase 3 CardRepository — no equivalent duplicate to replace yet).
- `duplicateIds(cards) : id[]` — dev/test-only dup detection; not used in production paths.

## Dependency direction & purity
`core/util/*` depends on **nothing** — no DOM, no `localStorage`, no Supabase, no
auth, no mutable app globals, no network, no storage writes. Consumers depend inward
on `HSKUtil`. Pure ⇒ same inputs → same outputs (given an injected `rnd`), fully
unit-testable in isolation. This is the innermost ring of the target architecture.

## Migrated call sites (12)
| File | Was | Now |
|---|---|---|
| `app.js:5` | inline `LEVELS` sort | `HSKUtil.levels.levelsFromCards(cards)` |
| `app.js` (startSession) | `new Map(cards.map(...))` | `HSKUtil.cardIndex.buildCardById(cards)` |
| `test.js:26` | inline `LEVELS` IIFE | `HSKUtil.levels.levelsFromCards(CARDS)` |
| `test.js` opts | `shuffle(opts)` | `HSKUtil.shuffle.shuffleInPlace(opts)` |
| `test.js` types | `shuffle(types.slice())` | `HSKUtil.shuffle.shuffledCopy(types)` |
| `test.js` pool | `shuffle(pool.slice())` | `HSKUtil.shuffle.shuffledCopy(pool)` |
| `test.js` assign | `shuffle(assign)` | `HSKUtil.shuffle.shuffleInPlace(assign)` |
| `test.js` (local `shuffle` def) | Fisher–Yates fn | removed (moved to util) |
| `test.js` todayStr | `new Date().toISOString()...` | `HSKUtil.date.isoDay()` |
| `insights.js:10` | `new Map(CARDS.map(...))` | `HSKUtil.cardIndex.buildCardById(CARDS)` |
| `insights.js:11` | inline `LEVELS` IIFE | `HSKUtil.levels.levelsFromCards(CARDS)` |
| `insights.js` fmtDate | inline UTC slice | `d ? HSKUtil.date.isoDay(d) : ""` |
| `metadata.js:17` | inline `localDay` | `HSKUtil.date.localDay(d)` (delegates) |

`HSKMeta.localDay` remains exported and now delegates, so `insights.js` callers are unaffected.

## Intentionally deferred duplicates (documented, not changed)
- **`app.js today()`, due-date line, streak** — UTC-day formatting, but SRS/streak-
  critical; out of scope ("do not change due/streak"). Can adopt `isoDay` in a later phase.
- **`app.js:190,384` `sort(()=>Math.random()-.5)`** — a **different** (biased) shuffle
  algorithm; converting to Fisher–Yates would change the randomness distribution
  (violates "preserve randomness semantics"). Left as-is.
- **`app.js levelCards`/`dueCards` filters** — per-level filters; not a duplicated map.
  Candidate for `buildCardsByLevel` in Phase 3.
- **`sync.js nowISO()/shortTime()`, `test.js` history date** already delegated where a
  duplicate existed; `nowISO`/`shortTime` are single-use/different and left in place.

## Performance
- No new O(n) full-card scan added to any hot render path. `buildCardById` is built at
  the same points as before (once at insights load; per `startSession`, a rare user
  action). Level lists are computed once at load (unchanged frequency). No network
  calls, no storage writes introduced. Initial load for 5,002 cards is unchanged
  (`levelsFromCards` and `buildCardById` are single linear passes, as before).

## Tests
- `tests/browser/test_util_units.py` (added to the runner as group "Utilities (Phase 2)"):
  date local-vs-UTC in an **Asia/Ho_Chi_Minh (UTC+7)** context + midnight boundary +
  malformed/missing; level ordering incl. HSK7/HSK10/unknown/empty; shuffle copy/
  in-place/deterministic/empty/one-item/no-source-mutation; card index over 5,002
  (every id resolves, level grouping counts, no mutation, dup detection).
- Full suite: **15/15 PASS** (`python tests/run_regression.py`).

## Service worker
Bumped **once** at the end: `hsk-flashcards-v9 → v10`, and the four `core/util/*.js`
files added to the precache `ASSETS`. **Caching strategy unchanged** (cache-first,
same install/activate/fetch handlers). Required so the new offline-shell scripts are
available offline; existing `activate` cleanup removes the old cache.

## Rollback
Phase 2 is reversible and self-contained.
1. `git revert <phase-2-commit>` on `architecture-v2` (restores inline implementations,
   removes the util `<script>` tags, and reverts `sw.js` to `v9`), **or**
   `git checkout bfb35a4 -- hsk_flashcard_app tests/run_regression.py` then delete
   `hsk_flashcard_app/core/` and `tests/browser/test_util_units.py`.
2. To restore a single inline implementation without a full revert, copy it back from
   `production-baseline-v1` (e.g. `git show production-baseline-v1:hsk_flashcard_app/test.js`).
3. Re-run `python tests/run_regression.py` — expect 14/14 after rollback (the util
   suite is removed) or 15/15 if only the migrations are reverted but the util files kept.
4. Phase 1 fixtures/baseline (`tests/`, tag `production-baseline-v1`) are **not**
   deleted by rollback.
