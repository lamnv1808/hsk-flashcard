/* ============================================================
 *  core/progress/progress-writer.js  (FlashEdu — Phase 12)
 *  Narrow WRITE-capable boundary around the existing Study Mode grading
 *  transaction. It owns ONLY the per-card grade write:
 *    read current state -> compute next state (existing SRS) -> assign
 *    progress[cardId] -> persist (save) -> mark dirty / notify sync.
 *
 *  It is NOT a scheduler and NOT a storage system. SRS math stays with
 *  the caller (injected srsCalculator = the exact current formula block).
 *  ProgressRepository stays read-only; this writer performs the mutation.
 *
 *  Explicitly OUT of scope (stays in app.js / other owners):
 *    flip/transition guards, undo snapshot/revert, sessionGrades, UI
 *    advance, recordDailyLearn, updateStreak, skip/reset, sync transport,
 *    bookmark/note/settings writes, Test Mode.
 *
 *  Writes to the CURRENT active progress object via a live provider, so
 *  cloud-pull reassignment / account switch are honored (no stale capture).
 * ============================================================ */
(function (NS) {
  "use strict";

  // deps:
  //   progressProvider   - () => live progress map (assignment target)
  //   progressRepository - Phase 8 read repo (current-state reads; getOrDefault)
  //   srsCalculator      - (state, grade, nowDate) => state  (mutates+returns; the
  //                        exact existing SRS block — this writer never does SRS math)
  //   save               - () => void   (existing persistence; localStorage write)
  //   markDirty          - (cardId) => void  (existing dirty/sync trigger; may be a
  //                        no-op wrapper that checks window.HSKSync, as today)
  //   dateProvider       - () => Date "now" (default new Date(); injectable for tests)
  function createProgressWriter(deps) {
    deps = deps || {};
    var getProgress = (typeof deps.progressProvider === "function")
      ? deps.progressProvider
      : function () { return deps.progressProvider || {}; };
    var repo = deps.progressRepository;
    var srs = deps.srsCalculator;
    var save = (typeof deps.save === "function") ? deps.save : function () {};
    var markDirty = (typeof deps.markDirty === "function") ? deps.markDirty : function () {};
    var getNow = (typeof deps.dateProvider === "function") ? deps.dateProvider : function () { return new Date(); };

    // Grade transaction — preserves the exact current order of operations
    // (read -> srs -> assign -> save -> markDirty). Returns the states for callers/tests;
    // app.js keeps its own undo snapshot flow and ignores the return value.
    function grade(args) {
      args = args || {};
      var cardId = args.cardId;
      if (cardId == null) return null;            // defensive: no partial mutation (unreachable in production)
      var g = args.grade;

      var prog = getProgress();
      var now = getNow();
      var todayKey = now.toISOString().slice(0, 10);   // captured before srs mutates `now`

      // snapshot the pre-grade row for the return value (single row; not the whole map)
      var prevRow = prog[cardId];
      var previousState = prevRow ? JSON.parse(JSON.stringify(prevRow)) : null;

      // current state: live row for a touched card, else the SAME fresh default as
      // getCardState() (its `due` is overwritten by the SRS step below).
      var s = repo ? repo.getOrDefault(cardId, todayKey)
                   : (prog[cardId] || { due: todayKey, interval: 0, reps: 0, correct: 0, attempts: 0 });

      var next = srs(s, g, now);        // existing SRS: mutates s (and now), returns s
      prog[cardId] = next;              // assign (creates the row for an untouched card)
      save();                            // persist through the existing save path
      markDirty(cardId);                 // existing dirty/sync trigger

      return { cardId: cardId, grade: g, previousState: previousState, nextState: next };
    }

    // Undo/skip restore transaction (Phase 13): apply the previous per-card persistence
    // state, then persist + notify sync — the exact block from skipCard's revert path.
    // The controller still owns the snapshot map, session index, navigation and UI.
    //   hadState=true  -> restore the previous row (deep clone, as revertSnapshot did)
    //   hadState=false -> delete the row created by the grade (NOT a default row)
    // Preserves order: restore/delete -> save() -> markDirty(cardId). Exactly one each.
    function restore(args) {
      args = args || {};
      var cardId = args.cardId;
      if (cardId == null) return null;            // no partial mutation
      var prog = getProgress();
      if (args.hadState) prog[cardId] = JSON.parse(JSON.stringify(args.previousState));
      else delete prog[cardId];
      save();
      markDirty(cardId);
      return { cardId: cardId, hadState: !!args.hadState };
    }

    return { grade: grade, restore: restore };
  }

  NS.createProgressWriter = createProgressWriter;
})(window.HSKUtil = window.HSKUtil || {});
