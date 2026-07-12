/* ============================================================
 *  core/util/levels.js — pure, deterministic level ordering.
 *  No DOM/storage/network/global-state. Generic (numeric suffix),
 *  not HSK-specific, but preserves current HSK1..HSK6 ordering exactly.
 * ============================================================ */
(function () {
  "use strict";
  var NS = (window.HSKUtil = window.HSKUtil || {});

  // Numeric order parsed from a level identifier's digits.
  // Byte-identical to the previous inline logic: parseInt(digits) || 0.
  // Unknown/empty/missing -> 0 (deterministic fallback, sorts first).
  function levelOrder(level) {
    return (parseInt(String(level).replace(/\D/g, ""), 10) || 0);
  }

  // Stable ascending sort by numeric order. Returns a new array (does not mutate input).
  function sortLevels(levels) {
    return (levels || []).slice().sort(function (a, b) { return levelOrder(a) - levelOrder(b); });
  }

  // Distinct, ordered level list derived from a cards array.
  // Equivalent to: [...new Set(cards.map(c=>c.level))].sort(byNumericOrder).
  function levelsFromCards(cards) {
    var seen = {}, out = [];
    (cards || []).forEach(function (c) {
      var lv = c && c.level;
      if (lv != null && !seen[lv]) { seen[lv] = 1; out.push(lv); }
    });
    return sortLevels(out);
  }

  NS.levels = { levelOrder: levelOrder, sortLevels: sortLevels, levelsFromCards: levelsFromCards };
})();
