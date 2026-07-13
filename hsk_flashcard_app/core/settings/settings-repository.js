/* ============================================================
 *  core/settings/settings-repository.js  (FlashEdu — Phase 4)
 *  Read-only SettingsRepository: a centralized, normalizing READ
 *  seam over the existing per-user settings blob.
 *
 *  WHY a provider (not a frozen singleton like CardRepository):
 *  the active settings object is NOT stable for the page lifetime.
 *    - cloud pull  -> app.js reloadState() REASSIGNS `settings`
 *    - login/logout/account-switch/delete -> location.reload() (fresh module)
 *  So the repository must always read the CURRENT active object. It
 *  captures a `provider()` thunk, never a specific settings object,
 *  and re-reads it on every call. No stale cache can survive.
 *
 *  STRICT READ-ONLY CONTRACT (Phase 4):
 *    - no save/set/update/patch/delete/markDirty/sync/push/pull
 *    - never mutates the source settings object or its arrays
 *    - reading never writes localStorage, never marks dirty,
 *      never schedules sync, never creates storage
 *
 *  Defaults mirror the CURRENT HSK product exactly (DATA_CONTRACTS.md
 *  section 3). A future FlashEdu product overrides them via `config`;
 *  nothing here is speculative — every key already exists at runtime.
 * ============================================================ */
(function (NS) {
  "use strict";

  // Current product defaults — byte-for-byte the fallbacks used by the
  // existing runtime expressions. Overridable per product via `config`.
  var DEFAULTS = {
    levels: ["HSK1"],                    // settings.selectedLevels fallback
    sessionSize: "20",                   // settings.sessionSize || "20"
    speechRates: [0.5, 0.75, 1, 1.25, 1.5], // allowed rates; others -> speechRate
    speechRate: 1,                       // normSpeechRate fallback
    autoReadWord: false,                 // !!settings.autoReadWord
    autoReadExample: false,              // !!settings.autoReadExample
    showFrontPinyin: true,               // settings.showFrontPinyin !== false
    dark: false,                         // !!settings.dark
    streak: 0                            // settings.streak || 0
  };

  function assign(base, over) {
    var out = {}, k;
    for (k in base) if (Object.prototype.hasOwnProperty.call(base, k)) out[k] = base[k];
    if (over) for (k in over) if (Object.prototype.hasOwnProperty.call(over, k)) out[k] = over[k];
    return out;
  }

  // provider: () => settingsObject (the CURRENT active blob).
  //   A falsy/non-object return (missing settings) is treated as {} —
  //   exactly the "missing settings object behaves as today" rule.
  // config:   optional overrides of DEFAULTS (product config).
  function createSettingsRepository(provider, config) {
    var cfg = assign(DEFAULTS, config);
    var read = (typeof provider === "function")
      ? provider
      : function () { return provider; };

    // Always the CURRENT source object; { } when absent. Never cached.
    function src() {
      var s = read();
      return (s && typeof s === "object") ? s : {};
    }

    return {
      // Live current settings object (same ref app already exposes via
      // getSettings()); read-only by contract — callers must not mutate.
      getAll: function () { return src(); },

      // Generic additive-field read. undefined/null -> fallback; explicit
      // false / 0 / "" are preserved (matches "current semantics").
      get: function (key, fallback) {
        var v = src()[key];
        return (v === undefined || v === null) ? fallback : v;
      },

      has: function (key) {
        return Object.prototype.hasOwnProperty.call(src(), key);
      },

      // ---- typed convenience (each reproduces the exact runtime rule) ----

      // matches app.js reloadState(): present & non-empty array -> use (copy);
      // else product default. Returns a COPY so the source array is never
      // exposed for mutation.
      getSelectedLevels: function () {
        var s = src();
        return (Array.isArray(s.selectedLevels) && s.selectedLevels.length)
          ? s.selectedLevels.slice()
          : cfg.levels.slice();
      },

      // matches: settings.sessionSize || "20"
      getSessionSize: function () {
        return src().sessionSize || cfg.sessionSize;
      },

      // matches normSpeechRate(): allowed numeric rate else default.
      getSpeechRate: function () {
        var v = Number(src().speechRate);
        return cfg.speechRates.indexOf(v) >= 0 ? v : cfg.speechRate;
      },

      // matches: settings.showFrontPinyin !== false  (undefined => true)
      getFrontPinyinEnabled: function () {
        return src().showFrontPinyin !== false;
      },

      // matches: !!settings.autoReadWord
      getAutoReadWordEnabled: function () { return !!src().autoReadWord; },

      // matches: !!settings.autoReadExample
      getAutoReadExampleEnabled: function () { return !!src().autoReadExample; },

      // matches: settings.streak || 0
      getStreak: function () { return src().streak || cfg.streak; },

      // matches: !!settings.dark
      getDarkEnabled: function () { return !!src().dark; }
    };
  }

  NS.createSettingsRepository = createSettingsRepository;
  // Shared instance for consumers OUTSIDE app.js (e.g. insights.js), which
  // load after app.js has defined HSK_APP. Reads the active account's live
  // settings through the app bridge; { } before the bridge exists.
  NS.settings = createSettingsRepository(function () {
    return (window.HSK_APP && window.HSK_APP.getSettings()) || {};
  });

})(window.HSKUtil = window.HSKUtil || {});
