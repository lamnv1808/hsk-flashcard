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
    wroteManifest: false,
    // Retained so switchPack() validates against the SAME validated registry
    // the boot decision used, rather than rebuilding one that could differ.
    registry: null
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
      state.registry = registry;
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

  /* ------------------------------------------------ explicit pack switch */

  /*
   * switchPack(targetPackId) — the FIRST AND ONLY writer of activePackId.
   *
   * Boot stays strictly read-only (see the no-write contract); persistence
   * happens only here, in response to an explicit user choice.
   *
   * Validation reuses planPackBoot against the retained registry rather than
   * re-implementing the identifier rule or the visibility/version gates. The
   * planner is built to FALL BACK, so its fallbacks must never be read as
   * success: a switch is valid only when the planner returns the exact pack
   * that was asked for, for the 'requested' reason. Anything else -- malformed,
   * unknown, hidden, version-gated -- is a failure, never a silent landing on
   * HSK.
   *
   * Ordering is deliberate and load-bearing:
   *   validate -> await sync readiness -> stop audio -> mutate -> save ->
   *   bounded flush -> reload
   * Readiness comes before any mutation because pullSettings() replaces the
   * settings blob wholesale and only accepts a server copy newer than SETTIME;
   * writing first would suppress the pull and let the next push overwrite the
   * account's bookmarks and notes. Readiness failure is therefore fail-closed:
   * nothing is stopped, written, pushed or reloaded.
   */
  var switching = null;
  var TIMED_OUT = {};

  function race(promise, ms) {
    return Promise.race([
      Promise.resolve(promise),
      new Promise(function (res) { setTimeout(function () { res(TIMED_OUT); }, ms); })
    ]);
  }

  // Planner reason -> stable failure code.
  var REASON_CODE = {
    "fallback-malformed-request": "MALFORMED_PACK_ID",
    "default-first-run": "MALFORMED_PACK_ID",
    "fallback-unknown-pack": "UNKNOWN_PACK",
    "fallback-not-launch-visible": "PACK_HIDDEN",
    "fallback-incompatible-app-version": "PACK_INCOMPATIBLE"
  };

  function failure(code, message, packId) {
    return { ok: false, code: code, message: message, packId: packId };
  }

  function switchPack(targetPackId) {
    // Guard is set before the first await, so a second call cannot interleave.
    if (switching) {
      if (switching.target === targetPackId) return switching.promise;
      return Promise.resolve(failure(
        "SWITCH_IN_PROGRESS", "a pack switch is already in progress", targetPackId));
    }

    var registry = state.registry;
    if (!registry) {
      return Promise.resolve(failure(
        "NO_CATALOG", "no validated catalog is available", targetPackId));
    }

    var candidate;
    try {
      candidate = NS.planPackBoot({
        registry: registry,
        requestedPackId: targetPackId,
        appVersion: registry.getAppVersion()
      });
    } catch (e) {
      return Promise.resolve(failure(
        "PLAN_FAILED", String((e && e.message) || e), targetPackId));
    }
    if (!candidate || candidate.ok !== true) {
      return Promise.resolve(failure(
        "PLAN_FAILED", "boot planning produced no usable plan", targetPackId));
    }
    if (candidate.reason !== "requested" || candidate.packId !== targetPackId) {
      return Promise.resolve(failure(
        REASON_CODE[candidate.reason] || "PLAN_FAILED",
        "target rejected: " + candidate.reason, targetPackId));
    }

    // Same EFFECTIVE pack: a complete no-op. A malformed stored value is
    // deliberately NOT repaired here -- repairing it would be a settings write
    // the user never asked for, which is exactly what the no-write contract
    // forbids.
    var current = state.plan ? state.plan.packId : null;
    if (targetPackId === current) {
      return Promise.resolve({
        ok: true, changed: false, packId: targetPackId, reason: "same-pack"
      });
    }

    var entry = { target: targetPackId, promise: null };
    switching = entry;
    entry.promise = (function () {
      var reloadIssued = false;
      return (async function () {
        try {
          // Yield once before doing anything. In local-only mode there is no
          // readiness/flush await, so without this the whole body -- including
          // the finally that clears the guard -- would run synchronously inside
          // the switchPack() call, and a caller firing twice in the same tick
          // would execute the switch twice.
          await Promise.resolve();

          // ---- initial-pull readiness (fail-closed) ---------------------
          var sync = window.HSKSync;
          if (sync) {
            if (typeof sync.whenReady !== "function") {
              return failure("SYNC_NOT_READY",
                             "sync is present but exposes no readiness contract",
                             targetPackId);
            }
            var settled;
            try {
              settled = await race(sync.whenReady(), 5000);
            } catch (e) {
              // A rejected readiness promise is NOT swallowed.
              return failure("SYNC_NOT_READY",
                             "readiness rejected: " + String((e && e.message) || e),
                             targetPackId);
            }
            if (settled === TIMED_OUT) {
              return failure("SYNC_NOT_READY",
                             "initial settings sync did not settle in time",
                             targetPackId);
            }
          }
          // HSKSync absent => genuine local-only mode; proceed.

          // ---- verify the write path BEFORE touching anything ------------
          var app = window.HSK_APP;
          if (!app || typeof app.getSettings !== "function" ||
              typeof window.saveSettings !== "function") {
            return failure("WRITE_FAILED", "settings write path unavailable",
                           targetPackId);
          }
          var live = app.getSettings();
          if (!live || typeof live !== "object") {
            return failure("WRITE_FAILED", "live settings object unavailable",
                           targetPackId);
          }

          // ---- transaction ----------------------------------------------
          var storageKey = settingsKey();
          var hadKey = Object.prototype.hasOwnProperty.call(live, "activePackId");
          var prevValue = live.activePackId;

          // Snapshot the exact previous raw blob BEFORE anything is touched.
          // A successful read returning null means "absent"; a THROW means we
          // cannot roll back, which is a different thing entirely. Swallowing
          // the throw and continuing with prevRaw = null would mean a later
          // save failure "restores" by deleting a blob we never actually read
          // -- destroying the user's settings. So a failed read fails closed,
          // before any speech stop, mutation, save, flush or reload.
          var prevRaw;
          try {
            prevRaw = localStorage.getItem(storageKey);
          } catch (e) {
            return failure("WRITE_FAILED",
                           "settings snapshot unreadable: " + String((e && e.message) || e),
                           targetPackId);
          }

          // Everything that can fail has now succeeded, so this is the last
          // point before user-visible effects begin.
          if (typeof window.stopSpeech === "function") window.stopSpeech();

          live.activePackId = targetPackId;   // only this key changes
          try {
            window.saveSettings();            // exactly once; owns SETTIME
          } catch (e) {
            // Restore the property EXACTLY, including its absence.
            if (hadKey) live.activePackId = prevValue;
            else delete live.activePackId;
            // Best-effort: undo any partial persisted blob.
            try {
              if (prevRaw === null) localStorage.removeItem(storageKey);
              else localStorage.setItem(storageKey, prevRaw);
            } catch (_) {}
            return failure("WRITE_FAILED", String((e && e.message) || e),
                           targetPackId);
          }

          // ---- bounded best-effort push, then reload regardless ----------
          // A dead network must not trap the user on the old pack; the local
          // write and SETTIME survive, so the existing start()/online -> flush
          // path retries the choice later.
          var pushed = false;
          if (sync && typeof sync.flush === "function") {
            try { pushed = (await race(sync.flush(), 3000)) === true; }
            catch (_) { pushed = false; }
          }

          // The activation boundary. Once reload has been REQUESTED the guard
          // must stay latched: the promise resolves before navigation actually
          // happens, so clearing it here would open a window in which a second
          // call could save, flush and reload again on a document that is
          // already on its way out. The new document resets module state
          // naturally, so nothing needs to unlatch it.
          location.reload();
          reloadIssued = true;
          return {
            ok: true, changed: true, packId: targetPackId,
            previousPackId: current, pushed: pushed, reloading: true
          };
        } finally {
          // Only an operation that did NOT request navigation releases the
          // guard; if reload() threw, reloadIssued stays false and the guard
          // clears normally.
          if (!reloadIssued) switching = null;
        }
      })();
    })();
    return entry.promise;
  }

  NS.packBootShim = {
    writeCards: writeCards,
    writeManifest: writeManifest,
    switchPack: switchPack,
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
