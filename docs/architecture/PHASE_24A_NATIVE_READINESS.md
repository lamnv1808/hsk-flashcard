# Phase 24A — Runtime Native-Readiness

Prepares the existing web runtime for a FUTURE locally-bundled Capacitor shell. **No Capacitor
project, no dependency, no native build, no store work.** Web/PWA behavior is preserved exactly.

## Scope (four tightly-scoped changes)
1. **Platform adapter** (`core/platform/platform.js`) — the single web↔native seam.
2. **Service-worker registration routed through the adapter** (web registers; native no-op).
3. **Stop active speech when the app is backgrounded/hidden.**
4. **Replace `prompt()` PIN flows** (change-PIN, delete-account confirm) with an accessible in-DOM modal.

## Platform adapter (`window.HSKUtil.platform`)
- `isNative()` — capability detection via `window.Capacitor?.isNativePlatform?.()`; safe `false` on plain web; never imports Capacitor, never assumes it exists, never throws.
- `platform()` — `"web" | "ios" | "android"` (web is the default; only a native Capacitor shell overrides).
- `registerServiceWorker(path)` — web/PWA: registers `sw.js` exactly as before (relative path, errors swallowed); native: returns without registering (bundled assets; WKWebView SW is unreliable). Never throws (guards missing `serviceWorker`, throwing `register`).
- `onBackground(cb)` — fires `cb` only when the document becomes **hidden** (`visibilitychange`), not on return-to-visible; returns an unsubscribe fn. Compatible with a future Capacitor `App.appStateChange({isActive:false})` bridge.
Contains no learning-domain logic, storage, network, or Back/TTS/secure-storage/share adapters (deferred).

## app.js integration
`navigator.serviceWorker.register("sw.js")` → `HSKUtil.platform.registerServiceWorker("sw.js")`; plus one `HSKUtil.platform.onBackground(stopSpeech)`. Backgrounding cancels speech and clears the speaking UI via the existing `stopSpeech()` path; returning to foreground never auto-plays. No change to renderCard/flip/grade/skip/state-machine/answer-leak/auto-read/spoken-content/rate/audio buttons/keyboard/Daily-Goal/streak/completion/targeted-continuity.

## PIN modal (auth.js)
One reusable accessible modal (`openPinModal`) replaces `prompt()` for **change-PIN** and **delete-account confirm** only. It reuses the existing `.auth-gate`/`.auth-card`/`.auth-input`/`.auth-label`/`.auth-msg` styling.
- **Preserved exactly:** Edge Function names (`change-pin`, `delete-account`), payload shapes (`{oldPin,newPin}` / `{pin}`), `validPin` (`/^\d{4}$/`), error meaning, `alert()` success feedback, delete's `localLogout()`+reload, login/register, storage, account isolation, lockout (server-side).
- **PIN fields:** `type=password`, `inputmode="numeric"`, `maxlength=4`; change-PIN has current/new/confirm; delete has current-PIN + destructive warning.
- **Security:** PIN values never logged, never inserted via `innerHTML`, never placed in storage/URL/dataset/title/error text; **cleared on every close** (cancel/Escape/success). Verified: PIN string not present in `localStorage`.
- **Accessibility:** `role="dialog"` + `aria-modal="true"` + labelled heading; real `<label for>`; intentional initial focus (first field); focus trap (Tab cycles); Escape cancels (no request); focus restored on close (to the active element at open — `body`, since the profile menu self-hides first — never trapped/lost); errors in an `aria-live="assertive"` region; ≥44px buttons; background interaction blocked (`body.auth-locked`).
- **No reachable `window.prompt()` remains** for these two flows (grep-verified; only comment references remain).

Behavior contract: `onSubmit(values)` returns an error **string** to keep the modal open (no server request made), or falsy on success (modal closes). Invalid PIN / new-PIN mismatch → error shown, **zero** requests. Server failure → error meaning shown, modal stays open.

## HTML / CSS
`index.html`: one `<script src="core/platform/platform.js">` before `app.js`. `styles.css`: modal-only additions (`.pin-modal-actions`, `.pin-danger` — 4 rules); everything else reuses existing auth styles. No layout change outside the modal; verified no horizontal overflow and Study one-screen unchanged at 360×800/375×667/390×844/1366×768, light + dark.

## Service Worker
Cache **v33 → v34**; added exactly one new precache asset `core/platform/platform.js` (must work offline). All existing assets, fetch/install/activate behavior, and cache strategy unchanged.

## Tests
`tests/regression/platform_adapter.py` (registered → **33/33**): adapter present; `isNative()` false on web + true under a Capacitor stub; `platform()` web/android; web registers SW once (boot + call); native registers none; missing/throwing SW & missing Capacitor never throw; `onBackground` fires on hidden, not visible, unsubscribe works; background clears `body.speaking` (stops speech), foreground does not; PIN modal opens without `prompt` (change-PIN + delete); `role=dialog`/`aria-modal`; invalid/mismatch/Escape/cancel make zero requests; valid change-PIN and valid delete each make exactly one Edge Function request; PIN not stored; focus into modal then safely restored. Full regression **33/33 PASS** (incl. p0 answer-leak, SRS goldens, daily_goal, completion_loop, streak_semantics, targeted_continuity, metadata_sync, auth isolation, offline).

## Files
Changed: `core/platform/platform.js` (new), `app.js`, `auth.js`, `index.html`, `styles.css` (modal only), `sw.js`, `tests/regression/platform_adapter.py` (new), `tests/run_regression.py`, this doc.
Unchanged: SRS/Scheduler, StudySessionEngine/StateMachine/Query, ProgressWriter/Repository, Analytics/UserMetadata queries, `metadata.js` write ownership, `sync.js` transport, `supabase/**`, `data.js`, importer, ContentPack, Test Mode logic, storage keys/schema, cloud payloads, Daily-Goal/streak/`lastLearnDay`, bookmark/note behavior, renderCard/flipCard/answer-leak. **No package.json / Capacitor / native project.**

## Rollback
Branch `phase-24a-native-readiness` off Phase 23 anchor `8e2df1d`. Revert: delete `core/platform/platform.js` + its script tag; restore direct `serviceWorker.register` and drop the `onBackground` line in `app.js`; restore the `prompt()`-based `promptChangePin`/`promptDelete` in `auth.js`; remove the modal CSS; SW v34→v33 (drop `platform.js` from ASSETS); remove the suite + registration + this doc. `git revert <sha>` restores current behavior. No stored user data changes. Regression after rollback: 32/32.
