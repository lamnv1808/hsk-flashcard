/* ============================================================
 *  insights.js — Weak Words, Smart Review (analysis only), daily
 *  learning chart, and the Bookmarks page. Read-only over existing
 *  data; never alters SRS, intervals, due dates, ratings or progress.
 * ============================================================ */
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var repo = window.HSKUtil.cards;   // shared read-only CardRepository (built once)
  var ANALYTICS = window.HSKUtil.analytics;   // shared read-only AnalyticsQuery (Phase 6)
  var MQ = window.HSKUtil.userMetadata;   // shared read-only UserMetadataQuery (Phase 7)
  var LEVELS = window.HSKUtil.contentPack.getDeckIds();   // deck identity/order from the active pack (Phase 11)
  function trim(x) { return String(x == null ? "" : x).trim(); }
  function setActive(id) { document.querySelectorAll(".view").forEach(function (v) { v.classList.toggle("active", v.id === id); }); }
  function goHome() { if (window.stopSpeech) window.stopSpeech(); document.body.classList.remove("testing"); setActive("homeView"); if (window.renderHome) window.renderHome(); }

  // Weakness model, level retention, daily aggregates and the daily series now live
  // in core/analytics/analytics-query.js (Phase 6). insights.js consumes the read
  // models via ANALYTICS and keeps all DOM/SVG rendering below.

  /* ---------------- shared bits ---------------- */
  function populateLevelSelect(sel, allLabel) {
    if (!sel) return;
    sel.innerHTML = "";
    var o = document.createElement("option"); o.value = "all"; o.textContent = allLabel; sel.appendChild(o);
    LEVELS.forEach(function (lv) { var op = document.createElement("option"); op.value = lv; op.textContent = lv; sel.appendChild(op); });
  }
  function fmtDate(d) { return d ? window.HSKUtil.date.isoDay(d) : ""; }   // UTC day; falsy -> "" (unchanged)
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
    var all = ANALYTICS.getWeakWords(level);
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
    var m = ANALYTICS.getSmartReviewModel(), box = $("insightsBody"); box.innerHTML = "";
    if (!m.hasData) { box.innerHTML = '<p class="muted empty-state">Chưa đủ dữ liệu để phân tích.</p>'; return; }

    var rows = [];
    if (m.levelRetention) {
      rows.push(["Cấp độ nhớ kém nhất", m.levelRetention.weakest.level + " (" + m.levelRetention.weakest.pct + "%)"]);
      rows.push(["Cấp độ nhớ tốt nhất", m.levelRetention.strongest.level + " (" + m.levelRetention.strongest.pct + "%)"]);
    } else {
      rows.push(["Nhớ theo cấp độ", "Chưa đủ dữ liệu để phân tích."]);
    }
    rows.push(["Tổng số từ cần cải thiện", String(m.weakCount)]);
    rows.push(["Từ vừa gặp khó (7 ngày)", String(m.recentStruggles)]);
    rows.push(["Đã học hôm nay", String(m.today)]);
    rows.push(["Đã học 7 ngày qua", String(m.last7)]);
    rows.push(["Đã học 30 ngày qua", String(m.last30)]);
    rows.push(["Chuỗi ngày hiện tại", String(m.streak)]);

    rows.forEach(function (r) {
      var d = document.createElement("div"); d.className = "insight-row";
      var k = document.createElement("span"); k.textContent = r[0];
      var v = document.createElement("b"); v.textContent = r[1];
      d.appendChild(k); d.appendChild(v); box.appendChild(d);
    });
  }

  /* ---------------- daily chart (inline SVG) ---------------- */
  var chartDays = 7;
  function renderChart() {
    // Read-only series from AnalyticsQuery (Phase 6); SVG building stays here.
    var series = ANALYTICS.getDailySeries(chartDays);
    var labels = series.labels, vals = series.values, total = series.total, max = series.max;
    var W = chartDays * 16, H = 120, pad = 4, bw = 16 - 6;
    var svg = '<svg viewBox="0 0 ' + W + ' ' + (H + 16) + '" preserveAspectRatio="none" width="100%" height="150" xmlns="http://www.w3.org/2000/svg">';
    vals.forEach(function (v, i) {
      var h = Math.round((v / max) * (H - pad));
      var x = i * 16 + 3, y = H - h;
      svg += '<rect x="' + x + '" y="' + y + '" width="' + bw + '" height="' + Math.max(h, v > 0 ? 2 : 0) + '" rx="2" style="fill:var(--accent)"' + (v === 0 ? ' opacity="0.15"' : '') + '></rect>';
      if (v > 0) svg += '<text x="' + (x + bw / 2) + '" y="' + (y - 2) + '" font-size="8" text-anchor="middle" style="fill:var(--muted)">' + v + '</text>';
    });
    // first & last date labels
    svg += '<text x="1" y="' + (H + 12) + '" font-size="8" style="fill:var(--muted)">' + fmtDate(labels[0]).slice(5) + '</text>';
    svg += '<text x="' + (W - 1) + '" y="' + (H + 12) + '" font-size="8" text-anchor="end" style="fill:var(--muted)">' + fmtDate(labels[labels.length - 1]).slice(5) + '</text>';
    svg += "</svg>";
    $("dailyChart").innerHTML = svg;
    var avg = series.average.toFixed(1);
    $("dailyChartSummary").textContent = total === 0
      ? "Chưa có dữ liệu học trong " + chartDays + " ngày gần đây."
      : "Tổng " + total + " từ trong " + chartDays + " ngày · trung bình " + avg + " từ/ngày.";
    $("chart7").classList.toggle("active", chartDays === 7);
    $("chart30").classList.toggle("active", chartDays === 30);
  }
  function showInsights() { setActive("insightsView"); $("insightsView").scrollTop = 0; renderInsights(); renderChart(); }

  /* ---------------- Bookmarks page ---------------- */
  // Bookmark-card resolution now via the read-only UserMetadataQuery (Phase 7):
  // requested (insertion) order, numeric ids, skips missing — unchanged.
  function bookmarkCards() { return MQ.getBookmarkedCards(); }
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
  // Phase 23: pass the transient source so completion can offer "return to this feature". The
  // feature string is validated by app.js against its allowlist; unknown -> generic explicit.
  function studyIds(ids, source) { if (window.HSK_APP && ids.length) HSK_APP.startSession(ids, source); }

  /* ---------------- wire up ---------------- */
  function on(id, fn) { var el = $(id); if (el) el.onclick = fn; }
  on("openWeakBtn", showWeak);
  on("openInsightsBtn", showInsights);
  on("openBookmarksBtn", showBookmarks);
  on("weakBack", goHome); on("insightsBack", goHome); on("bmBack", goHome);
  var wl = $("weakLevel"); if (wl) wl.onchange = renderWeak;
  var wt = $("weakTop"); if (wt) wt.onchange = renderWeak;
  on("weakStudyBtn", function () { studyIds(weakShown.map(function (x) { return x.card.id; }), { feature: "weak" }); });
  on("chart7", function () { chartDays = 7; renderChart(); });
  on("chart30", function () { chartDays = 30; renderChart(); });
  var bl = $("bmLevel"); if (bl) bl.onchange = renderBookmarks;
  var bs = $("bmSearch"); if (bs) bs.oninput = renderBookmarks;
  on("bmStudyBtn", function () {
    var ids = MQ.getBookmarkedCards({ level: $("bmLevel").value }).map(function (c) { return c.id; });
    studyIds(ids, { feature: "bookmarks" });
  });

  window.HSKInsights = { showWeak: showWeak, showInsights: showInsights, showBookmarks: showBookmarks };
})();
