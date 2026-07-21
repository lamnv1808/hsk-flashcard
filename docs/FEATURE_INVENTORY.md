# FEATURE INVENTORY (Phase 0)

Every production feature, traced to real runtime code. Columns: **Behavior** ·
**Source** · **In-memory state** · **Storage** · **Cloud** · **Compat contract** ·
**Regression before extraction**.

| Feature | Behavior | Source file(s) | State | Storage | Cloud | Compatibility | Regression gate |
|---|---|---|---|---|---|---|---|
| **Content HSK1–HSK6** | 5,002 cards, 6 levels, auto-detected | `data.js`, `scripts/import_hsk_excel.py` | `cards`, `LEVELS` | — | — | **Card IDs 1–5002 immutable**; schema fixed | ID count + per-level counts + byte-stable HSK1–4 |
| **Excel import** | Regenerate `data.js` from xlsx, preserve IDs | `scripts/import_hsk_excel.py` | — | `data.js` | — | Deterministic, ID-preserving, atomic write | Re-run = byte-identical; missing source = safe fail |
| **Register** | username + 4-digit PIN → account + auto-login | `auth.js`, `functions/register` | `HSK_AUTH` | `hsk_session`,`hsk_current_user` | `profiles`, Auth user | HMAC-pepper cred, unique username | Register `test`/`1234` → gate closes |
| **Login** | username + PIN, rate-limited, no enumeration | `auth.js`, `functions/login` | `HSK_AUTH` | `hsk_session`,`hsk_current_user` | Auth token | 5 fails/15-min lock; generic error | Wrong PIN generic msg; 6th = 429 |
| **Logout / Switch** | clears session token + in-memory, reload | `auth.js` | `HSK_AUTH` | removes `hsk_session`,`hsk_current_user` | — | Never erases cloud data | Logout → gate; relogin restores |
| **Change PIN** | verify old, set new via Edge Fn | `auth.js`, `functions/change-pin` | — | — | Auth `updateUserById` | Old-PIN required | Change → login with new PIN |
| **Delete account** | verify PIN, cascade delete | `auth.js`, `functions/delete-account` | — | clears local | Auth + cascaded rows | Only that account | Deleted account cannot log in |
| **Config-gated rollout** | blank `SUPABASE_CONFIG` ⇒ local-only, no chooser at all | `supabase-config.js`, `auth.js` | `HSK_AUTH.configured` | base keys | — | Existing local users unaffected | Blank config → no gate, app works |
| **No-account choice** | configured deploy offers Đăng nhập / Đăng ký / "Học không cần tài khoản"; the third studies with base keys, no session, no sync, no request, and survives reload incl. offline | `auth.js` (`chooseLocalOnly`, `buildAccountCta`) | `HSK_AUTH.localOnly` | `hsk_auth_mode_v1="local"` (never a session/identity) | — | Never an implicit bypass: a context with no recorded choice is still asked; login/register clears the preference | Fresh ctx → chooser with 3 actions; choose → base keys + 0 backend calls; reload/offline reload → no gate; login → preference cleared + `::uid` keys |
| **Cloud sync** | local-first, changed-only push, latest-wins | `sync.js` | dirty set, meta | `hsk_sync_*::uid` | RPCs, tables | See `SYNC_CONTRACT.md` | Grade → 1-row push; pull merges newer |
| **Offline queue** | queue while offline, flush on reconnect | `sync.js` | dirty set | `hsk_sync_dirty::uid` | RPCs on reconnect | Never lose local edits | Offline grade → queued → flush |
| **Legacy migration** | one-time optional import of legacy local progress | `sync.js` (`maybeMigrateLegacy`) | — | `hsk_import_done::uid` | settings/progress push | Never delete/overwrite newer | First login prompt; local preserved |
| **SRS grading** | Again/Hard/Good/Easy → interval/due/reps | `app.js` (`gradeCard`) | `progress`, `snapshots` | `hsk_flashcard_progress_v2[::uid]` | `card_progress` | Field names + meanings frozen | `good` on fresh ⇒ interval 3; revisit no double-count |
| **Study Mode** | flip, grade, next/skip, previous | `app.js` (`renderCard`,`flipCard`,`swipe*`) | `session`,`current`,`flipped` | — | — | **No next-card answer leak** | P0 leak suite (grade/click/swipe/rapid) |
| **Session build** | due + fresh by selected levels + size | `app.js` (`startStudy`) | `session` | reads progress | — | Unchanged selection semantics | Level/size combinations |
| **Test Mode** | 6 MCQ types, no retry, scoring, results/review | `test.js` | own state | `hsk_test_history[::uid]` (local) | — | **No SRS/progress writes** | All 6 types, isolation, no leak |
| **Weak Words** | rank struggling cards, filter, study them | `insights.js` | reads `progress` | — | — | Read-only analysis | Ranking, excludes untouched, study launch = only studyView |
| **Smart Review** | insight dashboard + insufficient-data state | `insights.js` | reads `progress`,`settings` | — | — | Read-only | Values match data; "Chưa đủ dữ liệu" |
| **Daily chart** | words learned/day, 7/30, SVG | `insights.js`, `metadata.js` | reads `dailyCounts` | `settings.dailyCounts`,`todayLearn` | settings blob | Once/card/local-day; Study only | Grade increments once; Test excluded |
| **Bookmarks** | per-card star + page + study saved | `metadata.js`, `insights.js` | reads `settings.bookmarks` | `settings.bookmarks[]` | settings blob | Per-account, no SRS effect | Toggle persists; account-isolated |
| **Notes** | back-side per-card note editor | `metadata.js` | reads `settings.notes` | `settings.notes{}` | settings blob | Back-only; empty = no clutter; ≤1000 | Save/edit/delete-by-empty; never on front/Test |
| **Audio / auto-read / Read-All** | zh-CN word/example, speeds, indicator | `app.js` (`speak*`) | `speech` | `settings.speechRate/autoRead*` | settings blob | Chinese-only; never pinyin/Vietnamese | Speak word/example; readAll; 5 speeds |
| **Front-pinyin preference** | show/hide vocab pinyin front↔back | `app.js` (`applyPinyinDisplay`) | reads `settings.showFrontPinyin` | `settings.showFrontPinyin` | settings blob | Default on; back always keeps example pinyin | On/off; per-account |
| **Swipe / mouse-drag** | left=next, right=prev, thresholds | `app.js` (pointer handlers) | `drag`,`suppressClick` | — | — | No accidental flip | Swipe both dirs; drag |
| **Keyboard** | Space/1-4/N/S/Esc (Study), Test shortcuts | `app.js`, `test.js` | — | — | — | Study/Test isolated | All shortcuts per mode |
| **Dark mode** | toggle, persists | `app.js` (`themeBtn`) | body class | `settings.dark` | settings blob | — | Toggle persists |
| **Responsive / one-screen** | mobile study fits `--app-h` | `styles.css`, `app.js` | `--app-h` | — | — | No horizontal overflow | 375/390/360 fit |
| **PWA / offline** | installable, offline shell | `manifest.webmanifest`, `sw.js`, `icons` | — | Cache API | — | SW cache-first; update on version bump | Install; offline load |

## Cross-cutting compatibility invariants (must hold through every phase)

1. Card IDs are the join key for all progress (local + `card_progress.card_id`). **Never renumber.**
2. `progress[id]` shape `{due,interval,reps,correct,attempts}` and their meanings are frozen.
3. `settings` is a single synced JSON blob; new metadata is added as **new keys with safe defaults**, never by repurposing existing keys.
4. Storage-key names (base + `::uid` namespacing) are the account-isolation contract.
5. Supabase schema, RLS, RPC signatures, and Edge-Function contracts are frozen until an approved migration.
