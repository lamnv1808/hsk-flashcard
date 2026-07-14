# Phase 22B — Streak Semantics Correction

Additive, reversible correction of when a streak "day" is earned. No SRS/state-machine/sync
redesign; whole-settings-blob last-writer-wins sync is preserved.

## Old bug
`updateStreak()` ran at **session start** (`startStudy` and `HSK_APP.startSession`), so opening a
session and immediately exiting — grading nothing — earned a streak day. It also anchored on the
**UTC** day (`today()` / `settings.lastStudy`), whose boundary differs from the Phase 22A daily
count (local day), and its "yesterday" mixed a local `setDate(-1)` with `toISOString()` (UTC),
risking off-by-one across DST/timezone boundaries.

## New active-day definition
A streak day is activated by the **first unique Study Mode card graded during the learner's local
calendar day** — the exact same trigger and day-basis as the Phase 22A daily count. Again/Hard/Good/
Easy all qualify; Skip and Test Mode never reach the counter; a regrade/duplicate of the same card
the same day does not re-activate.

## Local-day contract
Days use `HSKUtil.date.localDay()` only. "Yesterday" is computed in **local space** —
`var d=new Date(); d.setDate(d.getDate()-1); localDay(d)` — reading local Y-M-D components (no
`toISOString`), so month/year/leap/DST boundaries are calendar-correct (verified in tests).

## `lastLearnDay` contract
Additive optional `settings.lastLearnDay` = local `"YYYY-MM-DD"` of the last activated day. On the
first counted card of a new local day (`streak` is normalized to a non-negative int first):
- `lastLearnDay` absent → `streak = max(normalizedStreak, 1)` (lazy migration: preserve an existing
  streak; activate a fresh user to 1);
- `=== today` → unchanged (already active today);
- `=== local yesterday` → `streak + 1`;
- otherwise (older / future / corrupt) → reset to `1` (never inflates).
Then `lastLearnDay = today`. Legacy `settings.lastStudy` is **left untouched and inert** (never read
or written again).

## Lazy migration
No page-load migration. On the first qualifying grade after upgrade, an absent `lastLearnDay` is
anchored to today and the existing streak is **preserved** (not reset, not doubled). A user who had
already graded earlier *today* (pre-upgrade `todayLearn.day === today`) anchors on their next new
local day — one documented, non-destructive transition day where an increment may be deferred.

## Single-save ownership
`metadata.js` `recordDailyLearn(id)` is the streak write owner. The streak/anchor update happens
**before** its existing single `persist()`, folded into the same settings mutation that already
writes `todayLearn`/`dailyCounts`. Net effect per first qualifying grade of a day: **exactly one
settings save + one sync-dirty notification** (unchanged from Phase 22A); **zero** at session start;
**zero** on same-day duplicate grades. `app.js` no longer writes streak (the two start-site
`updateStreak()` calls and the dead function were removed).

## Account / offline / sync behavior
`streak`, `lastLearnDay`, `dailyCounts`, `todayLearn` all live in the per-account settings blob →
**account-namespaced** when logged in, base key local-only, same shape both modes. Offline grades
persist to localStorage and push on reconnect via the existing settings path. Sync is unchanged:
**whole-blob last-writer-wins** (no field merge).

## Known deferred limitation
Under whole-blob last-writer-wins, concurrent same-day or split-across-devices activity is not
merged — a stale device pushing an old blob can overwrite a newer `streak`/`lastLearnDay`. This is a
pre-existing sync property, **not** addressed here (non-goal); documented as deferred technical debt.

## Streak transition table
| Prior `lastLearnDay` | Prior `streak` | First grade of a new local day → | `lastLearnDay` after |
|---|---|---|---|
| absent | absent/0 | **1** (fresh activation) | today |
| absent | 5 | **5** (migration preserve) | today |
| yesterday | 5 | **6** | today |
| today | 5 | **5** (unchanged) | today |
| older (>1 day) | 5 | **1** (reset) | today |
| future | 5 | **1** (safe reset) | today |
| corrupt | 5 | **1** (safe reset) | today |
| yesterday | corrupt/negative/NaN | **1** (normalize→0, +1) | today |
| yesterday | 2.9 | **3** (floor→2, +1) | today |

Session start / immediate exit / skip-only / Test Mode → **no change**; second card, regrade, and
"Học tiếp" the same local day → **no change**.

## Tests
`tests/regression/streak_semantics.py` (registered): triggers (start/exit/skip/Test Mode unchanged;
each grade activates; second/regrade/Keep-Going unchanged; explicit-session grade activates),
sequence/anchor transitions, corrupt/future/missing safety, lazy migration, exact save count
(1 on first grade, 0 on dup), reload persistence, account-blob isolation, and local-calendar
yesterday correctness at month/year/leap boundaries. Full suite **31/31 PASS** (Daily Goal,
completion_loop, p0 answer-leak, SRS goldens, auth isolation, offline all green).

## Service Worker
Cache bumped once **v31 → v32** (`metadata.js`/`app.js` are precached). Asset list, install/activate/
fetch, and strategy unchanged.

## Rollback
Branch `phase-22b-streak` only; `main` untouched. `git revert <sha>` restores start-triggered streak
and drops the metadata change; SW reactivates v31. The orphaned `lastLearnDay` key is inert if
reverted. No stored data (`streak`/`dailyCounts`/`lastStudy`) is destructively rewritten.
