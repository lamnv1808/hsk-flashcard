# Phase 21 — Rich end-of-session completion screen + "Keep going" loop

**Product UX phase (not architecture).** Additive only; preserves every Architecture v2
boundary (SRS, Scheduler, StudySessionStateMachine, StudySessionEngine, ProgressWriter,
auth/sync/local-only, storage schema, cloud payloads — all unchanged).

## Objective
Replace the dead-end completion screen (one sentence + "Về trang chủ") with a screen that
shows the session's grade breakdown and the daily-habit context, and lets the learner start
the next same-levels session in one tap.

## Files changed
- `hsk_flashcard_app/index.html` — completeView: added `#completeBreakdown`, `#completeHabit`,
  and a `.complete-actions` row with `#continueStudyBtn` (kept `#homeBtn`).
- `hsk_flashcard_app/app.js` — module-level `studySource`; set it in `startStudy` (`{type:"levels"}`)
  and `HSK_APP.startSession` (`{type:"explicit"}`); rewrote `finishSession` (breakdown + habit +
  continue gating via `tallyGrades`/`cbCell`/`chItem` helpers); `#continueStudyBtn` handler.
- `hsk_flashcard_app/styles.css` — `.complete-breakdown/.cb-cell/.complete-habit/.ch-item/
  .complete-allclear/.complete-actions` (+ mobile rules). Existing visual language reused.
- `hsk_flashcard_app/sw.js` — cache `v29 → v30` (one bump; asset list & strategy unchanged).
- `tests/regression/completion_loop.py` (new) + registered in `tests/run_regression.py`.

## Completion behavior
- **Summary line** unchanged in format: "Bạn đã xem N thẻ, chấm điểm M thẻ, nhớ tốt G thẻ[, bỏ qua S thẻ]."
- **Grade breakdown** (5 cells): Chưa nhớ / Khó / Nhớ được / Rất dễ / Bỏ qua (+ "Chưa chấm" only
  if an ungraded hole exists — does not occur in normal completion).
- **Habit row**: "Còn cần ôn" (due remaining, level sessions only), "Đã học hôm nay", "Chuỗi ngày".
- **Continue**: primary "Học tiếp N thẻ" shown only for level-based sessions with due remaining;
  N = `min(sessionSize, dueRemaining)` (all due when size = "Tất cả thẻ đến hạn"). Clicking calls
  the normal `startStudy(studySource.levels)` path (existing size, fresh selection, next card
  front-side). If no due remain: soft "Hôm nay tạm ổn rồi 🎉", no continue button.
- **"Về trang chủ"** always present (primary when there's no continue button, secondary otherwise).

## Session-source rules
`studySource` is transient module state used **only** to gate completion UX. It is never
persisted, synced, exposed to the cloud, or placed in `sessionState` / the state machine.
- `startStudy(levels)` → `{type:"levels", levels:[...]}` → eligible for "Học tiếp".
- `HSK_APP.startSession(ids)` (Weak Words / Bookmarks / Smart Review) → `{type:"explicit"}` →
  generic completion, no same-level continue; "Về trang chủ" only.

## Data sources (read-only, existing)
- **Grade counts** from `sessionState.gradesByIndex` (no mutation; `"skip"` counted as skipped;
  `undefined` hole counted as ungraded).
- **Due remaining** via existing `dueCards(studySource.levels)` — read **after** the session's
  grade writes (grading writes synchronously before advancing into `finishSession`), scoped to
  the selected levels only. No new query module.
- **Today learned** via `HSKMeta.dailyCounts()[HSKMeta.localDay()]`.
- **Streak** via `settingsRepo.getStreak()`. (Existing "streak increments on session start"
  semantics are **displayed, not changed** — deferred to a later habit-loop phase.)

## Tests
`tests/regression/completion_loop.py` (in the full suite; **29/29 PASS**):
1. Level session, known grade mix → breakdown counts, summary text, due-remaining, learned=9,
   streak=1, continue "Học tiếp 10 thẻ".
2. Continue click → back in study, next card front-side (no answer leak), same levels, size respected.
3. Explicit session → continue hidden, home present, breakdown rendered.
4. Level session with all cards future-due → due=0, continue hidden, soft all-clear message, home primary.
Plus full regression incl. `p0_test` (answer-leak), `regression`, `features_test`, `qa2`,
`metadata_sync`, `auth_test`, `offline_test`.

## Rollback
Branch `phase-21-completion-loop` only; `main` untouched. Revert the phase commit
(`git revert <sha>`), or delete the branch. SW returns to `v29` on revert and clients reactivate.
