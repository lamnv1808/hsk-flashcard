# Phase 9 — Read-only TestModeQuery / Question-Generation Seam

Domain query boundary for **FlashEdu** (HSK is content pack #1). A single
`TestModeQuery` now owns the deterministic Test Mode **question/session generation**
extracted verbatim from `test.js`: eligible-card selection, prompt/answer formatting,
distractor generation, option shuffling and session assembly. **This is question-
generation extraction, not a controller** — `test.js` keeps all mutable session/UI
state (index, selected answer, score, reveal, navigation, rendering, audio, history);
every behavior is unchanged (full suite 22/22; the end-to-end `test_mode` UI suite green;
cards/IDs/importer/baseline and all prior repos/queries identical to
`production-baseline-v1`). Test Mode stays fully independent of Study progress and SRS.

- Phase 8 anchor (rollback): `005a2ba`
- Phase 9 = the commit introducing this document.

## Module
`hsk_flashcard_app/core/testing/test-mode-query.js` — classic script, no
bundler/ESM/TS. `core/testing/` matches the `core/<domain>/` convention of Phases 3–8.
Extends `window.HSKUtil`.
- `HSKUtil.createTestModeQuery({cardRepository, randomProvider})`.
- `HSKUtil.testMode` — shared instance over the production `CardRepository` (Math.random).

Load order (`index.html`): … `core/metadata/user-metadata-query.js` →
**`core/testing/test-mode-query.js`** → `supabase-config.js` → … → `test.js`.

## Read-only contract
No writes of any kind. The query never mutates cards/progress/settings/bookmarks/notes/
source arrays, never grades SRS, creates progress rows, writes history, changes score,
marks dirty, writes localStorage, enqueues sync, calls Supabase, touches DOM, or
starts/stops audio. It reads cards (via `CardRepository`) and returns plain question
data. **No settings or progress dependency** — Test Mode reads neither (its setup is
in-memory in `test.js`, never persisted to the settings blob).

## Question modes (frozen — integer ids)
| id | prompt (`q`) | answer (`a`) | label |
|---|---|---|---|
| 1 | word | [pinyin] | Hán tự → Pinyin |
| 2 | pinyin | [word] | Pinyin → Hán tự |
| 3 | word | [meaning] | Hán tự → Nghĩa |
| 4 | pinyin | [meaning] | Pinyin → Nghĩa |
| 5 | word | [pinyin, meaning] | Hán tự → Pinyin + Nghĩa |
| 6 | pinyin | [word, meaning] | Pinyin → Hán tự + Nghĩa |

**Mix** is `cfg.mix === true` → `types = [1..6]` (not a 7th id). Ids/labels/fields are
unchanged from `test.js`.

## Question read model (== current `test.js` shape)
```
{
  card, type,
  options: [{ card, isCorrect, lines: [answer strings] }],   // shuffled
  correctIndex,                                              // index of the correct option
  answeredIndex: null, correct: null, revealed: false        // initial mutable fields test.js owns
}
```
`answerLines(card, type) = type.a.map(f => trim(card[f]))`; combined answers are joined
by the UI (`lines.join(" · ")`). `trim = String(x==null?"":x).trim()`. No normalization
beyond `trim` (whitespace/punctuation/case preserved). Missing answer field ⇒ the
card is excluded as an option (`answerValid` requires every `a` field non-empty).

## Distractor semantics (frozen)
`pickDistractors(card, pool, type, 3)`: pool = eligible cards (all selected levels,
source order). A candidate is **usable** iff `c.id !== card.id`, `answerValid(c,type)`,
its **prompt differs** from the correct prompt (`trim(c[qField]) !== correctPrompt` — so
the prompt has exactly one valid answer among the options), and its `answerKey` is
unseen. Selection: **random sampling** `pool[(rnd()*pool.length)|0]` up to
`min(160, pool.length*3)` attempts, then a **linear source-order fallback**; dedup by
`answerKey`. `createQuestion` needs ≥1 distractor (else `null`); options =
`[correct, …distractors]` then `shuffleInPlace`; `correctIndex` read from the shuffled
order. Up to 4 options (1 correct + up to 3). Insufficient pool ⇒ fewer options;
single-card pool ⇒ `null`.

## Randomness
A **single injected `randomProvider`** (default `Math.random`) threads through BOTH the
distractor sampling and the Phase 2 Fisher–Yates shuffle calls
(`shuffleInPlace(_, rnd)` / `shuffledCopy(_, rnd)`), preserving the exact algorithms and
the global random-call order. Production is byte-identical to the pre-Phase-9 code
(which used the same global `Math.random`). Tests inject a seeded PRNG for determinism.
Source arrays are never sorted in place (pool/cardOrder are copies).

## Mix & session construction (frozen — `createSession(cfg)`)
- `pool = cardRepository.getAll().filter(level ∈ cfg.levels)` — source order (matches the
  original `CARDS.filter`; no `HSK_CARDS` access).
- `types = cfg.mix ? [1..6] : cfg.types.slice()`.
- `N = cfg.count === "all" ? pool.length : min(parseInt(cfg.count), pool.length)` (default `"20"`).
- `cardOrder = shuffledCopy(pool, rnd)`.
- Per-question mode: round-robin `assign[i] = types[i % types.length]` then
  `shuffleInPlace(assign, rnd)` — indexed by `questions.length` (skipped cards don't
  advance it).
- Build until `N` questions or `cardOrder` exhausted; a card yielding no buildable
  question is skipped (`createQuestion(want) || firstBuildable(shuffled types)`).
No duplicate cards (each `cardOrder` entry used once). **Redo** reuses `createSession`
with the same cfg → a freshly shuffled session (no separate method).

## Wrong-answer reveal
The reveal payload is simply the correct `card` (word/pinyin/meaning/example/
examplePinyin/translation), already on `question.card`. The query does **not** trigger
the reveal, lock the answer, mutate correctness, or navigate — `test.js` owns the
no-retry lock, auto-reveal-on-wrong, and rendering.

## Result summary — deferred
`finishTest` computes total/correct/wrong/pct from **mutable** `state.score`
(set by `selectAnswer`). It is not purely derivable from a static input and is not
duplicated, so it stays in `test.js` (result-screen state + `saveHistory` remain there).

## Migrated logic (into the query)
`TYPE_DEFS`, `typeDef`, `qField`, `answerLines`/`answerKey`/`answerValid`/`questionValid`,
`pickDistractors`, `buildQuestion` (→ `createQuestion`), `firstBuildable`,
`buildTest` (→ `createSession`), plus the eligible-pool filter (→ `getEligibleCards`).
`test.js` now: `var TMQ = HSKUtil.testMode`; `TYPE_DEFS = TMQ.getTypeDefs()` (picker);
`typeDef`/`qField` are thin delegates; `buildTest(cfg) = TMQ.createSession(cfg)`;
`LEVELS = HSKUtil.cards.getLevels()` (was `levelsFromCards(HSK_CARDS)`).

## Deferred (state / UI / write — unchanged)
Setup/session state, `renderQuestion`, `selectAnswer` (score), `setReveal`, `next`,
`finishTest`, `renderReview`, `redoTest` orchestration, audio, keyboard, `loadHistory`/
`saveHistory` (per-user history persistence), all DOM.

## Why the Test Mode controller/session state is deferred
Current index, selected answer, answer locking, score mutation, reveal toggling,
navigation, result screen and history persistence are mutable session state + DOM +
storage. Wrapping them is a controller/state-machine change, not question generation,
and belongs to a later phase.

## Performance
- Query instantiated once (shared `HSKUtil.testMode`; tests build their own). No
  `CardRepository` index rebuild. `getEligibleCards` is one source-order filter; the
  resulting **pool is reused** across every question and distractor pick (no per-option
  5,002-card scan). Only the current session's pool/cardOrder are copied. No network,
  no storage, no settings/progress captured (no stale on account switch).

## Characterization
`tests/browser/test_test_mode_query.py` re-implements the **original inline** `test.js`
generation (`__oldGen`, threading the same injected seeded `rnd`) and compares to
`TMQ.createSession`/`createQuestion` over identical fixtures across 5 configs
(single-type, all-6, Mix, count="all", two-level) — asserting equal card ids, modes,
prompts, correct answers, distractor sets, option order and `correctIndex`. Plus:
eligible cards, per-type prompt/answer formatting, distractor rules (exactly-one-correct,
uniqueness, same-prompt exclusion, insufficient/single-card pools), Mix determinism,
session sizes/redo, Study isolation, and no-side-effects. The end-to-end `test_mode`
suite validates the rendered quiz/answer/reveal/result flow.

## Service worker
Bumped **once**: `v16 → v17`; added `core/testing/test-mode-query.js` to the precache
`ASSETS`. **Strategy unchanged** (cache-first; existing `activate` removes old caches).

## Rollback
Phase 9 is independently reversible.
1. `git revert <phase-9-commit>` on `architecture-v2` — restores the inline `test.js`
   generation, removes the query `<script>` tag, and reverts `sw.js` to `v16`.
2. Or manual: `git checkout 005a2ba -- hsk_flashcard_app/test.js hsk_flashcard_app/index.html hsk_flashcard_app/sw.js tests/run_regression.py`,
   then delete `hsk_flashcard_app/core/testing/` and `tests/browser/test_test_mode_query.py`.
3. Re-run `python tests/run_regression.py` — expect **21/21** after full rollback
   (Phase 9 suite removed).
4. Phase 1–8 fixtures, baselines, and the `production-baseline-v1` tag are preserved.

## Recommended Phase 10 scope (do not begin)
The read/query seams are now complete across every domain (Cards, Settings, Progress,
Session, Analytics, User-Metadata, Test Mode). The next step is the **first write-capable
boundary**: a **write-capable `ProgressRepository` / `ProgressWriter` for SRS grading
persistence** — wrap `gradeCard`'s read-modify-write (`getCardState` → apply SRS →
`progress[id]=…` → `save()` → `HSKSync` dirty/push) behind one repository method,
characterized against the frozen SRS goldens and dirty/push behavior, **without**
changing SRS formulas, due-date math, storage keys or cloud payloads. This is a larger,
sync-coupled write phase needing its own characterization budget. Lower-risk
intermediate alternatives: a read-only **`TestHistoryQuery`** over the Test Mode history
list, or a read-only **`SyncStatusQuery`** over sync bookkeeping. Defer
`BookmarkRepository`/`NoteRepository` writes, the Test Mode controller/session-state
extraction, sync ownership, and content-pack/DeckRepository work.
