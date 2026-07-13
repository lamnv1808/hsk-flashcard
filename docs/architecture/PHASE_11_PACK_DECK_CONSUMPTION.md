# Phase 11 — ContentPack Deck-Metadata Consumption (Level Discovery + TestMode types)

Completes the first safe consumption of ContentPack metadata **beyond CardRepository
initialization**: level/deck identity for the UI and queries now flows from the active
pack's declared decks, and Test Mode type definitions are sourced from the pack at
runtime. **Structural seam only** — HSK1..HSK6, order, counts, selected values, and every
behavior are unchanged (full suite 23/23; importer byte-identical; all prior repos/queries
behaviorally identical to `production-baseline-v1`).

```
BEFORE:  raw cards → levelsFromCards(HSK_CARDS) (re-derived per module) → UI/queries
AFTER:   active ContentPack → getDeckIds() (declared, derived once) → UI/queries
         (raw cards remain the source of card RECORDS; the pack is the source of DECK identity)
```

- Phase 10 anchor (rollback): `3d49725`
- Phase 11 = the commit introducing this document.

## Pack as source of deck identity/order; cards as source of records
- **ContentPack** declares deck identity, order, titles and counts (derived once from the
  cards at pack construction). Consumers read `HSKUtil.contentPack.getDeckIds()`.
- **CardRepository** remains card-derived: it indexes cards by `card.level` and serves
  `getByLevel(deckId)`; `getLevels()` still reflects the actual card levels (repository
  integrity). The repo was **not** made to depend on the pack.
- Result: deck identity has one authoritative source (the pack) while card records and
  per-level card indexing stay with the repository.

## Deck-count consistency
Deck **identity/order** come from the pack; **actual card counts** come from
`CardRepository` (AnalyticsQuery already computes per-level counts from `getByLevel` —
unchanged, so no stale metadata can be shown). Because the HSK pack derives its declared
`cardCount` from the cards at construction, declared == actual — a test asserts
`pack.getDecks()[*].cardCount === cardRepo.countByLevel()` (149/150/295/600/1295/2513).

## Migrated consumers (level discovery → `contentPack.getDeckIds()`)
| File | Was | Now |
|---|---|---|
| `app.js:6` | `levelsFromCards(cards)` | `HSKUtil.contentPack.getDeckIds()` |
| `insights.js:13` | `levelsFromCards(CARDS)` (+ dead `var CARDS` removed) | `HSKUtil.contentPack.getDeckIds()` |
| `test.js:19` | `HSKUtil.cards.getLevels()` | `HSKUtil.contentPack.getDeckIds()` |

`getDeckIds()` returns an ordered **copy** `["HSK1".."HSK6"]`, byte-equal to the previous
derivations. Downstream consumers (`app.js` level picker / deck grid / `getLevelSummary`
/ `getHomeSummary` / `HSK_APP.levels()`; `insights.js` level `<select>`; `test.js` level
picker + setup default) are otherwise unchanged.

## TestMode mapping decision — WIRED (Phase 10 deferred it)
`createTestModeQuery` now accepts an optional `typeDefs` dep; when present it replaces the
built-in `DEFAULT_TYPE_DEFS` (kept as the standalone default). The shared `HSKUtil.testMode`
passes `HSKUtil.contentPack.getTestModes()`, so **the active pack owns Test Mode type
definitions at runtime**. This was wired because it is small and **proven byte-identical**:
- type IDs 1–6, Mix, prompts, answers, distractors and random-call order all unchanged;
- a characterization asserts a pack-`typeDefs` query and a default query produce
  **identical sessions** under the same seeded rnd;
- the Phase 9 `test_mode_query` suite (which passes no `typeDefs` → default path) still
  passes unchanged.

## Field-role consumption decision — DEFERRED
Field-role runtime consumption (renderCard / audio `zh-CN` / pinyin toggle / note & Test
UI) stays presentation-owned and out of scope — no single surgical helper adds value now.
Field roles remain descriptive pack metadata (validated by the `content_pack` suite).

## Capability metadata
Validated and exposed only. **No** capability-driven UI hiding (audio/Test/notes/
bookmarks/pinyin/examples all render exactly as before). Production HSK UI unchanged.

## Active-pack lifecycle
One active pack instance (`HSKUtil.contentPack`), built once at load; decks derived once at
construction. No runtime switching, no persistence, no registry, no per-render
reconstruction, no new globals. `getDeckIds()`/`getDecks()` return copies (callers can't
mutate pack internals).

## Genericity boundary
Generic consumers read decks via `getDeckIds()`; they no longer scan cards for level
identity. Presentation that still hardcodes HSK (auth heading, UI copy, field names,
audio lang, pinyin toggle) remains intentionally deferred — not pretended generic.

## Importer compatibility (reconfirmed)
`source_data/HSK1-HSK6.xlsx → importer → data.js → HSK_CARDS → HSK pack` unchanged;
`importer_determinism` green. No new manually-maintained file; the pack's deck manifest is
**derived** from the card data (cannot drift from Excel/cards).

## Performance
`getDeckIds()` is O(#decks) returning a small copy. This **removes three repeated 5,002-card
`levelsFromCards` scans** that previously ran at module load (app.js/insights.js/test.js) —
a small net improvement. Pack built once; decks derived once; no per-render reconstruction;
no dataset clone; no network/storage.

## Service worker
**No SW change / no cache bump** — no new runtime asset was added (only existing files
edited). Caching strategy and asset list unchanged (still `v18`).

## Rollback
Phase 11 is independently reversible (source-only; no asset/SW change).
1. `git revert <phase-11-commit>` on `architecture-v2` — restores `levelsFromCards(...)`
   / `getLevels()` level discovery in app.js/insights.js/test.js (and the removed
   `var CARDS`), and the built-in-only `TestModeQuery` type defs.
2. Or manual: `git checkout 3d49725 -- hsk_flashcard_app/app.js hsk_flashcard_app/insights.js hsk_flashcard_app/test.js hsk_flashcard_app/core/testing/test-mode-query.js tests/browser/test_content_pack.py`.
3. Re-run `python tests/run_regression.py` — expect **23/23** (no suite count change; Phase 11
   only extended `content_pack`).
4. Phase 1–10 files, baselines, and the `production-baseline-v1` tag are preserved.

## Recommended Phase 12 scope (do not begin)
With deck identity and Test Mode types flowing from the pack, the next low-risk step is a
**read-only capability/degradation seam**: a tiny `engine`/capability helper that reads
`contentPack.hasCapability(...)` and, for a synthetic pack lacking a capability, would hide
the corresponding control — **characterized on synthetic packs only, with the HSK pack
declaring all capabilities so production UI stays byte-identical** (no HSK UI change).
Alternatively, the first **write-capable boundary** (a `ProgressWriter` wrapping
`gradeCard` + `HSKSync` dirty/push, characterized against the frozen SRS goldens). Continue
deferring dynamic pack loading, a pack registry/switcher, a generic importer, multi-pack
support, UI branding/rename, field-role rendering rewrites, and Bookmark/Note/Deck write
repositories.
