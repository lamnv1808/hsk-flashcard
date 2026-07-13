# CURRENT STATE — Architecture Audit (Phase 0)

> Baseline commit: `ecd13fb` (tag `production-baseline-v1`). This document traces
> the **actual runtime code**, not the README. No runtime files were changed to
> produce it.

## 1. Runtime shape

A **static, no-build, vanilla-JS PWA** served from `hsk_flashcard_app/`. There is
no bundler, no framework, no module system — every `.js` file is a classic
`<script>` sharing one global lexical scope. Backend is **Supabase** (Postgres +
Auth + Edge Functions), reached over `fetch`. Deployed as a Render Static Site.

### 1.1 Script load order (`index.html`, end of `<body>`)

| # | File | LOC | Role | Exposes |
|---|------|-----|------|---------|
| 1 | `data.js` | 3 (1 huge line) | Content pack (5,002 cards) | `window.HSK_CARDS` |
| 2 | `supabase-config.js` | 16 | Config gate | `window.SUPABASE_CONFIG` |
| 3 | `auth.js` | 365 | Accounts + session + gate/profile UI | `window.HSK_AUTH` (sync boot), `window.HSKAuth` |
| 4 | `app.js` | 478 | **Core**: Study Mode, SRS, sessions, audio, swipe, keyboard, home | `window.HSK_APP`, many top-level fns |
| 5 | `sync.js` | 254 | Cloud sync engine (local-first) | `window.HSKSync` |
| 6 | `test.js` | 433 | Multiple-choice Test Mode | `window.TestMode` |
| 7 | `metadata.js` | 138 | Bookmarks, notes, daily aggregates + study hooks | `window.HSKMeta` |
| 8 | `insights.js` | 245 | Weak Words, Smart Review, chart, Bookmarks page | `window.HSKInsights` |

Non-JS runtime: `styles.css` (410), `sw.js` (service worker, cache `hsk-flashcards-v9`),
`manifest.webmanifest`, `icons/*`.

### 1.2 Module boundary today = the `window.*` namespaces

The only real seams are these globals; everything else is implicit shared scope.

- `HSK_CARDS` — content data (read-only array).
- `SUPABASE_CONFIG` — `{url, anonKey}` (blank ⇒ local-only mode).
- `HSK_AUTH` — synchronous boot result: `{configured, userId, username, progressKey, settingsKey, needsAuth}`. **Decides the storage namespace before `app.js` runs.**
- `HSKAuth` — auth API: `accessToken()`, `headers()`, `base()`, `currentUser()`, `isLoggedIn()`, `showGate()`, `hideGate()`, `setSyncState()`.
- `HSK_APP` — the app bridge: `keys()`, `getProgress()`, `getSettings()`, `cards()`, `levels()`, `startSession(ids)`, `reloadState()`.
- `HSKSync` — `start()`, `pullAll()`, `flush()`, `markDirty(id)`, `onSettingsChanged()`, `onReset()`, `maybeMigrateLegacy()`.
- `TestMode` — `open()`.
- `HSKMeta` — `syncCard()`, `onFlip(flipped)`, `recordDailyLearn(id)`, `isBookmarked`, `toggleBookmark`, `removeBookmark`, `bookmarks`, `getNote`, `hasNote`, `notesMap`, `dailyCounts`, `localDay`.
- `HSKInsights` — `showWeak()`, `showInsights()`, `showBookmarks()`.

## 2. Global mutable state (all in `app.js`, lexical/shared)

`cards`, `progress`, `settings`, `session[]`, `current`, `selectedLevels[]`,
`flipped`, `sessionGrades[]`, `snapshots{}`, `speech{}`, `stateKey`, `settingsKey`,
`AUTH`, `LEVELS`. Other scripts mutate this state through `HSK_APP`/`window.saveSettings`
or by calling top-level functions that are hoisted onto `window`
(`currentCard`, `renderHome`, `showView`, `speak`, `stopSpeech`, `gradeCard`, …).

`LEVELS` is derived at load: `[...new Set(cards.map(c=>c.level))]` sorted by the
**numeric suffix** of the level name — the one place level enumeration is generic.

## 3. Key runtime flows (traced)

### 3.1 Boot
`auth.js` runs a **synchronous IIFE** first: if `SUPABASE_CONFIG` is blank →
`HSK_AUTH={configured:false}` and `app.js` uses the original global keys. If
configured and a cached user exists → namespaced keys; else `{needsAuth:true}` and
the gate is shown. `app.js` then reads `localStorage[stateKey|settingsKey]` into
`progress`/`settings` and renders home. `sync.js` self-activates only if logged in
and runs `start()` (pull → reflect → migrate → flush).

### 3.2 Study Mode
`startStudy(levels)` → builds `session` from due + fresh cards (`dueCards`,
`getCardState`) → `showView('studyView')` → `renderCard()`. `renderCard()` resets
flip **without animation** (`no-flip-anim` + reflow — the P0 leak fix), writes
front content, calls `HSKMeta.syncCard()`. `flipCard()` toggles `.flipped`, shows
rating + note zone (`HSKMeta.onFlip`). `gradeCard(grade)` guards `if(!flipped)`,
snapshots for undo, applies SRS math, `save()`, `HSKSync.markDirty`,
`HSKMeta.recordDailyLearn`, advances. Swipe/drag = pointer handlers on `#flashcard`
(`swipeNext`=skip, `swipePrev`=previous). Custom sessions (`HSK_APP.startSession`)
reuse the same renderer/grading.

### 3.3 SRS
Pure function of `progress[id]` and the grade. `again`→+1min/interval 0;
`hard`→max(1, interval×1.2); `good`→max(3, interval×2); `easy`→max(7, interval×3).
Increments `reps`, `attempts`; `correct` only on good/easy. Snapshot/`revertSnapshot`
per session index prevents double-count when revisiting. **No timestamps stored per
grade**; "last graded" is derived elsewhere as `due − interval`.

### 3.4 Test Mode
Self-contained in `test.js`. Reads `HSK_CARDS`, builds MCQs (6 types), never calls
`gradeCard`/`save`/`HSKSync` — diagnostic only. Own views, own keyboard handler,
own local history key `hsk_test_history[::uid]`.

### 3.5 Sync
See `SYNC_CONTRACT.md`. Local-first: dirty set of changed card IDs, debounced push
via RPC `sync_push_progress` (latest-`updated_at`-wins), settings pushed as one
`jsonb` blob via `sync_push_settings`, pull on load, offline queue flushed on
`online`. Metadata (bookmarks/notes/daily) rides the settings blob.

## 4. Storage keys (exact)

Local base keys (local-only mode, or fallback): `hsk_flashcard_progress_v2`,
`hsk_flashcard_settings_v2`. When logged in they are **namespaced** `…_v2::<userId>`.
Auth: `hsk_session` `{access_token,refresh_token,expires_at}`, `hsk_current_user`
`{id,username}`. Sync bookkeeping (per user): `hsk_sync_dirty::<uid>`,
`hsk_sync_meta::<uid>`, `hsk_sync_lastpull::<uid>`, `hsk_sync_settime::<uid>`,
`hsk_import_done::<uid>`. Test history: `hsk_test_history[::<uid>]`. Exact shapes in
`DATA_CONTRACTS.md`.

## 5. Supabase surface

Tables: `profiles`, `card_progress`, `user_settings`, `login_attempts` (+ RLS).
RPCs: `sync_push_progress(rows jsonb)`, `sync_push_settings(p_data jsonb, p_updated_at timestamptz)`.
Edge Functions: `register`, `login`, `change-pin`, `delete-account` (HMAC-pepper
credential derivation, per-username rate limit, no user enumeration). Full detail in
`DATA_CONTRACTS.md`, `docs/SUPABASE_SETUP.md`.

## 6. Service worker

`sw.js`: cache-first for same-origin GET; **ignores non-GET and cross-origin**
(so it never caches auth/sync/Supabase). Precaches the app shell + all JS + icons;
`install` = `skipWaiting`, `activate` = delete old caches. Update reaches users only
when the `CACHE` version string changes.

## 7. Content importer & generated data

`scripts/import_hsk_excel.py`: reads `source_data/HSK1-HSK6.xlsx`, auto-detects
`HSK*` sheets, maps columns B–G → `{word,pinyin,meaning,example,examplePinyin,translation}`,
**preserves existing card IDs** by anchoring to the current `data.js` via the unique
`(level, word)` key, assigns new IDs `max+1` deterministically, writes `data.js`
atomically. The browser only ever loads the generated `data.js`; it never parses Excel.

## 8. Coupling & risk hot-spots (findings)

- **Single god-module (`app.js`)** owns state + rendering + SRS + audio + sessions +
  home. Everything else reaches in via globals. This is the biggest extraction target.
- **UI ↔ storage are directly coupled**: `save()`/`saveSettings()` write localStorage
  inline; `sync.js` and `metadata.js` also read/write localStorage directly. No
  repository seam.
- **HSK/Chinese assumptions baked into "generic" logic** (must be lifted to a content
  pack): audio language is hardcoded `"zh-CN"` in `speakWord/speakExample/readAll`;
  the card model assumes `word`=Chinese, `pinyin`, `meaning`=Vietnamese,
  `example/examplePinyin/translation`; the **front-pinyin preference**, the six
  **Test Mode question types**, and the level label parsing (`parseInt` of `HSKn`) are
  all Chinese/HSK-specific.
- **Implicit load-order dependency**: `HSK_AUTH` must be computed (auth.js) before
  `app.js` reads keys; `HSKMeta`/`HSKSync` must exist before `app.js` hooks fire (guarded
  with `if(window.X)`). Fragile but currently correct.
- **Animation/state race** class of bug: the P0 next-card leak was one (fixed via
  `no-flip-anim` reflow); speech uses a `token` to invalidate stale callbacks; swipe
  uses `suppressClick`. These are ad-hoc, not a general pattern.
- **No circular *import* dependencies** (no imports at all), but a **circular runtime
  dependency** exists conceptually: `app.js` ⇄ `metadata.js` ⇄ `sync.js` all mutate the
  same `settings` object through `HSK_APP`.
- **Duplicated logic**: level-list derivation is duplicated in `app.js`, `test.js`,
  `insights.js`; `localDay`/date helpers duplicated; "setActive across `.view`"
  duplicated in `test.js` and `insights.js` (and `app.js`'s `showView` only knows 3
  views — the source of the Phase-N view-overlap class of bug already seen once).

## 9. Extract-first vs leave-late

**Extract first (low risk, high leverage):** pure utilities (date/day, level
sort, shuffle, id-map), the content array behind a `CardRepository`, and read-only
analytics (`insights.js` already only reads). **Leave until late (high risk):** SRS
math, session construction, the flip/swipe render loop, auth/session lifecycle,
sync engine, service worker — these carry the compatibility contract and the
subtle race fixes.
