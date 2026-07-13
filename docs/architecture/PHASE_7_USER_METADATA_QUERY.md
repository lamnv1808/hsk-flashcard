# Phase 7 — Read-only User-Metadata Query Seam (Bookmarks & Notes)

Fifth read-only boundary for **FlashEdu** (HSK is content pack #1). A single
`UserMetadataQuery` now centralizes the read-only **bookmark and note** computations
that were inline in `metadata.js` and `insights.js`. **This centralizes reads only** —
all write/editor/sync paths are untouched and every UI output is unchanged (full suite
20/20; the bookmark/note UI regression suites `features_test`/`qa2`/`metadata_sync`
stay green; cards/IDs/importer/baseline/SRS and every prior repo/query identical to
`production-baseline-v1`).

- Phase 6 anchor (rollback): `22feef8`
- Phase 7 = the commit introducing this document.

## Why one query for bookmarks AND notes
Bookmarks (`settings.bookmarks`) and notes (`settings.notes`) are **both nested in the
per-user settings blob** and share one lifecycle (same account scoping, same
cloud-pull reassignment, same account-switch reload, same legacy migration). They have
**no separate source or lifecycle**, so a single cohesive `UserMetadataQuery` is the
right boundary — two tiny `BookmarkQuery`/`NoteQuery` modules would be premature
fragmentation. Future **write** repositories may still be split as
`BookmarkRepository` / `NoteRepository`; that separation is deferred.

## Module
`hsk_flashcard_app/core/metadata/user-metadata-query.js` — classic script, no
bundler/ESM/TS. `core/metadata/` matches the `core/<domain>/` convention of Phases 3–6
and the existing `metadata.js` domain name. Extends `window.HSKUtil`.
- `HSKUtil.createUserMetadataQuery({cardRepository, metadataProvider})`.
- `HSKUtil.userMetadata` — shared instance (all consumers run after `HSK_APP` exists).

Load order (`index.html`): … `core/analytics/analytics-query.js` →
**`core/metadata/user-metadata-query.js`** → `supabase-config.js` → … → `app.js` → … →
`metadata.js` → `insights.js`.

## Read-only contract
No writes. The query never mutates bookmarks/notes/settings/progress/cards/source
arrays, never writes localStorage / marks dirty / enqueues sync / calls Supabase,
never creates or removes metadata, never cleans up invalid entries. No DOM, no audio,
no network. Returned arrays/objects are copies (ids, notes map); card objects may be
live source refs, treated read-only.

## Metadata-provider lifecycle
Bookmarks/notes live in the settings blob, so `metadataProvider` is exactly
`metadata.js`'s `S()`: `() => (HSK_APP && HSK_APP.getSettings()) || {}`. It is re-read on
every call, so cloud-pull reassignment (`reloadState`) and account-switch reloads are
observed with **no stale metadata and no cross-account leakage**. One shared instance
suffices — unlike Settings/Analytics there is no first-`renderHome` bootstrap, because
all metadata reads happen during Study Mode / dashboard interaction, after `HSK_APP`
and `HSKMeta` exist.

## Card-ID & ordering policy (frozen)
- Bookmark membership: `Array.isArray(bookmarks) && bookmarks.indexOf(id) >= 0` —
  strict equality (numeric ids; a string id misses, as today).
- Resolution: `cardRepository.getManyByIds(getBookmarkIds().map(Number))` — **insertion
  order**, keeps duplicates, skips ids with no card. No renumbering, no cleanup.
- Note keys: `notes[cardId]` (number id coerces to string key), exactly as `metadata.js`.
- No normalization/repair of invalid stored entries (a bookmarked id with no card is
  still "bookmarked" for membership but is skipped in card resolution — unchanged).

## API (signatures & rules)
| Method | Rule (mirrors current runtime) |
|---|---|
| `isBookmarked(cardId)` | `indexOf(cardId) >= 0` |
| `getBookmarkIds()` | **copy** of `bookmarks` (guarded `Array.isArray?:[]`) |
| `getBookmarkedCards({level?})` | `getManyByIds(ids.map(Number))`; optional **generic** `card.level` filter (`"all"`/absent = none) |
| `countBookmarks({level?})` | `getBookmarkedCards(...).length` |
| `hasNote(cardId)` | `trim(getNote) !== ""` |
| `getNote(cardId)` | `n ? String(n) : ""` (whitespace note returned raw; only `hasNote` trims) |
| `getNotesMap()` | shallow **copy** of `notes` (guarded) |
| `getCardMetadata(cardId)` | `{cardId, bookmarked, hasNote, note}` |

## Search / filter boundary
**Level filter** (`card.level`) is generic and lives in `getBookmarkedCards({level})`.
**Bookmark search** (`(word+" "+pinyin+" "+meaning).toLowerCase().indexOf(q)`) is
HSK-field-specific, so it **stays in `insights.js` presentation** — moving it into the
generic query would hardcode Chinese/pinyin/Vietnamese card fields (forbidden). Case
handling (`toLowerCase`, no diacritic folding) and empty-query behavior are unchanged.
This is the smallest clean boundary: the query owns card **resolution** + generic level
filtering; presentation owns the product-specific search predicate.

## Note read semantics (frozen)
`getNote` returns `""` for missing/empty; returns the **raw** string for whitespace-only
/ multiline / long (≤1000 stored) / HTML-or-script-looking text (as a plain string —
the UI escapes via `textContent`). `hasNote` trims, so a whitespace-only note yields no
indicator while `getNote` still returns the whitespace. The query returns **data only**;
front-hide / back-only display / editor open/Save/Cancel / rendering all remain in the
UI (`metadata.js` note zone, `insights.js` rows).

## Migrated read sites
| File | Was | Now |
|---|---|---|
| `metadata.js bookmarks()` | `Array.isArray(S().bookmarks)?…:[]` | `MQ.getBookmarkIds()` |
| `metadata.js isBookmarked()` | `bookmarks().indexOf(id)>=0` | `MQ.isBookmarked(id)` |
| `metadata.js notesMap()` | `(S().notes&&typeof==="object")?…:{}` | `MQ.getNotesMap()` |
| `metadata.js getNote()` | `notesMap()[id] ? String(...) : ""` | `MQ.getNote(id)` |
| `metadata.js hasNote()` | `trim(getNote(id))!==""` | `MQ.hasNote(id)` |
| `insights.js bookmarkCards()` | `repo.getManyByIds(HSKMeta.bookmarks().map(Number))` | `MQ.getBookmarkedCards()` |
| `insights.js bmStudyBtn` | `bookmarkCards().filter(level).map(id)` | `MQ.getBookmarkedCards({level}).map(id)` |

`HSKMeta`'s public API is **unchanged** — the five read helpers now delegate to the
shared query, so every downstream consumer (`updateBookmarkBtn`, `renderNoteZone`,
`openEditor` pre-fill, Weak/bookmark row `hasNote` indicators, `insights` resolution)
is untouched and behaves identically.

## Deferred (write / editor / sync — unchanged)
`toggleBookmark`, `removeBookmark`, `setNote`, `saveEditor`/`closeEditor`/`openEditor`
mutation, `persist()`, bookmark-button & note-toggle click handlers, `recordDailyLearn`,
`updateStreak`, sync callbacks, legacy migration/account cleanup. `metadata.js` write
functions still mutate `S()` directly + `persist()`; the query observes those writes
live (verified: mutate via the write path → subsequent query read reflects it). Bookmark
**search** predicate stays in presentation. `app.js` was not touched (no direct
bookmark/note reads there).

## Why BookmarkRepository / NoteRepository writes are deferred
Toggling a bookmark and saving/deleting a note are mutable-state + settings/sync writes
(`persist()` → `HSKSync.onSettingsChanged()` → dirty + push). Wrapping them changes the
write path and must be characterized separately as write-capable repositories, not mixed
into this read-only seam.

## Performance
- One shared query instance (built once); never rebuilt per card or per render.
- Reuses the Phase 3 `CardRepository` indexes — `getBookmarkedCards` is one
  `getManyByIds` (indexed `Map.get` per id, no full 5,002-card scan), `isBookmarked` is
  one `indexOf` over the small bookmark array.
- No caching (recompute on read → no stale across account switch), no clone of the
  dataset, no network, no storage.

## Characterization
`tests/browser/test_user_metadata_query.py` re-implements each **original inline** read
(`__oldBookmarks`/`__oldIsBookmarked`/`__oldNotesMap`/`__oldGetNote`/`__oldHasNote`/
`__oldBookmarkCards`) and compares to the query over identical fixtures (numeric ids,
missing card, duplicate id, invalid stored id; empty/whitespace/multiline/long/
script-looking notes) — asserting equal outputs and order, plus source metadata/card
objects unmutated, provider replacement observed (account isolation A→B→A), and existing
write-path visibility. The UI suites `features_test`/`qa2`/`metadata_sync` continue to
validate the rendered Study bookmark button, note zone, Weak/bookmark rows and
bookmark-page filter/search end-to-end.

## Service worker
Bumped **once**: `v14 → v15`; added `core/metadata/user-metadata-query.js` to the
precache `ASSETS`. **Strategy unchanged** (cache-first; existing `activate` removes old
caches).

## Rollback
Phase 7 is independently reversible.
1. `git revert <phase-7-commit>` on `architecture-v2` — restores the inline
   `metadata.js` read helpers and `insights.js bookmarkCards`/`bmStudyBtn`, removes the
   query `<script>` tag, and reverts `sw.js` to `v14`.
2. Or manual: `git checkout 22feef8 -- hsk_flashcard_app/metadata.js hsk_flashcard_app/insights.js hsk_flashcard_app/index.html hsk_flashcard_app/sw.js tests/run_regression.py`,
   then delete `hsk_flashcard_app/core/metadata/` and `tests/browser/test_user_metadata_query.py`.
3. Re-run `python tests/run_regression.py` — expect **19/19** after full rollback
   (Phase 7 suite removed).
4. Phase 1–6 fixtures, baselines, and the `production-baseline-v1` tag are preserved.

## Recommended Phase 8 scope (do not begin)
With all read seams extracted (Cards, Settings, Session, Analytics, User-Metadata), the
natural next step is the **first WRITE-capable repository: a `ProgressRepository`
write/read boundary for SRS grading persistence** — wrap the existing `getCardState`/
`save()`/grade write path (and its `HSKSync` dirty/push trigger) behind one repository,
characterized against the frozen SRS goldens, **without** changing SRS formulas, due
dates, sync payloads, or storage keys. This is a larger, write-path phase and must be
planned with its own characterization budget; alternatively, a lower-risk intermediate
step is a read-only `TestModeQuery` seam over Test Mode history/results display. Defer
`BookmarkRepository`/`NoteRepository` writes, sync ownership, and content-pack/
DeckRepository work.
