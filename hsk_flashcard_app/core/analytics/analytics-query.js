/* ============================================================
 *  core/analytics/analytics-query.js  (FlashEdu — Phase 6)
 *  Read-only ANALYTICS / dashboard read-model seam. Centralizes the
 *  existing display computations (home summary, per-level summary,
 *  Weak Words ranking, Smart Review model, daily-learning series)
 *  with ZERO write side-effects. It returns plain data; app.js and
 *  insights.js keep all DOM/SVG rendering.
 *
 *  STRICT READ-ONLY CONTRACT:
 *    - never mutates progress / settings / cards / source arrays
 *    - never updates streak or daily counts, never creates progress
 *      rows for untouched cards, never marks dirty / writes storage /
 *      enqueues sync / calls Supabase / grades / changes SRS
 *    - no DOM, no audio, no network
 *
 *  Formulas are frozen to the CURRENT runtime (app.js renderHome +
 *  insights.js). A future analytics v2 may differ — out of scope.
 * ============================================================ */
(function (NS) {
  "use strict";

  var DATE = NS.date;   // core/util/date.js (localDay = LOCAL day, isoDay = UTC day)
  var DAY_MS = 86400000;

  // deps:
  //   cardRepository      - Phase 3 repo (getAll/getById/getByLevel/getLevels)
  //   progressProvider    - () => live progress map { "<id>": {due,interval,reps,correct,attempts} }
  //   settingsRepository  - Phase 4 repo (getStreak)
  //   dailyCountsProvider - () => live daily-counts map { "YYYY-MM-DD": int } (LOCAL day keys)
  //   dateProvider        - () => Date "now"  (default new Date(); injectable for tests)
  function createAnalyticsQuery(deps) {
    deps = deps || {};
    var repo = deps.cardRepository;
    var settings = deps.settingsRepository;
    var getProgress = fn(deps.progressProvider, {});
    var getDaily = fn(deps.dailyCountsProvider, {});
    var getNow = (typeof deps.dateProvider === "function") ? deps.dateProvider : function () { return new Date(); };

    function fn(p, empty) {
      return (typeof p === "function") ? p : function () { return p || empty; };
    }

    // Mirror of app.js getCardState(): live row else the SAME default shape.
    // Reading NEVER writes the row (untouched card stays untouched).
    function stateOf(prog, id, todayStr) {
      return prog[id] || { due: todayStr, interval: 0, reps: 0, correct: 0, attempts: 0 };
    }

    /* -------------------- HOME / DASHBOARD SUMMARY -------------------- */
    // Global counts (over ALL cards / ALL progress rows), matching renderHome:
    //   learned  = cards with reps>0
    //   attempts = sum of progress.attempts ; correct = sum of progress.correct
    //   retention= attempts ? round(correct/attempts*100)+"%" : "0%"
    //   dueCount = cards in `levels` with due<=today (untouched count as due)
    function getHomeSummary(levels) {
      var prog = getProgress();
      var todayStr = DATE.isoDay(getNow());
      var all = repo.getAll();
      var levelSet = null;
      if (levels && levels.length) { levelSet = {}; for (var i = 0; i < levels.length; i++) levelSet[levels[i]] = true; }

      var learned = 0, dueCount = 0;
      for (var j = 0; j < all.length; j++) {
        var c = all[j], st = stateOf(prog, c.id, todayStr);
        if (st.reps > 0) learned++;
        if ((!levelSet || levelSet[c.level] === true) && st.due <= todayStr) dueCount++;
      }
      var attempts = 0, correct = 0, keys = Object.keys(prog);
      for (var k = 0; k < keys.length; k++) { var x = prog[keys[k]]; attempts += (x.attempts || 0); correct += (x.correct || 0); }

      var retentionPct = attempts ? Math.round(correct / attempts * 100) : 0;
      return {
        total: repo.count(),
        learned: learned,
        attempts: attempts,
        correct: correct,
        retentionPct: retentionPct,
        retentionText: attempts ? retentionPct + "%" : "0%",
        dueCount: dueCount
      };
    }

    // Per-level rows in the given order: {level,total,learned,due,pct}.
    // pct = round(learned/total*100) (matches renderHome; total 0 -> NaN as before).
    function getLevelSummary(levels) {
      var prog = getProgress();
      var todayStr = DATE.isoDay(getNow());
      var order = (levels && levels.length) ? levels : repo.getLevels();
      var out = [];
      for (var i = 0; i < order.length; i++) {
        var lv = order[i], all = repo.getByLevel(lv);
        var learned = 0, due = 0;
        for (var j = 0; j < all.length; j++) {
          var st = stateOf(prog, all[j].id, todayStr);
          if (st.reps > 0) learned++;
          if (st.due <= todayStr) due++;
        }
        out.push({ level: lv, total: all.length, learned: learned, due: due, pct: Math.round(learned / all.length * 100) });
      }
      return out;
    }

    /* -------------------- WEAK WORDS -------------------- */
    function lastGradedDate(st) {
      if (!st.due) return null;
      var due = new Date(st.due + "T00:00:00");
      if (isNaN(due)) return null;
      return new Date(due.getTime() - (st.interval || 0) * DAY_MS);
    }
    function daysSince(d, nowMs) { if (!d) return 30; return Math.max(0, Math.round((nowMs - d.getTime()) / DAY_MS)); }
    function weakness(st, nowMs) {
      var attempts = st.attempts || 0;
      if (attempts <= 0) return null;
      var failures = attempts - (st.correct || 0);
      if (failures <= 0) return 0;
      var sfr = (failures + 1) / (attempts + 2);
      var rec = 1 / (1 + daysSince(lastGradedDate(st), nowMs) / 14);
      return failures * sfr * rec;
    }

    // Ranked weak-word read model (== insights.weakCards). level "all"/falsy = no filter.
    // sort: score desc, then failures desc. Untouched/never-failed excluded.
    function getWeakWords(levelFilter) {
      var prog = getProgress(), nowMs = getNow().getTime(), out = [];
      Object.keys(prog).forEach(function (id) {
        var card = repo.getById(Number(id)); if (!card) return;
        if (levelFilter && levelFilter !== "all" && card.level !== levelFilter) return;
        var st = prog[id], w = weakness(st, nowMs);
        if (w == null || w <= 0) return;
        out.push({ card: card, st: st, score: w, failures: (st.attempts || 0) - (st.correct || 0), attempts: st.attempts || 0, last: lastGradedDate(st) });
      });
      out.sort(function (a, b) { return b.score - a.score || b.failures - a.failures; });
      return out;
    }

    /* -------------------- SMART REVIEW MODEL -------------------- */
    // Semantic model behind renderInsights (presentation stays in insights.js).
    function getSmartReviewModel() {
      var prog = getProgress(), nowMs = getNow().getTime();
      var touched = Object.keys(prog);
      if (!touched.length) return { hasData: false };

      var byLvl = {};
      touched.forEach(function (id) {
        var card = repo.getById(Number(id)); if (!card) return;
        var st = prog[id], a = st.attempts || 0; if (!a) return;
        var l = byLvl[card.level] || (byLvl[card.level] = { att: 0, cor: 0 });
        l.att += a; l.cor += (st.correct || 0);
      });
      var lvlStats = Object.keys(byLvl).filter(function (l) { return byLvl[l].att >= 10; })
        .map(function (l) { return { level: l, ret: byLvl[l].cor / byLvl[l].att }; });
      var levelRetention = null;
      if (lvlStats.length) {
        lvlStats.sort(function (a, b) { return a.ret - b.ret; });
        var top = lvlStats[lvlStats.length - 1];
        levelRetention = {
          weakest: { level: lvlStats[0].level, pct: Math.round(lvlStats[0].ret * 100) },
          strongest: { level: top.level, pct: Math.round(top.ret * 100) }
        };
      }

      var weak = getWeakWords("all");
      var recent = weak.filter(function (x) { return x.last && daysSince(x.last, nowMs) <= 7; }).length;

      var dc = getDaily();
      return {
        hasData: true,
        levelRetention: levelRetention,
        weakCount: weak.length,
        recentStruggles: recent,
        today: dc[DATE.localDay(getNow())] || 0,
        last7: sumDays(dc, 7),
        last30: sumDays(dc, 30),
        streak: settings ? settings.getStreak() : 0
      };
    }

    function sumDays(dc, n) {
      var t = 0, nowMs = getNow().getTime();
      for (var i = 0; i < n; i++) { var d = new Date(nowMs - i * DAY_MS); t += dc[DATE.localDay(d)] || 0; }
      return t;
    }

    /* -------------------- DAILY LEARNING SERIES -------------------- */
    // {labels:[Date oldest..newest], values:[int], total, max, average}.
    // value = dailyCounts[localDay(day)] || 0 ; max = Math.max(1, max(values)).
    function getDailySeries(days) {
      var dc = getDaily(), nowMs = getNow().getTime(), labels = [], values = [];
      for (var i = days - 1; i >= 0; i--) {
        var d = new Date(nowMs - i * DAY_MS);
        labels.push(d); values.push(dc[DATE.localDay(d)] || 0);
      }
      var total = values.reduce(function (a, b) { return a + b; }, 0);
      var max = Math.max(1, Math.max.apply(null, values));
      return { labels: labels, values: values, total: total, max: max, average: total / days };
    }

    return {
      getHomeSummary: getHomeSummary,
      getLevelSummary: getLevelSummary,
      getWeakWords: getWeakWords,
      getSmartReviewModel: getSmartReviewModel,
      getDailySeries: getDailySeries
    };
  }

  NS.createAnalyticsQuery = createAnalyticsQuery;
  // Shared instance for consumers outside app.js (insights.js), which load after
  // app.js (HSK_APP) and metadata.js (HSKMeta). Providers are lazy, so the later
  // existence of those bridges is fine.
  NS.analytics = createAnalyticsQuery({
    cardRepository: NS.cards,
    progressProvider: function () { return (window.HSK_APP && window.HSK_APP.getProgress()) || {}; },
    settingsRepository: NS.settings,
    dailyCountsProvider: function () { return (window.HSKMeta && window.HSKMeta.dailyCounts()) || {}; },
    dateProvider: function () { return new Date(); }
  });

})(window.HSKUtil = window.HSKUtil || {});
