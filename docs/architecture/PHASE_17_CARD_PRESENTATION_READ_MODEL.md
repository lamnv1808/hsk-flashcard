# Phase 17 — Wire the Card Presentation Read Model into renderCard

`renderCard` now sources its card data from `StudySessionEngine.describeCard(...)`
instead of reading raw card fields inline. **Read-model consumption only** — app.js keeps
current-card selection, `flipped` state, all DOM writes, class/animation toggles, the note
editor, bookmark clicks, audio, rating buttons, navigation and completion. The rendered
Study card is visually and behaviorally identical (full suite 26/26; **`p0_test`
answer-leak green**; SRS goldens + Study/features regression green; everything identical to
`production-baseline-v1`).

```
BEFORE:  renderCard() → c.word / c.pinyin / c.meaning / … (inline card-field reads) → DOM
AFTER:   renderCard() → m = studyEngine.describeCard({card:c, flipped:false})
                        → m.front.* → front-face DOM ; m.back.* → back-face DOM
```

- Phase 16 anchor (rollback): `739f901`
- Phase 17 = the commit introducing this document.

## Presentation read-model purpose
Centralize `renderCard`'s card-data reads behind the already-characterized `describeCard`
read model, so the front/back field mapping (and its answer-leak safety) is one
well-tested seam. No renderer abstraction is introduced; app.js still formats the DOM.

## Read-model shape consumed (`describeCard({card, flipped:false})`)
```
{ id, deckId, flipped, frontPinyinVisible,
  autoReadWord, autoReadExample, speechRate,          // NEW in Phase 17 (audio flags)
  front: { primary, pronunciation },                  // prompt only — answer-leak safe
  back:  { primary, pronunciation, definition, example, examplePronunciation, translation },
  bookmarked, hasNote, note, learned, due }
```
Fields resolve via **ContentPack field roles** (`primaryPrompt→word`, `pronunciation→pinyin`,
`definition→meaning`, `exampleText→example`, `examplePronunciation→examplePinyin`,
`exampleTranslation→translation`, `deck→level`) — generic and exact; no runtime card field
renamed, no importer/data change.

## Front/back safety contract (answer-leak)
`describeCard.front` carries **only** the prompt (+ pronunciation) — **no**
definition/example/translation/note. `renderCard` maps:
- `m.front.primary` → `$("word")`, `m.front.pronunciation` → `$("pinyin")` (the **visible
  front** elements → only front-safe values), `m.deckId` → `$("levelBadge")`, aria-label,
  srStatus.
- `m.back.*` → `$("meaning")/$("example")/$("examplePinyin")/$("translation")/$("backWord")/
  $("backPinyin")` (the **CSS-hidden back face**).
`renderCard` necessarily populates **both** faces each render (required for the flip); the
answer-leak protection remains the **existing CSS/animation guard** (`no-flip-anim` +
`flipped=false` + drop `.flipped` + reflow) — unchanged. Because the front-face DOM receives
only `m.front` values, no new leak path is introduced. A DOM-equivalence test asserts the
front element never carries an answer string; the live grade→advance sequence confirms the
next card's front never inherits the prior card's back content.

## ContentPack field-role mapping
Unchanged from Phase 16 (the engine derives fields via `contentPack.getRole(...)` with legacy
fallbacks). Phase 17 only added the audio flags (`autoReadWord`/`autoReadExample`/`speechRate`)
from `SettingsRepository`.

## Pinyin behavior (unchanged)
`applyPinyinDisplay()` (shared: renderCard + reloadState + onchange) keeps its own
`settingsRepository.getFrontPinyinEnabled()` read and toggles pinyin placement/CSS. The model
also exposes `frontPinyinVisible` for future consumers, but Phase 17 does **not** move the
pinyin placement logic. Empty/missing pronunciation, default-on, account-specific and
local-only settings behave exactly as before.

## Bookmark / note / progress flags
- **Bookmark & note zone** stay owned by `metadata.js` `HSKMeta.syncCard()`/`onFlip()`
  (renderCard doesn't read them directly; `describeCard.bookmarked/hasNote/note` are exposed
  for later use). Note UI still appears only after flip; note **writes** untouched.
- **Progress flags** (`learned`/`due`) are exposed but **not** consumed by renderCard (no such
  indicator today); reads create no progress rows.

## Audio boundary (unchanged)
The engine returns text/flags only. `renderCard` now reads `m.autoReadWord` (was
`settingsRepo.getAutoReadWordEnabled()`) to decide auto-read, but **all playback** —
`stopSpeech()`, `speakWord()`, `speakExample()`, voice selection, timing, stop button —
stays in app.js. `flipCard`'s `getAutoReadExampleEnabled()` read is **out of scope** (Phase
17 is renderCard only); `describeCard.autoReadExample`/`speechRate` are exposed for it later.

## Migrated renderCard read sites
| Was | Now |
|---|---|
| `$("levelBadge")=c.level; $("word")=c.word; $("pinyin")=c.pinyin` | `m.deckId / m.front.primary / m.front.pronunciation` |
| `$("meaning")/$("example")/$("examplePinyin")/$("translation")=c.*` | `m.back.definition / .example / .examplePronunciation / .translation` |
| `$("backWord")=c.word; $("backPinyin")=c.pinyin` | `m.back.primary / m.back.pronunciation` |
| aria-label / srStatus `c.word`, `c.level` | `m.front.primary`, `m.deckId` |
| `if(settingsRepo.getAutoReadWordEnabled())` | `if(m.autoReadWord)` |
One `describeCard({card:c, flipped:false})` call per `renderCard`.

## Controller/DOM responsibilities retained (deferred)
Flip-reset animation guard + all class toggles + reflow, `applyPinyinDisplay`,
`HSKMeta.syncCard()` (bookmark/note zone), `stopSpeech`/`speakWord` execution, rating/logic
panel toggles, `flipCard`/`gradeCard`/`skipCard`/navigation/completion, and all mutable state
(`session`/`current`/`flipped`/`snapshots`/`sessionGrades`).

## DOM equivalence
`tests/browser/test_study_session_engine.py` adds a DOM-equivalence check: it renders a real
card (HSK1 first + HSK6 last) via the app and asserts each element's `textContent` equals the
corresponding `describeCard` field (front→word/pinyin/level, back→meaning/example/…), that the
front element never carries answer text, and that the card starts unflipped. Non-deterministic
animation timing is intentionally excluded. The existing `p0_test`/`regression.py` validate
the rendered DOM + answer-leak + advance/skip/undo end-to-end.

## Performance
One engine instance (Phase 16); **one `describeCard` per `renderCard`**; O(1) card/progress/
metadata/settings reads; no card/progress clone, no storage/network. Flip/next latency
unchanged.

## Service worker
Bumped **once**: `v23 → v24`. The precached `study-session-engine.js` and `app.js` contents
changed. No new asset; asset list and caching strategy unchanged.

## Rollback
Phase 17 is independently reversible.
1. `git revert <phase-17-commit>` on `architecture-v2` — restores `renderCard`'s inline
   `c.word/c.pinyin/…` reads and the `getAutoReadWordEnabled()` audio read, removes the
   `autoReadWord/autoReadExample/speechRate` fields from `describeCard`, and reverts `sw.js`
   to `v23`.
2. Or manual: `git checkout 739f901 -- hsk_flashcard_app/app.js hsk_flashcard_app/core/sessions/study-session-engine.js hsk_flashcard_app/sw.js tests/browser/test_study_session_engine.py`.
3. Re-run `python tests/run_regression.py` — expect **26/26** (no suite-count change; Phase 17
   only edited existing files/tests).
4. Phase 1–16 files, baselines, and the `production-baseline-v1` tag are preserved.

## Recommended Phase 18 scope (do not begin)
Two candidates:
- **(A) flipCard read-model consumption** — a small, symmetric follow-up: have `flipCard`
  read `describeCard`'s `autoReadExample`/`speechRate` (and, if clean, drive the back-side
  note/bookmark refresh through the model) — **without** moving `flipped` state or animation.
  Characterize the flipped DOM byte-for-byte.
- **(B) Scheduler extraction (read-only)** — extract the SRS interval/due math (currently
  `srsNextState` in app.js, injected into `ProgressWriter`) into a pure, characterized
  `core/srs/scheduler.js` (`computeNext(state, grade, now)`), delegated to by app.js's
  injected `srsCalculator` — **without** changing any interval/due output (validated against
  the frozen SRS goldens). This isolates the last piece of scheduling logic in app.js.
Continue deferring mutable session state, grading/skip/undo, `auth.js`/`sync.js` writes, sync
transport, `metadata`/bookmark/note writes, dynamic pack loading, and UI branding.
