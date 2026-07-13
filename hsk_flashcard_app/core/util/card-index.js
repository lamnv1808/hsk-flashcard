/* ============================================================
 *  core/util/card-index.js — deterministic card lookup/index builders.
 *  Pure: does NOT mutate or clone card objects; builds an index once.
 *  ID handling matches the current contract (Map keyed by the raw id;
 *  last-wins on duplicate, same as new Map(cards.map(...))).
 * ============================================================ */
(function () {
  "use strict";
  var NS = (window.HSKUtil = window.HSKUtil || {});

  // id -> card Map. Equivalent to `new Map(cards.map(c => [c.id, c]))`.
  // Does not coerce ids and does not copy card objects (references only).
  function buildCardById(cards) {
    var m = new Map();
    (cards || []).forEach(function (c) { m.set(c.id, c); });
    return m;
  }

  // Lookup helper (thin wrapper over Map.get) — reserved companion to buildCardById.
  function getCardById(index, id) {
    return index ? index.get(id) : undefined;
  }

  // level -> [cards] grouping, preserving source order within each level.
  // Tested + provided for Phase 3; not yet wired into runtime call sites.
  function buildCardsByLevel(cards) {
    var out = {};
    (cards || []).forEach(function (c) {
      var lv = c && c.level;
      if (lv == null) return;
      (out[lv] || (out[lv] = [])).push(c);
    });
    return out;
  }

  // Duplicate-id detection for TEST/DEV paths only (does not affect production lookups).
  function duplicateIds(cards) {
    var seen = {}, dups = [];
    (cards || []).forEach(function (c) {
      if (seen[c.id]) dups.push(c.id); else seen[c.id] = 1;
    });
    return dups;
  }

  NS.cardIndex = {
    buildCardById: buildCardById, getCardById: getCardById,
    buildCardsByLevel: buildCardsByLevel, duplicateIds: duplicateIds,
  };
})();
