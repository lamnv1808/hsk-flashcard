/* ============================================================
 *  metadata.js — per-user bookmarks, notes, and daily-learning
 *  aggregates, stored inside the EXISTING synced settings blob
 *  (window.HSK_APP.getSettings() + window.saveSettings()).
 *  - No Supabase schema change, no second sync engine.
 *  - Namespaced per account automatically (settings is namespaced).
 *  - Never touches SRS/progress; missing fields default safely.
 *  Also owns the Study Mode bookmark button + back-side note zone.
 * ============================================================ */
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  function S() { return (window.HSK_APP && window.HSK_APP.getSettings()) || {}; }
  function persist() { if (window.saveSettings) window.saveSettings(); }
  function curCard() { return window.currentCard ? window.currentCard() : null; }
  function trim(x) { return String(x == null ? "" : x).trim(); }
  function localDay(d) {
    d = d || new Date();
    var m = d.getMonth() + 1, day = d.getDate();
    return d.getFullYear() + "-" + (m < 10 ? "0" : "") + m + "-" + (day < 10 ? "0" : "") + day;
  }

  /* ---------------- bookmarks ---------------- */
  function bookmarks() { var s = S(); return Array.isArray(s.bookmarks) ? s.bookmarks : []; }
  function isBookmarked(id) { return bookmarks().indexOf(id) >= 0; }
  function toggleBookmark(id) {
    var s = S(); if (!Array.isArray(s.bookmarks)) s.bookmarks = [];
    var i = s.bookmarks.indexOf(id);
    if (i >= 0) s.bookmarks.splice(i, 1); else s.bookmarks.push(id);
    persist();
    return i < 0;
  }
  function removeBookmark(id) { var s = S(); if (Array.isArray(s.bookmarks)) { var i = s.bookmarks.indexOf(id); if (i >= 0) { s.bookmarks.splice(i, 1); persist(); } } }

  /* ---------------- notes (plain text) ---------------- */
  function notesMap() { var s = S(); return (s.notes && typeof s.notes === "object") ? s.notes : {}; }
  function getNote(id) { var n = notesMap()[id]; return n ? String(n) : ""; }
  function hasNote(id) { return trim(getNote(id)) !== ""; }
  function setNote(id, text) {
    var s = S(); if (!s.notes || typeof s.notes !== "object") s.notes = {};
    var t = trim(text);
    if (t === "") delete s.notes[id]; else s.notes[id] = t.slice(0, 1000);
    persist();
  }

  /* ---------------- daily learning (Study Mode grades, once/card/day) ---------------- */
  function dailyCounts() { var s = S(); return (s.dailyCounts && typeof s.dailyCounts === "object") ? s.dailyCounts : {}; }
  function recordDailyLearn(id) {
    var s = S(), day = localDay();
    var tl = (s.todayLearn && s.todayLearn.day === day) ? s.todayLearn : { day: day, ids: [] };
    if (tl.ids.indexOf(id) >= 0) return;   // already counted today -> once per card per day
    tl.ids.push(id); s.todayLearn = tl;
    if (!s.dailyCounts || typeof s.dailyCounts !== "object") s.dailyCounts = {};
    s.dailyCounts[day] = (s.dailyCounts[day] || 0) + 1;
    pruneDaily(s.dailyCounts);
    persist();
  }
  function pruneDaily(dc) {
    var keys = Object.keys(dc);
    if (keys.length <= 400) return;         // keep a rolling ~365 days
    keys.sort();
    var remove = keys.length - 365;
    for (var i = 0; i < remove; i++) delete dc[keys[i]];
  }

  /* ---------------- Study Mode: bookmark button ---------------- */
  function updateBookmarkBtn() {
    var btn = $("bookmarkBtn"); if (!btn) return;
    var c = curCard();
    if (!c) { btn.disabled = true; return; }
    btn.disabled = false;
    var on = isBookmarked(c.id);
    btn.textContent = on ? "★" : "☆";
    btn.classList.toggle("active", on);
    btn.setAttribute("aria-pressed", on ? "true" : "false");
    btn.setAttribute("aria-label", on ? "Bỏ lưu từ này" : "Lưu từ này");
  }

  /* ---------------- Study Mode: back-side note zone ---------------- */
  // Empty note + closed editor => ONLY the small icon shows (no label/box/placeholder).
  function renderNoteZone() {
    var c = curCard(); if (!c) return;
    $("noteEditor").hidden = true;
    $("noteToggle").setAttribute("aria-expanded", "false");
    var note = getNote(c.id), disp = $("noteDisplay"), tog = $("noteToggle");
    if (trim(note) !== "") {
      disp.textContent = note;               // textContent => no HTML/script; CSS preserves line breaks
      disp.hidden = false;
      tog.classList.add("has-note");
      tog.setAttribute("aria-label", "Sửa ghi chú");
    } else {
      disp.textContent = ""; disp.hidden = true;
      tog.classList.remove("has-note");
      tog.setAttribute("aria-label", "Thêm ghi chú");
    }
  }
  function openEditor() {
    var c = curCard(); if (!c) return;
    var inp = $("noteInput");
    inp.value = getNote(c.id);
    $("noteEditor").hidden = false;
    $("noteToggle").setAttribute("aria-expanded", "true");
    $("noteDisplay").hidden = true;
    updateCounter();
    inp.focus();
  }
  function closeEditor() { $("noteEditor").hidden = true; $("noteToggle").setAttribute("aria-expanded", "false"); renderNoteZone(); }
  function saveEditor() { var c = curCard(); if (!c) return; setNote(c.id, $("noteInput").value); closeEditor(); }
  function updateCounter() { var inp = $("noteInput"); if (inp) $("noteCounter").textContent = inp.value.length + "/1000"; }

  /* ---------------- hooks called by app.js ---------------- */
  function syncCard() { // front state after a card change: refresh bookmark, hide note zone
    updateBookmarkBtn();
    $("noteEditor").hidden = true;
    $("noteToggle").setAttribute("aria-expanded", "false");
    $("noteZone").hidden = true;
  }
  function onFlip(flipped) {
    if (flipped) { $("noteZone").hidden = false; renderNoteZone(); }
    else { $("noteEditor").hidden = true; $("noteZone").hidden = true; }
  }

  /* ---------------- wire up ---------------- */
  var bm = $("bookmarkBtn");
  if (bm) bm.onclick = function (e) { e.stopPropagation(); var c = curCard(); if (!c) return; toggleBookmark(c.id); updateBookmarkBtn(); };
  var nt = $("noteToggle");
  if (nt) nt.onclick = function (e) { e.stopPropagation(); if ($("noteEditor").hidden) openEditor(); else closeEditor(); };
  var ns = $("noteSave"); if (ns) ns.onclick = function (e) { e.stopPropagation(); saveEditor(); };
  var nc = $("noteCancel"); if (nc) nc.onclick = function (e) { e.stopPropagation(); closeEditor(); };
  var ni = $("noteInput"); if (ni) ni.addEventListener("input", updateCounter);

  window.HSKMeta = {
    syncCard: syncCard, onFlip: onFlip, recordDailyLearn: recordDailyLearn,
    isBookmarked: isBookmarked, toggleBookmark: toggleBookmark, removeBookmark: removeBookmark,
    bookmarks: bookmarks, getNote: getNote, hasNote: hasNote, notesMap: notesMap,
    dailyCounts: dailyCounts, localDay: localDay
  };
})();
