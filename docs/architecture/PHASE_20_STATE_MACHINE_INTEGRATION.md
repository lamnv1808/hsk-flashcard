# Phase 20 — StudySessionStateMachine Integration + Architecture v2 Release

The pure `StudySessionStateMachine` (Phase 19) is now the **authoritative owner** of the
mutable in-memory Study session state in production, and architecture-v2 is merged to `main`
and tagged. **No user-visible behavior change** (full suite 28/28; `p0_test` answer-leak green;
SRS goldens green; smoke test clean; everything identical to `production-baseline-v1`).

- Phase 19 anchor (rollback): `b45889b`
- Phase 20 = the integration commit + the merge to `main`.

## What integrated
The independent module-level `let current`, `let flipped`, `let sessionGrades` were **removed**
from `app.js` and replaced by a single authority `let sessionState = sessionSM.createInitialState()`
(`sessionSM = HSKUtil.createStudySessionStateMachine()`). `session` (resolved card objects,
same order as `cardIds`) remains the render source; `snapshots` remains an opaque undo payload.

| Handler | Now |
|---|---|
| `startStudy` / `HSK_APP.startSession` / `shuffleBtn` | `sessionState = sessionSM.startSession({cardIds: session.map(c=>c.id)})` |
| `flipCard` | `sessionState = sessionSM.flip(sessionState)`; DOM/audio applied from `sessionState.flipped` |
| `gradeCard` | guard `sessionState.flipped`; **`ProgressWriter.grade` first**, then `sessionState = sessionSM.grade(sessionState, grade)` (record@idx + advance + flipped=false) |
| `skipCard` | `ProgressWriter.restore` (if snapshot) then `sessionState = sessionSM.skip(sessionState)` |
| `swipePrev` | `if(sessionState.currentIndex>0) sessionState = sessionSM.prev(sessionState)` |
| `renderCard` | reads `sessionState.currentIndex`; DOM `.flipped` reset unchanged (the JS `flipped=false` assignment removed — the transition already reset it) |
| `finishSession` | reads `sessionState.gradesByIndex` |
| keyboard 1–4 / `s` | guard/branch on `sessionState.flipped` |

## Removed duplicate mutable state
`let current`, `let flipped`, `let sessionGrades` (module-level). Their reads are now
`sessionState.currentIndex` / `.flipped` / `.gradesByIndex`; their writes go through the pure
transitions. Single source of truth: **`sessionState`**. (`session` and `snapshots` are
retained — different concerns: resolved card objects and opaque undo payloads.)

## Retained in app.js (controller)
`session` (card mapping), `snapshots`, `captureSnapshot`/`revertSnapshot`, all DOM writes/
classes/animation (incl. the P0 answer-leak reflow guard), SpeechSynthesis/auto-read,
`ProgressWriter` calls, `recordDailyLearn`, `updateStreak`, view switching, event listeners,
completion navigation.

## Order safety (grade)
`ProgressWriter.grade` runs **before** the state-machine advance, so a persistence failure
never leaves a partial advance (matches the pre-refactor order).

## Answer-leak (release gate — PASS)
Every card-changing transition returns `flipped=false`; the smoke test verified no leak across
start / 4 grades / skip / undo / keyboard grade / explicit session / mobile — `flipped=false`,
no `.flipped` class, front word never equals a back answer.

## Module loading & service worker
`core/sessions/study-session-state-machine.js` added to `index.html` (before `app.js`) and the
SW precache `ASSETS`; cache bumped **once**: `v25 → v26`. Strategy unchanged. The state-machine
module file is **byte-unchanged** from Phase 19 (integration only wires it in).

## Tests updated (state accessor only — assertions unchanged)
`p0_test.py`, `regression.py`, `features_test.py`, `qa2.py`, `test_metadata_sync.py` read/write
the relocated session state via `sessionState`/`sessionSM` instead of the removed
`current`/`flipped`/`sessionGrades`. No expected value changed. The Phase 19 pure state-machine
suite is retained.

## Rollback
1. `git revert <phase-20-commit>` on `architecture-v2` — restores the inline `current`/`flipped`/
   `sessionGrades` variables + handlers, the test accessors, removes the `<script>` tag, reverts
   `sw.js` to `v25`. Expect 28/28.
2. After the merge to `main`: `git revert -m 1 <merge-commit>` on `main`, or re-point Render to
   `ecd13fb` (the untouched production baseline).
3. Phase 1–19 files, baselines, and the `production-baseline-v1` tag are preserved.

See [ARCHITECTURE_V2_RELEASE.md](ARCHITECTURE_V2_RELEASE.md) for the full release record.
