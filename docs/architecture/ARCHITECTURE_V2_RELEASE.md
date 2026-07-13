# Architecture v2 — Release (Phases 0–20)

This is the release record for the **architecture-v2** refactor: a 20-phase, strangler-fig
migration of the HSK flashcard PWA (first **FlashEdu** content pack) from a monolithic
`app.js` into explicit read/write seams — **with zero user-visible behavior change**.

- **Production baseline:** `production-baseline-v1` = `ecd13fb` (frozen; never modified).
- **Compatibility guarantee:** 5,002 cards, all IDs, importer output, SRS goldens, storage
  keys and cloud payloads are **byte-identical** to the baseline throughout.
- **Test gate:** `python tests/run_regression.py` → **28/28 suites PASS**.

## Phase summary
| # | Phase | Delivered |
|---|---|---|
| 0 | Audit + safety | architecture docs, `production-baseline-v1` tag |
| 1 | Characterization + safety net | one-command regression runner, data-stability tests |
| 2 | Pure utilities | `core/util/{date,levels,shuffle,card-index}.js` |
| 3 | CardRepository (read) | `core/cards/card-repository.js` |
| 4 | SettingsRepository (read) | `core/settings/settings-repository.js` |
| 5 | StudySessionQuery (read) | `core/sessions/study-session-query.js` |
| 6 | AnalyticsQuery (read) | `core/analytics/analytics-query.js` |
| 7 | UserMetadataQuery (read) | `core/metadata/user-metadata-query.js` |
| 8 | ProgressRepository (read) | `core/progress/progress-repository.js` |
| 9 | TestModeQuery (read) | `core/testing/test-mode-query.js` |
| 10 | ContentPack + HSK adapter | `core/content/content-pack.js`, `packs/hsk/hsk-content-pack.js` |
| 11 | Pack metadata consumption | deck ids + Test-mode defs sourced from the pack |
| 12 | ProgressWriter.grade (write) | `core/progress/progress-writer.js` |
| 13 | ProgressWriter.restore (write) | undo/skip restore-or-delete |
| 14 | ProgressWriter.reset (write) | global progress reset |
| 15 | AuthContextQuery (read) | `core/auth/auth-context-query.js` |
| 16 | StudySessionEngine (read) | `core/sessions/study-session-engine.js` |
| 17 | Presentation read model | `renderCard` consumes `describeCard` |
| 18 | SRS Scheduler (pure) | `core/srs/scheduler.js` |
| 19 | StudySessionStateMachine (pure) | `core/sessions/study-session-state-machine.js` |
| 20 | State-machine integration + release | `sessionState` is authoritative; merge to main |

## Final module map (`hsk_flashcard_app/`)
```
data.js                         window.HSK_CARDS (generated from source_data/HSK1-HSK6.xlsx)
core/util/*                     pure date/levels/shuffle/card-index helpers
core/content/content-pack.js    generic ContentPack contract (no HSK literals)
packs/hsk/hsk-content-pack.js   HSK adapter -> HSKUtil.contentPack (field roles, decks, testModes)
core/cards/card-repository.js   HSKUtil.cards          (read: getById/getByLevel/getAll/…)
core/settings/…                 HSKUtil.settings       (read: getFrontPinyinEnabled/…)
core/progress/progress-repository.js  HSKUtil.progress (read: getStored/getOrDefault/isLearned/isDue)
core/progress/progress-writer.js      writer instance in app.js (grade/restore/reset)
core/srs/scheduler.js           HSKUtil.srsScheduler   (pure computeNext(state,grade,now))
core/sessions/study-session-query.js    HSKUtil.…       (select standard/explicit sessions)
core/sessions/study-session-engine.js   engine in app.js (buildSession/describeSession/describeCard)
core/sessions/study-session-state-machine.js  sessionSM (pure navigation transitions)
core/analytics/analytics-query.js   HSKUtil.analytics  (home/weak/smart/daily read models)
core/metadata/user-metadata-query.js HSKUtil.userMetadata (bookmark/note reads)
core/testing/test-mode-query.js  HSKUtil.testMode      (MCQ generation)
core/auth/auth-context-query.js  HSKUtil.authContext   (account identity / storage namespace)
auth.js  sync.js  metadata.js  insights.js  test.js  app.js   (existing runtime; app.js orchestrates)
```

## Read / write ownership
- **Reads:** CardRepository, SettingsRepository, ProgressRepository, StudySessionQuery,
  AnalyticsQuery, UserMetadataQuery, TestModeQuery, AuthContextQuery, StudySessionEngine.
- **Writes:** `ProgressWriter` (grade/restore/reset — the only per-card progress write path);
  `metadata.js` (bookmark/note writes); `sync.js` (cloud transport); `auth.js` (auth/session).
- **Pure logic:** `SrsScheduler` (scheduling math), `StudySessionStateMachine` (navigation state).
- **Orchestration/DOM/audio:** `app.js` (event handlers, rendering, SpeechSynthesis, view
  switching, snapshot/undo capture).

## Study flow (post-integration)
`startStudy`/`HSK_APP.startSession` → `StudySessionEngine.buildSession` (delegates selection to
`StudySessionQuery`) → `sessionState = sessionSM.startSession({cardIds})`. `renderCard` reads
`sessionState.currentIndex`/`describeSession`/`describeCard` and writes the DOM (the P0
answer-leak reflow guard is unchanged). `flipCard`→`sessionSM.flip`. `gradeCard`: guard on
`sessionState.flipped` → `ProgressWriter.grade` (write, first) → `sessionSM.grade` (record +
advance, after). `skipCard`: `ProgressWriter.restore` (if snapshot) → `sessionSM.skip`.
`swipePrev`→`sessionSM.prev`. Completion when `sessionState.currentIndex >= session.length`.

## Test flow
`test.js` owns Test Mode UI/state; `TestModeQuery` generates questions/distractors (delegating
shuffle to Phase 2). Fully independent of Study progress/SRS.

## Progress flow
`getCardState`-style reads via `ProgressRepository`; grade → `ProgressWriter.grade`
(read state → `SrsScheduler.computeNext` → assign `progress[id]` → `save()` →
`HSKSync.markDirty`), exactly one save + one markDirty (local-only = save, no dirty); undo →
`ProgressWriter.restore`; reset → `ProgressWriter.reset`.

## Scheduler flow
`SrsScheduler.computeNext(state, grade, now)` is a pure function (no mutation of state/now)
injected into `ProgressWriter` as `srsCalculator`. Formulas frozen: again→0/+1min; hard
`max(1,round(iv*1.2):1)`; good `max(3,…*2…:3)`; easy `max(7,…*3…:7)`; UTC due; unknown grade →
easy math, no `correct++`.

## Auth / sync boundaries
`AuthContextQuery` centralizes the read-only account identity + storage-namespace selection
(no tokens/PINs/secrets exposed). `auth.js` still owns login/register/PIN/logout/delete +
`HSK_AUTH`; `sync.js` still owns dirty set/push/pull/merge/reset transport. Neither was
modified for behavior in the refactor.

## Compatibility guarantees (verified)
No change to: card data/IDs/order/counts, importer output, progress schema
(`{due,interval,reps,correct,attempts}`), settings blob, localStorage keys
(`hsk_flashcard_progress_v2[::uid]` etc.), cloud RPC payloads, SRS golden outputs, Study/Test
UI, bookmarks/notes, auth/sync/local-only/offline/PWA behavior. `production-baseline-v1`
(`ecd13fb`) untouched.

## Test-suite status (28/28)
util_units · card_repository · settings_repository · session_query · study_session_engine ·
study_session_state_machine · analytics_query · user_metadata_query · progress_repository ·
progress_writer · test_mode_query · content_pack · auth_context_query · srs_scheduler ·
srs_characterization · card_stability · baseline_comparison · importer_determinism ·
adapter_roundtrip · contracts · p0_test · regression · features_test · qa2 · metadata_sync ·
test_mode · auth_test · offline_test.

## Rollback strategy
- **Whole refactor:** production `main` remains at `ecd13fb`; deploying `main` (pre-merge) or
  re-pointing Render to `ecd13fb` fully reverts. After the merge, `git revert -m 1 <merge>`.
- **Per phase:** each phase commit is an independent `git revert` (documented in each
  `PHASE_N_*.md`), with the exact anchor commit and expected suite count.
- **SW:** cache is `v26`; reverting a phase restores its prior `vNN` and the browser reactivates.

## Production smoke-test checklist (owner)
1. `run.bat` (or `python -m http.server` in the repo root), open `/hsk_flashcard_app/`.
2. Local-only: study ≥3 cards — flip, Again/Hard/Good/Easy, skip, swipe-back (undo),
   reach the complete screen. Confirm each next card shows the **front** (no answer leak).
3. Weak Words → "study these"; Bookmarks → "study saved"; run one Test Mode quiz.
4. Reload → progress persists; no console errors.
5. (Configured account) register/login on a test account; confirm namespaced storage, sync
   status, logout. **Never use real user data.**
6. Offline: load once online, go offline, confirm the app shell + a study session still work
   (SW `v26`).

## Known intentionally-deferred areas
- **Bookmark/Note writes** remain in `metadata.js` (read side is behind `UserMetadataQuery`).
- **Sync transport ownership** stays in `sync.js` (only account-context reads were extracted).
- **Test Mode controller/session state** stays in `test.js` (generation is behind `TestModeQuery`).
- **Dynamic pack loading / pack registry / multi-pack / generic importer** — documented in
  `CONTENT_PACK_STANDARD.md §6`, not implemented (single active HSK pack).
- **UI branding / copy** unchanged (no rename of the production HSK UI).
- **Render auto-deploy** is manual (Manual Deploy → Deploy latest commit).
