# ADR-001 — Adopt a Modular Monolith (not microservices, not a framework)

- **Status:** Accepted (Phase 0, direction only — no code moved yet)
- **Date:** 2026-07-12
- **Context:** The product must grow from a single HSK PWA into a multi-language,
  white-label, eventually-mobile learning platform. The current code is a working
  vanilla-JS static PWA with a Supabase backend and ~2,700 LOC across 8 scripts.

## Decision
Evolve into a **modular monolith** — one deployable app with clear internal module
boundaries and dependency rules (`DOMAIN_BOUNDARIES.md`) — using **incremental,
reversible** extraction. Explicitly **rejected**: microservices, runtime plugin
loading, a mandatory framework migration (React/Vue), a new backend/database, or a
big-bang rewrite.

## Rationale
- Team/scale is small; a monolith keeps deploy + reasoning simple and preserves the
  no-build static-hosting advantage (Render + PWA + offline).
- The real problem is **coupling and HSK assumptions**, not deployment topology.
  Boundaries + interfaces solve that without new infrastructure.
- Reversibility: each phase is a small commit that can be reverted independently; a
  framework migration cannot.
- Mobile/white-label are enabled by DOM-free domain + repository seams, not by
  services.

## Consequences
- We keep classic scripts initially; ES modules are introduced only if/when a phase
  proves net-positive and keeps static hosting working (no mandatory bundler).
- We accept a transitional period where legacy globals and new modules coexist behind
  adapters.
- Every change is gated by the regression baseline (`docs/REGRESSION_BASELINE.md`).
