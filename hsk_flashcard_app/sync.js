/* ============================================================
 *  sync.js — cloud sync for the logged-in account.
 *  Local-first: localStorage stays the live store; only CHANGED
 *  cards are pushed. Conflict rule = latest updated_at wins
 *  (server never overwrites a newer row; see sync_push_* RPCs).
 *  Fully inert unless a user is logged in (zero regression).
 * ============================================================ */
(function () {
  "use strict";

  var A = window.HSK_AUTH || {};
  if (!(A.configured && A.userId && window.HSKAuth)) return; // not logged in -> do nothing

  var uid = A.userId;
  var DIRTY_KEY  = "hsk_sync_dirty::"  + uid;   // [cardId,...] pending upload
  var META_KEY   = "hsk_sync_meta::"   + uid;   // {cardId: updatedAtISO}
  var LASTPULL   = "hsk_sync_lastpull::" + uid; // ISO of last successful pull
  var SETTIME    = "hsk_sync_settime::" + uid;  // settings updatedAt ISO
  var IMPORTDONE = "hsk_import_done::"  + uid;   // legacy-import prompt shown once

  function progressKey() { return window.HSK_AUTH.progressKey; }
  function settingsKey() { return window.HSK_AUTH.settingsKey; }
  function rd(k, d) { try { var v = JSON.parse(localStorage.getItem(k)); return v == null ? d : v; } catch (_) { return d; } }
  function wr(k, v) { localStorage.setItem(k, JSON.stringify(v)); }
  function nowISO() { return new Date().toISOString(); }
  function base() { return window.HSKAuth.base(); }

  function dirtySet() { return rd(DIRTY_KEY, []); }
  function setDirty(arr) { wr(DIRTY_KEY, arr); }
  function meta() { return rd(META_KEY, {}); }
  function setMeta(m) { wr(META_KEY, m); }

  function uiState(t) { if (window.HSKAuth.setSyncState) window.HSKAuth.setSyncState(t); }

  /* -------------------- REST helpers -------------------- */
  async function authedFetch(path, opts) {
    var token = await window.HSKAuth.accessToken(); // throws when offline / no session
    opts = opts || {};
    opts.headers = window.HSKAuth.headers({ "Authorization": "Bearer " + token,
      "Prefer": opts.prefer || "return=minimal" });
    if (opts.prefer) delete opts.prefer;
    var res = await fetch(base() + path, opts);
    if (!res.ok) throw { status: res.status, message: "sync " + res.status };
    return res;
  }
  async function rpc(fn, body) {
    return authedFetch("/rest/v1/rpc/" + fn, { method: "POST", body: JSON.stringify(body) });
  }

  /* -------------------- PUSH -------------------- */
  var pushTimer = null;
  function schedulePush() { clearTimeout(pushTimer); pushTimer = setTimeout(function () { pushProgress(); pushSettings(); }, 1200); }

  function markDirty(id) {
    if (id == null) return;
    id = Number(id);
    var d = dirtySet();
    if (d.indexOf(id) < 0) { d.push(id); setDirty(d); }
    var m = meta(); m[id] = nowISO(); setMeta(m);
    uiState("Chờ đồng bộ…");
    schedulePush();
  }

  async function pushProgress() {
    var ids = dirtySet();
    if (!ids.length) return;
    var prog = rd(progressKey(), {});
    var m = meta();
    var rows = [], deletes = [];
    ids.forEach(function (id) {
      var p = prog[id];
      if (p) rows.push({ card_id: id, due: p.due || null, interval: p.interval || 0,
        reps: p.reps || 0, correct: p.correct || 0, attempts: p.attempts || 0,
        updated_at: m[id] || nowISO() });
      else deletes.push(id);
    });
    try {
      if (rows.length) await rpc("sync_push_progress", { rows: rows });
      if (deletes.length) await authedFetch("/rest/v1/card_progress?card_id=in.(" + deletes.join(",") + ")", { method: "DELETE" });
      setDirty([]); // everything we just tried is now committed
      uiState("Đã đồng bộ · " + shortTime());
    } catch (e) {
      uiState(offlineish(e) ? "Ngoại tuyến · sẽ đồng bộ sau" : "Lỗi đồng bộ (thử lại sau)");
    }
  }

  // Returns TRUE only when the server confirmed this settings blob. Phase
  // 24E-B.5B: the pack-switch API needs to report whether the user's choice
  // actually reached the cloud. Existing callers ignore the return value and
  // the catch/retry behavior is unchanged -- a failure is still swallowed and
  // retried by the next flush()/online event.
  async function pushSettings() {
    var s = rd(settingsKey(), null);
    if (!s) return false;
    var t = localStorage.getItem(SETTIME) || nowISO();
    try {
      await rpc("sync_push_settings", { p_data: s, p_updated_at: t });
      return true;
    } catch (_) { return false; /* keep for later */ }
  }

  /* -------------------- PULL / MERGE -------------------- */
  async function pullProgress(full) {
    var since = full ? null : localStorage.getItem(LASTPULL);
    var q = "/rest/v1/card_progress?select=card_id,due,interval,reps,correct,attempts,updated_at";
    if (since) q += "&updated_at=gt." + encodeURIComponent(since);
    var res = await authedFetch(q, { method: "GET", prefer: "return=representation" });
    var rows = await res.json();
    if (!Array.isArray(rows)) return 0;
    var prog = rd(progressKey(), {});
    var m = meta();
    var d = dirtySet();
    var changed = 0;
    rows.forEach(function (row) {
      var id = row.card_id;
      var localTime = m[id];
      // Do not clobber a locally pending (dirty) change that is newer.
      if (d.indexOf(id) >= 0 && localTime && localTime >= row.updated_at) return;
      if (!localTime || row.updated_at > localTime) {
        prog[id] = { due: row.due, interval: row.interval, reps: row.reps, correct: row.correct, attempts: row.attempts };
        m[id] = row.updated_at; changed++;
      }
    });
    if (changed) { wr(progressKey(), prog); setMeta(m); }
    localStorage.setItem(LASTPULL, nowISO());
    return changed;
  }

  async function pullSettings() {
    var res = await authedFetch("/rest/v1/user_settings?select=data,updated_at", { method: "GET", prefer: "return=representation" });
    var rows = await res.json();
    if (!Array.isArray(rows) || !rows.length) return 0;
    var srv = rows[0];
    var localT = localStorage.getItem(SETTIME);
    if (!localT || srv.updated_at > localT) {
      wr(settingsKey(), srv.data || {});
      localStorage.setItem(SETTIME, srv.updated_at);
      return 1;
    }
    return 0;
  }

  /* -------------------- public lifecycle -------------------- */
  async function pullAll() { // used right after login (page reloads afterwards)
    await pullProgress(true);
    await pullSettings();
  }

  /*
   * Initial-pull readiness (Phase 24E-B.5B).
   *
   * pullSettings() replaces the settings blob WHOLESALE and only accepts the
   * server copy when it is newer than SETTIME. So anything that writes settings
   * before the initial pull has settled makes local look newer, suppresses the
   * pull, and lets the next whole-blob push overwrite the account's bookmarks
   * and notes. The pack-switch API must therefore be able to wait for this.
   *
   * readyPromise settles after the initial pullProgress + pullSettings attempt
   * and any reloadState() handling -- including the offline/failure path, which
   * is caught below -- but BEFORE maybeMigrateLegacy(), because that shows a
   * modal and waits for the user. Nothing else about the sequence changes.
   */
  var startPromise = null, readyResolve = null;
  var readyPromise = new Promise(function (res) { readyResolve = res; });
  function whenReady() { return readyPromise; }

  function start() { // used on every normal load while logged in
    // Idempotent: repeated calls reuse the one start operation, so the "online"
    // listener below can never be registered twice.
    if (startPromise) return startPromise;
    startPromise = (async function () {
      window.addEventListener("online", flush);
      // background: pull cloud changes (full on a fresh device), reflect them, then
      // run the one-time legacy import prompt, then flush anything pending.
      // The two pulls are guarded INDEPENDENTLY. They used to share one try,
      // so a rejected progress request skipped the settings request entirely
      // while readiness still settled -- and a pack switch could then overwrite
      // cloud bookmarks/notes this device had never seen. Progress is still
      // attempted first; settings is attempted regardless of its outcome.
      var changed = 0, failedAny = false;
      try { changed += await pullProgress(false); }
      catch (e) { failedAny = true; }
      try { changed += await pullSettings(); }
      catch (e) { failedAny = true; }
      try {
        if (changed && window.HSK_APP) window.HSK_APP.reloadState();
      } catch (e) { failedAny = true; }
      uiState(failedAny
        ? (navigator.onLine ? "Lỗi đồng bộ (thử lại sau)" : "Ngoại tuyến · sẽ đồng bộ sau")
        : "Đã đồng bộ · " + shortTime());
      readyResolve(true);            // settles before the legacy prompt blocks
      try { await maybeMigrateLegacy(); } catch (_) {}
      flush();
    })();
    return startPromise;
  }

  // Progress push and its existing error/UI behavior are unchanged; the return
  // value reports the SETTINGS push specifically.
  async function flush() { await pushProgress(); return await pushSettings(); }

  function onSettingsChanged() { localStorage.setItem(SETTIME, nowISO()); schedulePush(); }

  async function onReset() {
    setDirty([]); setMeta({});
    try { await authedFetch("/rest/v1/card_progress?card_id=gte.0", { method: "DELETE" }); uiState("Đã đồng bộ · " + shortTime()); }
    catch (_) { uiState("Ngoại tuyến · sẽ đồng bộ sau"); }
  }

  /* -------------------- one-time legacy import -------------------- */
  function legacyProgress() { try { return JSON.parse(localStorage.getItem("hsk_flashcard_progress_v2") || "null"); } catch (_) { return null; } }
  function legacySettings() { try { return JSON.parse(localStorage.getItem("hsk_flashcard_settings_v2") || "null"); } catch (_) { return null; } }

  async function maybeMigrateLegacy() {
    if (localStorage.getItem(IMPORTDONE)) return;
    var lp = legacyProgress();
    var count = lp ? Object.keys(lp).length : 0;
    if (!count) { localStorage.setItem(IMPORTDONE, "1"); return; }
    var choice = await legacyPrompt(count, lp);
    if (choice === "import") {
      importLegacy(lp, legacySettings());
      await flush();
    }
    localStorage.setItem(IMPORTDONE, "1"); // asked once, regardless of choice. Legacy data is NOT deleted.
  }

  function importLegacy(lp, ls) {
    var prog = rd(progressKey(), {});
    var m = meta();
    var d = dirtySet();
    var t = nowISO();
    var added = 0;
    // Only fill cards the cloud does NOT already have -> never overwrite newer cloud data.
    Object.keys(lp).forEach(function (id) {
      if (prog[id] == null) {
        prog[id] = lp[id];
        m[id] = t;
        if (d.indexOf(Number(id)) < 0) d.push(Number(id));
        added++;
      }
    });
    if (added) { wr(progressKey(), prog); setMeta(m); setDirty(d); }
    // Adopt legacy settings only if this account has none yet.
    var cur = rd(settingsKey(), null);
    if ((!cur || !Object.keys(cur).length) && ls) { wr(settingsKey(), ls); localStorage.setItem(SETTIME, t); }
  }

  function legacyPrompt(count, lp) {
    return new Promise(function (resolve) {
      var back = document.createElement("div");
      back.className = "auth-gate visible migrate-gate";
      back.innerHTML =
        '<div class="auth-card">' +
          '<h2 style="margin:0 0 6px">Tìm thấy tiến độ trên thiết bị</h2>' +
          '<p class="muted" style="margin:0 0 14px">Bạn đã có <b>' + count + '</b> thẻ đã học trên thiết bị này. ' +
          'Nhập vào tài khoản của bạn?</p>' +
          '<div id="mgSummary" class="migrate-summary auth-hidden"></div>' +
          '<div class="migrate-actions">' +
            '<button type="button" class="primary-btn" data-a="import">Nhập vào tài khoản</button>' +
            '<button type="button" class="secondary-btn" data-a="summary">Xem chi tiết</button>' +
            '<button type="button" class="secondary-btn" data-a="skip">Bỏ qua</button>' +
          '</div>' +
          '<p class="auth-hint">Dữ liệu trên thiết bị sẽ KHÔNG bị xóa. Nhập sẽ không ghi đè dữ liệu mới hơn trên cloud.</p>' +
        '</div>';
      document.body.appendChild(back);
      back.querySelectorAll("[data-a]").forEach(function (b) {
        b.onclick = function () {
          var a = b.dataset.a;
          if (a === "summary") {
            var lv = {}; Object.keys(lp).forEach(function (id) { var c = (window.HSK_CARDS || []).find(function (x) { return x.id == id; }); var L = c ? c.level : "?"; lv[L] = (lv[L] || 0) + 1; });
            var s = Object.keys(lv).sort().map(function (k) { return k + ": " + lv[k]; }).join(" · ");
            var box = back.querySelector("#mgSummary"); box.textContent = "Tổng " + count + " thẻ — " + (s || "");
            box.classList.remove("auth-hidden");
            return;
          }
          back.remove();
          resolve(a); // "import" | "skip"
        };
      });
    });
  }

  /* -------------------- utils -------------------- */
  function offlineish(e) { return !navigator.onLine || (e && (e.message === "Failed to fetch" || e.name === "TypeError")); }
  function shortTime() { var d = new Date(); return ("0" + d.getHours()).slice(-2) + ":" + ("0" + d.getMinutes()).slice(-2); }

  window.HSKSync = {
    start: start,
    whenReady: whenReady,
    pullAll: pullAll,
    flush: flush,
    markDirty: markDirty,
    onSettingsChanged: onSettingsChanged,
    onReset: onReset,
    maybeMigrateLegacy: maybeMigrateLegacy
  };
})();
