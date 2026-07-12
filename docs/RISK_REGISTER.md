# RISK REGISTER (Phase 0)

Ranked by (likelihood × impact). Each risk: **likelihood · impact · detection ·
mitigation · rollback.** L/M/H scale.

## Top 5 (highest priority)

### R1 — Card-ID instability
- **Likelihood:** M · **Impact:** H (breaks ALL progress, local + cloud join key)
- **Detection:** data-stability test (id count, per-level counts, byte-stable HSK1–4,
  contiguous 1–5002); importer determinism test.
- **Mitigation:** ADR-002 freeze; importer anchors IDs to existing `data.js` via unique
  `(level,word)`; new IDs = `max+1`; adapters never renumber; `(packId,cardId)` only when a
  2nd pack ships with approved migration.
- **Rollback:** revert phase; restore `data.js` from `production-baseline-v1`.

### R2 — Legacy progress / settings incompatibility
- **Likelihood:** M · **Impact:** H (silent data loss / user-visible reset)
- **Detection:** `legacy→canonical→legacy` round-trip byte-identical test; settings
  unknown-key-preservation test; live smoke on a copy of real localStorage.
- **Mitigation:** adapters only; new metadata as new settings keys w/ safe defaults;
  never rename/repurpose keys/columns/RPCs; no schema migration for metadata.
- **Rollback:** revert; on-disk bytes unchanged by design, so no data cleanup needed.

### R3 — Stale service-worker assets after refactor
- **Likelihood:** H (any file move/rename) · **Impact:** H (users stuck on old JS, or
  broken offline)
- **Detection:** SW update-flow test (bump → new asset served → offline still works);
  version-string diff check in CI.
- **Mitigation:** no directory moves early; when moved (Phase 12), do a **single**
  deliberate cache bump + keep `activate` old-cache cleanup + URL aliases; never bump
  cache for docs-only changes.
- **Rollback:** restore previous `sw.js` cache version + asset list + paths.

### R4 — Cross-account data leakage
- **Likelihood:** L · **Impact:** H (privacy/trust; also App-Store blocker)
- **Detection:** two-user isolation tests (distinct namespaced keys; B never sees A's
  progress/bookmarks/notes); RLS policy tests (`auth.uid()` scoping).
- **Mitigation:** keep namespace-by-`::uid` + RLS as the isolation contract; repositories
  are account-scoped by construction; reload on account switch.
- **Rollback:** revert; isolation contract is legacy-frozen so reverting restores it.

### R5 — HSK/Chinese assumptions leaking into "generic" engine
- **Likelihood:** H (they already exist) · **Impact:** M (blocks multi-language; risk of
  half-migrated literals) 
- **Detection:** grep gate for `HSK`/`zh-CN`/`pinyin` literals in `core/` paths; pack-swap
  smoke (a stub non-Chinese pack renders without crashing).
- **Mitigation:** ADR-003 content packs; audio reads `pack.audioRules`; test modes read
  `pack.testModes`; graceful degradation on absent capabilities.
- **Rollback:** revert config-driven reads to literals (kept simple/localized per phase).

## Additional tracked risks

| ID | Risk | L | I | Detection | Mitigation | Rollback |
|---|---|---|---|---|---|---|
| R6 | Sync conflicts (multi-device) | M | M | latest-wins tests; two-device merge smoke | freeze `updated_at`-wins; never overwrite newer | revert |
| R7 | Direct localStorage coupling blocks tests | H | M | grep UI→storage; unit-test feasibility | repositories (ADR-004) | revert to inline access |
| R8 | Animation/state races (next-card leak class) | M | H | P0 leak suite; transform-motion assertion | keep `no-flip-anim`/token/`suppressClick`; centralize in session controller | revert render loop |
| R9 | Importer output drift | L | H | re-run = byte-identical; determinism test | atomic write + validation-before-write; ID anchor | restore generated `data.js` |
| R10 | Over-refactoring / scope creep | M | M | phase stop/go criteria; PR size limits | strangler-fig; one concern/phase; ADR-001 non-goals | revert phase |
| R11 | Insufficient regression coverage | M | H | coverage vs FEATURE_INVENTORY | Phase-1 characterization tests before any change | pause plan |
| R12 | App-Store privacy/account rules (username+PIN, data export/delete) | M | H | policy checklist; delete-account/export tests | keep delete-account + export; document data handling; may need email/OAuth for stores | n/a (product decision) |
| R13 | Future school multi-tenancy | L | M | design review | `(packId,cardId)` + tenant/client config planned, not built | n/a |
| R14 | `.temp` Supabase CLI files tracked in repo | M | L | secrets scan (done: no secret keys; contains project-ref + password-less pooler URL) | gitignore + `git rm --cached` in a follow-up hygiene commit | restore files |
| R15 | Anon key/public config in repo | L | L | secrets scan | anon key is public by design + RLS; keep service_role/pepper only in Edge secrets | rotate if ever mis-scoped |

## Notes from the Phase-0 secrets scan
No service_role key, DB password, or `PIN_PEPPER` value is tracked. `supabase-config.js`
holds the **public** anon key (safe). `supabase/.temp/*` holds project ref + a
password-less pooler URL + version strings — already on public `main`; **flagged R14**
for a hygiene follow-up (not a Phase-0 change).
