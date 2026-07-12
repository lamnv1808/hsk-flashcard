/* ============================================================
 *  insights.js — Weak Words, Smart Review (analysis only), daily
 *  learning chart, and the Bookmarks page. Read-only over existing
 *  data; never alters SRS, intervals, due dates, ratings or progress.
 * ============================================================ */
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var CARDS = window.HSK_CARDS || [];
  var BY = new Map(CARDS.map(function (c) { return [c.id, c]; }));
  var LEVELS = (function () {
    var s = {}; CARDS.forEach(function (c) { s[c.level] = 1; });
    return Object.keys(s).sort(function (a, b) { return (parseInt(String(a).replace(/\D/g, ""), 10) || 0) - (parseInt(String(b).replace(/\D/g, ""), 10) || 0); });
  })();
  function P() { return (window.HSK_APP && window.HSK_APP.getProgress()) || {}; }
  function trim(x) { return String(x == null ? "" : x).trim(); }
  function setActive(id) { document.querySelectorAll(".view").forEach(function (v) { v.classList.toggle("active", v.id === id); }); }
  function goHome() { if (window.stopSpeech) window.stopSpeech(); document.body.classList.remove("testing"); setActive("homeView"); if (window.renderHome) window.renderHome(); }

  /* ---------------- weakness model ----------------
     Signals come only from the existing progress record {due,interval,reps,correct,attempts}.
     failures = attempts - correct (Again/Khó don't add to correct).
     lastGraded ≈ due - interval days.
     weakness = failures * smoothedFailRate * recencyWeight
       smoothedFailRate = (failures+1)/(attempts+2)   // evidence-aware, low-data can't dominate
       recencyWeight    = 1/(1 + daysSince/14)         // recent failures weigh more
     Untouched (attempts 0) => excluded. Touched-but-never-failed => weakness 0 (not weak). */
  function lastGradedDate(st) {
    if (!st.due) return null;
    var due = new Date(st.due + "T00:00:00");
    if (isNaN(due)) return null;
    return new Date(due.getTime() - (st.interval || 0) * 86400000);
  }
  function daysSince(d) { if (!d) return 30; return Math.max(0, Math.round((Date.now() - d.getTime()) / 86400000)); }
  function weakness(st) {
    var attempts = st.attempts || 0;
    if (attempts <= 0) return null;
    var failures = attempts - (st.correct || 0);
    if (failures <= 0) return 0;
    var sfr = (failures + 1) / (attempts + 2);
    var rec = 1 / (1 + daysSince(lastGradedDate(st)) / 14);
    return failures * sfr * rec;
  }

  function weakCards(levelFilter) {
    var prog = P(), out = [];
    Object.keys(prog).forEach(function (id) {
      var card = BY.get(Number(id)); if (!card) return;
      if (levelFilter && levelFilter !== "all" && card.level !== levelFilter) return;
      var st = prog[id], w = weakness(st);
      if (w == null || w <= 0) return;
      out.push({ card: card, st: st, score: w, failures: (st.attempts || 0) - (st.correct || 0), attempts: st.attempts || 0, last: lastGradedDate(st) });
    });
    out.sort(function (a, b) { return b.score - a.score || b.failures - a.failures; });
    return out;
  }

  /* ---------------- shared bits ---------------- */
  function populateLevelSelect(sel, allLabel) {
    if (!sel) return;
    sel.innerHTML = "";
    var o = document.createElement("option"); o.value = "all"; o.textContent = allLabel; sel.appendChild(o);
    LEVELS.forEach(function (lv) { var op = document.createElement("option"); op.value = lv; op.textContent = lv; sel.appendChild(op); });
  }
  function fmtDate(d) { if (!d) return ""; return d.toISOString().slice(0, 10); }
  function wordRow(card, opts) {
    opts = opts || {};
    var row = document.createElement("div"); row.className = "word-row";
    var main = document.createElement("div"); main.className = "word-row-main";
    var w = document.createElement("span"); w.className = "wr-word"; w.textContent = card.word;
    var py = document.createElement("span"); py.className = "wr-py"; py.textContent = card.pinyin;
    var mean = document.createElement("div"); mean.className = "wr-mean"; mean.textContent = card.meaning;
    var meta = document.createElement("div"); meta.className = "wr-meta";
    var lvl = document.createElement("span"); lvl.className = "wr-lvl"; lvl.textContent = card.level; meta.appendChild(lvl);
    if (opts.metaText) { var mt = document.createElement("span"); mt.className = "wr-note"; mt.textContent = opts.metaText; meta.appendChild(mt); }
    if (opts.hasNote) { var ni = document.createElement("span"); ni.className = "wr-noteicon"; ni.textContent = "📝"; ni.setAttribute("aria-label", "Có ghi chú"); ni.title = "Có ghi chú"; meta.appendChild(ni); }
    main.appendChild(w); main.appendChild(py); main.appendChild(mean); main.appendChild(meta);
    row.appendChild(main);
    if (opts.removeId != null) {
      var rm = document.createElement("button"); rm.type = "button"; rm.className = "wr-remove"; rm.textContent = "✕";
      rm.setAttribute("aria-label", "Bỏ lưu " + card.word);
      rm.onclick = opts.onRemove;
      row.appendChild(rm);
    }
    return row;
  }

  /* ---------------- Weak Words ---------------- */
  var weakShown = [];
  function renderWeak() {
    var level = $("weakLevel").value, topN = parseInt($("weakTop").value, 10) || 20;
    var all = weakCards(level);
    weakShown = all.slice(0, topN);
    var box = $("weakList"); box.innerHTML = "";
    if (!weakShown.length) {
      box.innerHTML = '<p class="muted empty-state">Chưa có từ nào cần cải thiện. Hãy học thêm để có dữ liệu.</p>';
      $("weakStudyBtn").disabled = true; return;
    }
    $("weakStudyBtn").disabled = false;
    weakShown.forEach(function (x) {
      var meta = x.failures + "/" + x.attempts + " sai" + (x.last ? " · " + fmtDate(x.last) : "");
      box.appendChild(wordRow(x.card, { metaText: meta, hasNote: window.HSKMeta && HSKMeta.hasNote(x.card.id) }));
    });
  }
  function showWeak() {
    populateLevelSelect($("weakLevel"), "Tất cả cấp độ");
    setActive("weakWordsView"); $("weakWordsView").scrollTop = 0; renderWeak();
  }

  /* ---------------- Smart Review insights ---------------- */
  function renderInsights() {
    var prog = P(), box = $("insightsBody"); box.innerHTML = "";
    var touched = Object.keys(prog);
    if (!touched.length) { box.innerHTML = '<p class="muted empty-state">Chưa đủ dữ liệu để phân tích.</p>'; return; }

    // level retention
    var byLvl = {};
    touched.forEach(function (id) {
      var card = BY.get(Number(id)); if (!card) return;
      var st = prog[id]; var a = st.attempts || 0; if (!a) return;
      var l = byLvl[card.level] || (byLvl[card.level] = { att: 0, cor: 0 });
      l.att += a; l.cor += (st.correct || 0);
    });
    var lvlStats = Object.keys(byLvl).filter(function (l) { return byLvl[l].att >= 10; })
      .map(function (l) { return { level: l, ret: byLvl[l].cor / byLvl[l].att }; });
    var rows = [];
    if (lvlStats.length) {
      lvlStats.sort(function (a, b) { return a.ret - b.ret; });
      rows.push(["Cấp độ nhớ kém nhất", lvlStats[0].level + " (" + Math.round(lvlStats[0].ret * 100) + "%)"]);
      var top = lvlStats[lvlStats.length - 1];
      rows.push(["Cấp độ nhớ tốt nhất", top.level + " (" + Math.round(top.ret * 100) + "%)"]);
    } else {
      rows.push(["Nhớ theo cấp độ", "Chưa đủ dữ liệu để phân tích."]);
    }

    var weak = weakCards("all");
    rows.push(["Tổng số từ cần cải thiện", String(weak.length)]);
    var recent = weak.filter(function (x) { return x.last && daysSince(x.last) <= 7; }).length;
    rows.push(["Từ vừa gặp khó (7 ngày)", String(recent)]);

    // daily aggregates
    var dc = (window.HSKMeta && HSKMeta.dailyCounts()) || {};
    rows.push(["Đã học hôm nay", String(dc[HSKMeta.localDay()] || 0)]);
    rows.push(["Đã học 7 ngày qua", String(sumDays(dc, 7))]);
    rows.push(["Đã học 30 ngày qua", String(sumDays(dc, 30))]);
    var streak = (window.HSK_APP && HSK_APP.getSettings().streak) || 0;
    rows.push(["Chuỗi ngày hiện tại", String(streak)]);

    rows.forEach(function (r) {
      var d = document.createElement("div"); d.className = "insight-row";
      var k = document.createElement("span"); k.textContent = r[0];
      var v = document.createElement("b"); v.textContent = r[1];
      d.appendChild(k); d.appendChild(v); box.appendChild(d);
    });
  }
  function sumDays(dc, n) {
    var t = 0, now = new Date();
    for (var i = 0; i < n; i++) { var d = new Date(now.getTime() - i * 86400000); t += dc[HSKMeta.localDay(d)] || 0; }
    return t;
  }

  /* ---------------- daily chart (inline SVG) ---------------- */
  var chartDays = 7;
  function renderChart() {
    var dc = (window.HSKMeta && HSKMeta.dailyCounts()) || {};
    var now = new Date(), labels = [], vals = [];
    for (var i = chartDays - 1; i >= 0; i--) { var d = new Date(now.getTime() - i * 86400000); labels.push(d); vals.push(dc[HSKMeta.localDay(d)] || 0); }
    var total = vals.reduce(function (a, b) { return a + b; }, 0);
    var max = Math.max(1, Math.max.apply(null, vals));
    var W = chartDays * 16, H = 120, pad = 4, bw = 16 - 6;
    var svg = '<svg viewBox="0 0 ' + W + ' ' + (H + 16) + '" preserveAspectRatio="none" width="100%" height="150" xmlns="http://www.w3.org/2000/svg">';
    vals.forEach(function (v, i) {
      var h = Math.round((v / max) * (H - pad));
      var x = i * 16 + 3, y = H - h;
      svg += '<rect x="' + x + '" y="' + y + '" width="' + bw + '" height="' + Math.max(h, v > 0 ? 2 : 0) + '" rx="2" fill="var(--accent)"' + (v === 0 ? ' opacity="0.15"' : '') + '></rect>';
      if (v > 0) svg += '<text x="' + (x + bw / 2) + '" y="' + (y - 2) + '" font-size="8" text-anchor="middle" fill="var(--muted)">' + v + '</text>';
    });
    // first & last date labels
    svg += '<text x="1" y="' + (H + 12) + '" font-size="8" fill="var(--muted)">' + fmtDate(labels[0]).slice(5) + '</text>';
    svg += '<text x="' + (W - 1) + '" y="' + (H + 12) + '" font-size="8" text-anchor="end" fill="var(--muted)">' + fmtDate(labels[labels.length - 1]).slice(5) + '</text>';
    svg += "</svg>";
    $("dailyChart").innerHTML = svg;
    var avg = (total / chartDays).toFixed(1);
    $("dailyChartSummary").textContent = total === 0
      ? "Chưa có dữ liệu học trong " + chartDays + " ngày gần đây."
      : "Tổng " + total + " từ trong " + chartDays + " ngày · trung bình " + avg + " từ/ngày.";
    $("chart7").classList.toggle("active", chartDays === 7);
    $("chart30").classList.toggle("active", chartDays === 30);
  }
  function showInsights() { setActive("insightsView"); $("insightsView").scrollTop = 0; renderInsights(); renderChart(); }

  /* ---------------- Bookmarks page ---------------- */
  function bookmarkCards() {
    var ids = (window.HSKMeta && HSKMeta.bookmarks()) || [];
    return ids.map(function (id) { return BY.get(Number(id)); }).filter(Boolean);
  }
  function renderBookmarks() {
    var level = $("bmLevel").value, q = trim($("bmSearch").value).toLowerCase();
    var list = bookmarkCards().filter(function (c) {
      if (level !== "all" && c.level !== level) return false;
      if (q && (c.word + " " + c.pinyin + " " + c.meaning).toLowerCase().indexOf(q) < 0) return false;
      return true;
    });
    var box = $("bmList"); box.innerHTML = "";
    var allEmpty = !bookmarkCards().length;
    if (allEmpty) { box.innerHTML = '<p class="muted empty-state">Bạn chưa lưu từ nào.</p>'; $("bmStudyBtn").disabled = true; return; }
    $("bmStudyBtn").disabled = false;
    if (!list.length) { box.innerHTML = '<p class="muted empty-state">Không có từ khớp bộ lọc.</p>'; return; }
    list.forEach(function (c) {
      box.appendChild(wordRow(c, {
        hasNote: window.HSKMeta && HSKMeta.hasNote(c.id),
        removeId: c.id,
        onRemove: function () { HSKMeta.removeBookmark(c.id); renderBookmarks(); }
      }));
    });
  }
  function showBookmarks() {
    populateLevelSelect($("bmLevel"), "Tất cả cấp độ");
    $("bmSearch").value = "";
    setActive("bookmarksView"); $("bookmarksView").scrollTop = 0; renderBookmarks();
  }

  /* ---------------- study-session launchers ---------------- */
  function studyIds(ids) { if (window.HSK_APP && ids.length) HSK_APP.startSession(ids); }

  /* ---------------- wire up ---------------- */
  function on(id, fn) { var el = $(id); if (el) el.onclick = fn; }
  on("openWeakBtn", showWeak);
  on("openInsightsBtn", showInsights);
  on("openBookmarksBtn", showBookmarks);
  on("weakBack", goHome); on("insightsBack", goHome); on("bmBack", goHome);
  var wl = $("weakLevel"); if (wl) wl.onchange = renderWeak;
  var wt = $("weakTop"); if (wt) wt.onchange = renderWeak;
  on("weakStudyBtn", function () { studyIds(weakShown.map(function (x) { return x.card.id; })); });
  on("chart7", function () { chartDays = 7; renderChart(); });
  on("chart30", function () { chartDays = 30; renderChart(); });
  var bl = $("bmLevel"); if (bl) bl.onchange = renderBookmarks;
  var bs = $("bmSearch"); if (bs) bs.oninput = renderBookmarks;
  on("bmStudyBtn", function () {
    var ids = bookmarkCards().filter(function (c) { return $("bmLevel").value === "all" || c.level === $("bmLevel").value; }).map(function (c) { return c.id; });
    studyIds(ids);
  });

  window.HSKInsights = { showWeak: showWeak, showInsights: showInsights, showBookmarks: showBookmarks };
})();
