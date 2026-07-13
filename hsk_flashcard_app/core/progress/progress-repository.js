/* ============================================================
 *  core/progress/progress-repository.js  (FlashEdu — Phase 8)
 *  Read-only PROGRESS read seam over the per-user progress object
 *  ({ "<cardId>": {due,interval,reps,correct,attempts} }). It freezes
 *  and centralizes the exact read + default-state contract that was
 *  duplicated inline as app.js getCardState() and the StudySessionQuery/
 *  AnalyticsQuery stateOf() helpers.
 *
 *  READ-ONLY ONLY (write capability is a later, separately characterized
 *  phase). It never:
 *    - creates a progress row (reading an untouched card creates nothing)
 *    - assigns/mutates progress[cardId] or any field (due/interval/reps/
 *      attempts/correct)
 *    - grades/schedules, updates streak/daily counts, marks dirty,
 *      writes localStorage, enqueues sync, calls Supabase
 *    - mutates cards/settings/metadata, touches DOM
 *
 *  It owns ONLY per-card learning progress reads — NOT bookmarks, notes,
 *  settings, dailyCounts, streak, cards, Test Mode, auth or sync transport.
 *
 *  Schema/default are frozen to the current runtime (DATA_CONTRACTS §2).
 * ============================================================ */
(function (NS) {
  "use strict";

  var HAS = Object.prototype.hasOwnProperty;

  // deps:
  //   progressProvider - () => live progress map. Re-read every call so
  //     reloadState() reassignment (cloud pull), account switch and sync
  //     merges are observed with no stale capture.
  function createProgressRepository(deps) {
    deps = deps || {};
    var read = (typeof deps.progressProvider === "function")
      ? deps.progressProvider
      : function () { return deps.progressProvider; };

    function prog() {
      var p = read();
      return (p && typeof p === "object") ? p : {};
    }

    // stored row or undefined (LIVE reference — read-only by contract).
    function getStored(cardId) { return prog()[cardId]; }

    // has a stored row? (numeric id coerces to string key, as everywhere).
    function has(cardId) { return HAS.call(prog(), cardId); }
    function isTouched(cardId) { return has(cardId); }

    // EXACT mirror of getCardState()/stateOf(): live row for a touched card,
    // else a freshly-allocated default whose `due` is the caller's today key.
    // Never writes the row back.
    function getOrDefault(cardId, todayKey) {
      var p = prog();
      return p[cardId] || { due: todayKey, interval: 0, reps: 0, correct: 0, attempts: 0 };
    }

    function getCardIds() { return Object.keys(prog()); }         // string keys, enumeration order
    function getEntries() {
      var p = prog(), ks = Object.keys(p), out = [];
      for (var i = 0; i < ks.length; i++) out.push([ks[i], p[ks[i]]]);
      return out;
    }
    function count() { return Object.keys(prog()).length; }

    // learned = a stored row with reps>0 (untouched default reps 0 => false).
    function isLearned(cardId) {
      var r = prog()[cardId];
      return !!(r && r.reps > 0);
    }
    // due = getOrDefault(id,today).due <= today (untouched => due today => true).
    function isDue(cardId, todayKey) {
      return getOrDefault(cardId, todayKey).due <= todayKey;
    }

    return {
      has: has,
      isTouched: isTouched,
      getStored: getStored,
      getOrDefault: getOrDefault,
      getCardIds: getCardIds,
      getEntries: getEntries,
      count: count,
      isLearned: isLearned,
      isDue: isDue
    };
  }

  NS.createProgressRepository = createProgressRepository;
  // Shared instance over the active account's live progress (via the app bridge).
  // Provided for symmetry/tests; app.js injects its own instance into the queries.
  NS.progress = createProgressRepository({
    progressProvider: function () { return (window.HSK_APP && window.HSK_APP.getProgress()) || {}; }
  });

})(window.HSKUtil = window.HSKUtil || {});
