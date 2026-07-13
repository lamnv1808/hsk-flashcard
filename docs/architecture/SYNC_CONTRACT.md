# SYNC CONTRACT (Phase 0)

Documents the **current** cloud-sync behavior exactly. It is frozen: any future
repository/sync extraction must preserve every rule here.

## 1. Modes
- **Local-only** (`SUPABASE_CONFIG` blank): no network; localStorage is the store; `HSKSync` never activates.
- **Cloud** (configured + logged in): local-first with background sync. `HSKSync` self-activates in `sync.js` only when `HSK_AUTH.userId` is set.

## 2. Model
Local storage is always the live/optimistic store. The account's namespace is
`::<userId>`. Two data families sync:
1. **Per-card progress** → table `card_progress`, pushed **per changed card**.
2. **Settings blob** (incl. bookmarks/notes/daily) → table `user_settings.data`, pushed **whole**.

## 3. Write path (optimistic)
1. UI mutates memory + writes localStorage (`save`/`saveSettings`).
2. `HSKSync.markDirty(cardId)` adds the id to `hsk_sync_dirty::uid` and stamps `hsk_sync_meta::uid[id]=now`.
3. `onSettingsChanged()` stamps `hsk_sync_settime::uid=now`.
4. A **1200 ms debounce** then pushes: progress via RPC `sync_push_progress`, settings via RPC `sync_push_settings`.

## 4. Conflict resolution — **latest `updated_at` wins**
Both RPCs upsert only when `excluded.updated_at > existing.updated_at`. A stale
device can never overwrite newer server data. Client sends its `updated_at` (from
`hsk_sync_meta`/`hsk_sync_settime`). Deletes: `DELETE …card_id=in.(…)`; reset =
`…card_id=gte.0`.

## 5. Read path (pull + merge)
On `start()` (every logged-in load): `GET card_progress?updated_at=gt.<lastpull>`
(full pull when no lastpull) and `GET user_settings`. Merge rule per card: apply
server row only if `server.updated_at > local meta` **and** not locally-dirty-newer;
settings applied only if `server.updated_at > local settime`. After merge,
`HSK_APP.reloadState()` re-reads memory and re-renders (never mid-session).

## 6. Offline & retry
`accessToken()`/`fetch` throw when offline → dirty set and settime persist. A
`window 'online'` listener calls `flush()` (push pending). No data is lost across
reconnect. The service worker never caches these cross-origin calls.

## 7. Migration (one-time)
`maybeMigrateLegacy()` after first login: if legacy un-namespaced progress exists
and `hsk_import_done::uid` is unset, prompt Import/Skip/Summary. Import merges only
cards the cloud lacks (never overwrites newer), uploads, then marks done. **Legacy
local data is never deleted.**

## 8. Invariants (must not change)
- Only **changed** cards are uploaded; never all 5,002.
- Settings sync as **one** jsonb row; new metadata keys ride along automatically.
- Account isolation is by storage-key namespace + RLS `auth.uid()`; no cross-account read/write.
- No second sync engine. No Supabase schema change to add metadata (it lives in `user_settings.data`).
- Token in localStorage is the Supabase default; SW must not cache auth responses.

## 9. Future (target) — behind `*Repository` interfaces
`ProgressRepository`, `SettingsRepository`, `BookmarkRepository`, `NoteRepository`,
`AnalyticsRepository` will each expose `get/put/subscribe` and a `SyncEngine` will
own the dirty-set + debounce + conflict rule described above. The **first**
implementations wrap exactly this behavior (a "LegacyLocalStore" + "SupabaseStore"
pair), verified equivalent by characterization tests before anything is rewired.
