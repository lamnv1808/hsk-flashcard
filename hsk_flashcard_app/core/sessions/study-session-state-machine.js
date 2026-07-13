/* ============================================================
 *  core/sessions/study-session-state-machine.js  (FlashEdu — Phase 19)
 *  PURE, deterministic model of the mutable in-memory Study session
 *  state and its transitions. It freezes the state-transition contract
 *  currently spread across app.js (session/current/flipped/sessionGrades
 *  + start/flip/grade/skip/prev/complete) INDEPENDENTLY of persistence,
 *  SRS, DOM, audio and network.
 *
 *  PURE TRANSITION CONTRACT: every transition returns a NEW state object,
 *  never mutates the input state or its arrays, and has no storage /
 *  network / DOM / audio / global / ProgressWriter / Scheduler access.
 *  Deterministic and serializable.
 *
 *  It owns ONLY navigation state. It does NOT grade progress, compute
 *  SRS, save, mark dirty, play audio, render, or interpret undo snapshots
 *  (which hold progress rows — those stay controller/ProgressWriter-owned).
 *
 *  FOUNDATION PHASE: not wired into production (Phase 20 integrates it).
 *
 *  State shape (plain, serializable):
 *    { cardIds:number[], currentIndex:number, flipped:boolean,
 *      gradesByIndex:(string|undefined)[], status:"idle"|"studying"|"completed" }
 * ============================================================ */
(function (NS) {
  "use strict";

  function createStudySessionStateMachine() {

    // completed when there are no cards, or the index has passed the last card
    // (== app.js renderCard's `current>=session.length` completion guard).
    function statusFor(cardIds, currentIndex) {
      return (cardIds.length === 0 || currentIndex >= cardIds.length) ? "completed" : "studying";
    }

    function createInitialState() {
      return { cardIds: [], currentIndex: 0, flipped: false, gradesByIndex: [], status: "idle" };
    }

    // Start a session from ALREADY-SELECTED card ids (StudySessionEngine selects them;
    // this machine never selects/dedups/reorders). Requested order + duplicates preserved.
    function startSession(opts) {
      opts = opts || {};
      var ids = (opts.cardIds || []).slice();   // copy: input array never mutated
      return { cardIds: ids, currentIndex: 0, flipped: false, gradesByIndex: [], status: statusFor(ids, 0) };
    }

    // Flip the current card (toggle) — matches app.js flipCard (no guard).
    function flip(state) {
      return assign(state, { flipped: !state.flipped });
    }

    // Raw advance to the next card — index+1, next card lands FRONT-side (answer-leak rule).
    function advance(state) {
      var idx = state.currentIndex + 1;
      return assign(state, { currentIndex: idx, flipped: false, status: statusFor(state.cardIds, idx) });
    }

    // Grade the current card in SESSION state, then advance. Records grade@currentIndex
    // then index+1 + flipped=false (== gradeCard's state effects). No-op when not flipped
    // (== gradeCard's `if(!flipped) return`). Progress/SRS writes stay OUTSIDE.
    function grade(state, gradeStr) {
      if (!state.flipped) return state;
      var grades = state.gradesByIndex.slice();   // copy-on-write (session-sized)
      grades[state.currentIndex] = gradeStr;
      var idx = state.currentIndex + 1;
      return assign(state, { gradesByIndex: grades, currentIndex: idx, flipped: false, status: statusFor(state.cardIds, idx) });
    }

    // Skip the current card: record "skip"@currentIndex then advance (== skipCard's state
    // effects; no flip guard). SRS-revert of a previously-graded position stays OUTSIDE.
    function skip(state) {
      var grades = state.gradesByIndex.slice();
      grades[state.currentIndex] = "skip";
      var idx = state.currentIndex + 1;
      return assign(state, { gradesByIndex: grades, currentIndex: idx, flipped: false, status: statusFor(state.cardIds, idx) });
    }

    // Navigate to the previous card (== swipePrev). Lands FRONT-side; only when index>0.
    function prev(state) {
      if (state.currentIndex <= 0) return state;
      var idx = state.currentIndex - 1;
      return assign(state, { currentIndex: idx, flipped: false, status: "studying" });
    }

    // Exit/back to the home state (== exitStudy's session-state effect).
    function exit(_state) { return createInitialState(); }

    // ---- read helpers (derived; the caller uses these instead of raw effects) ----
    function getCurrentCardId(state) {
      return (state.status === "studying") ? state.cardIds[state.currentIndex] : null;
    }
    function isCompleted(state) { return state.status === "completed"; }

    // shallow immutable update — new top-level object; arrays are only ever replaced
    // (via slice) when a transition changes them, never mutated in place.
    function assign(state, patch) {
      var out = {}, k;
      for (k in state) if (Object.prototype.hasOwnProperty.call(state, k)) out[k] = state[k];
      for (k in patch) if (Object.prototype.hasOwnProperty.call(patch, k)) out[k] = patch[k];
      return out;
    }

    return {
      createInitialState: createInitialState,
      startSession: startSession,
      flip: flip,
      advance: advance,
      grade: grade,
      skip: skip,
      prev: prev,
      exit: exit,
      getCurrentCardId: getCurrentCardId,
      isCompleted: isCompleted
    };
  }

  NS.createStudySessionStateMachine = createStudySessionStateMachine;

})(window.HSKUtil = window.HSKUtil || {});
