/* ============================================================
 *  core/srs/scheduler.js  (FlashEdu — Phase 18)
 *  PURE SRS next-state calculator, extracted verbatim from app.js
 *  srsNextState. Same formulas, same rounding, same UTC due-date, same
 *  reps/attempts/correct rules, same unknown-grade quirk — byte-identical
 *  serialized output for every input.
 *
 *  PURE FUNCTION CONTRACT: no storage / network / DOM / global progress /
 *  sync / repositories. It does NOT mutate the input `state` or the input
 *  `now` Date; it returns a NEW state object (unknown fields preserved).
 *  Given the same (state, grade, now) it always returns the same output.
 *
 *  It owns ONLY the scheduling math. The grade write transaction
 *  (read -> compute -> assign -> save -> markDirty) stays in ProgressWriter,
 *  which consumes computeNext as its injected srsCalculator.
 * ============================================================ */
(function (NS) {
  "use strict";

  function createSrsScheduler() {
    // computeNext(state, grade, now) — positional to match ProgressWriter's srs(s,g,now).
    //   state: current progress row {due,interval,reps,correct,attempts} (read-only here)
    //   grade: "again" | "hard" | "good" | "easy"  (unknown -> easy interval, no correct++)
    //   now:   Date base time (cloned; never mutated)
    function computeNext(state, grade, now) {
      var s = state;                       // read-only; not mutated
      var d = new Date(now.getTime());     // clone: never mutate the input Date
      var interval = s.interval;
      var nextInterval;

      if (grade === "again") {
        d.setMinutes(d.getMinutes() + 1);
        nextInterval = 0;
      } else if (grade === "hard") {
        var hd = Math.max(1, interval ? Math.round(interval * 1.2) : 1);
        d.setDate(d.getDate() + hd);
        nextInterval = hd;
      } else if (grade === "good") {
        var gd = Math.max(3, interval ? Math.round(interval * 2.0) : 3);
        d.setDate(d.getDate() + gd);
        nextInterval = gd;
      } else {
        var ed = Math.max(7, interval ? Math.round(interval * 3.0) : 7);
        d.setDate(d.getDate() + ed);
        nextInterval = ed;
      }

      // Copy unknown fields first, then override the SRS fields — this reproduces the
      // old in-place mutation (which preserved any extra fields) exactly, including key
      // order, so JSON.stringify(computeNext(...)) === JSON.stringify(srsNextState(...)).
      var next = {};
      for (var k in s) if (Object.prototype.hasOwnProperty.call(s, k)) next[k] = s[k];
      next.interval = nextInterval;
      next.due = d.toISOString().slice(0, 10);
      next.reps = (s.reps || 0) + 1;
      next.attempts = (s.attempts || 0) + 1;
      if (grade === "good" || grade === "easy") next.correct = (s.correct || 0) + 1;
      return next;
    }

    return { computeNext: computeNext };
  }

  NS.createSrsScheduler = createSrsScheduler;
  // Stateless singleton — instantiated once at load; injected into ProgressWriter by app.js.
  NS.srsScheduler = createSrsScheduler();

})(window.HSKUtil = window.HSKUtil || {});
