# Phase 13 — ProgressWriter.restore (Study Mode undo/skip persistence)

A second, adjacent write boundary: the per-card **restore/delete** persistence
transaction used by the existing Study Mode undo/skip flow now goes through
`ProgressWriter.restore(...)`. **Not an undo redesign** — the controller keeps snapshot
capture, the snapshot map, session index, navigation and UI; only the
restore-or-delete + save + markDirty block moved. Behavior is identical (full suite
24/24; SRS goldens + skip regression `nSkips:true` green through the real
`skipCard → ProgressWriter.restore` path; everything behaviorally identical to
`production-baseline-v1`).

```
BEFORE (inline in skipCard):  revertSnapshot(current) → delete snapshot → save() → HSKSync.markDirty(sid)
AFTER:                        delete snapshot → ProgressWriter.restore({cardId, hadState, previousState})
                                                 (restore/delete → save() → markDirty(cardId))
```

- Phase 12 anchor (rollback): `50a91c5`
- Phase 13 = the commit introducing this document.

## Restore boundary purpose
`ProgressWriter` already owns controlled per-card progress mutation + `save`/`markDirty`
callbacks (Phase 12 `grade`). Undo's restore-or-delete is the **same domain** (per-card
progress persistence), so it is a **method on the existing writer**, not a new service
(no `ProgressRestoreWriter`). Added API: `restore({ cardId, hadState, previousState })`.

## Why snapshot ownership stays in the controller
The snapshot is **session-index/UI-coupled**: `snapshots["i"+index] = {id, had, state}`,
keyed by session position, captured once per position in `gradeCard`, and consumed by
navigation. `captureSnapshot`, the `snapshots` map, `revertSnapshot` (still used by
`gradeCard` for its in-memory pre-grade reset — no persistence), snapshot deletion,
`sessionGrades`, `current`/navigation and `renderCard` all remain in app.js. The writer
knows nothing about session index, card position, buttons, render state, daily counts or
audio.

## Restore/delete transaction (`restore`)
1. `if (cardId == null) return null;` — no partial mutation.
2. `hadState === true` → `progress[cardId] = JSON.parse(JSON.stringify(previousState))`
   (deep clone — exactly as `revertSnapshot` restored a card that had prior progress).
3. `hadState === false` → `delete progress[cardId]` (removes the row the grade created;
   **not** replaced with a default row).
4. `save()` then `markDirty(cardId)`.
Returns `{ cardId, hadState }` (controller ignores it). After a delete, reading the card
again returns the normal **unstored default** via `ProgressRepository.getOrDefault`
(`has(cardId) === false`).

## Save / dirty order & counts
`restore/delete → save() → markDirty(cardId)` — **exactly one `save` and one `markDirty`**
per undo of a graded position (asserted). `save` = localStorage-only; `markDirty` (injected
as `id => { if(window.HSKSync) HSKSync.markDirty(id); }`) = dirty set + meta + debounced
push. No save before mutation, no double scheduling. Sync debounce unchanged; `sync.js`
untouched.

## Local-only behavior
No `HSKSync` → the injected `markDirty` wrapper is a no-op: `save()` runs, **zero**
dirty/sync calls, no network. Unchanged.

## Daily-count / streak decision
Undo/skip does **not** reverse `recordDailyLearn` / `todayLearn` / `dailyCounts` / streak —
this matches current behavior (undo never reversed daily learning). Preserved exactly and
**not** "fixed" this phase; `restore` does not touch daily/streak.

## sessionGrades decision
`sessionGrades[current] = "skip"` stays controller-owned in `skipCard` (unchanged); the
writer does not manage session grade history.

## Migrated call site
`app.js skipCard` — the `revertSnapshot(current); delete snapshots[...]; save(); if(HSKSync)
markDirty(sid)` block → `delete snapshots[k]; progressWriter.restore({cardId: snap.id,
hadState: snap.had, previousState: snap.state})`. (Snapshot deletion moved just before the
writer call — behaviorally irrelevant since snapshots are never persisted; capturing `snap`
first preserves the id/flags/state.)

## Deferred (unchanged)
`gradeCard`'s bare `revertSnapshot` (in-memory pre-grade reset, **no** persistence — out of
scope), `ProgressWriter.grade` (unchanged), `resetBtn` (`progress={}`), `sync.js`
transport/merge/`onReset`, `metadata.js`/bookmark/note writes, Test Mode, `recordDailyLearn`,
`updateStreak`.

## Failure behavior
`cardId == null` → `null`, no mutation, no save/dirty. Missing snapshot → controller
guards (`if(k in snapshots)`) so `restore` isn't called. `hadState:true` with an absent
`previousState` → `JSON.parse(JSON.stringify(undefined))` throws — **identical to the
original `revertSnapshot`** and unreachable in production (`captureSnapshot` always sets
`state` when `had`). `save`/`markDirty` failures propagate as today (no new error UI).

## Provider lifecycle
`restore` writes to `progressProvider()[cardId]` (the live `progress` binding), so undo lands
on the currently active account (cloud-pull reassignment / account switch honored, no
stale). Same single writer instance as `grade` — not rebuilt per undo.

## Performance
Only one row restored/deleted + one single-row deep clone (matches the original);
no full-progress clone, no repository rebuild, no card scan, one `save`, one `markDirty`.
No added network. Undo latency unchanged.

## Characterization / tests
`tests/browser/test_progress_writer.py` (extended): a faithful copy of the inline skip
restore/delete transaction (`oldRestore`) vs `writer.restore` over identical fixtures
(learned + untouched) — equal progress object, `save===1`, `dirty===1`; restore-existing
(exact field restoration, other rows untouched, grade+restore = 2 saves/2 dirty); delete-
new (`has→false`, `getOrDefault→default`); sequences (each grade→undo→pre-state; untouched
grade→undo→regrade); local-only (save, no dirty); account isolation A→B→A; null-cardId
guard. `ProgressWriter.grade` tests unchanged. The real SRS goldens + `regression.py`
skip/undo run the actual app.js integration.

## Service worker
Bumped **once**: `v19 → v20`. The precached `core/progress/progress-writer.js` **content
changed** (added `restore`), so a bump is required for clients to fetch the new version.
No new asset; asset list and caching strategy unchanged.

## Rollback
Phase 13 is independently reversible.
1. `git revert <phase-13-commit>` on `architecture-v2` — restores `skipCard`'s inline
   `revertSnapshot; delete; save; markDirty` block, removes `ProgressWriter.restore`, and
   reverts `sw.js` to `v19`.
2. Or manual: `git checkout 50a91c5 -- hsk_flashcard_app/app.js hsk_flashcard_app/core/progress/progress-writer.js hsk_flashcard_app/sw.js tests/browser/test_progress_writer.py`.
3. Re-run `python tests/run_regression.py` — expect **24/24** (no suite-count change;
   Phase 13 only extended `progress_writer`).
4. Phase 1–12 files, baselines, and the `production-baseline-v1` tag are preserved.

## Recommended Phase 14 scope (do not begin)
Two low-risk options:
- **(A) Read-only `SyncStatusQuery`** over sync bookkeeping (dirty set, last-pull, pending
  count, sync-time) for the existing sync UI status — a read seam over `hsk_sync_*` keys,
  **without** touching transport/merge. Characterized against current status reads.
- **(B) `reset` write on `ProgressWriter`** — wrap `resetBtn`'s `progress={}; save();
  HSKSync.onReset()` behind a narrow `reset()` method (the last local progress write),
  characterized against current reset behavior, **without** changing `onReset`/sync
  transport or cloud delete semantics.
Continue deferring sync transport ownership, cloud merge/conflict, `metadata`/bookmark/note
writes, StudySessionEngine, dynamic pack loading, and UI branding.
