/* ============================================================
 *  test.js — multiple-choice TEST MODE (additive, self-contained).
 *  - Completely separate from Study Mode and SRS.
 *  - Never mutates progress, cards, settings, or triggers cloud sync.
 *  - Reuses existing audio (window.speak / window.stopSpeech) and the
 *    global --app-h for the mobile one-screen layout.
 *  Wrapped in an IIFE so it adds no globals except window.TestMode.
 * ============================================================ */
(function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };
  var CARDS = window.HSK_CARDS || [];

  // Six question types. q = field shown as the prompt; a = field(s) used for choices.
  var TYPE_DEFS = [
    { id: 1, label: "Hán tự → Pinyin",        q: "word",   a: ["pinyin"] },
    { id: 2, label: "Pinyin → Hán tự",        q: "pinyin", a: ["word"] },
    { id: 3, label: "Hán tự → Nghĩa",         q: "word",   a: ["meaning"] },
    { id: 4, label: "Pinyin → Nghĩa",         q: "pinyin", a: ["meaning"] },
    { id: 5, label: "Hán tự → Pinyin + Nghĩa", q: "word",   a: ["pinyin", "meaning"] },
    { id: 6, label: "Pinyin → Hán tự + Nghĩa", q: "pinyin", a: ["word", "meaning"] }
  ];
  function typeDef(id) { for (var i = 0; i < TYPE_DEFS.length; i++) if (TYPE_DEFS[i].id === id) return TYPE_DEFS[i]; return null; }

  var LEVELS = (function () {
    var s = {}; CARDS.forEach(function (c) { s[c.level] = 1; });
    return Object.keys(s).sort(function (a, b) {
      return (parseInt(String(a).replace(/\D/g, ""), 10) || 0) - (parseInt(String(b).replace(/\D/g, ""), 10) || 0);
    });
  })();

  // -------- setup state (independent of Study Mode) --------
  var setup = { levels: [LEVELS[0] || "HSK1"], count: "20", types: [1, 2, 3, 4, 5, 6], mix: false };
  var state = null; // active test session

  // ---------------- utils ----------------
  function shuffle(a) { for (var i = a.length - 1; i > 0; i--) { var j = (Math.random() * (i + 1)) | 0; var t = a[i]; a[i] = a[j]; a[j] = t; } return a; }
  function trim(x) { return String(x == null ? "" : x).trim(); }
  function esc(el, text) { el.textContent = text; return el; }
  function fmtDuration(ms) { var s = Math.round(ms / 1000); var m = (s / 60) | 0; s = s % 60; return m + ":" + (s < 10 ? "0" : "") + s; }

  function setActive(id) {
    document.querySelectorAll(".view").forEach(function (v) { v.classList.toggle("active", v.id === id); });
  }

  // ---------------- question model ----------------
  function qField(type) { return typeDef(type).q; }
  function answerLines(card, type) { return typeDef(type).a.map(function (f) { return trim(card[f]); }); }
  function answerKey(card, type) { return answerLines(card, type).join(""); }
  function answerValid(card, type) { return typeDef(type).a.every(function (f) { return trim(card[f]) !== ""; }); }
  function questionValid(card, type) { return trim(card[qField(type)]) !== "" && answerValid(card, type); }

  // Pick up to n distractor cards with distinct visible answer text (random sampling + linear fallback).
  // Also skip candidates whose PROMPT field equals the correct card's prompt (e.g. homophones),
  // so the prompt has exactly one valid answer among the choices.
  function pickDistractors(card, pool, type, n) {
    var qf = qField(type), qVal = trim(card[qf]);
    var seen = {}; seen[answerKey(card, type)] = 1;
    var out = [], attempts = 0, maxA = Math.min(160, pool.length * 3);
    function usable(c) {
      return c.id !== card.id && answerValid(c, type) && trim(c[qf]) !== qVal && !seen[answerKey(c, type)];
    }
    while (out.length < n && attempts < maxA) {
      attempts++;
      var c = pool[(Math.random() * pool.length) | 0];
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

  // Build one question, or null if a valid (>=2 distinct options) question is impossible.
  function buildQuestion(card, pool, type) {
    if (!questionValid(card, type)) return null;
    var distractors = pickDistractors(card, pool, type, 3);
    if (distractors.length < 1) return null; // need at least one alternative
    var opts = [{ card: card, isCorrect: true }];
    distractors.forEach(function (c) { opts.push({ card: c, isCorrect: false }); });
    shuffle(opts);
    return {
      card: card, type: type,
      options: opts.map(function (o) { return { card: o.card, isCorrect: o.isCorrect, lines: answerLines(o.card, type) }; }),
      correctIndex: opts.map(function (o) { return o.isCorrect; }).indexOf(true),
      answeredIndex: null, correct: null, revealed: false
    };
  }

  function firstBuildable(card, pool, types) {
    var order = shuffle(types.slice());
    for (var i = 0; i < order.length; i++) { var q = buildQuestion(card, pool, order[i]); if (q) return q; }
    return null;
  }

  function buildTest(cfg) {
    var pool = CARDS.filter(function (c) { return cfg.levels.indexOf(c.level) >= 0; });
    var types = cfg.mix ? [1, 2, 3, 4, 5, 6] : cfg.types.slice();
    var N = cfg.count === "all" ? pool.length : Math.min(parseInt(cfg.count, 10), pool.length);
    var cardOrder = shuffle(pool.slice());
    // balanced type assignment: round-robin then shuffle
    var assign = [];
    for (var i = 0; i < N; i++) assign.push(types[i % types.length]);
    shuffle(assign);
    var questions = [], idx = 0;
    while (questions.length < N && idx < cardOrder.length) {
      var card = cardOrder[idx++];
      var want = assign[questions.length];
      var q = buildQuestion(card, pool, want) || firstBuildable(card, pool, types);
      if (q) questions.push(q);
    }
    return questions;
  }

  // ---------------- level picker (reuse chip style) ----------------
  function renderLevelPicker() {
    var wrap = $("testLevelPicker"); wrap.innerHTML = "";
    LEVELS.forEach(function (level) {
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "level-chip" + (setup.levels.indexOf(level) >= 0 ? " active" : "");
      btn.textContent = level;
      btn.setAttribute("aria-pressed", setup.levels.indexOf(level) >= 0 ? "true" : "false");
      btn.onclick = function () {
        var i = setup.levels.indexOf(level);
        if (i >= 0) { if (setup.levels.length === 1) return; setup.levels.splice(i, 1); }
        else setup.levels.push(level);
        setup.levels.sort();
        renderLevelPicker();
      };
      wrap.appendChild(btn);
    });
  }

  function renderTypePicker() {
    var wrap = $("testTypes"); wrap.innerHTML = "";
    TYPE_DEFS.forEach(function (t) {
      var lab = document.createElement("label");
      lab.className = "switch-row test-type-row";
      var cb = document.createElement("input");
      cb.type = "checkbox"; cb.value = String(t.id); cb.className = "test-type-cb";
      cb.checked = setup.types.indexOf(t.id) >= 0;
      cb.disabled = setup.mix;
      cb.onchange = function () {
        if (cb.checked) { if (setup.types.indexOf(t.id) < 0) setup.types.push(t.id); }
        else { var i = setup.types.indexOf(t.id); if (i >= 0) setup.types.splice(i, 1); }
      };
      var span = document.createElement("span"); span.textContent = t.label;
      lab.appendChild(cb); lab.appendChild(span);
      wrap.appendChild(lab);
    });
  }

  function renderHistory() {
    var box = $("testHistory"); if (!box) return;
    var list = loadHistory();
    if (!list.length) { box.innerHTML = ""; return; }
    box.innerHTML = '<div class="section-title"><h3>Lịch sử gần đây</h3></div>';
    var ul = document.createElement("div"); ul.className = "test-history-list";
    list.slice(0, 20).forEach(function (h) {
      var row = document.createElement("div"); row.className = "test-history-row";
      var left = document.createElement("span"); left.textContent = (h.date || "") + " · " + (h.levels || []).join("+");
      var right = document.createElement("strong"); right.textContent = h.correct + "/" + h.total + " (" + h.percent + "%)";
      row.appendChild(left); row.appendChild(right); ul.appendChild(row);
    });
    box.appendChild(ul);
  }

  function showSetup() {
    window.stopSpeech && window.stopSpeech();
    document.body.classList.remove("testing");
    renderLevelPicker(); renderTypePicker(); renderHistory();
    $("testCount").value = setup.count;
    $("testMix").checked = setup.mix;
    $("testSetupMsg").textContent = "";
    setActive("testSetupView");
    $("testSetupView").scrollTop = 0;
  }

  // ---------------- quiz ----------------
  function startTest() {
    if (!setup.levels.length) { return msg("Chọn ít nhất một cấp độ."); }
    var types = setup.mix ? [1, 2, 3, 4, 5, 6] : setup.types.slice();
    if (!types.length) { return msg("Chọn ít nhất một dạng câu hỏi."); }
    var questions = buildTest(setup);
    if (!questions.length) { return msg("Không tạo được câu hỏi từ lựa chọn này."); }
    state = { cfg: { levels: setup.levels.slice(), count: setup.count, types: types.slice(), mix: setup.mix },
              questions: questions, current: 0, score: 0, startTime: null };
    document.body.classList.add("testing");
    setActive("testQuizView");
    state.startTime = nowMs();
    renderQuestion();
  }
  function msg(t) { $("testSetupMsg").textContent = t; }

  function renderQuestion() {
    var q = state.questions[state.current];
    var t = typeDef(q.type);
    $("testTypeLabel").textContent = t.label;
    $("testQIndex").textContent = state.current + 1;
    $("testQTotal").textContent = state.questions.length;
    $("testScore").textContent = state.score;
    $("testProgressBar").style.width = ((state.current / state.questions.length) * 100) + "%";
    $("testQBadge").textContent = q.card.level;
    // Show ONLY the prompt field (word or pinyin) — never leaks the answer field.
    esc($("testQuestion"), q.card[qField(q.type)]);
    $("testQuestion").className = "test-q-main " + (qField(q.type) === "word" ? "is-word" : "is-pinyin");

    // options
    var box = $("testOptions"); box.innerHTML = "";
    q.options.forEach(function (opt, i) {
      var b = document.createElement("button");
      b.type = "button"; b.className = "test-option"; b.setAttribute("data-i", String(i));
      var key = document.createElement("span"); key.className = "opt-key"; key.textContent = String(i + 1);
      var body = document.createElement("span"); body.className = "opt-body";
      opt.lines.forEach(function (ln, li) {
        var s = document.createElement("span"); s.className = "opt-line opt-line" + (li + 1); s.textContent = ln; body.appendChild(s);
      });
      var mark = document.createElement("span"); mark.className = "opt-mark"; mark.setAttribute("aria-hidden", "true");
      b.appendChild(key); b.appendChild(body); b.appendChild(mark);
      b.onclick = function () { selectAnswer(i); };
      box.appendChild(b);
    });

    $("testFeedback").textContent = ""; $("testFeedback").className = "test-feedback";
    $("testAnswerPanel").hidden = true;
    $("testRevealBtn").hidden = true; $("testRevealBtn").textContent = "Xem đáp án";
    $("testNextBtn").hidden = true;
    $("testNextBtn").textContent = (state.current === state.questions.length - 1) ? "Xem kết quả" : "Câu tiếp →";
    window.stopSpeech && window.stopSpeech();
    $("testQuestionCard").focus({ preventScroll: true });
  }

  function selectAnswer(i) {
    var q = state.questions[state.current];
    if (q.answeredIndex !== null) return;         // already resolved -> no double scoring
    q.answeredIndex = i;
    q.correct = (i === q.correctIndex);
    if (q.correct) state.score++;
    var btns = [].slice.call($("testOptions").querySelectorAll(".test-option"));
    btns.forEach(function (b, j) {
      b.disabled = true;
      var mark = b.querySelector(".opt-mark");
      if (j === q.correctIndex) { b.classList.add("correct"); mark.textContent = "✓"; b.setAttribute("aria-label", "Đáp án đúng"); }
      if (j === i && !q.correct) { b.classList.add("wrong"); mark.textContent = "✗"; b.setAttribute("aria-label", "Đáp án bạn chọn — sai"); }
    });
    var fb = $("testFeedback");
    fb.textContent = q.correct ? "Chính xác" : "Sai. Đáp án đúng đã được đánh dấu.";
    fb.className = "test-feedback " + (q.correct ? "ok" : "err");
    $("testScore").textContent = state.score;
    $("testRevealBtn").hidden = false;
    $("testNextBtn").hidden = false;
    if (!q.correct) setReveal(true);              // wrong -> auto reveal back side
  }

  function fillAnswerPanel(card) {
    esc($("testAnsWord"), card.word);
    esc($("testAnsPinyin"), card.pinyin);
    esc($("testAnsMeaning"), card.meaning);
    esc($("testAnsExample"), card.example);
    esc($("testAnsExamplePinyin"), card.examplePinyin);
    esc($("testAnsTranslation"), card.translation);
  }
  function setReveal(show) {
    var q = state.questions[state.current];
    q.revealed = show;
    if (show) fillAnswerPanel(q.card);
    $("testAnswerPanel").hidden = !show;
    $("testRevealBtn").textContent = show ? "Ẩn đáp án" : "Xem đáp án";
    if (!show) window.stopSpeech && window.stopSpeech();
  }

  function next() {
    var q = state.questions[state.current];
    if (q.answeredIndex === null) return;          // cannot advance before answering
    window.stopSpeech && window.stopSpeech();
    state.current++;
    if (state.current >= state.questions.length) finishTest();
    else renderQuestion();
  }

  // ---------------- audio on answer side (Chinese only; reuse engine) ----------------
  function speakWord() { if (state) window.speak([{ text: state.questions[state.current].card.word, lang: "zh-CN", el: $("testAnsWord") }]); }
  function speakExample() { if (state) window.speak([{ text: state.questions[state.current].card.example, lang: "zh-CN", el: $("testAnsExample") }]); }
  function readAll() { if (!state) return; var c = state.questions[state.current].card; window.speak([{ text: c.word, lang: "zh-CN", el: $("testAnsWord"), pauseAfter: 500 }, { text: c.example, lang: "zh-CN", el: $("testAnsExample") }]); }

  // ---------------- results ----------------
  function finishTest() {
    window.stopSpeech && window.stopSpeech();
    document.body.classList.remove("testing");
    var total = state.questions.length;
    var correct = state.score;
    var wrong = total - correct;
    var pct = total ? Math.round(correct / total * 100) : 0;
    var label = pct >= 90 ? "Xuất sắc" : pct >= 75 ? "Tốt" : pct >= 60 ? "Khá" : "Cần ôn thêm";
    var durMs = state.startTime ? (nowMs() - state.startTime) : 0;

    $("resLevels").textContent = state.cfg.levels.join(", ");
    $("resTypes").textContent = state.cfg.types.map(function (id) { return typeDef(id).label; }).join(" · ");
    $("resTotal").textContent = total;
    $("resCorrect").textContent = correct;
    $("resWrong").textContent = wrong;
    $("resPercent").textContent = pct + "%";
    $("resLabel").textContent = label;
    $("resLabel").className = "res-label pct-" + (pct >= 90 ? "xs" : pct >= 75 ? "good" : pct >= 60 ? "ok" : "low");
    $("resDuration").textContent = durMs ? fmtDuration(durMs) : "";
    $("resDurationRow").style.display = durMs ? "" : "none";
    var wrongCount = wrong;
    $("testReviewBtn").style.display = wrongCount ? "" : "none";

    saveHistory({ date: todayStr(), levels: state.cfg.levels.slice(),
      types: state.cfg.types.slice(), total: total, correct: correct, percent: pct });

    setActive("testResultView");
    $("testResultView").scrollTop = 0;
  }

  function renderReview() {
    var box = $("testReviewList"); box.innerHTML = "";
    var wrongs = state.questions.filter(function (q) { return q.correct === false; });
    if (!wrongs.length) { box.innerHTML = '<p class="muted">Không có câu sai. Tuyệt vời!</p>'; }
    wrongs.forEach(function (q) {
      var card = q.card, t = typeDef(q.type);
      var yourOpt = q.options[q.answeredIndex];
      var correctOpt = q.options[q.correctIndex];
      var div = document.createElement("div"); div.className = "review-item";
      div.innerHTML =
        '<div class="review-type">' + t.label + " · " + card.level + '</div>' +
        '<div class="review-q"></div>' +
        '<div class="review-row"><span class="review-k">Bạn chọn</span><span class="review-v review-wrong"></span></div>' +
        '<div class="review-row"><span class="review-k">Đáp án đúng</span><span class="review-v review-correct"></span></div>' +
        '<div class="review-card"><b class="review-word"></b> <span class="review-py"></span> — <span class="review-mean"></span>' +
        '<div class="review-ex"></div><div class="review-expy"></div><div class="review-tr"></div></div>';
      div.querySelector(".review-q").textContent = "Câu hỏi: " + card[qField(q.type)];
      div.querySelector(".review-wrong").textContent = yourOpt.lines.join(" · ");
      div.querySelector(".review-correct").textContent = correctOpt.lines.join(" · ");
      div.querySelector(".review-word").textContent = card.word;
      div.querySelector(".review-py").textContent = card.pinyin;
      div.querySelector(".review-mean").textContent = card.meaning;
      div.querySelector(".review-ex").textContent = card.example;
      div.querySelector(".review-expy").textContent = card.examplePinyin;
      div.querySelector(".review-tr").textContent = card.translation;
      box.appendChild(div);
    });
    setActive("testReviewView");
    $("testReviewView").scrollTop = 0;
  }

  function redoTest() {
    // same levels / count / types, freshly shuffled questions + options
    setup.levels = state.cfg.levels.slice();
    setup.count = state.cfg.count;
    setup.types = state.cfg.types.slice();
    setup.mix = state.cfg.mix;
    startTest();
  }

  function goHome() {
    window.stopSpeech && window.stopSpeech();
    document.body.classList.remove("testing");
    setActive("homeView");
    window.renderHome && window.renderHome();
  }

  function confirmExit() {
    // Only reachable from the quiz view, i.e. an unfinished test is in progress.
    if (!confirm("Bạn đang làm bài test dở. Thoát và hủy bài test?")) return;
    goHome(); // abandons the current test without grading the unanswered question
  }

  // ---------------- local per-user history (NOT synced) ----------------
  function historyKey() { var u = window.HSK_AUTH; return "hsk_test_history" + (u && u.userId ? "::" + u.userId : ""); }
  function loadHistory() { try { var v = JSON.parse(localStorage.getItem(historyKey()) || "[]"); return Array.isArray(v) ? v : []; } catch (_) { return []; } }
  function saveHistory(entry) {
    try { var list = loadHistory(); list.unshift(entry); list = list.slice(0, 20); localStorage.setItem(historyKey(), JSON.stringify(list)); } catch (_) {}
  }
  function todayStr() { try { return new Date().toISOString().slice(0, 10); } catch (_) { return ""; } }
  function nowMs() { try { return Date.now(); } catch (_) { return 0; } }

  // ---------------- keyboard (test quiz only) ----------------
  document.addEventListener("keydown", function (e) {
    if (!$("testQuizView").classList.contains("active")) return;
    var tag = (e.target.tagName || "").toLowerCase();
    if (tag === "input" || tag === "textarea" || tag === "select" || tag === "button" || e.target.isContentEditable) return;
    var k = e.key;
    var q = state && state.questions[state.current];
    if (!q) return;
    if (k >= "1" && k <= "4") {
      var idx = (+k) - 1;
      if (q.answeredIndex === null && idx < q.options.length) { e.preventDefault(); selectAnswer(idx); }
    } else if (k === "Enter" || k === "n" || k === "N") {
      if (q.answeredIndex !== null) { e.preventDefault(); next(); }
    } else if (k === " " || k === "Spacebar") {
      if (q.answeredIndex !== null) { e.preventDefault(); setReveal(!q.revealed); }
    } else if (k === "Escape") {
      e.preventDefault(); confirmExit();
    }
  });

  // ---------------- wire up (runs after DOM parsed; script is at end of body) ----------------
  function bind(id, fn) { var el = $(id); if (el) el.onclick = fn; }
  bind("openTestBtn", showSetup);
  bind("testSetupBack", goHome);
  bind("testStartBtn", startTest);
  bind("testExitBtn", confirmExit);
  bind("testNextBtn", next);
  bind("testRevealBtn", function () { var q = state.questions[state.current]; setReveal(!q.revealed); });
  bind("testSpeakWord", function (e) { e.stopPropagation(); speakWord(); });
  bind("testSpeakExample", function (e) { e.stopPropagation(); speakExample(); });
  bind("testReadAll", function (e) { e.stopPropagation(); readAll(); });
  bind("testStop", function (e) { e.stopPropagation(); window.stopSpeech && window.stopSpeech(); });
  bind("testResultReview", renderReview);
  bind("testReviewBtn", renderReview);
  bind("testReviewBack", function () { setActive("testResultView"); });
  bind("testRedoBtn", redoTest);
  bind("testResultHome", goHome);
  var mix = $("testMix");
  if (mix) mix.onchange = function () {
    setup.mix = mix.checked;
    if (setup.mix) setup.types = [1, 2, 3, 4, 5, 6];
    renderTypePicker();
  };
  var cnt = $("testCount");
  if (cnt) cnt.onchange = function () { setup.count = cnt.value; };

  window.TestMode = { open: showSetup };
})();
