# Phase 4 — Read-only SettingsRepository & Accessor Seam

Second repository boundary for **FlashEdu** (HSK is content pack #1). A single
read-only `SettingsRepository` now centralizes safe **reading + normalization** of
the existing per-user settings blob. **This is an accessor seam, not a persistence
change** — stored format, localStorage keys, cloud payloads, account namespaces,
sync/dirty/save behavior, defaults, and UI are all unchanged (full suite 17/17;
cards/IDs/importer/baseline/SRS/CardRepository all identical to
`production-baseline-v1`).

- Phase 3 anchor (rollback): `fc2960f`
- Phase 4 = the commit introducing this document.

## Module
`hsk_flashcard_app/core/settings/settings-repository.js` — classic script, no
bundler/ESM/TS. Path mirrors Phase 3's `core/cards/`. Extends the platform
namespace `window.HSKUtil`.
- `HSKUtil.createSettingsRepository(provider, config?)` — factory.
- `HSKUtil.settings` — shared instance for consumers **outside** app.js.

Load order (`index.html`): `data.js` → `core/util/*` → `core/cards/card-repository.js`
→ **`core/settings/settings-repository.js`** → `supabase-config.js` → `auth.js` →
`app.js` → `sync.js` → `test.js` → `metadata.js` → `insights.js`.

## Read-only contract
No `save/set/update/patch/delete/markDirty/sync/push/pull`. The repository never
mutates the source settings object or its arrays, never writes localStorage, never
marks dirty, never schedules sync, never creates storage. The **existing write path
is untouched**: `app.js saveSettings()` → `HSKSync.onSettingsChanged()`, all
onchange handlers, `metadata.js persist()`, and `sync.js` push/pull continue exactly
as before. The repository only *observes* the results of those writes.

## Provider / lifecycle (the key design point)
Unlike `CardRepository` (a frozen singleton over the stable `HSK_CARDS` array), the
active settings object is **not stable for the page lifetime**:
- **Cloud pull** → `app.js reloadState()` **reassigns** `settings = JSON.parse(...)`
  (`app.js:471`) and `sync.js:149` triggers it.
- **Login / logout / account-switch / account-delete** → `location.reload()`
  (`auth.js` 247 / 319 / 342) → fresh module, `settings` re-read from the new
  namespaced key.

So the repository captures a **`provider()` thunk, never a specific object**, and
re-reads it on every call. No stale cache can survive an account change.

- **Inside `app.js`:** a private instance `createSettingsRepository(() => settings)`.
  The closure tracks the live `let settings` binding, so it (a) observes
  `reloadState()` reassignment and (b) works during the first `renderHome()` — which
  runs *before* `window.HSK_APP` is assigned (`app.js:444` vs `:447`).
- **Outside `app.js`:** the shared `HSKUtil.settings` reads
  `() => (window.HSK_APP && HSK_APP.getSettings()) || {}`. `insights.js` loads after
  `app.js`, so the bridge always exists by the time it renders.

**Account-switch behavior:** because switches reload the page, each account gets a
brand-new module and a brand-new provider closure over that account's blob — there
is no cross-account carry-over by construction. The unit suite additionally proves
the provider reflects a swapped active object with no stale read (A→B→A).

## API (signatures & exact normalization)
`config` overrides the built-in `DEFAULTS` (current HSK product values from
`DATA_CONTRACTS.md §3`); every default is the *existing* fallback, nothing speculative.

| Method | Rule (reproduces current runtime expression) |
|---|---|
| `getAll()` | current live settings object (same ref app exposes via `getSettings()`); read-only, not cloned |
| `get(key, fallback)` | `v == null ? fallback : v` — **preserves explicit `false` / `0` / `""`**; `undefined`/`null` → fallback |
| `has(key)` | `hasOwnProperty(key)` |
| `getSelectedLevels()` | `Array.isArray && .length ? selectedLevels.slice() : ["HSK1"]` — returns a **copy** (source array never exposed) |
| `getSessionSize()` | `sessionSize \|\| "20"` |
| `getSpeechRate()` | `[0.5,0.75,1,1.25,1.5].indexOf(Number(v))>=0 ? Number(v) : 1` — identical to `normSpeechRate` |
| `getFrontPinyinEnabled()` | `showFrontPinyin !== false` (undefined ⇒ true) |
| `getAutoReadWordEnabled()` | `!!autoReadWord` |
| `getAutoReadExampleEnabled()` | `!!autoReadExample` |
| `getStreak()` | `streak \|\| 0` |
| `getDarkEnabled()` | `!!dark` |

### Default / normalization policy
Missing settings object ⇒ treated as `{}` (behaves as today). Missing field ⇒ current
fallback. `undefined`/`null` follow current semantics. Invalid/legacy speech rates
(`0.7`, `0.85`, `3`, `"fast"`) → `1`. Legacy blobs load unchanged. Unknown additive
keys are readable via `get()`/`has()` and are never dropped (the write path still owns
them verbatim). A returned array is always a copy; the source is never mutated.

## Migrated read sites (10)
| File | Was | Now |
|---|---|---|
| `app.js` decl | — | `const settingsRepo = HSKUtil.createSettingsRepository(() => settings)` |
| `app.js` `renderHome` | `settings.sessionSize \|\| "20"` | `settingsRepo.getSessionSize()` |
| `app.js` `renderHome` | `normSpeechRate(settings.speechRate)` | `settingsRepo.getSpeechRate()` |
| `app.js` `renderHome` | `!!settings.autoReadWord` | `settingsRepo.getAutoReadWordEnabled()` |
| `app.js` `renderHome` | `!!settings.autoReadExample` | `settingsRepo.getAutoReadExampleEnabled()` |
| `app.js` `renderHome` | `settings.showFrontPinyin!==false` | `settingsRepo.getFrontPinyinEnabled()` |
| `app.js` `renderHome` | `settings.streak\|\|0` | `settingsRepo.getStreak()` |
| `app.js` `applyPinyinDisplay` | `settings.showFrontPinyin !== false` | `settingsRepo.getFrontPinyinEnabled()` |
| `app.js` `renderCard` | `if(settings.autoReadWord)` | `if(settingsRepo.getAutoReadWordEnabled())` |
| `app.js` `flipCard` | `if(settings.autoReadExample)` | `if(settingsRepo.getAutoReadExampleEnabled())` |
| `insights.js:143` | `(HSK_APP && HSK_APP.getSettings().streak) \|\| 0` | `HSKUtil.settings.getStreak()` |

## Deferred (documented, unchanged)
- **Bootstrap reads** `app.js:14` (`selectedLevels` module init), `:27`
  (`speech.rate` init), `:436` (`if(settings.dark)` theme at load) — run before
  `HSK_APP`/DOM lifecycle is meaningful; left as direct reads.
- **Write / read-modify-write** `updateStreak` (`:173-177`), `startStudy`
  save (`:182`), all onchange handlers (`:382,424-427,435`), and level-picker writes
  (`:138,160`) — these persist; out of a read-only phase.
- **Lifecycle** `reloadState()` (`:470-476`) — it *is* the reassignment source the
  provider observes; not a consumer to migrate.
- **`metadata.js` (entire)** — bookmarks/notes/daily aggregates are read-**and**-write
  through a shared `S()`/`persist()` pair; migrating the reads would entangle the
  write path. Deferred to a BookmarkRepository/NoteRepository phase.
- **`sync.js` / `auth.js` settings touches** — cloud read/write + account snapshot;
  owned by the sync/auth layer.
- **`test.js`** — does not read the settings blob (no change needed).
- Repo methods `getAll/get/has/getDarkEnabled/getSelectedLevels/getSessionSize` are
  tested and available but only wired where a proven-equivalent consumer exists.

## Dependency direction
`ui/app/insights → SettingsRepository → provider → (live settings blob)`. The repo is
DOM-free, storage-free, network-free. Settings **key names** (e.g. `showFrontPinyin`)
are stored-preference identifiers, not card content; no card fields, pinyin/Vietnamese
values, or HSK card totals live in the core. Product **defaults** (`["HSK1"]`, the
rate list, `"20"`) are the current values and are `config`-overridable for a future
FlashEdu product.

## Performance
- Repository built **once** per module (app.js private instance; shared
  `HSKUtil.settings`) — never rebuilt per render or per card.
- Each read is a single provider call + one property read/normalization — no cloning
  of the settings object on render (`getAll()` returns the live ref, matching the
  pre-existing `getSettings()` behavior). Arrays returned by `getSelectedLevels()` are
  small copies only when that method is called.
- No new network calls, no storage writes, no dirty marks. Initial load unchanged.

## Service worker
Bumped **once**: `v11 → v12`; added `core/settings/settings-repository.js` to the
precache `ASSETS`. **Strategy unchanged** (cache-first; existing `activate` removes old
caches). Required so the new offline-shell script is available offline.

## Why write repositories are still deferred
`ProgressRepository`, `Bookmark/Note/AnalyticsRepository`, and a settings **write**
API all touch mutable per-user state + the sync/dirty machinery. Wrapping them changes
the write path and must be characterized separately, not mixed into this read-only
seam. `ContentPack`/`DeckRepository` need the pack model. All are explicitly out of
Phase 4 scope.

## Rollback
Phase 4 is independently reversible.
1. `git revert <phase-4-commit>` on `architecture-v2` — restores the inline
   `settings.*` reads, removes the repo `<script>` tag and the app.js `settingsRepo`
   decl, reverts `insights.js:143`, and reverts `sw.js` to `v11`.
2. Or manual: `git checkout fc2960f -- hsk_flashcard_app/app.js hsk_flashcard_app/insights.js hsk_flashcard_app/index.html hsk_flashcard_app/sw.js tests/run_regression.py`,
   then delete `hsk_flashcard_app/core/settings/` and `tests/browser/test_settings_repository.py`.
3. Re-run `python tests/run_regression.py` — expect 16/16 after full rollback (Phase 4
   suite removed).
4. Phase 1/2/3 fixtures, baselines, and the `production-baseline-v1` tag are preserved.

## Recommended Phase 5 scope (do not begin)
**Read-only characterization of session/due-card selection** (the `dueCards` / `learned`
/ `fresh` / `fallback` reads deferred in Phase 3), producing a documented, tested
read-only `SessionQuery` seam over `CardRepository` + progress — **without** extracting
SRS scheduling or session state. This is the next read-only boundary and the natural
precursor to a future `ProgressRepository`. Defer all write-path repositories,
`metadata.js`, `sync.js`, and content-pack work.
