# ADR-002 — Legacy is the Compatibility Contract; change only via adapters

- **Status:** Accepted
- **Date:** 2026-07-12

## Context
There are real production users with real cloud + local data: card progress keyed by
integer card IDs (1–5002), a settings JSON blob (now also holding bookmarks/notes/
daily aggregates), Supabase tables/RLS/RPCs, and Auth accounts. Data loss or ID
drift is unacceptable.

## Decision
The **current production data model is the compatibility contract.** It is frozen
until a *separately approved* migration exists. All new structure (canonical `Card`,
`UserCardState`, repositories) is introduced **behind adapters** that read/write the
exact legacy shapes. A `legacy → canonical → legacy` round-trip must be **byte-identical**
for untouched records, enforced by characterization tests.

## Rules
1. **Never renumber card IDs.** They are the join key everywhere.
2. **Never rename or repurpose** an existing localStorage key, `progress` field,
   `settings` field, Supabase column, RPC, or Edge-Function contract.
3. New per-user metadata goes into the existing synced `settings` blob as **new keys
   with safe defaults** — no schema migration.
4. Missing/unknown fields default safely; unknown settings keys are preserved verbatim
   on write (no lossy rewrites).
5. Any future canonical persistence (e.g., a `pack_id` column) ships only with an
   approved, reversible migration that defaults existing rows to `hsk`.

## Consequences
- Adapters add a thin indirection layer (acceptable).
- We can refactor internals freely as long as the on-disk/on-cloud bytes are preserved.
- The regression baseline includes explicit **data-stability** checks (IDs, counts,
  round-trip) as stop/go gates.
