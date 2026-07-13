# Phase 3 — Read-only CardRepository & Lookup Consolidation

First repository boundary for **FlashEdu** (the future generic flashcard engine; HSK
is content pack #1). A single read-only `CardRepository` now wraps the production card
dataset. **This is an abstraction seam, not a data migration** — no card data, IDs,
ordering, session/SRS/Test/analytics/bookmarks/notes/sync/auth/UI behavior changed
(full suite 16/16; card data/IDs/importer/baseline/SRS all identical to
`production-baseline-v1`).

- Phase 2 anchor (rollback): `a92eb02`
- Phase 3 = the commit introducing this document.

## Module
`hsk_flashcard_app/core/cards/card-repository.js` — classic script, no bundler/ESM/TS.
Extends the existing platform namespace: `window.HSKUtil`.
- `HSKUtil.createCardRepository(cards)` — factory; builds indexes once via the Phase 2
  utilities (`cardIndex.buildCardById`, `cardIndex.buildCardsByLevel`, `levels.levelsFromCards`).
- `HSKUtil.cards` — a **shared instance built once at load** over `window.HSK_CARDS`.

Load order (`index.html`): `data.js` → `core/util/*` → **`core/cards/card-repository.js`**
→ consumers. Depends only on the util modules + `HSK_CARDS` (loaded before it), so there
is no hidden init-order risk (a load-order characterization is in the repo test).

## Read-only contract
No `create/update/save/delete/mutate`. The repository never mutates source arrays,
card objects, ids, order, or fields. `getAll()` returns the **live source array**
(no clone — avoids cloning 5,002 cards); callers treat it as read-only exactly as the
app already treated `cards`. `getByLevel()` returns a fresh copy so the internal index
can't be mutated by callers.

## API (signatures & contracts)
| Method | Contract |
|---|---|
| `getAll()` | source array (same ref as `HSK_CARDS`), source order, read-only |
| `count()` | `cards.length` |
| `getById(id)` | strict `Map.get(id)` — **numeric-id contract**; unknown → `undefined`; no coercion (callers coerce as before) |
| `has(id)` | boolean (`Map.has`) |
| `getManyByIds(ids)` | resolve each via `getById`; **requested order**, **keeps duplicates**, **skips missing** (matches previous `.map(get).filter(Boolean)`); input not mutated |
| `getByLevel(level)` | fresh array copy in source order; unknown level → `[]` |
| `getLevels()` | ordered distinct levels (copy) |
| `groupByLevel()` | level→[cards] index (read-only) |
| `countByLevel()` | level→count (cached) |
| `duplicateIds()` | dev/test-only dup detection (never affects production lookups) |

### ID / error / empty policy
- IDs 1–5002 unchanged; no coercion inside the repo (numeric contract preserved).
  `getById(1)` hits; `getById("1")` misses (type-strict `Map`, same as `===`).
- Unknown id → `undefined`; unknown level → `[]`; empty dataset → `count()==0`,
  `getAll()==[]`, `getLevels()==[]`. Empty id list → `[]`. Malformed test cards don't
  crash construction. Duplicate source ids: last-wins in `getById` (production behavior
  unchanged); `duplicateIds()` surfaces them for dev/test only. No noisy production exceptions.

## Migrated call sites (7)
| File | Was | Now |
|---|---|---|
| `app.js:3` | — | `const cardRepo = window.HSKUtil.cards` |
| `app.js` `levelCards` | `cards.filter(c=>c.level===level)` | `cardRepo.getByLevel(level)` |
| `app.js` `renderHome` | `cards.length` | `cardRepo.count()` |
| `app.js` `startSession` | `new Map(cards.map(...))` per call + `byId.get(id)` | `cardRepo.getById(id)` (no per-call rebuild) |
| `insights.js:10` | `BY = buildCardById(CARDS)` | `repo = window.HSKUtil.cards` (shared) |
| `insights.js:45,116` | `BY.get(Number(id))` | `repo.getById(Number(id))` |
| `insights.js:192` | `ids.map(id=>BY.get(Number(id))).filter(Boolean)` | `repo.getManyByIds(ids.map(Number))` |

## Deferred (documented, unchanged)
- **`app.js` `dueCards`, `learned` count, `fresh` cards, `fallback` session** — all
  coupled to `getCardState`/SRS/session construction. Deferred (out of "don't extract
  SRS/Study Mode" scope). `dueCount` follows `dueCards`.
- **`test.js:98` pool filter** — Test-Mode question construction. Deferred.
- **`sync.js:228`** — legacy-migration `find(x=>x.id==id)` (loose `==`, migration-only,
  inside sync.js). Deferred (don't touch sync.js).
- **Search** (`insights.js` bookmark search over word/pinyin/meaning) — HSK-field-specific;
  extracting into the repo core would embed Chinese/Vietnamese assumptions ("no HSK
  assumptions inside repository core"). Deferred to a later phase.
- Repo API surface `getAll/has/getLevels/groupByLevel/countByLevel/duplicateIds` is
  tested and available but only wired where a proven-equivalent consumer exists.

## Dependency direction
`ui/app/insights → CardRepository → card-index/levels utils → (source array)`. The repo
is DOM-free, storage-free, network-free, and contains **no HSK/Chinese literals** (no
hardcoded six levels, no pinyin/Vietnamese/word fields). HSK-specific semantics stay in
the presentation/content layer.

## Performance
- **Instantiated once** (shared `HSKUtil.cards`; verified `HSKUtil.cards===HSKUtil.cards`).
- Indexes (`byId`, `byLevel`, `levels`) built **once** at load.
- **Net win:** `startSession` no longer rebuilds a 5,002-entry Map on every call —
  it uses the shared `getById`. `getByLevel` slices a prebuilt per-level array instead
  of filtering all 5,002. No new network calls, no storage writes, no full-dataset clone
  (`getAll()===HSK_CARDS`). Initial load unchanged (same one-pass index builds as before).

## Service worker
Bumped **once**: `v10 → v11`; added `core/cards/card-repository.js` to the precache
`ASSETS`. **Strategy unchanged** (cache-first; existing `activate` removes old caches).
Required so the new offline-shell script is available offline.

## Why ProgressRepository / DeckRepository are deferred
- **ProgressRepository/Settings/Bookmark/Note/Analytics** touch **mutable per-user
  state + sync**; wrapping them is a write-path change and must be characterized
  separately (Phase 4+), not mixed into this read-only seam.
- **DeckRepository** needs the deck/content-pack model (`buildCardsByLevel`/decks) which
  is only meaningful once packs are introduced; the level access here is the minimal
  precursor. Both are explicitly out of Phase 3 scope.

## Rollback
Phase 3 is independently reversible.
1. `git revert <phase-3-commit>` on `architecture-v2` — restores inline `cards.filter`/
   `buildCardById` call sites, removes the repo `<script>` tag, and reverts `sw.js` to `v10`.
2. Or manual: `git checkout a92eb02 -- hsk_flashcard_app/app.js hsk_flashcard_app/insights.js hsk_flashcard_app/index.html hsk_flashcard_app/sw.js tests/run_regression.py`, then delete `hsk_flashcard_app/core/cards/` and `tests/browser/test_card_repository.py`.
3. Re-run `python tests/run_regression.py` — expect 15/15 after full rollback (repo suite removed).
4. Phase 1/2 fixtures, baselines, and the `production-baseline-v1` tag are preserved.
