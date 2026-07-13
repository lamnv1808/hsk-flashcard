# Phase 14 — ProgressWriter.reset (global progress reset)

The global learning-progress reset transaction now goes through
`ProgressWriter.reset()`. **Not a UX redesign** — the controller keeps the confirmation
dialog, copy, and UI refresh; only the `progress` replacement + persist + `onReset` block
moved. Behavior is identical (full suite 24/24; auth/offline/SRS/metadata-sync green
through the real `resetBtn → ProgressWriter.reset` path; everything behaviorally identical
to `production-baseline-v1`).

```
BEFORE (inline in resetBtn):  confirm → progress={} → save() → if(HSKSync)HSKSync.onReset() → renderHome()
AFTER:                        confirm → progressWriter.reset() → renderHome()
                                        (replaceProgress({}) → save() → onReset())
```

- Phase 13 anchor (rollback): `15b1927`
- Phase 14 = the commit introducing this document.

## Reset boundary purpose
`ProgressWriter` already owns per-card progress mutation + injected persistence callbacks
(Phase 12 `grade`, Phase 13 `restore`). Global reset is the same domain (controlled
progress mutation + persistence), so it is a **method on the existing writer**, not a
separate ResetService. Added API: `reset()` (no parameters).

## Exact transaction order
1. `if (!replaceProgress) return null;` — needs the controller's reassign hook (defensive).
2. `replaceProgress({})` — the injected callback runs `progress = {}` in app.js (a **new**
   empty object; full-object replacement, not key-deletion).
3. `save()` — existing persistence; serializes the now-empty `progress` → `"{}"`.
4. `onReset()` — the existing sync-guarded callback (fire-and-forget).
Returns `{ cleared: true }`. **Exactly one** replacement, **one** save, **one** onReset
(when sync exists). **No per-card `markDirty` loop.**

## Why full-object replacement is preserved
The original reset **reassigns** `progress = {}` (does not delete keys on the old object).
Every read consumer (ProgressRepository, ProgressWriter, and — through the repo —
AnalyticsQuery/StudySessionQuery) reads through a `() => progress` **live provider** closure
over the `progress` **variable**, so reassigning the variable makes all of them observe the
new empty object immediately, with no repository/query reconstruction. Preserving the exact
reassignment keeps that live-provider architecture intact.

## replaceProgress provider design
The writer cannot reassign app.js's `progress` variable through a plain object reference, so
app.js injects `replaceProgress: (next) => { progress = next; }`. `replaceProgress` and the
existing `progressProvider: () => progress` operate on the **same binding**, so after reset
`progressProvider()` returns the new `{}`. `replaceProgress` runs **before** `save()` so
`save()` serializes the empty object.

## save / onReset ownership
- `save` (injected, unchanged) = `localStorage.setItem(stateKey, JSON.stringify(progress))`.
- `onReset` (injected as `() => { if(window.HSKSync) HSKSync.onReset(); }`) mirrors the
  original guard and is **fire-and-forget** (`HSKSync.onReset` is async; not awaited, as
  today). All sync-specific reset semantics stay inside `HSKSync.onReset`
  (`setDirty([])` + `setMeta({})` + a single bulk `DELETE /rest/v1/card_progress?card_id=gte.0`).
  The writer never touches the dirty set/meta, timers, cloud payloads, or Supabase.

## Local-only behavior
No `window.HSKSync` → the injected `onReset` wrapper is a no-op: `replaceProgress({})` +
`save()` run, **zero** onReset/network calls. Unchanged.

## Data reset scope (what "Xóa toàn bộ tiến độ học" resets today)
- **Reset:** per-card SRS **progress** (`progress` → `{}`, localStorage `stateKey` → `"{}"`);
  sync bookkeeping via `onReset` (local dirty set + per-card meta cleared; server
  `card_progress` rows deleted).
- **Preserved (intentionally, unchanged):** `todayLearn`, `dailyCounts`, `streak`,
  **bookmarks**, **notes**, **settings** (all in the settings blob, separate key), **Test
  Mode history** (`hsk_test_history` key), account credentials/session. Reset scope is
  **not** broadened.

## Repository / query observability (immediately after `reset()`)
`ProgressRepository.count()===0`, `getCardIds()===[]`, `has(prevId)===false`,
`getOrDefault(prevId)` → untouched default; `AnalyticsQuery` learned/attempts/correct = 0,
Weak Words empty, Smart Review `hasData===false`; `StudySessionQuery` treats all selected
cards as fresh. All observed through the live providers with **no** repository/query rebuild.

## Controller responsibilities retained
`confirm("Xóa toàn bộ tiến độ học?")` (dialog + copy), `renderHome()`, all session/
navigation/render state, reset-button handling. The writer knows nothing about UI, sessions,
snapshots, or `sessionGrades`.

## Failure behavior
`replaceProgress` absent → `reset()` returns `null`, no mutation. `save`/`onReset` failures
propagate as today (`onReset` is async + fire-and-forget, so it never throws synchronously).
Old progress being `null`/`undefined` is irrelevant (reset replaces, doesn't read it).
No new production UI errors.

## Deferred sync/cloud paths
`HSKSync.onReset` internals (dirty/meta clear + bulk server delete), sync transport/merge,
`reloadState`, `onSettingsChanged`, Supabase, cloud conflict resolution — all unchanged
(the writer only invokes the injected callback).

## Performance
O(1) object replacement — no loop over progress rows, no 5,002-card scan, no repository/
query rebuild, one `save`, one `onReset`, no per-card dirty events, no added network beyond
the existing `onReset` server delete. Reset latency unchanged.

## Migrated call site
`app.js resetBtn.onclick`'s `progress={}; save(); if(HSKSync)HSKSync.onReset()` block →
`progressWriter.reset()`. Confirmation + `renderHome()` unchanged. The writer instance
gained two deps: `replaceProgress` and `onReset`.

## Characterization / tests
`tests/browser/test_progress_writer.py` (extended): inline `progress={}; save(); onReset()`
vs `writer.reset()` over {populated, empty} — equal resulting progress, `{}`-became, **new
object identity**, `save===1`, `onReset===1`, **no per-card dirty**; read observability
(repo count 0 / ids [] / has false / getOrDefault default; Analytics 0; Weak empty; Smart
insufficient; Session all-fresh); local-only (save, no onReset); account isolation A→B→A
(reset A leaves B intact); absent-`replaceProgress` guard; no writer storage side effects.
`grade`/`restore` tests unchanged. The real `auth_test`/`offline_test`/SRS goldens exercise
the actual integration.

## Service worker
Bumped **once**: `v20 → v21`. The precached `core/progress/progress-writer.js` **content
changed** (added `reset`), so a bump is required for clients to fetch it (Phase 12–13
policy). No new asset; asset list and caching strategy unchanged.

## Rollback
Phase 14 is independently reversible.
1. `git revert <phase-14-commit>` on `architecture-v2` — restores `resetBtn`'s inline
   `progress={}; save(); onReset()` block, removes `ProgressWriter.reset` (+ the
   `replaceProgress`/`onReset` deps), and reverts `sw.js` to `v20`.
2. Or manual: `git checkout 15b1927 -- hsk_flashcard_app/app.js hsk_flashcard_app/core/progress/progress-writer.js hsk_flashcard_app/sw.js tests/browser/test_progress_writer.py`.
3. Re-run `python tests/run_regression.py` — expect **24/24** (no suite-count change; Phase 14
   only extended `progress_writer`).
4. Phase 1–13 files, baselines, and the `production-baseline-v1` tag are preserved.

## Recommended Phase 15 scope (do not begin)
With grade/restore/reset all behind `ProgressWriter`, the local per-card **progress write
surface is fully bounded**. The next low-risk step is a **read-only `SyncStatusQuery`** over
sync bookkeeping (`hsk_sync_dirty::uid` count, `hsk_sync_lastpull`, `hsk_sync_settime`,
sync UI state string) for the existing sync-status UI — a read seam over the `hsk_sync_*`
keys, **without** touching transport/merge/push/pull. Alternatively, extract the read-only
**account/session identity** accessor (`HSK_AUTH` → a small `AuthContextQuery`) consumed by
the storage-key namespacing. Continue deferring sync transport ownership, cloud
merge/conflict, `metadata`/bookmark/note **writes**, StudySessionEngine, dynamic pack
loading, and UI branding.
