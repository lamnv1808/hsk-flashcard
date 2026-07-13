# Phase 12 — Write-capable ProgressWriter (Study Mode grading)

The **first write-capable boundary**: one narrow `ProgressWriter` around the existing
Study Mode grading transaction. **Not a new scheduler, not new storage** — a write seam
around the current implementation. The product behaves exactly as before (full suite
24/24; the frozen SRS goldens `srs_characterization`/`p0_test`/`regression`/`features_test`
green through the real `gradeCard → ProgressWriter` path; cards/IDs/importer/baseline and
every prior repo/query/pack behaviorally identical to `production-baseline-v1`).

```
BEFORE (inline in gradeCard):  read getCardState → SRS mutate → progress[id]=s → save() → HSKSync.markDirty
AFTER:                         gradeCard → ProgressWriter.grade({cardId,grade})  (same order, same effects)
```

- Phase 11 anchor (rollback): `6c1ae4d`
- Phase 12 = the commit introducing this document.

## Module
`hsk_flashcard_app/core/progress/progress-writer.js` — classic script.
`HSKUtil.createProgressWriter(deps)` → `{ grade({cardId, grade}) }`. There is **no** shared
instance in the module (the writer needs app.js closures: `save`, `HSKSync.markDirty`,
`() => progress`); app.js builds the single instance. `ProgressRepository` stays
**read-only** — the writer *reads* current state through it and *writes* through injected
`save`/`markDirty` (chosen over adding write methods to the read repo, to keep the read
contract clean; no duplication — SRS math is injected and reads reuse the repo).

## Exact write transaction (`grade`)
Preserves the current order of operations (steps 5–10 of the old `gradeCard`):
1. `if (cardId == null) return null;` — defensive guard, **no partial mutation** (unreachable in production; production always passes `session[current].id`).
2. `now = dateProvider()`; `todayKey = now.toISOString().slice(0,10)` (captured before SRS mutates `now`).
3. `previousState` = deep clone of `progress[cardId]` (single row) or `null` — for the return value only.
4. `s = progressRepository.getOrDefault(cardId, todayKey)` — live row for a touched card, else the SAME fresh default as `getCardState()` (its `due` is overwritten in step 5).
5. `next = srsCalculator(s, grade, now)` — the **exact existing SRS block** (mutates `s` and `now`, returns `s`).
6. `progress[cardId] = next` — assign (creates the row for an untouched card).
7. `save()` — existing persistence (localStorage write).
8. `markDirty(cardId)` — existing dirty/sync trigger.
Returns `{ cardId, grade, previousState, nextState }` (app.js ignores it).

## Rating identifiers
Lowercase **strings** `"again" | "hard" | "good" | "easy"` (from the grade buttons),
**unchanged**. Per current behavior, an **unknown** rating falls into the SRS `else`
branch (easy interval math) and does **not** increment `correct` — preserved exactly
(not "rejected"). `cardId == null` is the only rejected input (returns `null`, no mutation).

## SRS math ownership
**Unchanged.** The formula block was extracted verbatim from `gradeCard` into
`app.js srsNextState(s, grade, now)` (byte-identical: again→interval 0/+1min; hard→
`max(1, interval?round(interval*1.2):1)`; good→`max(3,…*2…:3)`; easy(`else`)→
`max(7,…*3…:7)`; then `due=now.iso`, `reps++`, `attempts++`, `correct++` for good/easy).
It is **injected** as `srsCalculator`; the writer never does SRS math. UTC/local-day
semantics unchanged (`due` via `toISOString().slice(0,10)`).

## Provider lifecycle
`progressProvider = () => progress` (the live `let`, reassigned on cloud pull/reloadState,
page-reloaded on account switch). The writer assigns into `progressProvider()[cardId]`, so
grades always land on the **currently active** account's progress — no stale capture
(same pattern as Phase 8). Tests verify provider replacement A→B→A with no cross-account leak.

## Persistence / dirty / sync
`save()` = `localStorage.setItem(stateKey, JSON.stringify(progress))` — **localStorage only,
no dirty**. `markDirty(id)` (injected as `id => { if(window.HSKSync) HSKSync.markDirty(id); }`)
= dirty set + per-card meta timestamp + `schedulePush` (1.2s debounce). **Exactly one `save`
and one `markDirty` per successful grade, in that order** — asserted by tests
(`save===1`, `dirty===1`; N grades → N/N). **Local-only** mode (no `HSKSync`): the wrapper
is a no-op → `save` runs, `markDirty` does nothing (unchanged). No double-save, no duplicate
dirty; `sync.js` is untouched (transport/merge/`markDirty` unchanged).

## Migrated call site
`app.js gradeCard` steps 5–10 → `progressWriter.grade({ cardId: c.id, grade })`.

## Deferred (stays in app.js / other owners)
- **Flip guard** (`if(!flipped) return`), **undo snapshot/revert** (`captureSnapshot`/
  `revertSnapshot`, session-index-addressed), **sessionGrades**, `current++`/`renderCard`
  (UI advance) — controller/session state.
- **`recordDailyLearn`** (daily chart) and **`updateStreak`** (session-start, not in the
  grade transaction) — orchestration stays in app.js (writer is not a god service).
- `skipCard` revert-save-markDirty, `resetBtn` (`progress={}`), `sync.js` transport/merge/
  `onReset`, `metadata.js`/bookmark/note writes, Test Mode — all unchanged.

## Undo decision
Undo (`snapshots`) stays **outside** the writer: it is session-index/UI-coupled
(`snapshots["i"+index]`, `current`) and must survive re-grading a position. The writer
reads the state **after** app.js runs `captureSnapshot`+`revertSnapshot`, exactly as
before. Undo/skip behavior is unchanged (verified by `regression.py` "nSkips").

## Failure behavior
`cardId == null` → `null`, no mutation, no save/dirty. Unknown rating → `else`/easy math,
no `correct` increment (current quirk). Missing progress object → `getProgress()` returns
`{}` and the row is created. `save`/`markDirty` failures propagate as today (no new error UI).
Flip/transition guards remain at the controller (app.js) level.

## Performance
Writer built **once** (app.js). Per grade: reads/creates **only the graded row**, one small
`previousState` clone (single row, not the whole map), one `save`, one `markDirty`. No
repository rebuild, no full-progress clone, no 5,002-card scan, no added network. Grading
latency unchanged.

## Characterization / tests
`tests/browser/test_progress_writer.py`: a faithful copy of the **original inline** grade
transaction (`__oldGrade`, using the same extracted SRS) vs `writer.grade` over identical
fixtures + fixed `now` — equal resulting row, return `nextState`, and `save===1`/`dirty===1`
— across all **4 grades × {untouched, learned/overdue, future-due}**; exact fresh-card
field values; interval progression (good 3→6→12, easy 7→21→63, hard 1→1→1); sequences
(again→good, easy→again) + cross-card isolation; grade-creates-exactly-one-row / reads-
create-none; local-only (save, no dirty); account isolation A→B→A; invalid input; no
writer side effects beyond injected `save`/`markDirty`. The real SRS goldens
(`srs_characterization`, `p0_test`, `regression`, `features_test`) run the actual app.js
integration end-to-end.

## Service worker
Bumped **once**: `v18 → v19`; added `core/progress/progress-writer.js` to the precache
`ASSETS`. **Strategy unchanged**.

## Rollback
Phase 12 is independently reversible.
1. `git revert <phase-12-commit>` on `architecture-v2` — restores the inline `gradeCard`
   read-modify-write block (removing `srsNextState`/`progressWriter`), removes the writer
   `<script>` tag, and reverts `sw.js` to `v18`.
2. Or manual: `git checkout 6c1ae4d -- hsk_flashcard_app/app.js hsk_flashcard_app/index.html hsk_flashcard_app/sw.js tests/run_regression.py`,
   then delete `hsk_flashcard_app/core/progress/progress-writer.js` and
   `tests/browser/test_progress_writer.py`.
3. Re-run `python tests/run_regression.py` — expect **23/23** after full rollback.
4. Phase 1–11 files, baselines, and the `production-baseline-v1` tag are preserved.

## Recommended Phase 13 scope (do not begin)
With grading behind a writer, the next narrow write boundary is **`skipCard`'s
undo-and-persist** (revert snapshot → `save()` → `markDirty`) — a small, adjacent write
transaction that currently duplicates part of the persistence path. Wrap it (and,
optionally, the shared snapshot/undo capture) behind the same writer or a sibling
`ProgressUndoWriter`, characterized against the frozen skip/undo behavior — **without**
touching SRS, reset, sync transport, or Test Mode. Alternatively, a read-only
**`SyncStatusQuery`** over sync bookkeeping (dirty set / last-pull / pending count) for the
sync UI. Continue deferring reset-progress writes, sync transport ownership, cloud
merge/conflict, `metadata`/bookmark/note writes, dynamic pack loading, and UI branding.
