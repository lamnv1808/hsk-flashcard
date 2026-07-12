/* ============================================================
 *  core/cards/card-repository.js — read-only CardRepository seam.
 *  Wraps the current production card dataset (window.HSK_CARDS) behind a
 *  small, immutable read API. Indexes are built ONCE at construction using
 *  the Phase 2 card-index/level utilities. No mutators, no cloning of the
 *  5,002 cards, no data.js/importer/schema change, no HSK literals in core.
 *  Depends on: core/util/card-index.js, core/util/levels.js (loaded first).
 * ============================================================ */
(function () {
  "use strict";
  var NS = (window.HSKUtil = window.HSKUtil || {});
  var CI = NS.cardIndex, LV = NS.levels;

  // Factory: build a read-only repository over a card array. Indexes built once.
  function createCardRepository(cards) {
    cards = cards || [];
    var byId = CI.buildCardById(cards);         // id -> card Map (built once)
    var byLevel = CI.buildCardsByLevel(cards);  // level -> [cards] (built once, source order)
    var levels = LV.levelsFromCards(cards);     // ordered distinct levels (computed once)
    var countByLevelCache = null;

    return {
      // All cards in source order. Returns the LIVE source array (no clone) — read-only.
      getAll: function () { return cards; },
      count: function () { return cards.length; },

      // Strict Map lookup (numeric-id contract preserved; callers coerce as they do today).
      getById: function (id) { return byId.get(id); },
      has: function (id) { return byId.has(id); },

      // Resolve many ids -> cards, in REQUESTED order, keeping duplicates, SKIPPING missing.
      // (Matches the previous `ids.map(id=>map.get(id)).filter(Boolean)` consumer.)
      getManyByIds: function (ids) {
        var out = [];
        (ids || []).forEach(function (id) { var c = byId.get(id); if (c) out.push(c); });
        return out;
      },

      // Cards of a level, in source order. Returns a fresh copy (matches previous
      // `cards.filter(...)` semantics; protects the internal index from mutation).
      getByLevel: function (level) { return (byLevel[level] || []).slice(); },
      getLevels: function () { return levels.slice(); },
      groupByLevel: function () { return byLevel; },  // read-only internal index
      countByLevel: function () {
        if (!countByLevelCache) {
          countByLevelCache = {};
          levels.forEach(function (l) { countByLevelCache[l] = (byLevel[l] || []).length; });
        }
        return countByLevelCache;
      },

      // Dev/test-only: duplicate-id detection (never affects production lookups).
      duplicateIds: function () { return CI.duplicateIds(cards); },
    };
  }

  NS.createCardRepository = createCardRepository;
  // Shared repository over the production dataset — instantiated ONCE at load.
  NS.cards = createCardRepository(window.HSK_CARDS || []);
})();
