/* ============================================================
 *  auth.js — accounts + session (config-gated, additive).
 *  - Talks to Supabase Auth / Edge Functions over plain fetch
 *    (no external CDN, so the PWA stays offline-friendly).
 *  - When SUPABASE_CONFIG is empty this file is a NO-OP and the
 *    app behaves exactly as before (local-only, zero regression).
 * ============================================================ */
(function () {
  "use strict";

  var CFG = window.SUPABASE_CONFIG || {};
  var CONFIGURED = !!(CFG.url && CFG.anonKey);

  var SESSION_KEY = "hsk_session";        // {access_token, refresh_token, expires_at}
  var USER_KEY    = "hsk_current_user";   // {id, username}  (NOT sensitive; used for namespacing)
  var PROG_BASE   = "hsk_flashcard_progress_v2";
  var SET_BASE    = "hsk_flashcard_settings_v2";

  function readJSON(k) { try { return JSON.parse(localStorage.getItem(k) || "null"); } catch (_) { return null; } }
  function nsProgress(id) { return PROG_BASE + "::" + id; }
  function nsSettings(id) { return SET_BASE + "::" + id; }

  /* ---- SYNCHRONOUS boot: choose the storage namespace before app.js reads it ---- */
  var bootUser = CONFIGURED ? readJSON(USER_KEY) : null;
  if (!CONFIGURED) {
    window.HSK_AUTH = { configured: false };
    return; // local-only mode. Nothing else happens.
  }
  window.HSK_AUTH = (bootUser && bootUser.id)
    ? { configured: true, userId: bootUser.id, username: bootUser.username,
        progressKey: nsProgress(bootUser.id), settingsKey: nsSettings(bootUser.id) }
    : { configured: true, needsAuth: true };

  /* ---------------------- low-level HTTP ---------------------- */
  function base() { return CFG.url.replace(/\/+$/, ""); }
  function headers(extra) {
    var h = { "apikey": CFG.anonKey, "Content-Type": "application/json" };
    for (var k in (extra || {})) h[k] = extra[k];
    return h;
  }
  function getSession() { return readJSON(SESSION_KEY); }
  function setSession(s) {
    if (!s) { localStorage.removeItem(SESSION_KEY); return; }
    var expiresAt = s.expires_at ? s.expires_at * 1000
      : (Date.now() + (s.expires_in ? s.expires_in * 1000 : 3600000));
    localStorage.setItem(SESSION_KEY, JSON.stringify({
      access_token: s.access_token, refresh_token: s.refresh_token, expires_at: expiresAt
    }));
  }
  function setUser(u) { localStorage.setItem(USER_KEY, JSON.stringify({ id: u.id, username: u.username })); }

  async function callFn(name, body, accessToken) {
    var res = await fetch(base() + "/functions/v1/" + name, {
      method: "POST",
      headers: headers(accessToken ? { "Authorization": "Bearer " + accessToken } : null),
      body: JSON.stringify(body || {})
    });
    var data = null;
    try { data = await res.json(); } catch (_) {}
    if (!res.ok) throw { status: res.status, message: (data && data.error) || ("HTTP " + res.status), data: data };
    return data;
  }

  async function refreshSession() {
    var s = getSession();
    if (!s || !s.refresh_token) throw { message: "no session" };
    var res = await fetch(base() + "/auth/v1/token?grant_type=refresh_token", {
      method: "POST", headers: headers(), body: JSON.stringify({ refresh_token: s.refresh_token })
    });
    if (!res.ok) throw { message: "refresh failed", status: res.status };
    var j = await res.json();
    setSession(j);
    return j.access_token;
  }

  // Returns a valid access token, refreshing if it is near expiry. Throws when offline / invalid.
  async function accessToken() {
    var s = getSession();
    if (!s) throw { message: "no session" };
    if (s.expires_at && s.expires_at - Date.now() < 60000) return await refreshSession();
    return s.access_token;
  }

  /* ---------------------- auth actions ---------------------- */
  var USERNAME_RE = /^[a-z0-9._-]{3,20}$/;
  var PIN_RE = /^\d{4}$/;
  function normUser(u) { return String(u || "").trim().toLowerCase(); }
  function validUsername(u) { return USERNAME_RE.test(normUser(u)); }
  function validPin(p) { return PIN_RE.test(String(p || "")); }

  async function register(username, pin) {
    var out = await callFn("register", { username: normUser(username), pin: String(pin) });
    setSession(out.session); setUser(out.user);
    return out.user;
  }
  async function login(username, pin) {
    var out = await callFn("login", { username: normUser(username), pin: String(pin) });
    setSession(out.session); setUser(out.user);
    return out.user;
  }
  async function changePin(oldPin, newPin) {
    var t = await accessToken();
    return await callFn("change-pin", { oldPin: String(oldPin), newPin: String(newPin) }, t);
  }
  async function deleteAccount(pin) {
    var t = await accessToken();
    return await callFn("delete-account", { pin: String(pin) }, t);
  }
  function localLogout() {
    localStorage.removeItem(SESSION_KEY);
    localStorage.removeItem(USER_KEY);
  }

  /* ---------------------- expose API for sync.js ---------------------- */
  window.HSKAuth = {
    configured: true,
    cfg: CFG,
    base: base, headers: headers,
    accessToken: accessToken,
    currentUser: function () { return readJSON(USER_KEY); },
    isLoggedIn: function () { return !!getSession() && !!readJSON(USER_KEY); }
  };

  /* ============================================================
   *  UI — injected so index.html stays almost untouched.
   * ============================================================ */
  function el(tag, attrs, html) {
    var e = document.createElement(tag);
    for (var k in (attrs || {})) {
      if (k === "class") e.className = attrs[k];
      else if (k === "html") e.innerHTML = attrs[k];
      else e.setAttribute(k, attrs[k]);
    }
    if (html != null) e.innerHTML = html;
    return e;
  }

  function buildGate() {
    var wrap = el("div", { id: "authGate", class: "auth-gate", role: "dialog", "aria-modal": "true", "aria-label": "Đăng nhập" });
    wrap.innerHTML =
      '<div class="auth-card">' +
        '<div class="auth-brand"><div class="eyebrow">FLASHCARD TIẾNG TRUNG</div><h2>HSK1–HSK4</h2></div>' +
        '<div class="auth-tabs">' +
          '<button type="button" class="auth-tab active" data-tab="login">Đăng nhập</button>' +
          '<button type="button" class="auth-tab" data-tab="register">Đăng ký</button>' +
        '</div>' +
        '<form id="authForm" class="auth-form" autocomplete="off">' +
          '<label class="auth-label" for="auUser">Tên đăng nhập</label>' +
          '<input id="auUser" class="auth-input" type="text" inputmode="latin" autocapitalize="none" autocorrect="off" maxlength="20" placeholder="vd: minh_an" />' +
          '<label class="auth-label" for="auPin">Mã PIN (4 chữ số)</label>' +
          '<input id="auPin" class="auth-input" type="password" inputmode="numeric" pattern="\\d*" maxlength="4" placeholder="••••" />' +
          '<div id="auConfirmRow" class="auth-hidden">' +
            '<label class="auth-label" for="auPin2">Nhập lại mã PIN</label>' +
            '<input id="auPin2" class="auth-input" type="password" inputmode="numeric" pattern="\\d*" maxlength="4" placeholder="••••" />' +
          '</div>' +
          '<p id="auMsg" class="auth-msg" role="alert"></p>' +
          '<button id="auSubmit" type="submit" class="primary-btn auth-submit">Đăng nhập</button>' +
        '</form>' +
        '<p class="auth-hint">Chỉ cần tên đăng nhập và mã PIN 4 số. Tiến độ học của bạn được lưu và đồng bộ trên mọi thiết bị.</p>' +
      '</div>';
    return wrap;
  }

  var gateMode = "login";
  function setGateMode(mode) {
    gateMode = mode;
    document.querySelectorAll(".auth-tab").forEach(function (t) { t.classList.toggle("active", t.dataset.tab === mode); });
    document.getElementById("auConfirmRow").classList.toggle("auth-hidden", mode !== "register");
    document.getElementById("auSubmit").textContent = mode === "register" ? "Tạo tài khoản" : "Đăng nhập";
    msg("");
  }
  function msg(text, kind) {
    var m = document.getElementById("auMsg");
    if (!m) return;
    m.textContent = text || "";
    m.className = "auth-msg" + (kind ? " " + kind : "");
  }

  function showGate() {
    if (document.getElementById("authGate")) { document.getElementById("authGate").classList.add("visible"); return; }
    var gate = buildGate();
    document.body.appendChild(gate);
    document.body.classList.add("auth-locked");
    requestAnimationFrame(function () { gate.classList.add("visible"); });

    gate.querySelectorAll(".auth-tab").forEach(function (t) {
      t.onclick = function () { setGateMode(t.dataset.tab); };
    });
    document.getElementById("auPin").addEventListener("input", digitsOnly);
    document.getElementById("auPin2").addEventListener("input", digitsOnly);
    document.getElementById("authForm").addEventListener("submit", onSubmit);
    document.getElementById("auUser").focus();
  }
  function hideGate() {
    var g = document.getElementById("authGate");
    if (g) g.remove();
    document.body.classList.remove("auth-locked");
  }
  function digitsOnly(e) { e.target.value = e.target.value.replace(/\D/g, "").slice(0, 4); }

  function busy(on) {
    var b = document.getElementById("auSubmit");
    if (b) { b.disabled = on; b.textContent = on ? "Đang xử lý…" : (gateMode === "register" ? "Tạo tài khoản" : "Đăng nhập"); }
  }

  async function onSubmit(e) {
    e.preventDefault();
    var username = document.getElementById("auUser").value;
    var pin = document.getElementById("auPin").value;
    var pin2 = document.getElementById("auPin2").value;

    if (!validUsername(username)) { return msg("Tên đăng nhập 3–20 ký tự, chỉ gồm chữ thường, số, . _ -", "err"); }
    if (!validPin(pin)) { return msg("Mã PIN phải gồm đúng 4 chữ số.", "err"); }
    if (gateMode === "register" && pin !== pin2) { return msg("Hai lần nhập PIN không khớp.", "err"); }

    busy(true);
    try {
      var user = gateMode === "register" ? await register(username, pin) : await login(username, pin);
      msg("Thành công! Đang tải dữ liệu…", "ok");
      await afterLogin(user);
    } catch (err) {
      msg(errorText(err), "err");
      busy(false);
    }
  }

  function errorText(err) {
    if (err && err.status === 429) return "Sai quá nhiều lần. Vui lòng thử lại sau ít phút.";
    if (err && err.status === 409) return "Tên đăng nhập đã tồn tại. Hãy chọn tên khác.";
    if (err && err.status === 401) return "Sai tên đăng nhập hoặc mã PIN.";
    if (err && (err.message === "Failed to fetch" || err.name === "TypeError")) return "Không có kết nối mạng. Hãy thử lại khi online.";
    return (err && err.message) || "Có lỗi xảy ra. Vui lòng thử lại.";
  }

  /* ---- after a successful auth: reload so the app re-initializes under the account ----
     session + user are already stored. On reload, auth.js picks the namespaced storage
     keys and sync.js activates (pull cloud data, run the one-time migration prompt). ---- */
  async function afterLogin(user) {
    location.reload();
  }

  /* ============================================================
   *  Profile menu (compact button in the top bar)
   * ============================================================ */
  function buildProfile(username) {
    var host = document.querySelector(".topbar-actions") || document.querySelector(".topbar");
    var btn = el("button", { id: "profileBtn", class: "profile-btn icon-btn", type: "button", "aria-haspopup": "true", "aria-expanded": "false", "aria-label": "Tài khoản" });
    btn.textContent = (username || "?").slice(0, 1).toUpperCase();
    var menu = el("div", { id: "profileMenu", class: "profile-menu auth-hidden", role: "menu" });
    menu.innerHTML =
      '<div class="profile-head"><span class="profile-hi">Đang đăng nhập</span><strong id="profileName"></strong></div>' +
      '<button type="button" class="profile-item" data-act="export" role="menuitem">Xuất tiến độ (.json)</button>' +
      '<button type="button" class="profile-item" data-act="changepin" role="menuitem">Đổi mã PIN</button>' +
      '<button type="button" class="profile-item" data-act="switch" role="menuitem">Chuyển tài khoản</button>' +
      '<button type="button" class="profile-item" data-act="logout" role="menuitem">Đăng xuất</button>' +
      '<button type="button" class="profile-item danger" data-act="delete" role="menuitem">Xóa tài khoản</button>' +
      '<div class="profile-foot"><span id="syncState" class="sync-state"></span></div>';
    if (host) host.insertBefore(btn, host.firstChild);
    document.body.appendChild(menu);
    menu.querySelector("#profileName").textContent = "@" + username;

    function toggle(open) {
      var show = open != null ? open : menu.classList.contains("auth-hidden");
      menu.classList.toggle("auth-hidden", !show);
      btn.setAttribute("aria-expanded", show ? "true" : "false");
      if (show) positionMenu();
    }
    function positionMenu() {
      var r = btn.getBoundingClientRect();
      menu.style.top = (r.bottom + 8) + "px";
      menu.style.right = Math.max(8, (window.innerWidth - r.right)) + "px";
    }
    btn.onclick = function (e) { e.stopPropagation(); toggle(); };
    document.addEventListener("click", function (e) { if (!menu.contains(e.target) && e.target !== btn) toggle(false); });
    window.addEventListener("resize", positionMenu);

    menu.querySelectorAll(".profile-item").forEach(function (it) {
      it.onclick = function () { toggle(false); onProfileAction(it.dataset.act); };
    });
    window.HSKAuth.setSyncState = function (txt) { var s = document.getElementById("syncState"); if (s) s.textContent = txt || ""; };
  }

  async function onProfileAction(act) {
    if (act === "export") return exportProgress();
    if (act === "logout") return doLogout(false);
    if (act === "switch") return doLogout(true);
    if (act === "changepin") return promptChangePin();
    if (act === "delete") return promptDelete();
  }

  function exportProgress() {
    var app = window.HSK_APP;
    var payload = {
      exported_at: new Date().toISOString(),
      username: (readJSON(USER_KEY) || {}).username,
      progress: app ? app.getProgress() : {},
      settings: app ? app.getSettings() : {}
    };
    var blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "hsk-progress-" + (payload.username || "user") + ".json";
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(function () { URL.revokeObjectURL(a.href); }, 4000);
  }

  async function doLogout(switchAccount) {
    try { if (window.HSKSync) await window.HSKSync.flush(); } catch (_) {}
    localLogout();
    // Keep this account's namespaced local cache; it will re-sync on next login.
    location.reload();
  }

  function promptChangePin() {
    var oldPin = prompt("Nhập mã PIN hiện tại (4 số):");
    if (oldPin == null) return;
    if (!validPin(oldPin)) return alert("Mã PIN phải gồm 4 chữ số.");
    var newPin = prompt("Nhập mã PIN mới (4 số):");
    if (newPin == null) return;
    if (!validPin(newPin)) return alert("Mã PIN mới phải gồm 4 chữ số.");
    var newPin2 = prompt("Nhập lại mã PIN mới:");
    if (newPin !== newPin2) return alert("Hai lần nhập PIN mới không khớp.");
    changePin(oldPin, newPin)
      .then(function () { alert("Đã đổi mã PIN."); })
      .catch(function (e) { alert(errorText(e)); });
  }

  function promptDelete() {
    if (!confirm("Xóa tài khoản sẽ xóa vĩnh viễn toàn bộ tiến độ trên cloud. Tiếp tục?")) return;
    var pin = prompt("Nhập mã PIN để xác nhận xóa tài khoản:");
    if (pin == null) return;
    if (!validPin(pin)) return alert("Mã PIN phải gồm 4 chữ số.");
    deleteAccount(pin)
      .then(function () { localLogout(); alert("Đã xóa tài khoản."); location.reload(); })
      .catch(function (e) { alert(errorText(e)); });
  }

  /* ============================================================
   *  Boot
   * ============================================================ */
  function boot() {
    if (window.HSK_AUTH && window.HSK_AUTH.userId) {
      // Logged in: show profile, kick off background sync (sync.js self-activates).
      buildProfile(window.HSK_AUTH.username);
      if (window.HSKSync) window.HSKSync.start();
    } else {
      // Configured but not logged in -> block the app with the gate.
      showGate();
    }
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();

  // expose a couple of hooks used by sync.js after it loads
  window.HSKAuth.showGate = showGate;
  window.HSKAuth.hideGate = hideGate;
})();
