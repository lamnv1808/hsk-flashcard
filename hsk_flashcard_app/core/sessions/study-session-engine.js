/* ============================================================
 *  core/sessions/study-session-engine.js  (FlashEdu — Phase 16)
 *  Read-only Study session/card READ-MODEL engine. It COMPOSES the
 *  existing seams (ContentPack, CardRepository, ProgressRepository,
 *  SettingsRepository, StudySessionQuery, UserMetadataQuery) to
 *  DESCRIBE a study session — it owns no mutable runtime state and no DOM.
 *
 *  It is NOT a controller. It never mutates session/current/flipped/
 *  snapshots/sessionGrades/progress/settings/metadata, never grades/
 *  restores/resets/saves/marks-dirty/syncs, never writes storage, changes
 *  the index, flips cards, captures snapshots, renders HTML, plays audio,
 *  or calls Supabase. Every method is side-effect-free.
 *
 *  Session SELECTION is NOT reimplemented — it delegates to Phase 5
 *  StudySessionQuery (exact due/fresh/fallback/explicit behavior). The
 *  engine only normalizes request params and packages read models.
 *
 *  AuthContextQuery is intentionally NOT a dependency: the Study read
 *  model needs cards/progress/settings/metadata, not account identity.
 * ============================================================ */
(function (NS) {
  "use strict";

  // deps:
  //   contentPack        - Phase 10 (field roles: primaryPrompt/pronunciation/... /deck)
  //   cardRepository     - Phase 3 (getById for describeCard by id)
  //   progressRepository - Phase 8 (isLearned / isDue)
  //   settingsRepository - Phase 4 (getFrontPinyinEnabled)
  //   studySessionQuery  - Phase 5 (selectStandardSession / selectExplicitCardSession)
  //   userMetadataQuery  - Phase 7 (isBookmarked / hasNote / getNote)
  //   dateProvider       - () => "YYYY-MM-DD" today key (for `due`); default UTC today
  function createStudySessionEngine(deps) {
    deps = deps || {};
    var pack = deps.contentPack;
    var cardRepo = deps.cardRepository;
    var progressRepo = deps.progressRepository;
    var settingsRepo = deps.settingsRepository;
    var sessionQuery = deps.studySessionQuery;
    var metaQuery = deps.userMetadataQuery;
    var getToday = (typeof deps.dateProvider === "function")
      ? deps.dateProvider
      : function () { return new Date().toISOString().slice(0, 10); };

    // Field-role helpers (generic via ContentPack; falls back to legacy field names).
    function role(name, fallback) { return (pack && pack.getRole && pack.getRole(name)) || fallback; }
    var F_PROMPT = role("primaryPrompt", "word");
    var F_PRON = role("pronunciation", "pinyin");
    var F_DEF = role("definition", "meaning");
    var F_EX = role("exampleText", "example");
    var F_EXPRON = role("examplePronunciation", "examplePinyin");
    var F_EXTR = role("exampleTranslation", "translation");
    var F_DECK = role("deck", "level");

    // Distinct deck labels in session order (matches the current studyLevel join).
    function deckLabel(cards) {
      var seen = {}, out = [];
      for (var i = 0; i < cards.length; i++) {
        var d = cards[i][F_DECK];
        if (!seen[d]) { seen[d] = 1; out.push(d); }
      }
      return out.join(" + ");
    }

    // Session read model. `cards` is the SAME array reference the query returned
    // (not cloned — the query already made a fresh array). currentIndex is a plain
    // input; the engine owns none of it.
    function describeSession(opts) {
      opts = opts || {};
      var cards = opts.cards || [];
      var idx = (typeof opts.currentIndex === "number") ? opts.currentIndex : 0;
      var total = cards.length;
      var inRange = idx >= 0 && idx < total;
      return {
        cards: cards,
        total: total,
        currentIndex: idx,
        currentCard: inRange ? cards[idx] : null,
        currentNumber: idx + 1,                                  // 1-based (== cardIndex)
        remaining: Math.max(0, total - idx),                     // cards from current to end
        completed: idx >= total,                                 // == the renderCard completion guard
        deckLabel: deckLabel(cards),
        progressPct: total ? (idx / total) * 100 : 0             // caller appends "%"
      };
    }

    // Standard session: normalize sessionSize -> limit, delegate to Phase 5, package.
    function buildSession(opts) {
      opts = opts || {};
      var levels = opts.levels || [];
      var size = opts.sessionSize;
      var limit = size === "all" ? "all" : Number(size);
      var cards = sessionQuery.selectStandardSession({ levels: levels, limit: limit });
      return describeSession({ cards: cards, currentIndex: 0 });
    }

    // Explicit-card session (Weak Words / Bookmarks): delegate to Phase 5, package.
    function buildExplicitSession(opts) {
      opts = opts || {};
      var cards = sessionQuery.selectExplicitCardSession(opts.cardIds);
      return describeSession({ cards: cards, currentIndex: 0 });
    }

    // Card read model. Answer-leak-safe by STRUCTURE: `front` carries only the prompt
    // (+ pronunciation), `back` carries the answer fields. A front-only UI reads `.front`
    // and never sees the answer, regardless of `flipped`. The engine owns no flip state;
    // `flipped` is echoed for consumers. No card mutation.
    function describeCard(opts) {
      opts = opts || {};
      var card = opts.card || (cardRepo && cardRepo.getById(opts.cardId));
      if (!card) return null;
      var id = card[role("stableId", "id")];
      return {
        id: id,
        deckId: card[F_DECK],
        flipped: !!opts.flipped,
        frontPinyinVisible: settingsRepo ? settingsRepo.getFrontPinyinEnabled() : true,
        // audio/read flags (renderCard/flipCard read these; the engine never plays audio)
        autoReadWord: settingsRepo ? settingsRepo.getAutoReadWordEnabled() : false,
        autoReadExample: settingsRepo ? settingsRepo.getAutoReadExampleEnabled() : false,
        speechRate: settingsRepo ? settingsRepo.getSpeechRate() : 1,
        front: {
          primary: card[F_PROMPT],
          pronunciation: card[F_PRON]
        },
        back: {
          primary: card[F_PROMPT],
          pronunciation: card[F_PRON],
          definition: card[F_DEF],
          example: card[F_EX],
          examplePronunciation: card[F_EXPRON],
          translation: card[F_EXTR]
        },
        bookmarked: metaQuery ? metaQuery.isBookmarked(id) : false,
        hasNote: metaQuery ? metaQuery.hasNote(id) : false,
        note: metaQuery ? metaQuery.getNote(id) : "",
        learned: progressRepo ? progressRepo.isLearned(id) : false,
        due: progressRepo ? progressRepo.isDue(id, getToday()) : true
      };
    }

    return {
      buildSession: buildSession,
      buildExplicitSession: buildExplicitSession,
      describeSession: describeSession,
      describeCard: describeCard
    };
  }

  NS.createStudySessionEngine = createStudySessionEngine;
})(window.HSKUtil = window.HSKUtil || {});
