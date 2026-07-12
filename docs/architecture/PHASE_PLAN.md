# PHASE PLAN (Phase 0)

Small, reversible phases. Each: **objective · files · runtime risk · rollback ·
regression gate · stop/go · commit boundary.** Phase 0 (this session) is
documentation + tests only. Do **not** combine phases.

Global gate for every phase: full `docs/REGRESSION_BASELINE.md` green + zero console
errors + data-stability checks pass. Rollback for every phase: `git revert` the phase
commit(s) on `architecture-v2`; `main` untouched.

---

### Phase 0 — Audit & Safety Foundation  *(this session)*
- **Objective:** map current state, contracts, target, risks; create executable
  regression baseline. No runtime change.
- **Files:** `docs/**`, `tests/**` (non-runtime). Tag `production-baseline-v1`.
- **Risk:** none (docs/tests only). **Stop/go:** baseline runs green on `architecture-v2`.
- **Commit:** single "Phase 0" commit on `architecture-v2`.

### Phase 1 — Characterization tests (lock behavior)
- **Objective:** turn the manual baseline into repeatable automated checks (Study/SRS,
  Test, sync mock, features, P0 leak, data-stability round-trip).
- **Files:** `tests/**` only. **Risk:** none. **Rollback:** delete tests.
- **Regression gate:** the tests themselves must pass against `production-baseline-v1`.
- **Stop/go:** ≥ the feature-inventory coverage is automated. **Commit:** per suite.

### Phase 2 — Pure utilities extraction
- **Objective:** extract `util/` (date/localDay, level-order sort, shuffle, id-map)
  used identically by `app.js`/`test.js`/`insights.js`/`metadata.js`; remove duplication.
- **Files:** add `core/util/*`; rewire the 4 scripts to call them.
- **Risk:** low (pure fns). **Rollback:** revert; scripts keep inline copies.
- **Regression gate:** unit tests for utils + full baseline. **Stop/go:** byte-identical
  outputs vs old inline logic. **Commit:** one per utility group.

### Phase 3 — Lookup / index modules
- **Objective:** a single `CardRepository`-backed id-map + level index; replace scattered
  `cards.find`/`filter` and per-file `LEVELS` derivations.
- **Files:** `core/repositories/CardRepository` (concrete over `HSK_CARDS`), rewire readers.
- **Risk:** low. **Rollback:** revert. **Regression gate:** level counts, weak/bookmark
  lists, session build unchanged. **Stop/go:** no behavior delta.

### Phase 4 — Repositories & adapters (wrap legacy)
- **Objective:** implement `Progress/Settings/Bookmark/Note/Analytics/Auth` repos as
  thin wrappers over current localStorage + Supabase; adapters for legacy↔canonical.
- **Files:** `core/repositories/*`, `core/adapters/*`; rewire `save`/`saveSettings`/
  `metadata.js` to go through repos. **`sync.js` unchanged** (still the engine).
- **Risk:** medium (write paths). **Rollback:** revert; direct localStorage restored.
- **Regression gate:** round-trip byte-identical; sync push/pull/offline/migration
  suite; account isolation. **Stop/go:** data-stability + sync suites green.

### Phase 5 — Content-pack abstraction (HSK as a pack)
- **Objective:** introduce pack manifest + adapter; audio reads `pack.audioRules.lang`
  instead of literal `"zh-CN"`; display/testModes read pack config. HSK data unchanged.
- **Files:** `packs/hsk/manifest.json`, `core/adapters/cardAdapter`, audio/display/test
  config reads. **Risk:** medium (audio + test generation). **Rollback:** revert to literals.
- **Regression gate:** audio zh-CN only/never pinyin/VN; all 6 test types; pinyin pref.
- **Stop/go:** identical audio + test behavior; no HSK literal left in engine paths touched.

### Phase 6 — Session / use-case extraction
- **Objective:** move Study/Test session construction + navigation into `core/domain/session`
  + `core/domain/testEngine`; `app.js`/`test.js` become thin controllers calling them.
- **Files:** `core/domain/session.js`, `testEngine.js`; controllers rewired.
- **Risk:** medium-high (the flip/swipe render loop + P0 fix live here). **Rollback:** revert.
- **Regression gate:** **P0 answer-leak suite** + Study/Test full + rapid/gesture.
- **Stop/go:** no leak, no double-grade, gestures intact.

### Phase 7 — SRS isolation
- **Objective:** pure `core/domain/srs.js` `(UserCardState, grade) -> UserCardState`;
  `gradeCard` delegates; snapshot/undo stays in the controller.
- **Files:** `core/domain/srs.js`; `gradeCard` rewired. **Risk:** high (schedule/dates).
- **Rollback:** revert. **Regression gate:** interval/due/reps/correct/attempts exactly
  match legacy for all grades + revisit-no-double-count. **Stop/go:** SRS parity tests green.

### Phase 8 — Test Mode isolation
- **Objective:** finish moving Test generation/scoring behind `testEngine` + pack `testModes`.
- **Files:** `test.js` → controller over `core/domain/testEngine`. **Risk:** medium.
- **Regression gate:** all 6 types, distractor/no-leak, scoring, isolation-from-SRS.
- **Stop/go:** Test suite green; zero Study/progress writes.

### Phase 9 — Analytics isolation
- **Objective:** `core/domain/analytics.js` owns weakness score + aggregates; `insights.js`
  becomes presentation. **Files:** analytics module + rewire. **Risk:** low (read-only).
- **Regression gate:** weak ranking, smart-review values, chart counts (once/card/day).

### Phase 10 — UI component boundaries
- **Objective:** split `ui/` by screen (study/test/insights/bookmarks/notes/home/shell);
  remove any remaining UI→storage access. **Files:** `ui/**`, CSS split.
- **Risk:** medium (DOM wiring). **Regression gate:** desktop+mobile layout, one-screen,
  dark mode, no horizontal overflow, no console errors.

### Phase 11 — Theming & white-label config
- **Objective:** `config/client.*.json` selects pack/theme/features/backend; extract theme tokens.
- **Files:** `config/*`, `boot.js`, CSS var tokenization. **Risk:** low-medium.
- **Regression gate:** default client == current look/behavior exactly; a second sample
  client build renders with different theme + feature flags.

### Phase 12 — Mobile readiness (+ late physical move & SW bump)
- **Objective:** verify DOM-free core is embeddable (Capacitor/WebView smoke); perform the
  **single** physical directory move (`hsk_flashcard_app/`→`app/`) with URL alias + **one**
  SW cache bump; confirm offline + update flow.
- **Files:** tree move, `sw.js` (cache version + asset list), redirects. **Risk:** high
  (URLs, SW staleness). **Rollback:** revert move; restore old paths + previous SW version.
- **Regression gate:** PWA install, offline load, SW update reaches clients, all URLs
  resolve (or redirect), full baseline. **Stop/go:** zero stale-cache/URL regressions.

---

## Commit-boundary rules
- One phase = one focused branch off `architecture-v2` (or sequential commits), merged
  to `architecture-v2` only when its gate is green. `main` receives an approved,
  separately-reviewed merge **outside** this plan's automation.
- Never mix a data-shape change with a refactor in the same commit.
