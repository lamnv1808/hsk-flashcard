# Phase 10 — ContentPack Foundation & Legacy HSK Adapter

The first explicit **ContentPack** contract for **FlashEdu**, plus one adapter wrapping
the current HSK dataset. **This is a structural seam only** — the same 5,002 cards, IDs,
fields, order and runtime behavior; no data migration, no `data.js`/importer change
(full suite 23/23; `card_stability`/`baseline_comparison`/`importer_determinism` green;
every prior repo/query behaviorally identical to `production-baseline-v1`).

```
Legacy HSK dataset (data.js → window.HSK_CARDS)
        ↓  packs/hsk/hsk-content-pack.js  (adapter)
ContentPack read contract (core/content/content-pack.js, generic)
        ↓  HSKUtil.contentPack.getCards()  (same live array, no clone)
CardRepository  →  StudySessionQuery / AnalyticsQuery / TestModeQuery / …
```

- Phase 9 anchor (rollback): `806843b`
- Phase 10 = the commit introducing this document.

## Modules
- **Generic core:** `hsk_flashcard_app/core/content/content-pack.js` — `HSKUtil.createContentPack(spec)`.
  Hardcodes **nothing** product-specific (no HSK/Chinese/pinyin/Vietnamese, no fixed
  deck set, no fixed card count). Read-only.
- **HSK adapter:** `hsk_flashcard_app/packs/hsk/hsk-content-pack.js` — publishes the single
  active pack `HSKUtil.contentPack`. All HSK facts live here.

Load order (`index.html`): `data.js` → `core/util/*` → **`core/content/content-pack.js`**
→ **`packs/hsk/hsk-content-pack.js`** → `core/cards/card-repository.js` → … (pack built
before the repository that consumes it).

## Read-only contract
A pack never mutates its source cards/arrays, never writes storage/network, never
touches progress/settings/DOM. It is a **descriptive read seam** over an existing card
source and does **not** clone the cards (`getCards()` returns the live `window.HSK_CARDS`).

## Minimum contract (derived from current consumers)
`createContentPack(spec)` → pack with:
`getId()`, `getVersion()`, `getTitle()`, `getLanguages()`, `getCapabilities()`,
`hasCapability(c)`, `getCards()` (live source), `getDecks()`/`getDeckIds()` (ordered,
copies), `getFieldRoles()`/`getRole(role)`, `getTestModes()`, `validate()`.
`spec = { id, version, title, languages, capabilities, fieldRoles, testModes, getCards, decks|deckProvider }`.

## Semantic field roles (HSK adapter — no runtime field renamed)
| role | legacy field |
|---|---|
| primaryPrompt | word |
| pronunciation | pinyin |
| definition | meaning |
| exampleText | example |
| examplePronunciation | examplePinyin |
| exampleTranslation | translation |
| deck | level |
| stableId | id |
The engine-facing **roles** are generic; the **field names** are the HSK product's
current fields, unchanged at runtime.

## Deck / level metadata
**Derived from the cards** by the adapter (`deckProvider`) via `levelsFromCards` +
per-level counts — **not hardcoded to six**, so HSK7+ would appear automatically (same
philosophy as the rest of the app). Each deck: `{ id: "HSKn", order: n, title: "HSKn",
cardCount }`, ordered by numeric suffix. Current: HSK1..HSK6 = 149/150/295/600/1295/2513,
total 5002. Level/deck identifiers (`HSK1`…`HSK6`) are unchanged.

## Capabilities
Declared, declarative, minimal: `["study","srs","test","audio","frontReadingToggle",
"examples","translation","bookmarks","notes","analytics"]`. **Not** used to gate/redesign
UI in this phase (byte-equivalent behavior preserved). Purpose: architecture
documentation + testability.

## Active-pack lifecycle
One shared read-only instance `HSKUtil.contentPack`, built **once** at load (decks derived
once at construction). **No registry, no switcher, no UI control, no persisted selection,
no multi-pack sessions.**

## CardRepository integration
`core/cards/card-repository.js` now initializes from the active pack:
`createCardRepository((HSKUtil.contentPack && HSKUtil.contentPack.getCards()) || window.HSK_CARDS || [])`.
Because the HSK pack's `getCards()` returns the **same `window.HSK_CARDS` reference** (no
clone), `getAll()`/`getById`/`getByLevel`/`count`/`getLevels`/indexes are **byte-identical**
to initializing directly from `HSK_CARDS` (proven by an equivalence characterization).
Repository still built once; a defensive fallback keeps it working if the pack is absent.

## TestMode mapping decision — DEFERRED runtime wiring
`TestModeQuery` keeps its built-in `TYPE_DEFS`. The HSK pack **exposes** its `testModes`
(the six type defs) as pack metadata, and a characterization test asserts they are
**byte-identical** to `TestModeQuery.getTypeDefs()`. Runtime injection is **deferred** to
avoid churning the just-frozen Phase 9 seam for zero behavior change — exactly the
prompt's "create the pack mapping and characterize it, but defer runtime wiring" option.

## Importer compatibility (unchanged)
`source_data/HSK1-HSK6.xlsx → scripts/importer → data.js → window.HSK_CARDS` is untouched.
The pack's `getCards()` simply reads `window.HSK_CARDS`. Confirmed: **importer rerun stays
byte-identical** (`importer_determinism` green), **no new manually-maintained data file**,
**source Excel remains the single source of truth**, and future content updates still
require only replacing the Excel and running the existing importer. A future generic
importer could emit a pack *artifact* (manifest + validated cards) — documented, **not**
implemented in Phase 10.

## Migrated HSK assumptions
- `CardRepository` initialization: `HSK_CARDS` → active pack `getCards()` (the one runtime
  wiring). Field-role, deck, language, capability, and Test Mode metadata are now
  **owned by the HSK pack** (previously implicit/scattered).

## Deferred HSK assumptions (documented, unchanged)
- `app.js`/`insights.js` level-list derivation (`levelsFromCards`) — already generic;
  not rewired to `pack.getDecks()` (presentation-adjacent, low value, defer).
- All field-name/audio (`zh-CN`)/pinyin/`showFrontPinyin`/UI-copy/"HSK" branding literals
  in app.js/test.js/insights.js/index.html — presentation/domain (defer; described via
  pack metadata, not rewired — no UI rename).
- `sync.js:228` legacy-migration `HSK_CARDS.find` — sync-owned (defer).
- Importer/`data.js`/`source_data/` — importer-only (defer).
- `TestModeQuery` runtime type-def injection — deferred (above).

## Validation
`pack.validate()` (dev/test only, never in hot render paths): unique stable ids, unique
deck ids, all cards reference a declared deck, required roles present, per-deck counts.
Returns `{ ok, packId, version, cards, decks, byDeck, idsUnique, deckRefsValid, errors, warnings }`.

## Genericity boundary
The generic core (`content-pack.js`) contains **no** HSK/Chinese/pinyin/Vietnamese/
six-deck/5002 literals — it operates through semantic roles + deck metadata. Those facts
live only in the HSK adapter and tests.

## Performance
One pack instance (built once); decks derived once at construction; no per-render
reconstruction; **no 5,002-card clone** (`getCards()===HSK_CARDS`); CardRepository indexes
still built once; `validate()` runs only in tests. Initial load unchanged.

## Characterization / tests
`tests/browser/test_content_pack.py`: generic contract (valid synthetic pack; missing id;
duplicate deck id; card→undeclared-deck; duplicate stable id; missing role warning;
deterministic deck order; source not mutated), HSK pack (id/version/title; 6 decks + exact
counts + total 5002; IDs 1–5002 unique/contiguous; exact field-role map; languages;
capabilities; validation ok), **CardRepository equivalence** (pack-init vs direct-init:
same `getAll` ref/order/count/levels/`getById`/`getByLevel`), **TestMode mapping
equivalence** (pack `testModes` == query defs), and no-side-effects. `importer_determinism`
re-verified in the full suite.

## Service worker
Bumped **once**: `v17 → v18`; added `core/content/content-pack.js` and
`packs/hsk/hsk-content-pack.js` to the precache `ASSETS`. **Strategy unchanged**.

## Rollback
Phase 10 is independently reversible.
1. `git revert <phase-10-commit>` on `architecture-v2` — restores
   `createCardRepository(window.HSK_CARDS)`, removes the two pack `<script>` tags, and
   reverts `sw.js` to `v17`.
2. Or manual: `git checkout 806843b -- hsk_flashcard_app/core/cards/card-repository.js hsk_flashcard_app/index.html hsk_flashcard_app/sw.js tests/run_regression.py`,
   then delete `hsk_flashcard_app/core/content/`, `hsk_flashcard_app/packs/`, and
   `tests/browser/test_content_pack.py`.
3. Re-run `python tests/run_regression.py` — expect **22/22** after full rollback.
4. Phase 1–9 fixtures, baselines, and the `production-baseline-v1` tag are preserved.

## Future path: Excel → pack artifact
Today the pack is a thin descriptive adapter over `window.HSK_CARDS`. A future generic
importer could emit, per pack, a validated artifact `{ manifest, cards }` (manifest =
id/version/provenance/languages/capabilities/fieldRoles/decks/testModes) written alongside
`data.js`, with `validate()` gating the write (mirroring the importer's current fail-safe).
Dynamic multi-pack loading, a pack registry/switcher, and `(packId, cardId)` progress keys
remain deferred (see `CONTENT_PACK_STANDARD.md §6`).

## Recommended Phase 11 scope (do not begin)
Two low-risk options, pick one:
- **(A) Consume pack metadata in level discovery** — replace `app.js`/`insights.js`
  `levelsFromCards(HSK_CARDS)` with `HSKUtil.contentPack.getDeckIds()` (exact-equal),
  making deck identity flow from the pack; characterized against current level lists.
- **(B) First write-capable boundary** — a write-capable `ProgressRepository`/`ProgressWriter`
  wrapping `gradeCard`'s read-modify-write + `HSKSync` dirty/push, characterized against
  the frozen SRS goldens, **without** changing SRS formulas/keys/payloads.
Continue deferring dynamic pack loading, a generic importer, multi-pack support, UI
branding/rename, `BookmarkRepository`/`NoteRepository` writes, and DeckRepository writes.
