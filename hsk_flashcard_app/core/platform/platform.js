/* ============================================================
 *  core/platform/platform.js  (FlashEdu — Phase 24A)
 *  Tiny platform adapter: the single seam between the web runtime and a FUTURE
 *  locally-bundled Capacitor shell. No dependency on Capacitor, no import; it
 *  only capability-detects `window.Capacitor` if it happens to exist at runtime.
 *
 *  Web/PWA behavior is preserved exactly:
 *    - registerServiceWorker() registers `sw.js` on web (as app.js did before);
 *    - onBackground() uses the standard `visibilitychange` event.
 *  On a native shell, registerServiceWorker() is a safe no-op (assets are
 *  bundled locally, and WKWebView SW support is unreliable). The onBackground
 *  seam stays compatible with a future Capacitor App `appStateChange` hook.
 *
 *  Contains NO learning-domain logic, storage, network, or Back/TTS/secure-
 *  storage/share adapters (deferred to later native-integration phases).
 * ============================================================ */
(function (NS) {
  "use strict";

  // True only when running inside a Capacitor native shell. Safe on plain web:
  // window.Capacitor is undefined -> false; any access error -> false.
  function isNative() {
    try {
      return !!(window.Capacitor
        && typeof window.Capacitor.isNativePlatform === "function"
        && window.Capacitor.isNativePlatform());
    } catch (_) { return false; }
  }

  // "web" | "ios" | "android". Web is the safe default; only a native Capacitor
  // shell reporting ios/android overrides it.
  function platform() {
    try {
      if (isNative() && window.Capacitor && typeof window.Capacitor.getPlatform === "function") {
        var p = window.Capacitor.getPlatform();
        if (p === "ios" || p === "android") return p;
      }
    } catch (_) {}
    return "web";
  }

  // Web/PWA: register the service worker exactly as before (relative path, errors
  // swallowed). Native: return without registering. Never throws.
  function registerServiceWorker(path) {
    if (isNative()) return;
    try {
      if (typeof navigator !== "undefined" && "serviceWorker" in navigator) {
        navigator.serviceWorker.register(path).catch(function () {});
      }
    } catch (_) {}
  }

  // Invoke `callback` when the app becomes hidden/backgrounded (web: the document
  // transitions to visibilityState "hidden"). It does NOT fire on return-to-visible.
  // Returns an unsubscribe function. Compatible with a future Capacitor App
  // appStateChange({isActive:false}) bridge that would call the same callback.
  function onBackground(callback) {
    if (typeof document === "undefined" || typeof callback !== "function") return function () {};
    var handler = function () {
      if (document.visibilityState === "hidden") { try { callback(); } catch (_) {} }
    };
    document.addEventListener("visibilitychange", handler);
    return function () { document.removeEventListener("visibilitychange", handler); };
  }

  NS.platform = {
    isNative: isNative,
    platform: platform,
    registerServiceWorker: registerServiceWorker,
    onBackground: onBackground
  };
})(window.HSKUtil = window.HSKUtil || {});
