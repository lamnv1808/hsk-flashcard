/* ============================================================
 *  core/content/content-pack.js  (FlashEdu — Phase 10)
 *  Generic, read-only ContentPack contract. A content pack is a
 *  versioned bundle of learning content plus the semantic metadata
 *  the engine needs to present and test it. This GENERIC core hardcodes
 *  NOTHING product-specific — no HSK/Chinese/pinyin/Vietnamese, no fixed
 *  deck set, no fixed card count. Those facts live in the pack adapter
 *  (packs/<id>/…) and tests.
 *
 *  READ-ONLY: a pack never mutates its source cards/arrays, never writes
 *  storage/network, never touches progress/settings/DOM. It is a
 *  descriptive read seam over an existing card source; it does NOT clone
 *  the cards (getCards() returns the live source array).
 *
 *  Contract derived from the current HSK product's actual needs
 *  (see docs/architecture/CONTENT_PACK_STANDARD.md).
 * ============================================================ */
(function (NS) {
  "use strict";

  function isObj(x) { return x && typeof x === "object"; }

  // spec:
  //   id            (string, required)   - stable pack slug
  //   version       (string)             - semver
  //   title         (string)             - display name
  //   languages     ({role: code})       - e.g. { prompt, reading, meaning, audio }
  //   capabilities  (string[])           - declared engine capabilities
  //   fieldRoles    ({role: fieldName})  - semantic role -> legacy card field
  //   testModes     (any[])              - MCQ type definitions valid for this pack
  //   getCards      (() => card[])       - live source card array (NOT cloned)
  //   decks         (deck[])  OR
  //   deckProvider  ((cards) => deck[])  - derive decks from the cards (preferred)
  function createContentPack(spec) {
    spec = spec || {};
    var id = spec.id;
    var getCardsFn = (typeof spec.getCards === "function") ? spec.getCards : function () { return spec.getCards || []; };
    var fieldRoles = isObj(spec.fieldRoles) ? spec.fieldRoles : {};
    var languages = isObj(spec.languages) ? spec.languages : {};
    var capabilities = Array.isArray(spec.capabilities) ? spec.capabilities.slice() : [];
    var testModes = Array.isArray(spec.testModes) ? spec.testModes : [];

    // Decks: either provided explicitly or derived from the cards (built ONCE here).
    var decks;
    if (typeof spec.deckProvider === "function") decks = spec.deckProvider(getCardsFn()) || [];
    else decks = Array.isArray(spec.decks) ? spec.decks.slice() : [];

    function copyDeck(d) { return { id: d.id, order: d.order, title: d.title, cardCount: d.cardCount }; }

    var pack = {
      getId: function () { return id; },
      getVersion: function () { return spec.version; },
      getTitle: function () { return spec.title; },
      getLanguages: function () { var o = {}, k; for (k in languages) if (languages.hasOwnProperty(k)) o[k] = languages[k]; return o; },
      getCapabilities: function () { return capabilities.slice(); },
      hasCapability: function (c) { return capabilities.indexOf(c) >= 0; },

      // Live source card array (read-only by contract; NOT cloned).
      getCards: function () { return getCardsFn(); },

      // Ordered deck metadata (copies, so callers can't mutate the internal list).
      getDecks: function () { return decks.map(copyDeck); },
      getDeckIds: function () { return decks.map(function (d) { return d.id; }); },

      // Semantic role -> legacy field name (e.g. "primaryPrompt" -> "word").
      getFieldRoles: function () { var o = {}, k; for (k in fieldRoles) if (fieldRoles.hasOwnProperty(k)) o[k] = fieldRoles[k]; return o; },
      getRole: function (role) { return fieldRoles[role]; },

      // Test Mode type definitions valid for this pack (descriptive in Phase 10).
      getTestModes: function () { return testModes.map(function (t) { return isObj(t) ? { id: t.id, label: t.label, q: t.q, a: t.a.slice() } : t; }); },

      // Lightweight dev/test validation. NOT run on hot production paths.
      validate: function () {
        var errors = [], warnings = [];
        var cards = getCardsFn();
        if (!id || typeof id !== "string") errors.push("missing pack id");
        // unique stable ids
        var stable = fieldRoles.stableId || "id";
        var seen = {}, dupIds = 0;
        for (var i = 0; i < cards.length; i++) { var k = cards[i][stable]; if (seen[k]) dupIds++; else seen[k] = 1; }
        if (dupIds) errors.push(dupIds + " duplicate stable ids");
        // deck ids unique + referenced by cards
        var deckIds = {}, dupDecks = 0;
        decks.forEach(function (d) { if (deckIds[d.id]) dupDecks++; else deckIds[d.id] = 1; });
        if (dupDecks) errors.push(dupDecks + " duplicate deck ids");
        var deckField = fieldRoles.deck;
        var badRef = 0, byDeck = {};
        if (deckField) {
          for (var j = 0; j < cards.length; j++) {
            var dv = cards[j][deckField];
            byDeck[dv] = (byDeck[dv] || 0) + 1;
            if (!deckIds[dv]) badRef++;
          }
          if (badRef) errors.push(badRef + " cards reference an undeclared deck");
        }
        // required roles present as field names
        ["primaryPrompt", "stableId", "deck"].forEach(function (r) {
          if (!fieldRoles[r]) warnings.push("missing required role: " + r);
        });
        return {
          packId: id, version: spec.version, ok: errors.length === 0,
          cards: cards.length, decks: decks.length, byDeck: byDeck,
          idsUnique: dupIds === 0, deckRefsValid: badRef === 0,
          errors: errors, warnings: warnings
        };
      }
    };
    return pack;
  }

  NS.createContentPack = createContentPack;
})(window.HSKUtil = window.HSKUtil || {});
