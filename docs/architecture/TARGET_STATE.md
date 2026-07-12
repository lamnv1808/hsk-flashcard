# TARGET STATE (Phase 0, proposed — NOT yet moved)

The proposed modular-monolith layout for **Flashcard Learning Platform Core**. This
is a destination, reached by the reversible phases in `PHASE_PLAN.md`. **No files are
moved in Phase 0.** Static, no-mandatory-build hosting is preserved; ES modules are
adopted only if a phase proves it keeps offline/PWA working.

## 1. Proposed target tree

```
/
├─ app/                              # the deployable web app (was hsk_flashcard_app/)
│  ├─ index.html
│  ├─ styles/                        # theme tokens + component CSS (split later)
│  ├─ core/                          # GENERIC engine (DOM-free, pack-agnostic)
│  │  ├─ domain/
│  │  │  ├─ srs.js                   # scheduler (pure): (state, grade) -> state
│  │  │  ├─ session.js               # session construction + navigation policy
│  │  │  ├─ testEngine.js            # MCQ generation mechanics (config-driven)
│  │  │  └─ analytics.js             # weakness score, aggregates (pure)
│  │  ├─ repositories/               # interfaces (ADR-004)
│  │  ├─ adapters/                   # legacy<->canonical (DATA_CONTRACTS §9)
│  │  ├─ sync/                       # dirty-set, debounce, latest-wins (SYNC_CONTRACT)
│  │  └─ util/                       # date/day, id-map, shuffle, level-order
│  ├─ services/
│  │  ├─ auth/                       # session lifecycle, gate/profile
│  │  ├─ audio/                      # TTS engine (reads pack audioRules)
│  │  └─ platform/                   # config gate, service worker, PWA, feature flags
│  ├─ ui/                            # PRESENTATION only (views, gestures, keyboard, chart)
│  │  ├─ study/  test/  insights/  bookmarks/  notes/  home/  shell/
│  ├─ packs/                         # CONTENT PACKS
│  │  └─ hsk/                        # data.js (generated) + manifest.json + adapter
│  ├─ config/
│  │  └─ client.default.json         # white-label: pack(s), theme, features, supabase
│  └─ boot.js                        # composition root (wires repos+services+ui)
├─ packs-source/                     # was source_data/ (xlsx + importer inputs)
├─ tools/                            # was scripts/ (importer, pack validator)
├─ backend/                          # was supabase/ (schema, functions) — unchanged contract
├─ tests/                            # characterization + regression (added Phase 0)
└─ docs/
```

> Note: physical moves change served URLs and the SW asset list. Because
> **"preserve current URLs where practical"** and **PWA cache stability** are
> constraints (RISK_REGISTER), directory moves are scheduled **late** and done with a
> redirect/alias + a single deliberate SW cache bump. Early phases add `core/` modules
> *alongside* the current files without relocating them.

## 2. Module ownership & public interfaces

- `core/domain/*` — pure, no DOM/storage/network, no `HSK`/`zh` literals. Public: the
  functions in ADR-004/DATA_CONTRACTS. Owner: platform team.
- `core/repositories` + `core/sync` — the only storage/network gateways. Public:
  repository interfaces. Owner: platform team.
- `services/*` — auth, audio, platform. Public: small service facades.
- `ui/*` — depends inward on Application/use-cases and services; **never** on storage.
- `packs/*` — implement `CONTENT_PACK_STANDARD.md`; depend on nothing internal.
- `config/*` — white-label selection; depended on by `boot.js` + `ui` theming.
- `boot.js` — the composition root; the only place that knows concrete implementations.

## 3. Allowed dependencies
`ui → application → domain`; `application → repositories(interfaces)`;
`sync/auth/audio/platform` are leaf services; `packs → content standard only`;
`config → consumed by boot + ui theme`. No inward layer imports `ui`. (See
`DOMAIN_BOUNDARIES.md`.)

## 4. White-label configuration (target)
`config/client.<name>.json`:
```jsonc
{ "clientId":"acme-school","packs":["hsk"],"theme":{"--accent":"#0a7","logo":"…"},
  "features":{"test":true,"analytics":true,"bookmarks":true,"notes":true},
  "supabase":{"url":"…","anonKey":"…"} }
```
A build/boot selects one client config → picks packs, theme tokens, enabled features,
and backend. No engine change per client.

## 5. Mobile readiness
Because `core/*` and `services/*` are DOM-free (or DOM-optional), a Capacitor/WebView
shell (or later native) reuses them directly; only `ui/*` gains platform shells. No
domain rewrite.

## 6. Explicit non-goals (kept simple)
No microservices, no runtime plugin loader, no framework mandate, no new backend/DB,
no big-bang rewrite. Complexity is added only when a concrete pack/client/mobile need
justifies it.
