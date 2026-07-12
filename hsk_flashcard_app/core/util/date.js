/* ============================================================
 *  core/util/date.js — pure, deterministic date-key helpers.
 *  No DOM, no storage, no network, no global app state.
 *  Two DISTINCT semantics are preserved exactly as in production:
 *    - localDay(): LOCAL calendar day (used by daily-learning analytics)
 *    - isoDay():   UTC calendar day  (used by SRS due-dates/history display)
 *  These are intentionally NOT unified — mixing them would shift dates
 *  across the local/UTC boundary near midnight. See docs Phase 2.
 * ============================================================ */
(function () {
  "use strict";
  var NS = (window.HSKUtil = window.HSKUtil || {});

  // LOCAL calendar day "YYYY-MM-DD" from local Date components.
  // Byte-identical to the previous metadata.js localDay(). Missing/falsy -> now.
  function localDay(date) {
    var d = date || new Date();
    var m = d.getMonth() + 1, day = d.getDate();
    return d.getFullYear() + "-" + (m < 10 ? "0" : "") + m + "-" + (day < 10 ? "0" : "") + day;
  }

  // UTC calendar day "YYYY-MM-DD" via toISOString slice.
  // Byte-identical to the previous app.today()/test.todayStr()/insights.fmtDate():
  //   - no argument  -> new Date() (current UTC day)
  //   - falsy input  -> "" (matches fmtDate's null guard)
  //   - invalid Date -> "" (matches todayStr's try/catch)
  function isoDay(date) {
    if (date === undefined) date = new Date();
    if (!date) return "";
    try { return date.toISOString().slice(0, 10); } catch (_) { return ""; }
  }

  NS.date = { localDay: localDay, isoDay: isoDay };
})();
