/* ============================================================
 *  core/testing/test-mode-query.js  (FlashEdu — Phase 9)
 *  Read-only Test Mode QUESTION-GENERATION seam. Extracts the exact
 *  deterministic question/session construction from test.js: eligible-
 *  card selection, prompt/answer formatting, distractor generation,
 *  option shuffling and session assembly. Returns plain question data;
 *  test.js keeps ALL mutable session/UI state (index, selected answer,
 *  score, reveal, navigation, rendering, audio, history).
 *
 *  STRICT READ-ONLY CONTRACT:
 *    - never mutates cards/progress/settings/bookmarks/notes/source arrays
 *    - never grades SRS, creates progress rows, writes history, changes
 *      score, marks dirty, writes localStorage, enqueues sync, calls
 *      Supabase, touches DOM, or starts/stops audio
 *  Test Mode stays fully independent of Study progress and SRS.
 *
 *  Behavior is frozen to the current test.js. The single injected
 *  randomProvider (default Math.random) threads through BOTH the
 *  distractor sampling and the Phase 2 shuffle calls, preserving the
 *  exact algorithms and random-call order (production is byte-identical).
 * ============================================================ */
(function (NS) {
  "use strict";

  var SH = NS.shuffle;   // core/util/shuffle.js (Fisher–Yates; accepts an injected rnd)

  // Six question types (exact ids/labels/fields from test.js). q = prompt field;
  // a = answer field(s). These are Test Mode's type model (product config), not
  // generic orchestration. Kept here as the DEFAULT; a pack may inject its own
  // (byte-identical) defs via deps.typeDefs (Phase 11 — the active HSK pack owns them).
  var DEFAULT_TYPE_DEFS = [
    { id: 1, label: "Hán tự → Pinyin",         q: "word",   a: ["pinyin"] },
    { id: 2, label: "Pinyin → Hán tự",         q: "pinyin", a: ["word"] },
    { id: 3, label: "Hán tự → Nghĩa",          q: "word",   a: ["meaning"] },
    { id: 4, label: "Pinyin → Nghĩa",          q: "pinyin", a: ["meaning"] },
    { id: 5, label: "Hán tự → Pinyin + Nghĩa", q: "word",   a: ["pinyin", "meaning"] },
    { id: 6, label: "Pinyin → Hán tự + Nghĩa", q: "pinyin", a: ["word", "meaning"] }
  ];

  function trim(x) { return String(x == null ? "" : x).trim(); }

  function createTestModeQuery(deps) {
    deps = deps || {};
    var repo = deps.cardRepository;
    var rnd = (typeof deps.randomProvider === "function") ? deps.randomProvider : Math.random;
    // Type definitions: injected (from the active content pack) or the built-in default.
    var TYPE_DEFS = (Array.isArray(deps.typeDefs) && deps.typeDefs.length) ? deps.typeDefs : DEFAULT_TYPE_DEFS;

    function typeDef(id) { for (var i = 0; i < TYPE_DEFS.length; i++) if (TYPE_DEFS[i].id === id) return TYPE_DEFS[i]; return null; }
    function getTypeDefs() { return TYPE_DEFS.map(function (t) { return { id: t.id, label: t.label, q: t.q, a: t.a.slice() }; }); }

    function qField(type) { return typeDef(type).q; }
    function answerLines(card, type) { return typeDef(type).a.map(function (f) { return trim(card[f]); }); }
    function answerKey(card, type) { return answerLines(card, type).join(""); }
    function answerValid(card, type) { return typeDef(type).a.every(function (f) { return trim(card[f]) !== ""; }); }
    function questionValid(card, type) { return trim(card[qField(type)]) !== "" && answerValid(card, type); }

    // Eligible-card pool for the selected levels, in SOURCE ORDER (matches the
    // original CARDS.filter). getAll() is the live source array; .filter() copies.
    function getEligibleCards(opts) {
      var levels = (opts && opts.levels) || [];
      return repo.getAll().filter(function (c) { return levels.indexOf(c.level) >= 0; });
    }

    // Up to n distractor cards with distinct visible answer text (random sampling +
    // linear fallback). Skips candidates whose PROMPT equals the correct prompt, so
    // the prompt has exactly one valid answer among the options. rnd threaded.
    function pickDistractors(card, pool, type, n) {
      var qf = qField(type), qVal = trim(card[qf]);
      var seen = {}; seen[answerKey(card, type)] = 1;
      var out = [], attempts = 0, maxA = Math.min(160, pool.length * 3);
      function usable(c) {
        return c.id !== card.id && answerValid(c, type) && trim(c[qf]) !== qVal && !seen[answerKey(c, type)];
      }
      while (out.length < n && attempts < maxA) {
        attempts++;
        var c = pool[(rnd() * pool.length) | 0];
        if (!usable(c)) continue;
        seen[answerKey(c, type)] = 1; out.push(c);
      }
      if (out.length < n) {
        for (var i = 0; i < pool.length && out.length < n; i++) {
          var d = pool[i];
          if (!usable(d)) continue;
          seen[answerKey(d, type)] = 1; out.push(d);
        }
      }
      return out;
    }

    // Build one question, or null if a valid (>=2 distinct options) question is
    // impossible. Returns the SAME shape as the original (incl. the initial mutable
    // fields answeredIndex/correct/revealed that test.js owns thereafter).
    function createQuestion(args) {
      var card = args.card, pool = args.pool, type = args.type;
      if (!questionValid(card, type)) return null;
      var distractors = pickDistractors(card, pool, type, 3);
      if (distractors.length < 1) return null;
      var opts = [{ card: card, isCorrect: true }];
      distractors.forEach(function (c) { opts.push({ card: c, isCorrect: false }); });
      SH.shuffleInPlace(opts, rnd);
      return {
        card: card, type: type,
        options: opts.map(function (o) { return { card: o.card, isCorrect: o.isCorrect, lines: answerLines(o.card, type) }; }),
        correctIndex: opts.map(function (o) { return o.isCorrect; }).indexOf(true),
        answeredIndex: null, correct: null, revealed: false
      };
    }

    function firstBuildable(card, pool, types) {
      var order = SH.shuffledCopy(types, rnd);
      for (var i = 0; i < order.length; i++) { var q = createQuestion({ card: card, pool: pool, type: order[i] }); if (q) return q; }
      return null;
    }

    // Full session (== buildTest). Also the redo generator (redo just calls this
    // again with the same cfg -> a freshly shuffled session).
    function createSession(cfg) {
      cfg = cfg || {};
      var pool = getEligibleCards({ levels: cfg.levels || [] });
      var types = cfg.mix ? [1, 2, 3, 4, 5, 6] : (cfg.types || []).slice();
      var N = cfg.count === "all" ? pool.length : Math.min(parseInt(cfg.count, 10), pool.length);
      var cardOrder = SH.shuffledCopy(pool, rnd);
      // balanced type assignment: round-robin then shuffle
      var assign = [];
      for (var i = 0; i < N; i++) assign.push(types[i % types.length]);
      SH.shuffleInPlace(assign, rnd);
      var questions = [], idx = 0;
      while (questions.length < N && idx < cardOrder.length) {
        var card = cardOrder[idx++];
        var want = assign[questions.length];
        var q = createQuestion({ card: card, pool: pool, type: want }) || firstBuildable(card, pool, types);
        if (q) questions.push(q);
      }
      return questions;
    }

    return {
      getTypeDefs: getTypeDefs,
      typeDef: typeDef,
      qField: qField,
      answerLines: answerLines,
      getEligibleCards: getEligibleCards,
      createQuestion: createQuestion,
      createSession: createSession
    };
  }

  NS.createTestModeQuery = createTestModeQuery;
  // Shared instance over the production CardRepository (Math.random in production).
  // Test Mode type definitions are sourced from the active content pack (Phase 11);
  // they are byte-identical to DEFAULT_TYPE_DEFS, so behavior is unchanged.
  NS.testMode = createTestModeQuery({
    cardRepository: NS.cards,
    typeDefs: (NS.contentPack && NS.contentPack.getTestModes()) || null
  });

})(window.HSKUtil = window.HSKUtil || {});
