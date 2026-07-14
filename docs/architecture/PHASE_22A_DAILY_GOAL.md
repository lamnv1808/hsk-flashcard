# Phase 22A — Daily Goal (additive, display-only)

Product UX phase. **Additive only**; preserves every Architecture v2 boundary. Streak
semantics are **not** touched (deferred to Phase 22B).

## Objective
Let the learner set a simple daily study goal (10/20/30/50) and see progress toward it on
Home and at completion — reusing the existing daily-count value, with no new counter, storage
key, table, or migration.

## Locked counting semantics (unchanged — displayed, not redefined)
"Today learned" = **unique cards graded during the current LOCAL day**, read from
`HSKMeta.dailyCounts()[HSKMeta.localDay()] || 0` (written only by `recordDailyLearn` in
`metadata.js`, called only from `gradeCard`). It already counts Again/Hard/Good/Easy once per
card per day; **does not** count Skip or Test Mode; a regrade of the same card the same day does
not double-count; undo does not decrement; explicit sessions (Weak Words/Bookmarks/Smart
Review) contribute normally. Phase 22A changes none of this.

> Load-order note: `metadata.js` loads after `app.js`, so before `HSKMeta` exists the Home read
> helper falls back to the **same** underlying data (`settings.dailyCounts[HSKUtil.date.localDay()]`)
> — identical value and day-key, no semantic change — so the first Home paint isn't wrongly 0.

## dailyGoal settings contract
- Additive optional key `settings.dailyGoal` ∈ {10,20,30,50}; default/fallback **20**.
- `SettingsRepository.getDailyGoal()`: returns `Number(dailyGoal)` if allowed, else 20. Accepts a
  valid numeric string; missing/null/non-numeric/unsupported → 20. **Read-only** — never mutates
  the source, writes storage, or marks dirty.
- Shared pure read model in `app.js`: `dailyGoalModel() -> {learned, goal, percent, reached}`
  (`percent = min(100, round(learned/goal*100))`, `reached = learned>=goal`), used by both Home
  and completion for a single consistent calculation.

## Home behavior
New "Mục tiêu hằng ngày" panel between Hiển thị and the stats grid:
- `#dailyGoalSelect` (10/20/30/50 thẻ) with a real `<label for>`; on change → parse, accept only
  10/20/30/50, `settings.dailyGoal=v`, `saveSettings()` **once**, then re-render (render never writes).
- Progress text `N/G thẻ` and a compact bar; the bar has `role="progressbar"`, `aria-valuemin=0`,
  `aria-valuemax=<goal>`, `aria-valuenow=<learned>`. Bar caps at 100% while the text shows the real
  value (e.g. 25/20).

## Completion behavior
The Phase 21 habit row's existing "Đã học hôm nay" item is made **goal-aware** (shows `N/G`) —
**not duplicated**. A full-width goal progress bar is added below the row, and when `learned>=goal`
a short acknowledgment "Đã hoàn thành mục tiêu hôm nay." appears (hidden otherwise). All Phase 21
behavior is preserved exactly: grade breakdown, due-remaining, all-clear message, "Học tiếp N thẻ"
gating, explicit-session completion, Home button, session-source, summary sentence. Feedback shows
for level and explicit Study sessions (both feed `dailyCounts`); Test Mode is unaffected.

## Account / local-only / sync behavior
`dailyGoal` lives in the per-account settings blob → **account-namespaced** when logged in, base
key in local-only; **same shape** both modes. Sync is unchanged: **whole-settings-blob,
last-writer-wins** (`sync.js` pushes/pulls the entire `user_settings.data`; no field merge). The
goal value therefore follows the newest settings; daily *counts* keep their pre-existing
cross-device caveat (two devices the same day do not sum — documented, not worsened). No new
localStorage key, DB column, table, RPC, payload type, counter, migration, or server aggregation.

## Tests
- `tests/regression/daily_goal.py` (new, registered): settings contract; counting semantics
  (again/hard/good/easy count, skip/Test-Mode don't, regrade no double, undo no decrement, explicit
  counts, multi-session unique accumulation); Home 0/partial/reached/exceeded, select reflects
  setting, invalid-value fallback, local-only reload persistence, A→B→A isolation; completion
  no-duplicate item, N/G, acknowledgment gating, Phase 21 continue gating intact.
- `tests/browser/test_settings_repository.py` extended with `getDailyGoal` cases.
- `tests/regression/completion_loop.py`: one assertion updated to the intended goal-aware format
  (`9/20`), not a weakening.
- **Full suite: 30/30 PASS** (p0 answer-leak, SRS goldens, completion_loop, auth/offline all green).

## Service Worker
Cache bumped once **v30 → v31** (runtime assets changed). Asset list, install/activate/fetch, and
caching strategy unchanged.

## Rollback
Branch `phase-22a-daily-goal` only; `main` untouched. `git revert <sha>` (SW reactivates v30) or
delete the branch pre-merge. The orphaned `dailyGoal` key is inert if the code is reverted.

## Deferred
**Phase 22B** — streak semantics correction (move increment from session-start to first graded
card of the day, preserving existing values) — is explicitly **not** included here.
