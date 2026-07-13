# DOMAIN BOUNDARIES (Phase 0)

The target modular monolith — **Flashcard Learning Platform Core** — separates ten
concerns. This maps each to today's code and states the allowed dependency
directions. Nothing is moved in Phase 0; this is the contract the phases work toward.

## 1. The ten layers

| # | Layer | Owns | Today lives in | Generic or product-specific |
|---|---|---|---|---|
| 1 | **Presentation** | DOM render, views, gestures, keyboard, chart | `index.html`, `styles.css`, render fns in `app.js`/`test.js`/`insights.js`/`metadata.js` | generic + theme |
| 2 | **Application / use-cases** | Study session, Test session, "study these IDs", grade, navigate | `startStudy`,`gradeCard`,`renderCard`,`startSession`,`test.js` flow | generic |
| 3 | **Learning domain** | SRS scheduler, weakness scoring, session policy | `gradeCard` math, `insights.js` `weakness()` | **generic** (must be pack-agnostic) |
| 4 | **Content / data** | Cards, decks, levels, packs | `data.js`, `HSK_CARDS` | **product-specific → content pack** |
| 5 | **Persistence & sync** | Repositories, local store, cloud sync | `sync.js`, `save`/`saveSettings`, localStorage access | generic |
| 6 | **Authentication** | Session lifecycle, gate, profile | `auth.js`, Edge Functions | generic |
| 7 | **Audio** | TTS, speeds, indicator | `speak*` in `app.js` | generic engine + **pack audio rules** |
| 8 | **Platform / config** | Config gate, feature flags, service worker, PWA | `supabase-config.js`, `sw.js`, `manifest` | generic |
| 9 | **Branding / theme** | Colors, copy, logo, white-label | CSS vars in `styles.css`, VI strings | **client-specific** |
| 10 | **Content packs** | HSK and future packs implementing the pack standard | `data.js` + importer today | **product-specific** |

## 2. Allowed dependency directions (must point inward)

```
Presentation ─▶ Application ─▶ Learning domain
     │              │                 ▲
     │              ▼                 │
     └────────▶ Persistence/Sync ◀────┘   (domain defines repo INTERFACES; sync implements)
                    ▲
Auth ──▶ Platform/Config ──▶ (everything reads config)
Content packs ──▶ implement Content contract ──▶ consumed by Content/data
Audio: Application ─▶ Audio engine ◀─ pack audio rules
Branding/theme: pure config, depended on by Presentation only
```

Rules:
- **Learning domain depends on nothing** app-specific; it takes `Card`/`UserCardState`
  and returns new state. No DOM, no storage, no `HSK` literals.
- **Presentation may not touch storage directly** (today it does — the key debt to
  remove): it goes through Application → Repository interfaces.
- **Content packs never import engine internals**; they only produce data satisfying
  `CONTENT_PACK_STANDARD.md`.
- **No layer imports Presentation.** Auth/Sync/Platform are leaf services.
- Cyclic runtime coupling (`app ⇄ metadata ⇄ sync` via shared `settings`) is replaced
  by explicit repository calls.

## 3. Where product-specific ends and generic begins

- **Generic (core, reusable across packs/clients/mobile):** SRS, session engine,
  Test-mode engine *mechanics*, repositories, sync, auth, audio engine, analytics
  math, PWA shell.
- **Product-specific (a pack + client config):** the card fields' *language*
  (zh/vi), pinyin/reading system, which Test question types are valid, audio
  language, level naming, branding, copy.

The single most important refactor is making **layer 3 (domain)** and **layer 5
(persistence)** blind to HSK: the domain sees `Card`/`UserCardState`; audio reads a
pack's `audio.lang` instead of the literal `"zh-CN"`; Test Mode reads a pack's
`supportedTestModes` instead of hardcoding six Chinese-shaped types.

## 4. White-label & mobile (how boundaries pay off)

- **White-label:** layers 9 (theme) + 8 (config) + a chosen content pack = a client
  build. No engine change. A `client.config.json` selects pack(s), theme tokens,
  enabled features, and Supabase project.
- **Mobile:** a thin iOS/Android wrapper (Capacitor/WebView or native shell)
  consumes layers 2–7 as the "core"; only layer 1 gets platform-native shells later.
  Because the domain and repositories are DOM-free, they port unchanged.
