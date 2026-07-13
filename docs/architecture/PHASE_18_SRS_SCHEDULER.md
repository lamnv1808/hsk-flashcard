# Phase 18 — Pure SRS Scheduler Extraction

The SRS next-state math moved out of `app.js` into a dedicated pure module
`core/srs/scheduler.js`, injected into `ProgressWriter` as the `srsCalculator`. **Only the
pure calculation moved** — `ProgressWriter` still owns the grade write transaction and
app.js still owns grade events, the flip guard, snapshots, daily learning, navigation and
rendering. Behavior is byte-identical (full suite 27/27; the **frozen SRS goldens**
`srs_characterization`/`p0_test`/`regression` pass **unchanged**; `ProgressWriter` is
**byte-unchanged**; everything identical to `production-baseline-v1`).

```
BEFORE:  app.js srsNextState(s, grade, now)  ── injected ──▶ ProgressWriter.grade
AFTER:   core/srs/scheduler.js computeNext(state, grade, now) ── injected ──▶ ProgressWriter.grade
```

- Phase 17 anchor (rollback): `2c0cc82`
- Phase 18 = the commit introducing this document.

## Module
`hsk_flashcard_app/core/srs/scheduler.js` — `HSKUtil.createSrsScheduler()` →
`{ computeNext(state, grade, now) }`, plus a **stateless singleton** `HSKUtil.srsScheduler`
built once at load. Load order (`index.html`): … `core/progress/progress-repository.js` →
**`core/srs/scheduler.js`** → `core/progress/progress-writer.js` → … → `app.js`.

## Pure-function contract
No storage / network / DOM / global progress / sync / repositories / ContentPack / HSK /
account dependency. **Does not mutate the input `state` or the input `now` Date** — clones
`now`, reads (never writes) `state`, and returns a **new** state object (unknown fields
preserved). Given the same `(state, grade, now)` it always returns the same output.

## Exact grade formulas (unchanged, extracted verbatim)
`now` is the base `Date` (ProgressWriter's `dateProvider() = new Date()`); `interval` is the
previous interval.
- **again** → `interval=0`; `now.setMinutes(+1)` (same UTC day unless it crosses midnight).
- **hard**  → `days = Math.max(1, interval ? Math.round(interval*1.2) : 1)`; `now.setDate(+days)`.
- **good**  → `days = Math.max(3, interval ? Math.round(interval*2.0) : 3)`.
- **else (easy + any unknown grade)** → `days = Math.max(7, interval ? Math.round(interval*3.0) : 7)`.
Then `due = now.toISOString().slice(0,10)` (**UTC `YYYY-MM-DD`**), `reps = (reps||0)+1`,
`attempts = (attempts||0)+1`, and `correct = (correct||0)+1` **only** for good/easy.
**Unknown-grade quirk preserved:** unknown grades use the easy interval math but do **not**
increment `correct`. Golden progressions: good `3→6→12`, easy `7→21→63`, hard `1→1→1`.

## Date semantics (high-risk, preserved exactly)
`now` is cloned (`new Date(now.getTime())`) and never mutated. `again` adds 1 minute (so
its `due` is normally the same day; near UTC midnight `23:59` it rolls to the next day —
tested). Others add whole days via `setDate`, with `Date`-native month/year/leap rollover
(tested: Jan 30 +3 → Feb 02; Dec 28 +7 → next-year Jan 04; Feb 28 2028 +1 → Feb 29). Output
is UTC `toISOString().slice(0,10)`. No date library change.

## State copy / immutability semantics
The original `srsNextState` **mutated `s` in place** (preserving any extra fields) and
returned it; `ProgressWriter` consumes the **return value** (`prog[cardId] = next`) and
computes `todayKey` from `now` **before** the call, so it never depended on the mutation
side-effects. The pure `computeNext` **copies all of `state`'s own fields first, then
overrides the 5 SRS fields** — reproducing the in-place mutation's field set **and key
order**, so `JSON.stringify(computeNext(...)) === JSON.stringify(srsNextState(...))` for
every input (verified by the characterization matrix). For a touched card the row object is
now replaced (not mutated in place); the persisted data is byte-identical and nothing held
the old reference (undo uses a separate deep clone).

## ProgressWriter integration (byte-unchanged)
`ProgressWriter` already accepted an injected `srsCalculator`; app.js now injects
`HSKUtil.srsScheduler.computeNext` (was the inline `srsNextState`). The transaction order
is unchanged: **read current state → compute next state → assign row → save → markDirty**
(exactly one save + one markDirty; local-only = save, no dirty). `scheduler.js` never
imports `ProgressWriter` and never persists/saves/marks-dirty. `core/progress/progress-writer.js`
is **byte-unchanged** (git-verified).

## Migrated app.js formula site
Deleted `app.js srsNextState(...)` (the formula block); changed the ProgressWriter injection
`srsCalculator: srsNextState` → `srsCalculator: window.HSKUtil.srsScheduler.computeNext`.
**app.js no longer owns any SRS formula** (`window.srsNextState` is now `undefined`).

## Deferred controller/writer/UI behavior (unchanged)
`gradeCard`, the flip guard, `captureSnapshot`/`revertSnapshot`, `sessionGrades`,
`recordDailyLearn`, `updateStreak`, navigation, `renderCard`, rating button labels/
descriptions, and the entire ProgressWriter write transaction.

## Frozen-golden protection
The existing `srs_characterization` / `p0_test` / `regression` remain the release gate and
were **not** modified — they pass unchanged through the real `gradeCard → ProgressWriter →
computeNext` path (`grade3_interval:3`). The new `test_srs_scheduler.py` extends **around**
them (characterization matrix, sequences, date boundaries, immutability, quirks) — it does
not replace any golden expected value.

## Performance
Stateless singleton built **once**; one `computeNext` per successful grade; O(1); a single
small state-object clone; no card/progress scan, no storage/network. Grade latency unchanged.

## Characterization / tests
`tests/browser/test_srs_scheduler.py`: a faithful mutate-in-place copy of the original
`srsNextState` vs `computeNext` over {4 grades + unknown} × {untouched, interval 0/1/2/large,
overdue, future-due, zero/non-zero counters, extra-field row} + fixed UTC `now` — asserting
`JSON.stringify` equality of the full returned object; exact fresh-card field values; interval
progression sequences (good/easy/hard/mixed, exact each step); date boundaries; input
`state`+`Date` immutability + extra-field preservation; and the unknown-grade / missing-field
quirks.

## Service worker
Bumped **once**: `v24 → v25`; added `core/srs/scheduler.js` to the precache `ASSETS`.
**Strategy unchanged**.

## Rollback
Phase 18 is independently reversible.
1. `git revert <phase-18-commit>` on `architecture-v2` — restores app.js's inline
   `srsNextState` + the `srsCalculator: srsNextState` injection, removes the scheduler
   `<script>` tag, and reverts `sw.js` to `v24`.
2. Or manual: `git checkout 2c0cc82 -- hsk_flashcard_app/app.js hsk_flashcard_app/index.html hsk_flashcard_app/sw.js tests/run_regression.py`,
   then delete `hsk_flashcard_app/core/srs/` and `tests/browser/test_srs_scheduler.py`.
3. Re-run `python tests/run_regression.py` — expect **26/26** after full rollback (Phase 18
   suite removed).
4. Phase 1–17 files, baselines, and the `production-baseline-v1` tag are preserved.

## Recommended Phase 19 scope (do not begin) — mutable Study session controller boundary
With reads (StudySessionEngine/describeCard) and the grade/restore/reset writes
(ProgressWriter) and the SRS math (Scheduler) all extracted, the last large concentration in
app.js is the **mutable Study session controller**: `session`/`current`/`flipped`/`snapshots`/
`sessionGrades` + `gradeCard`/`skipCard`/`flipCard`/`captureSnapshot`/`revertSnapshot`/
navigation/completion. Introduce a **`StudySessionController` state machine** that owns this
mutable state and transitions (start/flip/grade/skip/undo/next/finish) while **delegating**
reads to `StudySessionEngine`, writes to `ProgressWriter`, and leaving **all DOM/audio in
app.js via a thin view callback** — characterized against the current navigation/answer-leak/
undo behavior, **without** changing SRS, ProgressWriter, or any rendered output. This is a
larger, state-owning phase needing its own before-coding audit and careful answer-leak
characterization. Continue deferring `auth.js`/`sync.js` writes, sync transport,
`metadata`/bookmark/note writes, Test Mode controller, dynamic pack loading, and UI branding.
