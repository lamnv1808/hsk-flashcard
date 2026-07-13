# Phase 19 — Pure Study Session State Machine (foundation)

A pure, deterministic `StudySessionStateMachine` now models the mutable in-memory Study
session state and its transitions, **independently** of persistence, SRS, DOM, audio and
network. **This is a foundation phase, not an integration** — the module is **not wired
into production** (app.js still owns the live session state); it is proven by tests and
ready for Phase 20. Production runtime is **byte-unchanged** (full suite 28/28; all current
Study/SRS/answer-leak suites green; `app.js`/`index.html`/`sw.js` untouched; everything
identical to `production-baseline-v1`).

- Phase 18 anchor (rollback): `e97b6b9`
- Phase 19 = the commit introducing this document.

## Purpose
The Study flow combines six concerns (in-memory transitions, progress persistence,
snapshot/undo, DOM, audio, navigation/completion). Moving all six at once is too risky.
Phase 19 **freezes the state-transition contract in isolation** so Phase 20 can integrate a
proven state machine.

## Module & loading decision
`hsk_flashcard_app/core/sessions/study-session-state-machine.js` —
`HSKUtil.createStudySessionStateMachine()`. **Test-only loading:** it is **not** referenced
by production `index.html`, so production runtime and the service-worker precache are
**unchanged** (no SW bump). The characterization test injects it via Playwright
`add_script_tag` after the app loads. Rationale: a foundation phase with **zero production
call sites** should not add runtime asset weight; Phase 20 adds the `<script>` tag + one SW
bump when it wires the machine in.

## State shape (plain, serializable)
```
{ cardIds:number[],            // already-selected ids (this machine never selects/dedups/reorders)
  currentIndex:number,
  flipped:boolean,
  gradesByIndex:(string|undefined)[],   // sessionGrades: grade string per session position
  status:"idle" | "studying" | "completed" }
```
**No `snapshots`** (undo payloads hold progress rows → opaque, controller/ProgressWriter-owned)
and **no `transitioning`** (the current code has no JS transitioning flag — the answer-leak
guard is a synchronous CSS reflow in `renderCard`; `drag`/`suppressClick` are DOM-input, not
session state). Holds card **ids**, not the 5,002-card objects.

## Transition API (pure — every transition returns a NEW state, never mutates input)
| Fn | Effect (mirrors app.js) |
|---|---|
| `createInitialState()` | `idle`, no cards |
| `startSession({cardIds})` | copy ids; `currentIndex 0`, `flipped false`, no grades; `studying` (or `completed` if empty) |
| `flip(state)` | toggle `flipped` (== `flipCard`, no guard) |
| `grade(state, grade)` | **no-op if `!flipped`** (== `if(!flipped) return`); else record grade@`currentIndex`, `currentIndex+1`, `flipped=false`, recompute status |
| `skip(state)` | record `"skip"`@`currentIndex`, `currentIndex+1`, `flipped=false`, status (no flip guard) |
| `advance(state)` | raw `currentIndex+1`, `flipped=false`, status |
| `prev(state)` | `currentIndex-1` if `>0`, `flipped=false`, `studying` (== `swipePrev`) |
| `exit(state)` | → `idle` (== `exitStudy` session-state effect) |
Read helpers: `getCurrentCardId(state)` (`studying ? cardIds[currentIndex] : null`),
`isCompleted(state)`.

## Semantics (frozen from app.js)
- **Start:** `session=ids; current=0; sessionGrades=[]` then `renderCard` sets `flipped=false`
  and, if `current>=length`, completes → empty session ⇒ `completed`, else `studying`.
- **Flip:** `flipped=!flipped` (toggle).
- **Grade:** guard `if(!flipped) return`; record `sessionGrades[current]=grade`; `current++`;
  next card `flipped=false`. (Progress/SRS/daily writes stay OUTSIDE.)
- **Skip:** `sessionGrades[current]="skip"`; `current++`; `flipped=false`. (SRS-revert of a
  previously-graded position stays OUTSIDE via ProgressWriter.)
- **Prev:** `if(current>0){current--}`; `flipped=false`.
- **Completion:** `current>=length` (== `renderCard`'s guard) → `completed`; the finish
  summary reading `sessionGrades` stays OUTSIDE.

## Effect / controller boundary
Transitions return the **state object** only (no effects framework). The caller derives what
it needs: `getCurrentCardId(state)` = which card to render, `isCompleted(state)` = show the
complete view. This matches how app.js reads `current`/`flipped` after mutating and then
calls `renderCard`/`finishSession`. Kept minimal per the prompt.

## Snapshot boundary
`snapshots` (undo history) hold **cloned progress rows**; they are **not** part of the pure
state and are never interpreted or mutated by the machine. In Phase 20, app.js/ProgressWriter
continue to own snapshot capture and SRS-revert; the machine only tracks navigation.

## Answer-leak protection
**Every card-changing transition returns `flipped === false`** (`start`, `grade`→next,
`skip`→next, `advance`, `prev`, restart) — the release-gating rule that the next active card
always begins front-side, with no prior-card back/answer state carried forward. A dedicated
test asserts all six card-changing transitions land front.

## Pure/immutability contract
Every transition returns a new top-level object (shallow `assign`); arrays are **replaced via
`slice()`** only when a transition changes them (`grade`/`skip` copy `gradesByIndex`; `start`
copies `cardIds`), never mutated in place. No storage/network/DOM/audio/global/ProgressWriter/
Scheduler access. Deterministic and serializable. Tests assert the input state, `cardIds`, and
`gradesByIndex` are unchanged, and identical sequences serialize identically.

## Production integration status
**Not integrated.** app.js's `session`/`current`/`flipped`/`sessionGrades`/`snapshots` and all
handlers (`gradeCard`/`skipCard`/`flipCard`/`swipePrev`/`renderCard`/`finishSession`) are
unchanged. The machine is a proven, test-only model.

## Performance
Transitions are O(1) except `gradesByIndex.slice()` (grade/skip) and the one-time
`cardIds.slice()` (start) — both **session-sized** (≤ session length, e.g. ≤ 100), not the
5,002-card dataset. No card/progress clone, no dataset scan, no storage/network. State size is
proportional only to the current session.

## Characterization / tests
`tests/browser/test_study_session_state_machine.py` runs a faithful **inline model of app.js's
session mutations** (`__inlineApply`: flip/grade/skip/prev/advance) and the state machine over
7 event sequences (start→flip→grade→next×2; grade→next→undo(prev)→regrade; skip→skip→grade;
last-card completion; undo-after-completion; empty session; mixed long) — asserting the
canonical `{cardIds,currentIndex,flipped,gradesByIndex,status}` is **byte-equal after every
step**. Plus: initial state, start (order/dups/one/empty/input-unmutated), flip, grade (all
grades + unknown + `!flipped` no-op + completion), skip, prev (first-guard, from-completed),
**exhaustive answer-leak**, immutability, and no side effects. The full regression (all current
Study/SRS/answer-leak/progress suites) confirms production is unchanged.

## Service worker
**No SW change / no bump** — no production runtime asset was added (the module is test-only).
Precache list and strategy unchanged (`v25`).

## Rollback
Phase 19 is independently reversible and touches no production runtime.
1. `git revert <phase-19-commit>` on `architecture-v2` (only un-registers the test suite), or
   manual: `git checkout e97b6b9 -- tests/run_regression.py`, then delete
   `hsk_flashcard_app/core/sessions/study-session-state-machine.js`,
   `tests/browser/test_study_session_state_machine.py`, and the Phase 19 doc.
2. Re-run `python tests/run_regression.py` — expect **27/27** after rollback (Phase 19 suite
   removed).
3. Phase 1–18 files, baselines, and the `production-baseline-v1` tag are preserved.

## Phase 20 integration & deploy plan (precise; do not begin)
1. **Load the module in production**: add `<script src="core/sessions/study-session-state-machine.js">`
   to `index.html` (before `app.js`) and to the `sw.js` precache `ASSETS`; **bump the SW cache
   once** (`v25 → v26`).
2. **Instantiate once** in app.js: `const sessionSM = HSKUtil.createStudySessionStateMachine();`
   and hold a single `let sessionState = sessionSM.createInitialState();`.
3. **Migrate write-free transitions first, one at a time, each behind the frozen suites:**
   - `flipCard` → `sessionState = sessionSM.flip(sessionState); flipped = sessionState.flipped;`
     (keep the DOM/audio in `flipCard`).
   - `startStudy`/`startSession` → `sessionState = sessionSM.startSession({cardIds})` and derive
     `session`/`current`/`sessionGrades` from it (cards resolved via `cardRepo` from `cardIds`).
   - `swipePrev` → `sessionSM.prev`; `renderCard` reads `sessionState.currentIndex`/`flipped`.
4. **Migrate the state effects of `gradeCard`/`skipCard`** to `sessionSM.grade`/`skip` while
   **leaving the writes exactly where they are** (`ProgressWriter.grade`/`.restore`,
   `recordDailyLearn`, snapshot capture) — the machine records the grade + advance; the writer
   still persists. Keep `snapshots` in app.js (opaque).
5. **After each step**: run `srs_characterization`, `p0_test` (answer-leak), `regression`,
   `features_test`, `progress_writer`, `study_session_engine`, and the new
   `study_session_state_machine`; require green + no answer leak + byte-equal DOM.
6. Keep `finishSession`, DOM, audio, view switching, and all writes in app.js.
Defer (still): `auth.js`/`sync.js` writes, sync transport, `metadata`/bookmark/note writes,
the Test Mode controller, dynamic pack loading, UI branding.
