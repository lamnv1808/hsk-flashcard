/* ============================================================
 *  core/sessions/study-session-query.js  (FlashEdu — Phase 5)
 *  Read-only Study Mode card-SELECTION seam. Extracts the exact
 *  inline logic that chooses which cards enter a normal Study
 *  session (and resolves explicit-card sessions), with ZERO
 *  write side-effects. It only reads inputs and returns a card list.
 *
 *  It does NOT own session state: the mutable session array, current
 *  index, current card, flip/animation state, grading, Next/prev,
 *  audio, completion, progress writes, dirty tracking and sync all
 *  remain in app.js. This is query extraction, not a session engine.
 *
 *  STRICT READ-ONLY CONTRACT:
 *    - never mutates cards / progress / settings / source arrays
 *    - never writes localStorage, marks dirty, enqueues sync
 *    - never changes SRS fields / due dates / grades cards
 *    - never creates progress for untouched cards (selecting a card
 *      does not touch its progress row)
 *    - no DOM, no audio, no network
 *
 *  Behavior is frozen to the CURRENT app.js runtime (a future
 *  Scheduler v2 may differ — that is out of scope here).
 * ============================================================ */
(function (NS) {
  "use strict";

  // deps:
  //   cardRepository   - Phase 3 read-only repo (getAll/getById), indexes built once
  //   progressProvider - () => live progress map { "<id>": state }  (re-read every call
  //                      so cloud-pull reassignment / account switch are observed)
  //   dateProvider     - () => "YYYY-MM-DD" today string (matches app.js today())
  //   randomProvider   - () => number in [0,1)  (default Math.random; injectable for tests)
  function createStudySessionQuery(deps) {
    deps = deps || {};
    var repo = deps.cardRepository;
    var getProgress = (typeof deps.progressProvider === "function")
      ? deps.progressProvider
      : function () { return deps.progressProvider || {}; };
    var getToday = (typeof deps.dateProvider === "function")
      ? deps.dateProvider
      : function () { return new Date().toISOString().slice(0, 10); };
    var rnd = (typeof deps.randomProvider === "function")
      ? deps.randomProvider
      : Math.random;

    // Mirror of app.js getCardState(): live progress row, else the SAME default
    // object shape. Reading NEVER writes the row (untouched stays untouched).
    function stateOf(prog, id, now) {
      return prog[id] || { due: now, interval: 0, reps: 0, correct: 0, attempts: 0 };
    }

    // Resolve `limit` exactly like app.js: "all" => whole pool; else slice(0, Number).
    // Number("20")=20; Number("all") never reached ("all" handled first). Preserves
    // the current (unreachable-from-UI) edge results for 0/invalid via slice semantics.
    function applyLimit(arr, limit) {
      if (limit === "all") return arr.slice();
      return arr.slice(0, Number(limit));
    }

    // Standard session: due -> fresh(not already due) -> [fallback if empty].
    // Preserves source order (no shuffle) on the primary path; fallback shuffles
    // via the EXACT current sort(()=>rnd()-.5) algorithm (not Fisher–Yates).
    function selectStandardSession(opts) {
      opts = opts || {};
      var levels = opts.levels || [];
      var limit = opts.limit;
      var now = getToday();
      var prog = getProgress();
      var levelSet = {};
      for (var i = 0; i < levels.length; i++) levelSet[levels[i]] = true;
      var inLevel = function (c) { return levelSet[c.level] === true; };

      // getAll() is the live source array (read-only); .filter() makes fresh arrays,
      // so source order is preserved and the source is never mutated.
      var all = repo.getAll();
      var due = all.filter(function (c) { return inLevel(c) && stateOf(prog, c.id, now).due <= now; });
      var fresh = all.filter(function (c) { return inLevel(c) && stateOf(prog, c.id, now).reps === 0; });

      var dueIds = {};
      for (var d = 0; d < due.length; d++) dueIds[due[d].id] = true;
      var merged = due.concat(fresh.filter(function (c) { return dueIds[c.id] !== true; }));

      var selected = applyLimit(merged, limit);
      if (!selected.length) {
        // Fallback: nothing due/fresh in the selected levels -> random review.
        var pool = all.filter(inLevel).slice();     // copy: never sort the source
        pool.sort(function () { return rnd() - 0.5; });
        selected = applyLimit(pool, limit);
      }
      return selected;
    }

    // Explicit-card session (Weak Words / Bookmarks): resolve ids via the repo in
    // REQUESTED order, dedup by resolved id, skip missing. No shuffle, no progress.
    function selectExplicitCardSession(ids) {
      var list = [], seen = {};
      var arr = ids || [];
      for (var i = 0; i < arr.length; i++) {
        var c = repo.getById(arr[i]);
        if (c && seen[c.id] !== true) { seen[c.id] = true; list.push(c); }
      }
      return list;
    }

    // Read-only classification helper (for characterization/tests). Returns id groups;
    // does not select or truncate. `due` and `fresh` follow the same rules as above and
    // a card may appear in both (untouched cards are due AND fresh).
    function classifyCards(opts) {
      opts = opts || {};
      var levels = opts.levels || [];
      var now = getToday();
      var prog = getProgress();
      var levelSet = {};
      for (var i = 0; i < levels.length; i++) levelSet[levels[i]] = true;
      var all = repo.getAll();
      var due = [], fresh = [];
      for (var j = 0; j < all.length; j++) {
        var c = all[j];
        if (levelSet[c.level] !== true) continue;
        var st = stateOf(prog, c.id, now);
        if (st.due <= now) due.push(c.id);
        if (st.reps === 0) fresh.push(c.id);
      }
      return { due: due, fresh: fresh };
    }

    return {
      selectStandardSession: selectStandardSession,
      selectExplicitCardSession: selectExplicitCardSession,
      classifyCards: classifyCards
    };
  }

  NS.createStudySessionQuery = createStudySessionQuery;

})(window.HSKUtil = window.HSKUtil || {});
