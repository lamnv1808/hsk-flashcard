# Store Release — Owner Decision Checklist

Each item below is an owner input required before native/store work. **Status `REQUIRED` = not yet
decided.** No placeholder or fake production value is recorded here, and none is written into the live
application. Do not guess these — fill them in deliberately.

| # | Decision | Status | Notes |
|---|---|---|---|
| 1 | Final public **app name** | REQUIRED | Shown in stores + on device |
| 2 | Apple **bundle ID** (e.g. reverse-DNS) | REQUIRED | e.g. `com.<owner>.flashedu` — owner chooses |
| 3 | Android **application ID** | REQUIRED | Usually matches the bundle ID |
| 4 | **Apple Developer Program** account | REQUIRED | Individual vs organization; $99/yr; membership status unknown |
| 5 | **Google Play Console** account | REQUIRED | $25 one-time; personal-account closed-testing rule may apply |
| 6 | **Privacy-policy URL** (public) | REQUIRED | Required by both stores; must be live before submission |
| 7 | **Support URL** (public) | REQUIRED | Required for listings |
| 8 | **Public account-deletion URL** | REQUIRED | Google Play requirement; in-app deletion already exists (auth.js) |
| 9 | **Release countries / regions** | REQUIRED | Availability scope |
| 10 | **Supported store languages** | REQUIRED | App UI is Vietnamese; listing locales TBD |
| 11 | **iOS build path** | REQUIRED | Physical Mac + Xcode, or macOS CI (GitHub Actions / Codemagic / Appflow) — no Mac on the current Windows machine |
| 12 | **Android toolchain** | REQUIRED | Install JDK + Android Studio/SDK (absent locally) |
| 13 | **Test devices** | REQUIRED | ≥1 physical iPhone + ≥1 physical Android |
| 14 | **Tester identities** | REQUIRED | Needed for Play closed testing / TestFlight |
| 15 | **Developer / seller display name** | REQUIRED | Shown on store listings |

## Security & privacy prerequisites (Phase 27 owner tasks)
- Publish a **privacy policy** (data collected: username, learning progress/settings; stored in
  Supabase under RLS). File Apple **App Privacy** + Google **Data Safety**.
- Confirm the shipped `supabase-config.js` contains only the **public anon key** (it does; protected by
  RLS). No service_role key / PIN pepper is in the client (they live only in Edge Function secrets).
- Provide the public **account-deletion URL** (#8) in addition to the existing in-app deletion.
- Consider moving auth tokens from `localStorage` to platform secure storage (Keychain/Keystore) as a
  Phase 27 hardening item (not a blocker).

> **Store-policy note:** Apple App Review Guidelines and Google Play requirements (target-API level,
> account-deletion, Data Safety, privacy) change over time and must be **re-verified against the live
> official pages at implementation time** (Phase 27/29). This file records decisions, not policy text.
