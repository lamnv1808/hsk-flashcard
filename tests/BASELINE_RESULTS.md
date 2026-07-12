# Phase 1 — Certified Baseline Results

Stable record of the characterization results captured on branch `architecture-v2`
(identical runtime to tag `production-baseline-v1` / commit `ecd13fb`). Re-run any time
with `python tests/run_regression.py`; the volatile per-run report lands in
`tests/reports/latest.{json,md}` (gitignored).

## Overall
**14/14 suites PASS** across 5 domains, no console/page errors.

## Card data (frozen contract)
| Metric | Value |
|---|---|
| Total cards | **5002** |
| HSK1 | **149** |
| HSK2 | **150** |
| HSK3 | **295** |
| HSK4 | **600** |
| HSK5 | **1295** |
| HSK6 | **2513** |
| IDs unique | ✅ | 
| IDs contiguous | ✅ 1..5002 |
| Ordering | deterministic (ascending id) |
| Empty Chinese word | 0 |
| Invalid level | 0 |

## Production-baseline comparison (vs `production-baseline-v1`)
- Renumbered cards: **0** · Missing baseline ids: **0** · Duplicate ids: **0**
- HSK1–HSK4 content byte-stable: **YES** (0 diffs)
- HSK5/HSK6 deterministic ids stable: **YES** (0 diffs)

## Importer determinism
- Two consecutive runs byte-identical: **YES**
- Regeneration matches committed `data.js` (source unchanged): **YES**
- `data.js` restored clean after test (tree unchanged): **YES**

## Legacy ↔ canonical adapter round-trip (prototype, test-only)
- Cards checked: **5002** · Round-trip mismatches: **0**
- Optional canonical metadata (`packId`, `audio`, `tags`, `extra`, `levelOrder`) never
  leaks into legacy output: **verified**

## SRS characterization (golden, frozen)
Fresh card, single grade → `{interval, reps, correct, attempts}`:
| Grade | interval | reps | correct | attempts | due |
|---|---|---|---|---|---|
| Chưa nhớ (again) | 0 | 1 | 0 | 1 | today |
| Khó (hard) | 1 | 1 | 0 | 1 | today+1 |
| Nhớ được (good) | 3 | 1 | 1 | 1 | today+3 |
| Rất dễ (easy) | 7 | 1 | 1 | 1 | today+7 |

Interval progression (repeated grade): good `3→6→12→24`; hard `1→1→1→1`; easy `7→21→63`.
Repeated again keeps interval 0 (reps/attempts increment, correct stays 0). Learned card
(interval 3) graded good → 6. Grading with the card not flipped is a **no-op** (guard).

## Contracts (progress/settings)
Default card state `{due:today, interval:0, reps:0, correct:0, attempts:0}`; new metadata
(`bookmarks`/`notes`/`dailyCounts`) defaults safely (`[]`/`{}`/`{}`) and does not corrupt
existing keys; `showFrontPinyin` absent ⇒ true; `speechRate` normalizes to the allowed
set; account-namespaced keys never collide; JSON round-trip preserves unicode/line breaks;
only dirty cards appear in a push payload.

## Study / Test / Auth / Sync (browser)
- **P0 answer-leak**: fixed (grade 1-4, click, Next, swipe both directions, rapid → next
  card front, back not animating, advances exactly once).
- **Study**: flip/keyboard/audio/auto-read/Read-All(no pinyin/VN)/dark; note back-only;
  bookmark no SRS change; weak/bookmark sessions reuse Study Mode.
- **Test Mode**: all 6 types + mixed, no answer leak, distinct distractors, correct-once,
  wrong-final + reveal, no writes to Study progress.
- **Auth/Sync (mocked)**: register/login/logout, generic error, 15-min lockout, legacy
  migration (local preserved), push-only-modified, offline queue + reconnect flush,
  two-user isolation; bookmarks/notes sync via the settings blob, account-isolated.
