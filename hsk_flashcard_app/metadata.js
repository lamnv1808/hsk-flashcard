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
  var MQ = window.HSKUtil.userMetadata;   // shared read-only UserMetadataQuery (Phase 7)
  function persist() { if (window.saveSettings) window.saveSettings(); }
  function curCard() { return window.currentCard ? window.currentCard() : null; }
  function trim(x) { return String(x == null ? "" : x).trim(); }
  function localDay(d) { return window.HSKUtil.date.localDay(d); }   // delegates to core/util/date.js

  /* ---------------- bookmarks ---------------- */
  // Reads delegate to the read-only UserMetadataQuery (Phase 7). Writes below
  // still mutate S() directly + persist(); the query observes them live.
  function bookmarks() { return MQ.getBookmarkIds(); }
  function isBookmarked(id) { return MQ.isBookmarked(id); }
  function toggleBookmark(id) {
    var s = S(); if (!Array.isArray(s.bookmarks)) s.bookmarks = [];
    var i = s.bookmarks.indexOf(id);
    if (i >= 0) s.bookmarks.splice(i, 1); else s.bookmarks.push(id);
    persist();
    return i < 0;
  }
  function removeBookmark(id) { var s = S(); if (Array.isArray(s.bookmarks)) { var i = s.bookmarks.indexOf(id); if (i >= 0) { s.bookmarks.splice(i, 1); persist(); } } }

  /* ---------------- notes (plain text) ---------------- */
  function notesMap() { return MQ.getNotesMap(); }
  function getNote(id) { return MQ.getNote(id); }
  function hasNote(id) { return MQ.hasNote(id); }
  function setNote(id, text) {
    var s = S(); if (!s.notes || typeof s.notes !== "object") s.notes = {};
    var t = trim(text);
    if (t === "") delete s.notes[id]; else s.notes[id] = t.slice(0, 1000);
    persist();
  }

  /* ---------------- daily learning (Study Mode grades, once/card/day) ---------------- */
  function dailyCounts() { var s = S(); return (s.dailyCounts && typeof s.dailyCounts === "object") ? s.dailyCounts : {}; }
  // Local calendar "yesterday" — decremented in LOCAL space then read via localDay()'s local
  // components (no UTC serialization), so month/year/leap/DST boundaries stay calendar-correct.
  function localYesterday() { var d = new Date(); d.setDate(d.getDate() - 1); return localDay(d); }
  // Normalize a possibly missing/corrupt streak to a non-negative integer.
  function normStreak(v) { return (typeof v === "number" && isFinite(v) && v > 0) ? Math.floor(v) : 0; }

  function recordDailyLearn(id) {
    var s = S(), day = localDay();
    var isNewDay = !(s.todayLearn && s.todayLearn.day === day);   // first counted card of this local day?
    var tl = isNewDay ? { day: day, ids: [] } : s.todayLearn;
    if (tl.ids.indexOf(id) >= 0) return;   // already counted today -> once per card per day (no persist)
    tl.ids.push(id); s.todayLearn = tl;
    // Phase 22B streak (metadata owns the daily-activity write): the FIRST unique graded card of a
    // local day activates the day. Same trigger/day-basis as the daily count above — Again/Hard/Good/
    // Easy all qualify; Skip and Test Mode never reach here; regrade/duplicate hit the early return.
    if (isNewDay) {
      var st = normStreak(s.streak), prev = s.lastLearnDay;
      if (prev === undefined || prev === null || prev === "") s.streak = Math.max(st, 1);   // lazy migration: preserve existing, or activate a fresh user
      else if (prev === day) s.streak = st;                 // already active today -> unchanged
      else if (prev === localYesterday()) s.streak = st + 1; // consecutive local day -> +1
      else s.streak = 1;                                     // older / future / corrupt anchor -> reset to today
      s.lastLearnDay = day;                                  // local-day anchor (settings.lastStudy left inert)
    }
    if (!s.dailyCounts || typeof s.dailyCounts !== "object") s.dailyCounts = {};
    s.dailyCounts[day] = (s.dailyCounts[day] || 0) + 1;
    pruneDaily(s.dailyCounts);
    persist();   // exactly one settings save + one sync-dirty notification for the qualifying grade
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
