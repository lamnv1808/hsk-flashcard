# Regression Report — Accounts & Cloud Sync

**Change type:** additive, **config-gated**. With `supabase-config.js` blank (the
committed default), the app behaves **exactly as before**. Accounts + sync only
activate once a Supabase URL + anon key are filled in.

Verified with automated browser tests (headless Chromium): existing features in
local-only mode, and the full account flow against a mocked Supabase backend
(the sandbox cannot reach a real project — live backend testing is done by the
operator via `docs/SUPABASE_SETUP.md`).

## Existing features

| Feature | Status | Notes |
|---|---|---|
| Flashcard flip (tap / Space) | **UNCHANGED** | `spaceFlips: true` |
| HSK1–HSK4 decks | **UNCHANGED** | deck grid intact |
| Mixed HSK selection | **UNCHANGED** | level picker intact |
| Session size | **UNCHANGED** | selector intact |
| Audio / speak (word, example) | **UNCHANGED** | zh-CN only |
| Auto-read | **UNCHANGED** | `autoReadWord` reads word |
| Read-all (no pinyin / no Vietnamese) | **UNCHANGED** | `readAll_noPinyinNoViet: true` |
| Swipe navigation | **UNCHANGED** | left=next, right=prev |
| Mouse drag | **UNCHANGED** | same gesture engine |
| Keyboard (Space/1-4/N/S/Esc) | **UNCHANGED** | all verified |
| Rating → SRS math | **UNCHANGED** | `good` ⇒ interval 3 |
| Previous-card SRS safety | **UNCHANGED** | snapshot revert intact |
| Progress / stats / streak | **UNCHANGED** | same computation |
| Dark mode | **UNCHANGED** | toggles + persists |
| One-screen mobile (375×667) | **UNCHANGED** | `noVScroll: true`, rating in view |
| PWA install | **UNCHANGED** | prompt logic intact |
| Offline assets / service worker | **CHANGED (safe)** | cache v4→v5, adds new JS files, and now **ignores non-GET/cross-origin** so it never touches auth/sync calls. Offline asset serving unchanged. |
| localStorage progress schema | **UNCHANGED** | same per-card shape; keys are namespaced per account **only when logged in**, else identical global keys |

## Files with behavior notes (CHANGED, backward-compatible)

- **`app.js`** — storage keys now fall back to the original global keys when
  `window.HSK_AUTH` is absent (local mode). Added 3 guarded one-line sync hooks
  (`if(window.HSKSync)…`) that are **no-ops** when sync isn't loaded, plus a
  read-only `window.HSK_APP` bridge. No study/SRS logic changed.
- **`index.html`** — 3 `<script>` tags added. In local mode `supabase-config.js`
  is empty, `auth.js` returns immediately, `sync.js` doesn't activate.
- **`sw.js`** — cache bump + precache new files + skip non-GET/cross-origin.

## New-feature verification (mocked Supabase backend)

| Test | Result |
|---|---|
| Local-only mode: no gate, no profile, `HSKSync` undefined | ✅ |
| Configured: Login/Register gate shown | ✅ |
| Register → auto-login → profile button | ✅ |
| Two accounts isolated (separate namespaced stores, different data) | ✅ |
| Logout → gate returns | ✅ |
| Login restores account | ✅ |
| Wrong PIN → generic "Sai tên đăng nhập hoặc mã PIN" (no enumeration) | ✅ |
| 5-fail lockout → 429 message | ✅ |
| Sync pushes **only modified cards** (1 row/push) | ✅ |
| Offline: study works, changes queue, nothing pushed | ✅ |
| Reconnect (`online`) → queue flushes | ✅ |
| Migration prompt on first login; Import merges; **legacy data preserved** | ✅ |
| No page/console errors in any scenario | ✅ |

## Not testable in this sandbox (operator to verify)

Real registration/login/PIN-change/delete/sync against a live Supabase project,
per the checklist in `docs/SUPABASE_SETUP.md` §10.

---

# Follow-up: front-pinyin setting + auth refinements

**All items above remain UNCHANGED** (re-verified). Additional changes this round:

| Area | Status | Notes |
|---|---|---|
| Front vocab pinyin (default ON) | **UNCHANGED** | undefined ⇒ true; existing users see identical front (word + pinyin), back with no vocab-pinyin duplication |
| New setting "Hiển thị Pinyin ở mặt trước" | **NEW** | home *Hiển thị* section; applies immediately; persisted in existing settings blob; per-user synced when logged in |
| Card back (setting OFF) | **CHANGED (opt-in only)** | shows word (col B) + vocab pinyin (col C) at top, then existing meaning/example/example-pinyin/translation. Example pinyin always shown; vocab pinyin never on both sides, never gone |
| Card back (setting ON) | **UNCHANGED** | `#backWordBlock` hidden → identical to production |
| Mobile one-screen (OFF mode) | **UNCHANGED** | page never scrolls; denser back top-aligns + compresses + internal-scroll safety net so the word is never clipped (375×667 verified) |
| Desktop layout | **UNCHANGED** | stable in both modes |
| Audio / auto-read | **UNCHANGED** | Chinese only; never reads vocab or example pinyin or Vietnamese |
| SRS / swipe / drag / keyboard / dark / PWA | **UNCHANGED** | full regression re-run green |
| Auth gate: show/hide PIN | **NEW** | "Hiện mã PIN" toggles PIN field type; numeric inputmode + Enter-submit unchanged |
| Display username | **CHANGED (additive)** | original case preserved for display; lowercase still used for uniqueness/login/HMAC. `profiles.display_username` added (idempotent `alter ... add column if not exists`) |
| Service worker | **CHANGED (safe)** | cache v5→v6 (HTML/JS/CSS changed); still ignores non-GET/cross-origin → never caches auth/sync |

### Verified (headless Chromium)
- Local mode: pinyin ON → front pinyin visible, back block hidden; OFF → front hidden, back shows word+vocab-pinyin, example pinyin still visible, word==backWord, pinyin==backPinyin, not duplicated. No console errors.
- Mobile 375×667 OFF: page no-scroll, back word fully inside the card (not clipped).
- Configured (mock): show/hide PIN toggles type; display username `Minh_An` preserved with id `u-minh_an`; two accounts have distinct namespaced settings keys (pinyin preference isolated).
- Auth/offline/migration suites all still green.
