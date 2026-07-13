/* ============================================================
 *  core/auth/auth-context-query.js  (FlashEdu — Phase 15)
 *  Read-only projection over the CURRENT account identity + storage
 *  namespace. A stable seam so future domain services (StudySessionEngine,
 *  Phase 16) never read window.HSK_AUTH internals, raw localStorage keys,
 *  or local-only detection from arbitrary places.
 *
 *  It is NOT an authentication service. It never logs in/out, registers,
 *  deletes accounts, touches PINs/tokens/secrets, calls Supabase, writes
 *  localStorage, mutates state, reloads, or triggers sync. It returns
 *  plain read-only data derived from the auth module's exposed state.
 *
 *  Source of truth (set synchronously by auth.js at load; immutable per
 *  page — auth transitions do location.reload()):
 *    window.HSK_AUTH =
 *      { configured:false }                                   // local-only
 *    | { configured:true, needsAuth:true }                    // gated (not logged in)
 *    | { configured:true, userId, username, progressKey, settingsKey } // logged in
 *  HSK_AUTH holds NO tokens/PIN/secret (it is the namespacing object).
 * ============================================================ */
(function (NS) {
  "use strict";

  // Storage-key bases — the app's progress/settings key roots (mirror auth.js
  // PROG_BASE/SET_BASE and app.js's fallback literals). Overridable via config.
  var DEFAULT_PROGRESS_BASE = "hsk_flashcard_progress_v2";
  var DEFAULT_SETTINGS_BASE = "hsk_flashcard_settings_v2";

  // deps:
  //   authProvider       - () => window.HSK_AUTH (live; re-read every call)
  //   authModuleProvider - () => window.HSKAuth (presence => auth module loaded; for canSync)
  //   progressKeyBase / settingsKeyBase - storage-key roots (defaults above)
  function createAuthContextQuery(deps) {
    deps = deps || {};
    var readAuth = (typeof deps.authProvider === "function")
      ? deps.authProvider
      : function () { return deps.authProvider; };
    var readModule = (typeof deps.authModuleProvider === "function")
      ? deps.authModuleProvider
      : function () { return deps.authModuleProvider; };
    var PROG_BASE = deps.progressKeyBase || DEFAULT_PROGRESS_BASE;
    var SET_BASE = deps.settingsKeyBase || DEFAULT_SETTINGS_BASE;

    function auth() {
      var a = readAuth();
      return (a && typeof a === "object") ? a : {};
    }

    function isConfigured() { return !!auth().configured; }
    function requiresAuth() { return !!auth().needsAuth; }
    function isAuthenticated() { return !!auth().userId; }
    function isLocalOnly() { return !auth().configured; }   // NOT-configured == local-only (not "not logged in")
    function getUserId() { return auth().userId || null; }
    function getUsername() { return auth().username || null; }
    function getDisplayUsername() { return auth().username || null; }   // HSK_AUTH.username is already display-case
    // matches app.js bootstrap: HSK_AUTH.progressKey || base
    function getProgressKey() { return auth().progressKey || PROG_BASE; }
    function getSettingsKey() { return auth().settingsKey || SET_BASE; }
    // matches sync.js gate exactly: A.configured && A.userId && window.HSKAuth
    function canSync() { var a = auth(); return !!(a.configured && a.userId && readModule()); }

    // Complete read model. Contains ONLY namespacing/config fields — never a
    // token, PIN, password-derived secret, session object, or Supabase key.
    function getContext() {
      var a = auth();
      return {
        configured: !!a.configured,
        requiresAuth: !!a.needsAuth,
        authenticated: !!a.userId,
        localOnly: !a.configured,
        userId: a.userId || null,
        username: a.username || null,
        displayUsername: a.username || null,
        progressKey: a.progressKey || PROG_BASE,
        settingsKey: a.settingsKey || SET_BASE,
        syncAvailable: !!(a.configured && a.userId && readModule())
      };
    }

    return {
      getContext: getContext,
      isConfigured: isConfigured,
      requiresAuth: requiresAuth,
      isAuthenticated: isAuthenticated,
      isLocalOnly: isLocalOnly,
      getUserId: getUserId,
      getUsername: getUsername,
      getDisplayUsername: getDisplayUsername,
      getProgressKey: getProgressKey,
      getSettingsKey: getSettingsKey,
      canSync: canSync
    };
  }

  NS.createAuthContextQuery = createAuthContextQuery;
  // Shared instance over the live auth module state. Built once at load.
  NS.authContext = createAuthContextQuery({
    authProvider: function () { return window.HSK_AUTH || {}; },
    authModuleProvider: function () { return window.HSKAuth; }
  });

})(window.HSKUtil = window.HSKUtil || {});
