/*
 * PackRegistry — product-neutral validation of a generated pack catalog.
 *
 * Phase 24E-A FOUNDATION ONLY. This file is deliberately NOT referenced by
 * index.html, not loaded by any production code path, and not present in the
 * service-worker precache. Phase 24E-B owns integration.
 *
 * Responsibility: given a catalog object, either return a validated registry or
 * THROW. There is no silent fallback from a malformed catalog — a wrong-pack
 * fallback is worse than a visible failure, because card ids are the join key
 * for every learner's SRS progress and mixing them corrupts data silently.
 *
 * The one job nothing else in the codebase does: reject cross-pack integer
 * id-range overlap. ContentPack v1 validates a single pack's declared range
 * (core/content/content-pack.js) but has no way to see a second pack, and its
 * validate() has no production caller at all. Overlap rejection has been
 * deferred to "the Phase 24E registry" since Phase 24C; this is it.
 *
 * Deliberately absent: script loading, storage, DOM, network, Supabase, session
 * construction, progress, SRS, and every HSK/Chinese literal.
 */
(function (NS) {
  "use strict";

  var SCHEMA_VERSION = 1;

  // Mirrored from core/content/content-pack.js so a pack id means the same
  // thing in the catalog as it does in the pack manifest.
  var IDENT_RE = /^[a-z0-9]([a-z0-9-]{0,30}[a-z0-9])?$/;
  var BCP47_RE = /^[A-Za-z]{2,3}(-[A-Za-z]{4})?(-(?:[A-Za-z]{2}|[0-9]{3}))?$/;
  var SCRIPT_RE = /^[A-Z][a-z]{3}$/;
  var CHECKSUM_RE = /^sha256:[0-9a-f]{64}$/;
  var VERSION_RE = /^[0-9]+(\.[0-9]+)*$/;

  var STATUS_VALUES = ["draft", "beta", "launch"];
  var READINESS_VALUES = ["internal", "beta", "launch"];
  var COURSE_TYPES = ["exam", "general"];
  var DIRECTIONS = ["ltr", "rtl"];

  // PostgreSQL int4 ceiling. card_progress.card_id is int and sync casts ::int,
  // so the whole id space is bounded by this.
  var MAX_CARD_ID = 2147483647;

  function fail(field, msg) {
    throw new Error("PackRegistry: '" + field + "' " + msg);
  }

  function isStr(v) { return typeof v === "string" && v.length > 0; }
  function isArr(v) { return Object.prototype.toString.call(v) === "[object Array]"; }
  function isObj(v) { return v !== null && typeof v === "object" && !isArr(v); }
  function isBool(v) { return v === true || v === false; }
  function isInt(v) {
    return typeof v === "number" && isFinite(v) && Math.floor(v) === v;
  }
  function has(o, k) { return Object.prototype.hasOwnProperty.call(o, k); }
  function inList(v, list) { return list.indexOf(v) >= 0; }

  function copyArr(a) { return isArr(a) ? a.slice() : []; }

  /*
   * Deep copy. A shallow array slice is not enough: `levels` is an array OF
   * OBJECTS, so slicing it would still hand callers the live deck objects and a
   * caller mutating one would corrupt the registry's own metadata.
   */
  function copyValue(v) {
    if (isArr(v)) return v.map(copyValue);
    if (isObj(v)) return copyPlain(v);
    return v;
  }

  function copyPlain(o) {
    if (!isObj(o)) return undefined;
    var out = {}, k;
    for (k in o) {
      if (has(o, k)) out[k] = copyValue(o[k]);
    }
    return out;
  }

  /* ---------------------------------------------------------------- paths */

  /*
   * Catalog paths are app-root-relative and are the ONLY source of a script
   * path the future boot adapter will ever insert. Everything that is not a
   * plain relative path is rejected here, so no traversal, absolute path, URL,
   * drive path or UNC path can reach markup later.
   */
  function checkRelPath(value, field) {
    if (!isStr(value)) fail(field, "must be a non-empty relative path string");
    if (value.indexOf("://") >= 0) fail(field, "must not be a URL");
    if (value.charAt(0) === "/" || value.slice(0, 2) === "//") {
      fail(field, "must not be an absolute or protocol-relative path");
    }
    if (value.charAt(0) === "\\" || value.slice(0, 2) === "\\\\") {
      fail(field, "must not be a UNC or backslash-rooted path");
    }
    if (/^[A-Za-z]:/.test(value)) fail(field, "must not be a drive-absolute path");
    if (value.indexOf("\\") >= 0) fail(field, "must use forward slashes only");
    var parts = value.split("/");
    for (var i = 0; i < parts.length; i++) {
      if (parts[i] === ".." ) fail(field, "must not contain a '..' segment");
      if (parts[i] === "") fail(field, "must not contain an empty path segment");
    }
    return value;
  }

  /* ------------------------------------------------------------- versions */

  /*
   * Structural dotted-numeric comparison only. This is not semver: it does not
   * understand pre-release or build metadata, and it is not trying to. It exists
   * so a pack can declare "I need at least app 1.2.0" and be hidden otherwise.
   */
  function compareVersions(a, b) {
    var pa = String(a).split("."), pb = String(b).split(".");
    var n = Math.max(pa.length, pb.length);
    for (var i = 0; i < n; i++) {
      var x = parseInt(pa[i] || "0", 10) || 0;
      var y = parseInt(pb[i] || "0", 10) || 0;
      if (x !== y) return x < y ? -1 : 1;
    }
    return 0;
  }

  /* ----------------------------------------------------------- validation */

  function validatePack(p, index) {
    var where = "packs[" + index + "]";
    if (!isObj(p)) fail(where, "must be an object");

    if (!isStr(p.packId) || !IDENT_RE.test(p.packId)) {
      fail(where + ".packId", "must match " + IDENT_RE.source);
    }
    var at = "packs['" + p.packId + "']";

    if (!isStr(p.version)) fail(at + ".version", "must be a non-empty string");
    if (!isStr(p.title)) fail(at + ".title", "must be a non-empty string");
    if (has(p, "shortTitle") && !isStr(p.shortTitle)) {
      fail(at + ".shortTitle", "must be a non-empty string when present");
    }
    if (!isStr(p.courseId) || !IDENT_RE.test(p.courseId)) {
      fail(at + ".courseId", "must match " + IDENT_RE.source);
    }
    if (!inList(p.courseType, COURSE_TYPES)) {
      fail(at + ".courseType", "must be one of: " + COURSE_TYPES.join(", "));
    }
    if (!inList(p.status, STATUS_VALUES)) {
      fail(at + ".status", "must be one of: " + STATUS_VALUES.join(", "));
    }

    // language profile
    var lp = p.languageProfile;
    if (!isObj(lp)) fail(at + ".languageProfile", "is required and must be an object");
    if (!isStr(lp.target) || !BCP47_RE.test(lp.target)) {
      fail(at + ".languageProfile.target", "must be a BCP-47 tag");
    }
    ["translation", "instruction"].forEach(function (k) {
      if (has(lp, k) && (!isStr(lp[k]) || !BCP47_RE.test(lp[k]))) {
        fail(at + ".languageProfile." + k, "must be a BCP-47 tag when present");
      }
    });
    if (has(lp, "script") && (!isStr(lp.script) || !SCRIPT_RE.test(lp.script))) {
      fail(at + ".languageProfile.script", "must be an ISO-15924 code when present");
    }
    if (has(lp, "direction") && !inList(lp.direction, DIRECTIONS)) {
      fail(at + ".languageProfile.direction", "must be ltr or rtl when present");
    }

    // audio policy (optional)
    if (has(p, "audio")) {
      var au = p.audio;
      if (!isObj(au)) fail(at + ".audio", "must be an object when present");
      if (has(au, "locale") && (!isStr(au.locale) || !BCP47_RE.test(au.locale))) {
        fail(at + ".audio.locale", "must be a BCP-47 tag when present");
      }
      if (has(au, "fallbackLocales")) {
        if (!isArr(au.fallbackLocales)) fail(at + ".audio.fallbackLocales", "must be an array");
        for (var f = 0; f < au.fallbackLocales.length; f++) {
          if (!isStr(au.fallbackLocales[f]) || !BCP47_RE.test(au.fallbackLocales[f])) {
            fail(at + ".audio.fallbackLocales", "contains an invalid BCP-47 tag");
          }
        }
      }
      if (has(au, "readFields") && !isArr(au.readFields)) {
        fail(at + ".audio.readFields", "must be an array when present");
      }
    }

    // catalogue metadata
    if (has(p, "capabilities") && !isArr(p.capabilities)) {
      fail(at + ".capabilities", "must be an array when present");
    }
    if (has(p, "categories") && !isArr(p.categories)) {
      fail(at + ".categories", "must be an array when present");
    }
    if (has(p, "levels")) {
      if (!isArr(p.levels)) fail(at + ".levels", "must be an array when present");
      var seenDeck = {};
      for (var d = 0; d < p.levels.length; d++) {
        var lv = p.levels[d];
        if (!isObj(lv)) fail(at + ".levels[" + d + "]", "must be an object");
        if (!isStr(lv.deckId)) fail(at + ".levels[" + d + "].deckId", "must be a non-empty string");
        if (!isInt(lv.order)) fail(at + ".levels[" + d + "].order", "must be an integer");
        if (has(seenDeck, lv.deckId)) {
          fail(at + ".levels", "declares deck '" + lv.deckId + "' more than once");
        }
        seenDeck[lv.deckId] = true;
      }
    }

    // launch metadata
    var la = p.launch;
    if (!isObj(la)) fail(at + ".launch", "is required and must be an object");
    if (!isBool(la.visible)) fail(at + ".launch.visible", "must be a boolean");
    if (!inList(la.readiness, READINESS_VALUES)) {
      fail(at + ".launch.readiness", "must be one of: " + READINESS_VALUES.join(", "));
    }
    // An honest catalog never claims a pack is publicly visible while admitting
    // it is not launch-ready. The generator must hide it instead.
    if (la.visible === true && (la.readiness !== "launch" || p.status !== "launch")) {
      fail(at + ".launch.visible",
           "cannot be true unless status and launch.readiness are both 'launch'");
    }

    // declared id range
    var ir = p.idRange;
    if (!isObj(ir)) fail(at + ".idRange", "is required and must be an object");
    if (!isInt(ir.min)) fail(at + ".idRange.min", "must be an integer");
    if (!isInt(ir.max)) fail(at + ".idRange.max", "must be an integer");
    if (ir.min <= 0) fail(at + ".idRange.min", "must be greater than 0");
    if (ir.max < ir.min) fail(at + ".idRange.max", "must be >= idRange.min");
    if (ir.max > MAX_CARD_ID) {
      fail(at + ".idRange.max", "must stay within the database integer ceiling (" + MAX_CARD_ID + ")");
    }

    // allocated range
    var al = p.allocated;
    if (!isObj(al)) fail(at + ".allocated", "is required and must be an object");
    if (!isInt(al.count) || al.count < 0) fail(at + ".allocated.count", "must be a non-negative integer");
    if (al.count === 0) {
      if (al.min !== null || al.max !== null) {
        fail(at + ".allocated", "must report null min/max when count is 0");
      }
    } else {
      if (!isInt(al.min)) fail(at + ".allocated.min", "must be an integer when count > 0");
      if (!isInt(al.max)) fail(at + ".allocated.max", "must be an integer when count > 0");
      if (al.max < al.min) fail(at + ".allocated.max", "must be >= allocated.min");
      if (al.min < ir.min || al.max > ir.max) {
        fail(at + ".allocated", "must fall inside the declared idRange");
      }
      if (al.count > (al.max - al.min + 1)) {
        fail(at + ".allocated.count", "exceeds the allocated span");
      }
    }
    if (has(al, "gaps") && (!isInt(al.gaps) || al.gaps < 0)) {
      fail(at + ".allocated.gaps", "must be a non-negative integer when present");
    }

    // checksums — consistency evidence, NOT tamper protection (see docs)
    ["sourceChecksum", "contentChecksum"].forEach(function (k) {
      if (!isStr(p[k]) || !CHECKSUM_RE.test(p[k])) {
        fail(at + "." + k, "must be 'sha256:' followed by 64 lower-case hex digits");
      }
    });

    // runtime asset paths
    checkRelPath(p.manifestPath, at + ".manifestPath");
    checkRelPath(p.cardsPath, at + ".cardsPath");
    if (p.manifestPath === p.cardsPath) {
      fail(at + ".cardsPath", "must differ from manifestPath");
    }

    if (has(p, "minAppVersion")) {
      if (!isStr(p.minAppVersion) || !VERSION_RE.test(p.minAppVersion)) {
        fail(at + ".minAppVersion", "must be a dotted numeric version string when present");
      }
    }
  }

  function rejectOverlaps(packs, field, pick) {
    var spans = [];
    for (var i = 0; i < packs.length; i++) {
      var s = pick(packs[i]);
      if (s) spans.push({ packId: packs[i].packId, min: s.min, max: s.max });
    }
    // O(n log n): sort by start, then a single adjacent-pair scan. Disjointness
    // is the invariant that keeps one pack's progress rows out of another's.
    spans.sort(function (a, b) {
      return a.min - b.min || a.max - b.max || (a.packId < b.packId ? -1 : 1);
    });
    for (var j = 1; j < spans.length; j++) {
      if (spans[j].min <= spans[j - 1].max) {
        fail(field,
             "packs '" + spans[j - 1].packId + "' (" + spans[j - 1].min + "-" + spans[j - 1].max +
             ") and '" + spans[j].packId + "' (" + spans[j].min + "-" + spans[j].max +
             ") overlap; card ids must be globally disjoint");
      }
    }
  }

  /* ------------------------------------------------------------- factory */

  function createPackRegistry(catalog) {
    if (!isObj(catalog)) fail("catalog", "must be an object");
    if (catalog.schemaVersion !== SCHEMA_VERSION) {
      fail("schemaVersion", "must be exactly " + SCHEMA_VERSION +
           " (unsupported catalog versions fail closed)");
    }
    if (!isArr(catalog.packs)) fail("packs", "must be an array");
    if (catalog.packs.length === 0) fail("packs", "must declare at least one pack");

    var byId = {};
    var order = [];
    var i;

    for (i = 0; i < catalog.packs.length; i++) {
      validatePack(catalog.packs[i], i);
      var id = catalog.packs[i].packId;
      if (has(byId, id)) fail("packs", "declares pack id '" + id + "' more than once");
      byId[id] = copyPlain(catalog.packs[i]);
      order.push(id);
    }

    rejectOverlaps(catalog.packs, "idRange", function (p) {
      return { min: p.idRange.min, max: p.idRange.max };
    });
    rejectOverlaps(catalog.packs, "allocated", function (p) {
      return p.allocated.count > 0
        ? { min: p.allocated.min, max: p.allocated.max }
        : null;
    });

    if (has(catalog, "defaultPackId")) {
      if (!isStr(catalog.defaultPackId) || !has(byId, catalog.defaultPackId)) {
        fail("defaultPackId", "must name a pack declared in this catalog");
      }
      var dp = byId[catalog.defaultPackId];
      if (dp.launch.visible !== true) {
        fail("defaultPackId", "must name a launch-visible pack");
      }
    }

    if (has(catalog, "appVersion") && !isStr(catalog.appVersion)) {
      fail("appVersion", "must be a non-empty string when present");
    }

    function get(id) {
      return has(byId, id) ? copyPlain(byId[id]) : undefined;
    }

    function isCompatible(id, appVersion) {
      if (!has(byId, id)) return false;
      var min = byId[id].minAppVersion;
      if (!min) return true;
      if (!isStr(appVersion)) return false;
      return compareVersions(appVersion, min) >= 0;
    }

    /*
     * Launch visibility is the product gate: a pack the owner has not certified
     * must never be offered. Filtering here (rather than at a call site) is what
     * keeps "no fake or coming-soon options" a structural property.
     */
    function launchVisibleIds(appVersion) {
      var out = [];
      for (var k = 0; k < order.length; k++) {
        var p = byId[order[k]];
        if (p.launch.visible !== true) continue;
        if (!isCompatible(p.packId, appVersion)) continue;
        out.push(p.packId);
      }
      return out;
    }

    /*
     * Deterministic and product-neutral: an explicit catalog default wins;
     * otherwise the launch-visible pack with the lowest declared range start.
     * Ranges are disjoint, so that is a total order with no tie-break needed
     * and no hard-coded pack name.
     */
    function defaultPackId(appVersion) {
      var visible = launchVisibleIds(appVersion);
      if (visible.length === 0) return null;
      if (has(catalog, "defaultPackId") && visible.indexOf(catalog.defaultPackId) >= 0) {
        return catalog.defaultPackId;
      }
      var best = null;
      for (var k = 0; k < visible.length; k++) {
        var p = byId[visible[k]];
        if (best === null || p.idRange.min < byId[best].idRange.min) best = p.packId;
      }
      return best;
    }

    return {
      getSchemaVersion: function () { return SCHEMA_VERSION; },
      getAppVersion: function () { return catalog.appVersion; },
      getPackIds: function () { return order.slice(); },
      hasPack: function (id) { return has(byId, id); },
      getPack: get,
      getAllPacks: function () {
        return order.map(function (id) { return copyPlain(byId[id]); });
      },
      getLaunchVisiblePackIds: launchVisibleIds,
      getLaunchVisiblePacks: function (appVersion) {
        return launchVisibleIds(appVersion).map(function (id) { return copyPlain(byId[id]); });
      },
      getDefaultPackId: defaultPackId,
      getIdRange: function (id) {
        return has(byId, id) ? copyPlain(byId[id].idRange) : undefined;
      },
      getAllocated: function (id) {
        return has(byId, id) ? copyPlain(byId[id].allocated) : undefined;
      },
      getAssetPaths: function (id) {
        if (!has(byId, id)) return undefined;
        return { manifestPath: byId[id].manifestPath, cardsPath: byId[id].cardsPath };
      },
      isCompatible: isCompatible,
      isLaunchVisible: function (id, appVersion) {
        return launchVisibleIds(appVersion).indexOf(id) >= 0;
      },
      // Exposed for the boot planner and for tests; pure, no state.
      compareVersions: compareVersions
    };
  }

  NS.createPackRegistry = createPackRegistry;
  NS.packRegistrySchemaVersion = SCHEMA_VERSION;
})(window.HSKUtil = window.HSKUtil || {});
