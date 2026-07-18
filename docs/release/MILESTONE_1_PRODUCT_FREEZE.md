# Milestone 1 — Product Freeze

## Objective & non-goals
Freeze the exact FlashEdu product that ships for Milestone 1 and add read-only release tooling.
**Phase 24B changes tooling and documentation only** — no production behavior, UI, learning logic,
runtime asset, storage, sync, auth, service-worker, or Supabase change. The service worker was
`hsk-flashcards-v35` at the time of Phase 24B; it is **`hsk-flashcards-v36`** since Phase 24C
bumped it exactly once. Phase 24D did not change it.

## Milestone 1 Definition of Done
FlashEdu is **approved and publicly available on BOTH the Apple App Store and Google Play**. A local
Capacitor build, TestFlight build, Play closed test, a merely-submitted app, or any web/PWA deploy
does **not** complete Milestone 1.

## Frozen must-ship scope (all currently implemented & regression-covered)
- HSK1–HSK6 bundled content (5,002 cards)
- Study Mode with the existing SRS (Again / Hard / Good / Easy), skip, undo/previous, swipe + keyboard
- Front/back **answer-leak protection** (P0 gate)
- Chinese word + example **audio** (zh-CN only; never pinyin/Vietnamese) — incl. Hotfix 24.1: the back
  always shows the Hanzi + pinyin and both are a click-to-speak target that reads the word once
- Level mixing + session-size selection
- Test Mode
- Weak Words, Bookmarks, Notes, Insights (daily chart)
- Daily Goal + corrected local-day streak semantics
- Completion breakdown + Keep Going + targeted-review return continuity (Weak Words / Bookmarks)
- Local-only mode; account auth (username+PIN) + cloud sync + account isolation; in-app account deletion
- Dark mode; responsive mobile layout; offline learning (PWA app shell + Study)

These must **not** be degraded on native: Study, SRS, account deletion, offline learning, notes,
bookmarks, progress persistence, answer-leak protection.

## Permitted native degradation (only with device evidence a browser API is unreliable)
- **PWA install prompt** — hidden in native (never fires there); harmless.
- **Export-to-JSON** — may use a native Share/Filesystem fallback, or be hidden, if `<a download>` is
  unreliable in the WebView.
- **SpeechSynthesis TTS** — may receive a Capacitor TTS fallback in Phase 26 *only if* device testing
  shows WKWebView/Android gaps; the zh-CN-only / no-leak contract is preserved either way.

## Deferred to Milestone 2 (out of scope now)
Multi-pack library beyond the three launch options; plugin architecture; teacher/school platform;
AI learning layer; unrelated UI redesign; framework migration (React/Flutter/React Native).

> **Superseded (Phase 24D):** this list previously deferred the *generic Excel→ContentPack
> pipeline* and the *dynamic pack registry/loading* to Milestone 2. Milestone 1 requires HSK,
> IELTS and TOEIC as three real study options, which requires a way to ingest that content, so
> the pipeline is Phase 24D (build-time only, shipped) and the registry is Phase 24E — both
> inside Milestone 1. See `docs/architecture/PHASE_24C_CONTENT_PACK_V1.md` and
> `docs/architecture/PHASE_24D_CONTENT_PACK_PIPELINE.md`. The freeze rules below are unaffected:
> Phase 24D changes no runtime file.

## Freeze rules (after Phase 24B)
Until Milestone 1 ships, only these changes are allowed on the web product: release blockers, native
compatibility fixes, privacy/security/store-compliance, store-review fixes, and crash/data-loss/
accessibility fixes. No unrelated product features.

## Phase 25 entry gates
Phase 25 (Capacitor shell) cannot fully start until: Phase 24B is merged & deployed; regression stays
green; the product freeze is accepted; and the owner decisions in `STORE_RELEASE_DECISIONS.md` for app
name, bundle/application ID, iOS build path (Mac or macOS CI), JDK + Android Studio/SDK installed,
Apple/Google account status, and privacy/support/account-deletion URLs are resolved. No Capacitor
files / `package.json` / native project are created in Phase 24B.
