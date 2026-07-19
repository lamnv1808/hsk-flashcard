/*
 * pack-boot-shim.js — the parser-time adapter that turns a boot PLAN into two
 * synchronous classic <script> insertions. Phase 24E-B.
 *
 * This is the only place in the app that inserts a script tag. It is a thin
 * adapter on purpose: every decision (which pack, why, which paths) is made by
 * the pure planner in core/content/pack-boot.js, which has no DOM access. All
 * this file does is execute that decision at the right two parse positions.
 *
 * WHY TWO INSERTION POINTS, AND WHY NOT plan.scripts
 * --------------------------------------------------
 * plan.scripts is [manifestPath, cardsPath]. That order is NOT the physical
 * load order and must not be used for insertion. The real dependency graph is:
 *
 *     data.js (window.HSK_CARDS)
 *       -> core/util/{levels,card-index}.js
 *       -> core/content/content-pack.js   (createContentPack)
 *       -> packs/hsk/hsk-content-pack.js  (reads HSK_CARDS, calls createContentPack)
 *       -> core/cards/card-repository.js  (eager singleton over the pack's cards)
 *
 * The manifest adapter therefore depends on BOTH the cards payload and three
 * core modules that sit between them, so the two payloads cannot be inserted
 * adjacently in either order. Instead the shim exposes writeCards() and
 * writeManifest(), called from index.html at exactly the parse positions the
 * static <script src="data.js"> and <script src="packs/hsk/hsk-content-pack.js">
 * tags used to occupy. Physical order is preserved byte-for-byte; only the
 * SOURCE of the two paths changes (now plan.expected.*). Fixing this by
 * reordering plan.scripts in core/content/pack-boot.js was explicitly rejected:
 * the planner is product-neutral and the ordering is a property of THIS app's
 * script graph, not of the plan.
 *
 * WHY document.write
 * ------------------
 * It is the only mechanism that inserts a parser-blocking classic script at the
 * current parse position with no async step. appendChild() would load async and
 * let card-repository.js initialize over an empty dataset; fetch/import/modules
 * are all forbidden here for the same reason. Both calls happen while the
 * document is still parsing, never after — writeCards()/writeManifest() refuse
 * to run once readyState leaves "loading".
 *
 * WHY IT READS SETTINGS ITSELF
 * ----------------------------
 * activePackId lives in the account-namespaced settings blob, but HSK_AUTH is
 * defined by auth.js far below this point, so it cannot be consulted. auth.js
 * derives its namespace synchronously from SUPABASE_CONFIG + the cached
 * hsk_current_user record, and this mirrors that exact rule (see auth.js
 * "SYNCHRONOUS boot" block). No network, no Supabase call, no async.
 *
 * Never boots empty and never boots mixed: the planner falls back to the
 * validated default launch-visible pack for unknown/malformed/hidden/
 * incompatible requests, and a catalog that fails validation renders a visible
 * error instead of an empty app.
 */
(function (NS) {
  "use strict";

  // Mirrors auth.js PROG_BASE/SET_BASE + USER_KEY. Kept in sync deliberately:
  // this file runs before auth.js exists, so it cannot import them.
  var SETTINGS_BASE = "hsk_flashcard_settings_v2";
  var USER_KEY = "hsk_current_user";

  var state = {
    plan: null,
    error: null,
    resolved: false,
    wroteCards: false,
    wroteManifest: false
  };

  function readJSON(key) {
    try { return JSON.parse(localStorage.getItem(key) || "null"); }
    catch (_) { return null; }
  }

  /*
   * The settings key for the CURRENT account, derived exactly as auth.js does:
   * namespaced only when Supabase is configured AND a cached user record with
   * an id exists; otherwise the original local-only key.
   */
  function settingsKey() {
    var cfg = window.SUPABASE_CONFIG || {};
    var configured = !!(cfg.url && cfg.anonKey);
    var user = configured ? readJSON(USER_KEY) : null;
    return (user && user.id) ? SETTINGS_BASE + "::" + user.id : SETTINGS_BASE;
  }

  /*
   * The RAW stored activePackId, passed through untouched.
   *
   * This deliberately does no validation. planPackBoot already classifies the
   * value -- absent/null/undefined/"" as first-run, any non-string or
   * non-matching string as malformed, an unmatched valid id as unknown -- and
   * records a distinct reason for each. Re-checking the shape here would create
   * a second source of truth that can drift from the planner's, and it would
   * silently collapse distinct outcomes: coercing a stored object or number to
   * null would report it as a clean first run rather than as the corrupted
   * storage it actually is.
   *
   * Only a missing/unreadable settings blob yields null, because then there is
   * genuinely nothing stored.
   */
  function readActivePackId() {
    var blob = readJSON(settingsKey());
    if (!blob || typeof blob !== "object") return null;
    return blob.activePackId;
  }

  function resolve() {
    if (state.resolved) return state.plan;
    state.resolved = true;
    try {
      var registry = NS.createPackRegistry(window.FLASHEDU_CATALOG);
      var plan = NS.planPackBoot({
        registry: registry,
        requestedPackId: readActivePackId(),
        // The app version comes from the VALIDATED catalog, never a literal
        // here. Without it every pack declaring a minAppVersion would be
        // treated as incompatible and silently hidden, because isCompatible()
        // fails closed on a non-string version.
        appVersion: registry.getAppVersion()
      });
      if (!plan || plan.ok !== true) {
        state.error = (plan && plan.error) ||
          { code: "NO_PLAN", message: "boot planning produced no plan" };
        return null;
      }
      state.plan = plan;
      return plan;
    } catch (e) {
      // A catalog that fails validation is fatal BY DESIGN: booting some other
      // pack could mix card ids across a learner's progress rows.
      state.error = { code: "CATALOG_INVALID", message: String((e && e.message) || e) };
      return null;
    }
  }

  /*
   * Defence in depth. The registry already rejects URLs, absolute paths, '..'
   * segments and backslashes, but this is the point where a string becomes
   * markup, so re-reject anything that could break out of the src attribute.
   */
  function safePath(path) {
    return typeof path === "string" && path.length > 0 &&
      path.indexOf('"') < 0 && path.indexOf("'") < 0 &&
      path.indexOf("<") < 0 && path.indexOf(">") < 0 &&
      path.indexOf("\\") < 0 && path.indexOf("://") < 0 &&
      path.charAt(0) !== "/" && path.split("/").indexOf("..") < 0;
  }

  function fail(code, message) {
    if (!state.error) state.error = { code: code, message: message };
    // Visible, not silent: an empty page with a clean console is the worst
    // possible outcome because it looks like "no cards yet".
    try {
      document.write(
        '<div style="padding:16px;margin:16px;border:2px solid #b91c1c;' +
        'border-radius:8px;font-family:system-ui,sans-serif;color:#b91c1c">' +
        "<strong>Không thể tải bộ thẻ.</strong><br>" +
        "Content pack failed to load (" + code + "). " +
        "Please reinstall or update the app.</div>");
    } catch (_) { /* nothing further we can do during parse */ }
  }

  function writeScript(path) {
    // The closing tag is split so this text can never terminate an enclosing
    // <script> element if this file is ever inlined.
    document.write('<script src="' + path + '"><\/script>');
  }

  function assertParsing(what) {
    if (document.readyState !== "loading") {
      state.error = state.error ||
        { code: "LATE_INSERTION", message: what + " called after parsing" };
      return false;
    }
    return true;
  }

  /* Insert the active pack's CARDS payload at the old data.js parse position. */
  function writeCards() {
    if (state.wroteCards) return false;          // no duplicate execution
    if (!assertParsing("writeCards")) return false;
    var plan = resolve();
    if (!plan) { fail(state.error.code, state.error.message); return false; }
    var path = plan.expected.cardsPath;          // NOT plan.scripts
    if (!safePath(path)) { fail("UNSAFE_PATH", "cardsPath rejected: " + path); return false; }
    state.wroteCards = true;
    writeScript(path);
    return true;
  }

  /* Insert the active pack's MANIFEST adapter at the old adapter position. */
  function writeManifest() {
    if (state.wroteManifest) return false;       // no duplicate execution
    if (!assertParsing("writeManifest")) return false;
    var plan = resolve();
    if (!plan) { fail(state.error.code, state.error.message); return false; }
    // Cards must already be in flight/executed; a manifest without its payload
    // would construct a ContentPack over an empty array.
    if (!state.wroteCards) {
      fail("ORDER_VIOLATION", "writeManifest called before writeCards");
      return false;
    }
    var path = plan.expected.manifestPath;       // NOT plan.scripts
    if (!safePath(path)) { fail("UNSAFE_PATH", "manifestPath rejected: " + path); return false; }
    state.wroteManifest = true;
    writeScript(path);
    return true;
  }

  NS.packBootShim = {
    writeCards: writeCards,
    writeManifest: writeManifest,
    // Introspection for tests and for the Phase 24F pack switcher.
    getPlan: function () { return state.plan; },
    getError: function () { return state.error; },
    getActivePackId: function () { return state.plan ? state.plan.packId : null; },
    getRequestedPackId: readActivePackId,
    getSettingsKey: settingsKey,
    getBootReason: function () { return state.plan ? state.plan.reason : null; },
    didWrite: function () {
      return { cards: state.wroteCards, manifest: state.wroteManifest };
    }
  };
})(window.HSKUtil = window.HSKUtil || {});
