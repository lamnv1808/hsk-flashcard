# Phase 16 — Read-only StudySessionEngine Foundation

One read-only `StudySessionEngine` now **composes the existing seams** to construct and
**describe** a study session — without owning any mutable runtime state or DOM. **Not a
controller** — app.js keeps `session`/`current`/`flipped`/`snapshots`/`sessionGrades`,
grading, navigation and all rendering. Behavior is identical (full suite 26/26; SRS
goldens + Study/features regression green through the real integration; everything
behaviorally identical to `production-baseline-v1`).

```
StudySessionEngine (read-only)  ── composes ──▶ ContentPack, CardRepository,
  buildSession / buildExplicitSession            ProgressRepository, SettingsRepository,
  describeSession / describeCard                 StudySessionQuery, UserMetadataQuery
app.js  ──▶ owns mutable session state + DOM rendering (unchanged)
```

- Phase 15 anchor (rollback): `5711f5b`
- Phase 16 = the commit introducing this document.

## Purpose
Study Mode orchestration is the largest remaining business-logic concentration in app.js.
This phase creates a stable **read model** that separates card/session domain data from
mutable UI/controller state and DOM — reducing app.js read computation **without**
increasing state coupling, and laying the foundation for a later navigation/flip phase.

## Module
`hsk_flashcard_app/core/sessions/study-session-engine.js` —
`HSKUtil.createStudySessionEngine(deps)`. **No shared instance** in the module (app.js
injects its live repos/queries). Load order (`index.html`): …
`core/sessions/study-session-query.js` → **`study-session-engine.js`** → … → `app.js`.

## Strict read-only contract
Every method is side-effect-free. The engine never mutates session/current/flipped/
snapshots/sessionGrades/progress/settings/metadata/cards, never grades/restores/resets/
saves/marks-dirty/syncs, never writes storage, changes the index, flips cards, renders
HTML, plays audio, or calls Supabase.

## Dependency composition (no logic duplication)
`{ contentPack, cardRepository, progressRepository, settingsRepository, studySessionQuery,
userMetadataQuery, dateProvider }`. Session **selection is delegated** to Phase 5
`StudySessionQuery` (exact due/fresh/fallback/explicit behavior — the engine only
normalizes params + packages read models). Flags come from Phase 8 `ProgressRepository`
(`isLearned`/`isDue`), Phase 7 `UserMetadataQuery` (bookmark/note), Phase 4
`SettingsRepository` (front-pinyin). Card fields use Phase 10 `ContentPack` field roles.

## Session construction (delegates to Phase 5)
- `buildSession({levels, sessionSize})` — normalizes `sessionSize` → `limit`
  (`"all"` | `Number`), calls `selectStandardSession({levels, limit})`, returns a session
  read model.
- `buildExplicitSession({cardIds})` — calls `selectExplicitCardSession(cardIds)` (requested
  order, dedup, skip-missing), returns a session read model.
Order, deduplication, missing-ID behavior, limit, due/fresh/fallback priority, fallback
shuffle and selected-level behavior are all Phase 5's — unchanged.

## Session read model (`describeSession({cards, currentIndex})`)
```
{ cards,            // SAME array reference the query returned (not cloned)
  total,            // cards.length
  currentIndex,     // input (engine owns none of it)
  currentCard,      // cards[idx] in range, else null
  currentNumber,    // idx+1 (== cardIndex)
  remaining,        // max(0, total-idx)  (NEW; not currently displayed)
  completed,        // idx >= total  (== renderCard completion guard)
  deckLabel,        // distinct deck ids in session order, " + "-joined (== studyLevel)
  progressPct }     // total ? (idx/total)*100 : 0   (caller appends "%")
```

## Card read model (`describeCard({card|cardId, flipped})`) — answer-leak-safe by structure
```
{ id, deckId, flipped, frontPinyinVisible,
  front: { primary, pronunciation },                               // prompt only
  back:  { primary, pronunciation, definition, example,            // answer fields
           examplePronunciation, translation },
  bookmarked, hasNote, note, learned, due }
```
Fields resolve through **ContentPack field roles** (`primaryPrompt→word`,
`pronunciation→pinyin`, `definition→meaning`, `exampleText→example`,
`examplePronunciation→examplePinyin`, `exampleTranslation→translation`, `deck→level`) —
generic and exact. **Answer-leak protection** is representable read-only: `front` carries
**only** the prompt (+ pronunciation), `back` carries the answer fields, so a front-only
consumer reads `.front` and can never surface `meaning/example/translation`, regardless of
`flipped`. The engine owns no flip state; `flipped` is echoed for consumers. No card mutation.

## Migrated app.js reads (small, reversible)
| Site | Was | Now |
|---|---|---|
| `startStudy` | `sessionQuery.selectStandardSession({levels, limit: size==="all"?"all":Number(size)})` | `studyEngine.buildSession({levels, sessionSize: size}).cards` |
| `HSK_APP.startSession` | `sessionQuery.selectExplicitCardSession(ids)` | `studyEngine.buildExplicitSession({cardIds: ids}).cards` |
| `renderCard` display trio | inline `studyLevel`/`cardIndex`/`cardTotal`/`progressBar` | `studyEngine.describeSession({cards:session, currentIndex:current})` fields |

`describeCard` is **exposed and characterized** but **not** wired into `renderCard`'s
field-writing DOM (avoids rewriting `renderCard` + its P0 answer-leak CSS guard) — it is the
documented read model for the Phase 17 navigation/flip work.

## Settings / metadata / auth decisions
- **Settings** via `SettingsRepository` (`getFrontPinyinEnabled` for `frontPinyinVisible`).
  Audio execution and settings writes stay in app.js.
- **Metadata** via `UserMetadataQuery` (bookmark/note reads). Bookmark/note **writes** stay
  in `metadata.js`.
- **AuthContextQuery is intentionally NOT injected**: the Study read model needs
  cards/progress/settings/metadata, not account identity. Account switch = page reload;
  cloud-pull is observed through the injected live-provider repos. Documented per the prompt.

## Deferred mutable/controller/DOM responsibilities (unchanged, in app.js)
`let session/current/flipped/transitioning`, `snapshots`, `sessionGrades`, `showView`,
`renderHome`, `renderCard` (all field-writing DOM + the `no-flip-anim` reflow answer-leak
guard), `flipCard`, `gradeCard`, `skipCard`, `captureSnapshot`, `revertSnapshot`,
`finishSession` (reads mutable `sessionGrades`), the `current>=session.length` completion
guard (control flow; the engine *exposes* `completed`), event listeners, audio.

## Performance
Engine built **once** (app.js). Session construction delegates to Phase 5 (no re-selection);
`describeSession` is O(session length) for the distinct-deck join (the same scan the inline
`studyLevel` did); `describeCard` is O(1) indexed reads. No 5,002-card clone, no progress
clone, no storage/network. `renderCard` adds one bounded `describeSession` call; initial and
next-card latency unchanged.

## Characterization / tests
`tests/browser/test_study_session_engine.py`: standard session (levels/sizes 10/20/50/all,
due/fresh/fallback via Phase 5, empty pool, order, source unchanged), explicit session
(order/dups/missing/empty), `describeSession` (first/middle/last/completed/empty/out-of-range;
`deckLabel` == inline distinct-join; total/current/remaining/progressPct exact), `describeCard`
(front/back, pinyin shown/hidden, note present/missing/whitespace, bookmark/learned/due flags,
by-id resolution, **answer-leak: `front` has no answer values**, no card mutation),
account/provider isolation A→B→A, and no side effects. The real SRS goldens + `regression.py`
(advance/skip/undo) + `features_test` exercise the app.js integration end-to-end.

## Service worker
Bumped **once**: `v22 → v23`; added `core/sessions/study-session-engine.js` to the precache
`ASSETS`. **Strategy unchanged**.

## Rollback
Phase 16 is independently reversible.
1. `git revert <phase-16-commit>` on `architecture-v2` — restores app.js's inline session
   construction + display trio (removes the `studyEngine` instance), removes the engine
   `<script>` tag, and reverts `sw.js` to `v22`.
2. Or manual: `git checkout 5711f5b -- hsk_flashcard_app/app.js hsk_flashcard_app/index.html hsk_flashcard_app/sw.js tests/run_regression.py`,
   then delete `hsk_flashcard_app/core/sessions/study-session-engine.js` and
   `tests/browser/test_study_session_engine.py`.
3. Re-run `python tests/run_regression.py` — expect **25/25** after full rollback (Phase 16
   suite removed).
4. Phase 1–15 files, baselines, and the `production-baseline-v1` tag are preserved.

## Recommended Phase 17 scope (do not begin) — navigation/flip read-model consumption
Wire `renderCard` to consume `engine.describeCard({card, flipped})` for the **front/back
field population** (replacing the inline `word/pinyin/meaning/…` writes with `.front`/`.back`
read-model fields) and consume the `bookmarked/hasNote/note/learned/due` flags — a surgical,
characterized replacement of `renderCard`'s field writes that preserves the exact DOM output
and the P0 answer-leak CSS guard, **without** moving the mutable `flipped`/`current`/`session`
state or `flipCard`/`gradeCard`/`skipCard` navigation. Characterize the rendered DOM
byte-for-byte against the current output. Continue deferring the mutable session state,
grading/skip/undo, `auth.js`/`sync.js` writes, sync transport, `metadata`/bookmark/note
writes, dynamic pack loading, and UI branding.
