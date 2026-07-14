# Phase 23 — Targeted-Review Continuity

Additive controller/navigation change: a targeted Study session returns the learner to the
**refreshed** originating feature after completion. No learning-domain, storage, sync, or
completion-metric change.

## Original dead-end
Targeted sessions (Weak Words / Bookmarks) launched via `HSK_APP.startSession(ids)` were tagged
only `{type:"explicit"}`, so completion showed the generic screen and `homeBtn` sent the learner to
**generic Home** — losing the targeted-review context.

## Verified sources
Discovery confirmed the only production callers of `HSK_APP.startSession` are two buttons in
`insights.js`:
- **Weak Words** — `weakStudyBtn` → `studyIds(weakShown.map(...id), {feature:"weak"})`.
- **Bookmarks** — `bmStudyBtn` → `studyIds(getBookmarkedCards({level})..., {feature:"bookmarks"})`.

**Smart Review / Insights (`insightsView`) is analysis-only — it has NO Study launcher**, so no
Smart Review source was added.

## Source-context contract
Transient module-local `studySource` in `app.js` — never persisted, synced, in `sessionState`, the
state machine, or cloud payloads. Discriminated shape (holds no cards/ids/DOM/callbacks):
```
{ type:"levels", levels:string[] }                     // Phase 21 (unchanged)
{ type:"targeted", feature:"weak"|"bookmarks" }        // Phase 23 (new)
{ type:"explicit" }                                    // generic fallback
```

## API compatibility
`HSK_APP.startSession(ids, source)` — the 2nd arg is optional and normalized by `normalizeSource`:

| Input | Result |
|---|---|
| missing / `null` / non-object / array / string | `{type:"explicit"}` |
| `{}` / `{foo:...}` / `{feature:123}` / `{feature:"smart"}` (unknown) | `{type:"explicit"}` |
| `{feature:"weak"}` | `{type:"targeted", feature:"weak"}` |
| `{feature:"bookmarks"}` | `{type:"targeted", feature:"bookmarks"}` |
| `{feature:"weak", extra:fn}` | `{type:"targeted", feature:"weak"}` (only `feature` read; callback ignored) |

Existing one-argument callers are unaffected. Card validation, dedup, order, `StudySessionEngine`
construction, `sessionState` init, snapshot reset, first render, front-side state and audio are all
unchanged; source never affects SRS/selection. `studySource` is set only at the existing safe point
(after the empty-list guard).

## Allowlist / security model
`feature` is validated against the fixed allowlist `["weak","bookmarks"]`. Completion labels
(`TARGETED_LABELS`) and return openers (`RETURN_OPENERS`) live in `app.js`, keyed by that enum — no
arbitrary DOM ids, view ids, or callbacks ever come from source data. Labels are set via
`textContent` (never `innerHTML`).

## Return-to-source behavior
Completion (`finishSession`) resets both extra actions to hidden and Home to primary, then applies
exactly one gating:
- **levels + due>0** → Phase 21 "Học tiếp N thẻ" (unchanged); Home secondary.
- **targeted** → primary `#returnSourceBtn` labelled "Quay lại Từ cần cải thiện" / "Quay lại Từ đã
  lưu"; Home secondary.
- **explicit / null / malformed** → generic Home primary (unchanged).

`#returnSourceBtn.onclick` reads `studySource` at click time, requires `type==="targeted"` + an
allowlisted feature + `window.HSKInsights`, then calls the mapped opener
(`HSKInsights.showWeak()` / `showBookmarks()`); otherwise it falls back to Home. It starts no Study
session, writes nothing, and is idempotent (double-click just re-renders the feature view).

## Live re-query / data freshness
Returning calls the existing feature openers, which **re-query live data**:
- Weak → `renderWeak()` → `AnalyticsQuery.getWeakWords` (reflects grades just completed).
- Bookmarks → `renderBookmarks()` → `UserMetadataQuery.getBookmarkedCards` (reflects removals during
  Study). Empty result → existing empty state.
No stale array is retained; no filter/source state is persisted; no extra full-deck scan beyond the
feature's existing query.

## Non-persistence & lifecycle
`studySource` is overwritten by every valid session start, reset to `null` on reload, and cleared by
account switch/logout (`location.reload`). Missing/invalid source → safe Home. No localStorage key,
no sync field.

## Account / reload / offline
Per-account isolation is inherent (module-local, reset on the reload that account switches perform).
Reload during Study → source lost → generic Home fallback. Local-only and offline return work with
no network (pure view re-render over local data).

## Save / dirty invariants
Return navigation performs **zero** ProgressWriter calls, settings saves, metadata persists,
sync-dirty notifications, SRS calculations, Daily-Goal changes, or streak changes (verified). Study
grades before completion keep their existing exact save/dirty behavior.

## Answer-leak safety
No change to `renderCard`/`flipCard`/card-face classes/answer-leak reflow guard/state machine/engine.
Returning switches to a **feature** `.view` (not `studyView`); the next Study session begins
front-side; malformed source cannot display answer data. `p0_test` green.

## Tests
`tests/regression/targeted_continuity.py` (registered): source normalization (all cases via observed
completion actions), level Keep Going unchanged, weak/bookmark return opens the refreshed view and
re-queries (spied), bookmark removal reflected + empty state, rapid double-click harmless, targeted
cleared by a new level/explicit session, handler Home fallback, zero writes on navigation, front-side
next session, no console errors. Full suite **32/32 PASS** (incl. p0, SRS goldens, daily_goal,
completion_loop, streak_semantics, metadata_sync, auth isolation, offline). Verified no horizontal
overflow and Study one-screen unchanged at 360×800/375×667/390×844/1366×768 in light + dark.

## Service Worker
Cache bumped once **v32 → v33** (`app.js`/`insights.js`/`index.html` precached). No new asset; asset
list + install/activate/fetch strategy unchanged.

## Rollback
Branch `phase-23-targeted-continuity` off Phase 22B anchor `cdf0d55`. Revert: the `studySource`
union + `normalizeSource` + `startSession(ids, source)` + `finishSession` gating + return handler
(`app.js`), the `{feature}` args (`insights.js`), the `#returnSourceBtn` markup (`index.html`), and
SW v33→v32; remove the focused suite + registration + this doc. `git revert <sha>` restores generic
explicit completion. No user-data migration/rollback (navigation state is transient). Expected
regression after rollback: 31/31.

## Deferred (not in this phase)
Remaining-targeted count and one-tap continue-targeted review are intentionally out of scope; the
re-opened feature list already shows the refreshed remaining set.
