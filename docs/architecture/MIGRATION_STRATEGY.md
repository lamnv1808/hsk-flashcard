# MIGRATION STRATEGY (Phase 0)

How we get from `CURRENT_STATE` to `TARGET_STATE` without breaking production.

## 1. Principles
1. **Characterize before change.** Lock behavior with tests (`REGRESSION_BASELINE.md`)
   before touching any module.
2. **Strangler-fig, inward-out.** Add new `core/` modules *beside* the legacy globals;
   route the legacy code to call them; delete the old path only once green.
3. **Adapters everywhere legacy data is touched** (ADR-002): on-disk/on-cloud bytes
   never change shape until an approved migration.
4. **Small reversible commits.** One concern per phase; each independently revertible.
5. **No URL/SW churn early.** Physical directory moves + the one SW cache bump happen
   in a single late, deliberate phase.
6. **Behavior-preserving until explicitly approved.** No UX/data change ships under the
   banner of "refactor".

## 2. Sequence (see PHASE_PLAN.md for detail)
Safety tests → pure utilities → id-map/lookup → repositories+adapters (wrap legacy) →
content-pack abstraction → session/use-case extraction → SRS isolation → Test-mode
isolation → analytics isolation → UI component boundaries → theming/white-label →
mobile readiness → (late) physical tree move + SW bump.

## 3. Data migration policy
- **No data migration in the near term.** All new structure is code-side, behind
  adapters; the settings blob absorbs new metadata (already true).
- The **only** future data migration considered is adding `pack_id` to progress when a
  **second** content pack ships — a separate, approved, reversible change defaulting
  existing rows to `hsk`. Until then, single-pack keeps integer IDs untouched.

## 4. Rollback model
Every phase commits on `architecture-v2`. Rollback = `git revert <phase commit>` (or
reset the branch) — production `main` is never touched. The `production-baseline-v1`
tag is the ultimate anchor. Because early phases are additive (new files + call
rewiring), reverts are clean.

## 5. Definition of done per phase
Green regression baseline + data-stability checks + no console errors + reviewer sign-off
on stop/go criteria. A phase that cannot meet its stop/go criteria is reverted, not patched forward.
