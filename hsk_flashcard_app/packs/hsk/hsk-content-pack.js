/* ============================================================
 *  packs/hsk/hsk-content-pack.js  (FlashEdu — Phase 10)
 *  The HSK content-pack ADAPTER: the first (and, in Phase 10, only)
 *  content pack. It wraps the EXISTING production dataset (window.HSK_CARDS)
 *  behind the generic ContentPack contract — same cards, ids, order,
 *  fields and behavior. No data migration, no clone, no data.js change.
 *
 *  ALL HSK/Chinese-specific facts live here (not in the generic core):
 *  field-role mapping, languages, capabilities, Test Mode types, and the
 *  deck set — which is DERIVED from the cards (so adding HSK7 needs no code
 *  change), exactly like the rest of the app.
 *
 *  Publishes the single active read-only pack as HSKUtil.contentPack.
 *  Depends on: data.js (HSK_CARDS), core/util/levels.js + card-index.js,
 *  core/content/content-pack.js (loaded first).
 * ============================================================ */
(function (NS) {
  "use strict";

  var CARDS = window.HSK_CARDS || [];
  var LV = NS.levels, CI = NS.cardIndex;

  // Semantic role -> legacy card field. The engine-facing roles are generic;
  // the field names are the HSK product's current fields (unchanged at runtime).
  var FIELD_ROLES = {
    primaryPrompt: "word",           // Hán tự
    pronunciation: "pinyin",         // pinyin
    definition: "meaning",           // Vietnamese meaning
    exampleText: "example",          // Chinese example
    examplePronunciation: "examplePinyin",
    exampleTranslation: "translation",
    deck: "level",                   // HSK level = deck
    stableId: "id"                   // 1..5002, stable + immutable
  };

  // Test Mode type definitions for HSK (byte-identical to TestModeQuery's built-in
  // TYPE_DEFS). DESCRIPTIVE in Phase 10 — TestModeQuery keeps its own defs; wiring
  // is deferred (a characterization test asserts these match exactly).
  var TEST_MODES = [
    { id: 1, label: "Hán tự → Pinyin",         q: "word",   a: ["pinyin"] },
    { id: 2, label: "Pinyin → Hán tự",         q: "pinyin", a: ["word"] },
    { id: 3, label: "Hán tự → Nghĩa",          q: "word",   a: ["meaning"] },
    { id: 4, label: "Pinyin → Nghĩa",          q: "pinyin", a: ["meaning"] },
    { id: 5, label: "Hán tự → Pinyin + Nghĩa", q: "word",   a: ["pinyin", "meaning"] },
    { id: 6, label: "Pinyin → Hán tự + Nghĩa", q: "pinyin", a: ["word", "meaning"] }
  ];

  // Decks derived from the cards (ordered by numeric level suffix, with counts) —
  // NOT hardcoded to six, so HSK7+ appears automatically.
  function deckProvider(cards) {
    var order = LV.levelsFromCards(cards);          // ["HSK1".."HSK6"] in numeric order
    var counts = CI.buildCardsByLevel(cards);       // level -> [cards]
    return order.map(function (id, i) {
      return { id: id, order: i + 1, title: id, cardCount: (counts[id] || []).length };
    });
  }

  var pack = NS.createContentPack({
    id: "hsk",
    version: "1.0.0",
    title: "HSK Tiếng Trung",
    languages: { prompt: "zh", reading: "pinyin", meaning: "vi", audio: "zh-CN" },
    capabilities: ["study", "srs", "test", "audio", "frontReadingToggle", "examples", "translation", "bookmarks", "notes", "analytics"],
    fieldRoles: FIELD_ROLES,
    testModes: TEST_MODES,
    deckProvider: deckProvider,
    getCards: function () { return window.HSK_CARDS || []; }   // live source; never cloned
  });

  // The single active content pack (read-only). No registry, no switcher.
  NS.contentPack = pack;
})(window.HSKUtil = window.HSKUtil || {});
