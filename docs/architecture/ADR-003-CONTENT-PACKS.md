# ADR-003 — HSK becomes a Content Pack; the engine is pack-agnostic

- **Status:** Accepted
- **Date:** 2026-07-12

## Context
HSK/Chinese assumptions are baked into "generic" code: hardcoded `"zh-CN"` audio,
`word/pinyin/meaning` card shape, front-pinyin preference, six Chinese-shaped Test
question types, `HSKn` level parsing. This blocks Chinese/English/French/Japanese/
academic/corporate content.

## Decision
Define a **Content Pack Standard** (`CONTENT_PACK_STANDARD.md`). HSK is refactored to
be **one pack** implementing that contract. The learning engine (SRS, sessions,
Test-mode mechanics, analytics, audio engine) consumes canonical `Card`s and pack
config (`languages`, `capabilities`, `testModes`, `audioRules`, `display`) instead of
HSK/Chinese literals.

## Rules
- The engine never references `HSK`, `zh-CN`, or `pinyin` literally; it reads pack config.
- Packs never import engine internals; they only produce validated data + manifest.
- Features degrade gracefully on absent capabilities/fields (hide, never crash).
- Introducing packs must not change current HSK runtime data or IDs (ADR-002).

## Consequences
- Audio, Test-mode generation, and display logic become config-driven (a mid-plan phase).
- Adding a language/subject later = ship a new pack + optional new test-mode templates,
  with **no** change to SRS/sync/auth/analytics.
- Multi-pack introduces `(packId, cardId)` as the logical key; single-pack today keeps
  the integer id with `packId="hsk"` injected (no migration).
