# REGRESSION BASELINE (Phase 0)

The behavior that must stay green through every migration phase. Baseline commit
`ecd13fb` (tag `production-baseline-v1`). Automated suites live in
`tests/regression/` (see `tests/README.md`); items that cannot be automated have exact
manual steps. This is the **stop/go gate** for all phases.

## A. Automated coverage (Playwright + Chromium; Supabase mocked)

| Baseline item | Suite | Key assertions |
|---|---|---|
| No next-card answer leak | `p0_test.py` | grade 1/2/3/4, click, Next, swipe prev/next, rapid → next card starts on front, back face not animating, advances exactly once |
| Study flip / keyboard | `regression.py` | Space flips; `S` reads example on back; Esc exits |
| SRS grading + due | `regression.py` | `good` on fresh ⇒ interval 3; advances; skip works |
| Audio / Read-All / auto-read | `regression.py` | word/example zh-CN; Read-All no pinyin/VN; auto-read word |
| Dark mode | `regression.py` | toggle + persists |
| Weak Words | `features_test.py` | ranks by failures; excludes untouched/never-failed; study launch |
| Smart Review | `features_test.py` | insight values; "Chưa đủ dữ liệu" state; chart SVG |
| Daily chart count | `features_test.py`, `qa2.py` | once per card per local day; custom-session grade counts |
| Bookmarks | `features_test.py`, `qa2.py` | add/remove; per-card star; no SRS change; page + empty state |
| Notes | `features_test.py`, `qa2.py` | back-only; empty=no clutter; save/edit/delete-by-empty; ≤1000; plain-text |
| Test Mode (all types) | `test_mode.py` | 6 types, real distractors, no answer leak, correct-once, no double-score |
| Test Mode isolation | `test_mode.py` | no writes to Study progress/SRS |
| Register/Login/Isolation/Lockout/Migration | `auth_test.py` | gate, 2-account isolation, generic error, 429 lock, legacy import preserved |
| Offline queue + reconnect | `offline_test.py` | studied offline queued; nothing pushed; flush on `online` |
| View overlap on custom-study | `qa2.py` | weak/bookmark study shows only `studyView`; exit → clean home |
| No console errors | all suites | `errors: []` / `pageerrors: []` |

**Data-stability checks (add as Phase-1 assertions):** card count 5002; per-level counts
149/150/295/600/1295/2513; IDs unique + contiguous 1–5002; HSK1–4 byte-stable vs
`production-baseline-v1`; `legacy→canonical→legacy` round-trip byte-identical.

## B. Manual steps (not currently automated)

1. **PWA install:** Chrome desktop + Android → install; launches standalone with correct icon/name.
2. **Offline app-shell:** install → go offline (DevTools) → reload → app loads; study cached cards.
3. **Service-worker update flow:** deploy a build with a bumped `CACHE` string → returning
   user gets new JS on next load; old caches deleted; offline still works. (Docs-only
   changes must **not** bump the cache.)
4. **iOS Safari:** first audio tap works; no horizontal scroll; note editor usable; chart bars
   visible (accent color) in light + dark.
5. **Change PIN / Delete account** against the real Supabase (staging): old sessions behave
   per contract; delete removes cloud rows and logs out; other accounts unaffected.
6. **Two-device sync:** grade on device A → appears on device B after reconnect; latest-wins on conflict.
7. **Responsive:** 375×667 / 390×844 / 360×800 study fits one screen; desktop stable; dark mode.
8. **Speech speeds:** all five apply and persist.

## C. How to certify a phase
Run all suites (`"pass": true` for each) + section A data-stability + spot-check the
section-B manual items relevant to the phase's risk. Any red = **stop**, revert the phase.

## D. Phase-0 baseline result
Recorded in the Phase-0 completion report (this session ran the suites on
`architecture-v2`, which is identical to `production-baseline-v1`). See the session
summary for the exact pass output.
