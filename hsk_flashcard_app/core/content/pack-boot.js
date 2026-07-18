/*
 * planPackBoot — pure resolution of "which pack should this page load, and
 * which scripts does that mean".
 *
 * Phase 24E-A FOUNDATION ONLY. Not referenced by index.html, not loaded by any
 * production code path, not in the service-worker precache. Phase 24E-B owns
 * the storage adapter and the parser-time script insertion that consume this.
 *
 * The core is deliberately PURE: it takes a validated registry plus a requested
 * pack id and returns a plan. It never touches the DOM, localStorage, the
 * network, document.write, or any global. That separation is the point — the
 * risky part (inserting a script tag during parse) becomes a thin adapter over
 * a decision that is fully testable on its own.
 *
 * Two invariants it must never violate, because both corrupt learner data
 * rather than merely breaking a screen:
 *   - never return an empty pack (a boot with no cards must be an explicit
 *     error, not a silently empty app)
 *   - never return a mixed plan (exactly one pack's scripts, in a fixed order)
 */
(function (NS) {
  "use strict";

  var PLAN_VERSION = 1;

  // Why a particular pack was chosen. Stable machine-readable strings so the
  // adapter and the tests can branch on them without parsing prose.
  var REASON = {
    REQUESTED: "requested",
    FIRST_RUN: "default-first-run",
    UNKNOWN: "fallback-unknown-pack",
    MALFORMED: "fallback-malformed-request",
    HIDDEN: "fallback-not-launch-visible",
    INCOMPATIBLE: "fallback-incompatible-app-version"
  };

  var ERROR = {
    NO_REGISTRY: "NO_REGISTRY",
    NO_LAUNCH_VISIBLE_PACK: "NO_LAUNCH_VISIBLE_PACK"
  };

  // Mirrors the registry's identifier rule. A requested id that cannot be a
  // pack id is rejected before it is ever used as a lookup key.
  var IDENT_RE = /^[a-z0-9]([a-z0-9-]{0,30}[a-z0-9])?$/;

  function isStr(v) { return typeof v === "string" && v.length > 0; }

  function copyPlain(o) {
    if (o === null || typeof o !== "object") return o;
    var out = {}, k;
    for (k in o) {
      if (Object.prototype.hasOwnProperty.call(o, k)) {
        out[k] = (o[k] !== null && typeof o[k] === "object")
          ? copyPlain(o[k]) : o[k];
      }
    }
    return out;
  }

  function errorPlan(code, message, requestedPackId) {
    return {
      planVersion: PLAN_VERSION,
      ok: false,
      packId: null,
      reason: null,
      requestedPackId: isStr(requestedPackId) ? requestedPackId : null,
      scripts: [],
      error: { code: code, message: message }
    };
  }

  function okPlan(registry, packId, reason, requestedPackId, fallbackFrom) {
    var pack = registry.getPack(packId);
    var paths = registry.getAssetPaths(packId);
    return {
      planVersion: PLAN_VERSION,
      ok: true,
      packId: packId,
      reason: reason,
      requestedPackId: isStr(requestedPackId) ? requestedPackId : null,
      fallbackFrom: fallbackFrom || null,
      // Exactly one pack, deterministic order: manifest before cards. Both
      // generated files are `|| {}`-guarded so either order works at runtime,
      // but a fixed order keeps the plan byte-stable and diffable.
      scripts: [paths.manifestPath, paths.cardsPath],
      idRange: copyPlain(pack.idRange),
      allocated: copyPlain(pack.allocated),
      expected: {
        packId: packId,
        version: pack.version,
        sourceChecksum: pack.sourceChecksum,
        contentChecksum: pack.contentChecksum,
        manifestPath: paths.manifestPath,
        cardsPath: paths.cardsPath
      },
      error: null
    };
  }

  /*
   * options:
   *   registry          - a validated PackRegistry (required)
   *   requestedPackId   - the stored activePackId, or null/undefined on first run
   *   appVersion        - current app version string, for minAppVersion gating
   *
   * Returns a plan object. Never throws for ordinary input; a missing registry
   * is reported as an error plan rather than an exception so the adapter has
   * exactly one failure shape to render.
   */
  function planPackBoot(options) {
    var opts = options || {};
    var registry = opts.registry;
    var requested = opts.requestedPackId;
    var appVersion = opts.appVersion;

    if (!registry || typeof registry.getDefaultPackId !== "function") {
      return errorPlan(ERROR.NO_REGISTRY,
                       "a validated pack registry is required", requested);
    }

    var fallbackId = registry.getDefaultPackId(appVersion);
    var visible = registry.getLaunchVisiblePackIds(appVersion);

    function fallback(reason) {
      if (fallbackId === null) {
        return errorPlan(
          ERROR.NO_LAUNCH_VISIBLE_PACK,
          "no launch-visible, version-compatible pack is available",
          requested);
      }
      return okPlan(registry, fallbackId, reason, requested,
                    isStr(requested) ? requested : null);
    }

    // First run: nothing stored yet.
    if (requested === null || requested === undefined || requested === "") {
      if (fallbackId === null) {
        return errorPlan(
          ERROR.NO_LAUNCH_VISIBLE_PACK,
          "no launch-visible, version-compatible pack is available",
          null);
      }
      return okPlan(registry, fallbackId, REASON.FIRST_RUN, null, null);
    }

    // A stored value that could not possibly be a pack id (corrupted storage,
    // wrong type, injected string) never becomes a lookup key or a path.
    if (typeof requested !== "string" || !IDENT_RE.test(requested)) {
      return fallback(REASON.MALFORMED);
    }
    if (!registry.hasPack(requested)) {
      return fallback(REASON.UNKNOWN);
    }
    if (visible.indexOf(requested) < 0) {
      // Present in the catalog but either hidden or version-gated. Distinguish
      // the two so the adapter can say "update the app" rather than "gone".
      return fallback(registry.isCompatible(requested, appVersion)
        ? REASON.HIDDEN
        : REASON.INCOMPATIBLE);
    }

    return okPlan(registry, requested, REASON.REQUESTED, requested, null);
  }

  /*
   * Deterministic serialization, for golden tests and for logging a plan
   * without leaking object identity. Key order is fixed here rather than
   * relying on insertion order.
   */
  function serializePlan(plan) {
    if (!plan) return "";
    var ordered = {
      planVersion: plan.planVersion,
      ok: plan.ok,
      packId: plan.packId,
      reason: plan.reason,
      requestedPackId: plan.requestedPackId,
      fallbackFrom: plan.fallbackFrom || null,
      scripts: (plan.scripts || []).slice(),
      idRange: plan.idRange || null,
      allocated: plan.allocated || null,
      expected: plan.expected || null,
      error: plan.error || null
    };
    return JSON.stringify(ordered);
  }

  NS.planPackBoot = planPackBoot;
  NS.serializePackBootPlan = serializePlan;
  NS.packBootReasons = REASON;
  NS.packBootErrors = ERROR;
  NS.packBootPlanVersion = PLAN_VERSION;
})(window.HSKUtil = window.HSKUtil || {});
