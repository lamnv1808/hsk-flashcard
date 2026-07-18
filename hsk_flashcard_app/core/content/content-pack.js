/* ============================================================
 *  core/content/content-pack.js  (FlashEdu — Phase 10)
 *  Generic, read-only ContentPack contract. A content pack is a
 *  versioned bundle of learning content plus the semantic metadata
 *  the engine needs to present and test it. This GENERIC core hardcodes
 *  NOTHING product-specific — no HSK/Chinese/pinyin/Vietnamese, no fixed
 *  deck set, no fixed card count. Those facts live in the pack adapter
 *  (packs/<id>/…) and tests.
 *
 *  READ-ONLY: a pack never mutates its source cards/arrays, never writes
 *  storage/network, never touches progress/settings/DOM. It is a
 *  descriptive read seam over an existing card source; it does NOT clone
 *  the cards (getCards() returns the live source array).
 *
 *  Contract derived from the current HSK product's actual needs
 *  (see docs/architecture/CONTENT_PACK_STANDARD.md).
 * ============================================================ */
(function (NS) {
  "use strict";

  function isObj(x) { return x && typeof x === "object"; }
  function isArr(x) { return Array.isArray(x); }
  function isStr(x) { return typeof x === "string" && x.length > 0; }
  function has(o, k) { return Object.prototype.hasOwnProperty.call(o, k); }

  /* ---------------- Content Pack v1 (Phase 24C) ----------------
   * A pack WITHOUT `schemaVersion` keeps the exact legacy behavior below (no new
   * validation, no new required fields) so existing callers/tests never regress.
   * A pack WITH `schemaVersion` enters STRICT v1 mode: the manifest is structurally
   * validated at construction and a malformed manifest THROWS (fail-closed) — it is
   * never silently downgraded to legacy defaults.
   *
   * v1 REQUIRED: schemaVersion(=1), packId, version, status, title, courseId,
   *              courseType, languageProfile.target, fieldRoles, idRange.min/max
   * v1 OPTIONAL: shortTitle, description, publisher, source{origin,license,url,
   *              acquiredAt}, sourceChecksum, contentChecksum, generatedAt,
   *              minAppVersion, languageProfile{translation,instruction,script,
   *              direction}, audio{locale,fallbackLocales,readFields},
   *              framework{name,version}, levels, categories, launch{visible,
   *              readiness}, search{fields,normalizer}, presentation{frontRoles,
   *              backRoles}, optionalRoles, capabilities, cardCount
   *
   * NOTE ON `languageProfile`: the legacy `languages` map (semantic role -> code) is
   * preserved verbatim and still returned by getLanguages(). v1 language metadata
   * (target/translation/instruction/script/direction) lives in the separate additive
   * `languageProfile` object so no existing return value changes.
   *
   * INTEGER ID INVARIANT: card identity is one global integer namespace (Supabase
   * card_progress.card_id is `int`). Packs declare a reserved, non-overlapping
   * idRange; cross-pack overlap rejection is the Phase 24E registry's job.
   */
  var SCHEMA_VERSION = 1;
  var STATUS_ALLOW = ["draft", "beta", "launch"];
  var READINESS_ALLOW = ["internal", "beta", "launch"];
  var COURSE_TYPE_ALLOW = ["exam", "general"];
  var DIRECTION_ALLOW = ["ltr", "rtl"];
  // Card ids must stay inside the database integer ceiling (PostgreSQL int4).
  var MAX_CARD_ID = 2147483647;
  // Semantic roles the engine understands. Unknown role declarations fail closed.
  var KNOWN_ROLES = [
    "stableId", "deck", "primaryPrompt", "pronunciation", "definition",
    "exampleText", "examplePronunciation", "exampleTranslation",
    "tags", "searchFields", "audioTextFields", "sourceRowRef"
  ];
  var REQUIRED_ROLES = ["stableId", "deck", "primaryPrompt"];
  // Conservative BCP-47 structural check: lang[-Script][-REGION]. Intentionally NOT a
  // full locale registry — it rejects obvious malformations only.
  var BCP47_RE = /^[A-Za-z]{2,3}(-[A-Za-z]{4})?(-(?:[A-Za-z]{2}|[0-9]{3}))?$/;
  var IDENT_RE = /^[a-z0-9]([a-z0-9-]{0,30}[a-z0-9])?$/;

  function fail(field, msg) {
    throw new Error("ContentPack v1: '" + field + "' " + msg);
  }
  function copyPlain(o) {   // shallow copy of a small plain object (never cards)
    var out = {}, k;
    for (k in o) if (has(o, k)) out[k] = isArr(o[k]) ? o[k].slice() : o[k];
    return out;
  }
  function reqStrIdent(spec, field) {
    var v = spec[field];
    if (!isStr(v)) fail(field, "is required and must be a non-empty string");
    if (!IDENT_RE.test(v)) fail(field, "must be a normalized lower-case identifier");
    return v;
  }
  function checkLocale(field, v) {
    if (!isStr(v) || !BCP47_RE.test(v)) fail(field, "must be a structurally valid BCP-47 language tag");
  }
  function checkStrArray(field, v) {
    if (!isArr(v)) fail(field, "must be an array");
    for (var i = 0; i < v.length; i++) if (!isStr(v[i])) fail(field, "must contain non-empty strings only");
  }

  // Structural manifest validation. Throws on the first problem, naming the field.
  // Does NOT read cards (construction stays O(1) w.r.t. card count) and never mutates input.
  function validateV1Manifest(spec) {
    if (spec.schemaVersion !== SCHEMA_VERSION) {
      fail("schemaVersion", "must be exactly " + SCHEMA_VERSION + " (unsupported version fails closed)");
    }
    var packId = reqStrIdent(spec, "packId");
    if (has(spec, "id") && spec.id !== packId) fail("packId", "must match the legacy 'id' when both are present");
    reqStrIdent(spec, "courseId");
    if (!isStr(spec.version)) fail("version", "is required and must be a non-empty string");
    if (!isStr(spec.title)) fail("title", "is required and must be a non-empty string");
    if (STATUS_ALLOW.indexOf(spec.status) < 0) fail("status", "must be one of: " + STATUS_ALLOW.join(", "));
    if (COURSE_TYPE_ALLOW.indexOf(spec.courseType) < 0) fail("courseType", "must be one of: " + COURSE_TYPE_ALLOW.join(", "));

    // ---- language profile ----
    var lp = spec.languageProfile;
    if (!isObj(lp) || isArr(lp)) fail("languageProfile", "is required and must be an object");
    checkLocale("languageProfile.target", lp.target);
    if (has(lp, "translation")) checkLocale("languageProfile.translation", lp.translation);
    if (has(lp, "instruction")) checkLocale("languageProfile.instruction", lp.instruction);
    if (has(lp, "script") && !/^[A-Z][a-z]{3}$/.test(lp.script)) fail("languageProfile.script", "must be an ISO 15924 script code");
    if (has(lp, "direction") && DIRECTION_ALLOW.indexOf(lp.direction) < 0) fail("languageProfile.direction", "must be 'ltr' or 'rtl'");

    // ---- audio policy ----
    if (has(spec, "audio")) {
      var au = spec.audio;
      if (!isObj(au) || isArr(au)) fail("audio", "must be an object");
      if (has(au, "locale")) checkLocale("audio.locale", au.locale);
      if (has(au, "fallbackLocales")) {
        if (!isArr(au.fallbackLocales)) fail("audio.fallbackLocales", "must be an array");
        for (var a = 0; a < au.fallbackLocales.length; a++) checkLocale("audio.fallbackLocales[]", au.fallbackLocales[a]);
      }
      if (has(au, "readFields")) {
        checkStrArray("audio.readFields", au.readFields);
        for (var r = 0; r < au.readFields.length; r++) {
          if (KNOWN_ROLES.indexOf(au.readFields[r]) < 0) fail("audio.readFields", "references unknown role '" + au.readFields[r] + "'");
        }
      }
    }

    // ---- id range (reserved integer block) ----
    var ir = spec.idRange;
    if (!isObj(ir) || isArr(ir)) fail("idRange", "is required and must be an object");
    if (!Number.isSafeInteger(ir.min)) fail("idRange.min", "must be a safe integer");
    if (!Number.isSafeInteger(ir.max)) fail("idRange.max", "must be a safe integer");
    if (ir.min <= 0) fail("idRange.min", "must be greater than 0");
    if (ir.max < ir.min) fail("idRange.max", "must be >= idRange.min");
    if (ir.max > MAX_CARD_ID) fail("idRange.max", "must stay within the database integer ceiling (" + MAX_CARD_ID + ")");

    // ---- field roles ----
    var fr = spec.fieldRoles;
    if (!isObj(fr) || isArr(fr)) fail("fieldRoles", "is required and must be an object");
    var optional = has(spec, "optionalRoles") ? spec.optionalRoles : [];
    if (!isArr(optional)) fail("optionalRoles", "must be an array");
    for (var o = 0; o < optional.length; o++) {
      if (KNOWN_ROLES.indexOf(optional[o]) < 0) fail("optionalRoles", "declares unknown role '" + optional[o] + "'");
    }
    var k;
    for (k in fr) {
      if (!has(fr, k)) continue;
      if (KNOWN_ROLES.indexOf(k) < 0) fail("fieldRoles", "declares unknown role '" + k + "'");
      if (!isStr(fr[k])) fail("fieldRoles." + k, "must map to a non-empty card field name");
    }
    for (var q = 0; q < REQUIRED_ROLES.length; q++) {
      var rr = REQUIRED_ROLES[q];
      if (!isStr(fr[rr]) && optional.indexOf(rr) < 0) fail("fieldRoles." + rr, "is a required role and is not declared optional");
    }

    // ---- optional descriptive metadata ----
    if (has(spec, "launch")) {
      var la = spec.launch;
      if (!isObj(la) || isArr(la)) fail("launch", "must be an object");
      if (has(la, "visible") && typeof la.visible !== "boolean") fail("launch.visible", "must be a boolean");
      if (has(la, "readiness") && READINESS_ALLOW.indexOf(la.readiness) < 0) fail("launch.readiness", "must be one of: " + READINESS_ALLOW.join(", "));
    }
    if (has(spec, "presentation")) {
      var pr = spec.presentation;
      if (!isObj(pr) || isArr(pr)) fail("presentation", "must be an object");
      ["frontRoles", "backRoles"].forEach(function (key) {
        if (!has(pr, key)) return;
        checkStrArray("presentation." + key, pr[key]);
        pr[key].forEach(function (role) {
          if (KNOWN_ROLES.indexOf(role) < 0) fail("presentation." + key, "references unknown role '" + role + "'");
        });
      });
    }
    if (has(spec, "search")) {
      var se = spec.search;
      if (!isObj(se) || isArr(se)) fail("search", "must be an object");
      if (has(se, "fields")) {
        checkStrArray("search.fields", se.fields);
        se.fields.forEach(function (role) {
          if (KNOWN_ROLES.indexOf(role) < 0) fail("search.fields", "references unknown role '" + role + "'");
        });
      }
      if (has(se, "normalizer") && !isStr(se.normalizer)) fail("search.normalizer", "must be a non-empty string");
    }
    if (has(spec, "source")) {
      if (!isObj(spec.source) || isArr(spec.source)) fail("source", "must be an object");
    }
    if (has(spec, "framework")) {
      if (!isObj(spec.framework) || isArr(spec.framework)) fail("framework", "must be an object");
    }
    if (has(spec, "levels") && !isArr(spec.levels)) fail("levels", "must be an array");
    if (has(spec, "categories")) checkStrArray("categories", spec.categories);
    if (has(spec, "cardCount") && !Number.isSafeInteger(spec.cardCount)) fail("cardCount", "must be a safe integer");
    ["shortTitle", "description", "publisher", "sourceChecksum", "contentChecksum", "generatedAt", "minAppVersion"].forEach(function (f) {
      if (has(spec, f) && !isStr(spec[f])) fail(f, "must be a non-empty string when present");
    });
  }

  // spec:
  //   id            (string, required)   - stable pack slug
  //   version       (string)             - semver
  //   title         (string)             - display name
  //   languages     ({role: code})       - e.g. { prompt, reading, meaning, audio }
  //   capabilities  (string[])           - declared engine capabilities
  //   fieldRoles    ({role: fieldName})  - semantic role -> legacy card field
  //   testModes     (any[])              - MCQ type definitions valid for this pack
  //   getCards      (() => card[])       - live source card array (NOT cloned)
  //   decks         (deck[])  OR
  //   deckProvider  ((cards) => deck[])  - derive decks from the cards (preferred)
  function createContentPack(spec) {
    spec = spec || {};
    // Mode select (Phase 24C). No schemaVersion => legacy behavior, byte-identical to
    // before. schemaVersion present => STRICT v1; a malformed manifest throws here and
    // can never be downgraded into legacy defaults.
    var isV1 = has(spec, "schemaVersion");
    if (isV1) validateV1Manifest(spec);
    var id = isV1 ? spec.packId : spec.id;
    var getCardsFn = (typeof spec.getCards === "function") ? spec.getCards : function () { return spec.getCards || []; };
    var fieldRoles = isObj(spec.fieldRoles) ? spec.fieldRoles : {};
    var languages = isObj(spec.languages) ? spec.languages : {};
    var capabilities = Array.isArray(spec.capabilities) ? spec.capabilities.slice() : [];
    var testModes = Array.isArray(spec.testModes) ? spec.testModes : [];

    // Decks: either provided explicitly or derived from the cards (built ONCE here).
    var decks;
    if (typeof spec.deckProvider === "function") decks = spec.deckProvider(getCardsFn()) || [];
    else decks = Array.isArray(spec.decks) ? spec.decks.slice() : [];

    function copyDeck(d) { return { id: d.id, order: d.order, title: d.title, cardCount: d.cardCount }; }

    var pack = {
      getId: function () { return id; },
      getVersion: function () { return spec.version; },
      getTitle: function () { return spec.title; },
      getLanguages: function () { var o = {}, k; for (k in languages) if (languages.hasOwnProperty(k)) o[k] = languages[k]; return o; },
      getCapabilities: function () { return capabilities.slice(); },
      hasCapability: function (c) { return capabilities.indexOf(c) >= 0; },

      // Live source card array (read-only by contract; NOT cloned).
      getCards: function () { return getCardsFn(); },

      // Ordered deck metadata (copies, so callers can't mutate the internal list).
      getDecks: function () { return decks.map(copyDeck); },
      getDeckIds: function () { return decks.map(function (d) { return d.id; }); },

      // Semantic role -> legacy field name (e.g. "primaryPrompt" -> "word").
      getFieldRoles: function () { var o = {}, k; for (k in fieldRoles) if (fieldRoles.hasOwnProperty(k)) o[k] = fieldRoles[k]; return o; },
      getRole: function (role) { return fieldRoles[role]; },

      // Test Mode type definitions valid for this pack (descriptive in Phase 10).
      getTestModes: function () { return testModes.map(function (t) { return isObj(t) ? { id: t.id, label: t.label, q: t.q, a: t.a.slice() } : t; }); },

      // ---- Content Pack v1 read accessors (Phase 24C) ----
      // All return defensive copies (or undefined in legacy mode); none touch cards.
      getSchemaVersion: function () { return isV1 ? spec.schemaVersion : undefined; },
      getPackId: function () { return isV1 ? spec.packId : spec.id; },
      getStatus: function () { return isV1 ? spec.status : undefined; },
      getCourse: function () {
        if (!isV1) return undefined;
        var c = { courseId: spec.courseId, courseType: spec.courseType };
        if (has(spec, "framework")) c.framework = copyPlain(spec.framework);
        return c;
      },
      getLanguageProfile: function () { return isV1 ? copyPlain(spec.languageProfile) : undefined; },
      getAudio: function () { return (isV1 && has(spec, "audio")) ? copyPlain(spec.audio) : undefined; },
      getIdRange: function () { return isV1 ? { min: spec.idRange.min, max: spec.idRange.max } : undefined; },
      getLaunch: function () { return (isV1 && has(spec, "launch")) ? copyPlain(spec.launch) : undefined; },
      getSource: function () { return (isV1 && has(spec, "source")) ? copyPlain(spec.source) : undefined; },
      getPresentation: function () { return (isV1 && has(spec, "presentation")) ? copyPlain(spec.presentation) : undefined; },
      getSearch: function () { return (isV1 && has(spec, "search")) ? copyPlain(spec.search) : undefined; },
      getOptionalRoles: function () { return (isV1 && has(spec, "optionalRoles")) ? spec.optionalRoles.slice() : []; },
      // Scalar descriptive metadata only (no cards, no nested source objects).
      getManifest: function () {
        if (!isV1) return undefined;
        var out = {}, keys = ["schemaVersion", "packId", "version", "status", "title", "shortTitle",
          "description", "publisher", "courseId", "courseType", "sourceChecksum", "contentChecksum",
          "generatedAt", "minAppVersion", "cardCount"];
        for (var i = 0; i < keys.length; i++) if (has(spec, keys[i])) out[keys[i]] = spec[keys[i]];
        return out;
      },

      // Lightweight dev/test validation. NOT run on hot production paths.
      validate: function () {
        var errors = [], warnings = [];
        var cards = getCardsFn();
        if (!id || typeof id !== "string") errors.push("missing pack id");
        // unique stable ids
        var stable = fieldRoles.stableId || "id";
        var seen = {}, dupIds = 0;
        for (var i = 0; i < cards.length; i++) { var k = cards[i][stable]; if (seen[k]) dupIds++; else seen[k] = 1; }
        if (dupIds) errors.push(dupIds + " duplicate stable ids");
        // deck ids unique + referenced by cards
        var deckIds = {}, dupDecks = 0;
        decks.forEach(function (d) { if (deckIds[d.id]) dupDecks++; else deckIds[d.id] = 1; });
        if (dupDecks) errors.push(dupDecks + " duplicate deck ids");
        var deckField = fieldRoles.deck;
        var badRef = 0, byDeck = {};
        if (deckField) {
          for (var j = 0; j < cards.length; j++) {
            var dv = cards[j][deckField];
            byDeck[dv] = (byDeck[dv] || 0) + 1;
            if (!deckIds[dv]) badRef++;
          }
          if (badRef) errors.push(badRef + " cards reference an undeclared deck");
        }
        // required roles present as field names
        ["primaryPrompt", "stableId", "deck"].forEach(function (r) {
          if (!fieldRoles[r]) warnings.push("missing required role: " + r);
        });
        var out = {
          packId: id, version: spec.version, ok: errors.length === 0,
          cards: cards.length, decks: decks.length, byDeck: byDeck,
          idsUnique: dupIds === 0, deckRefsValid: badRef === 0,
          errors: errors, warnings: warnings
        };
        // ---- v1 CONTENT checks (Phase 24C): integer ids inside the reserved range.
        // Read-only: never allocates, sorts, reorders or mutates cards.
        if (isV1) {
          var lo = spec.idRange.min, hi = spec.idRange.max;
          var nonInt = 0, outOfRange = 0, roleMiss = [];
          for (var n = 0; n < cards.length; n++) {
            var cid = cards[n][stable];
            if (!Number.isSafeInteger(cid)) { nonInt++; continue; }
            if (cid < lo || cid > hi) outOfRange++;
          }
          if (nonInt) errors.push(nonInt + " card ids are not safe integers");
          if (outOfRange) errors.push(outOfRange + " card ids fall outside the declared idRange " + lo + ".." + hi);
          // Declared roles must resolve to a real field on the first card, unless optional.
          var optionalRoles = has(spec, "optionalRoles") ? spec.optionalRoles : [];
          if (cards.length) {
            for (var rk in fieldRoles) {
              if (!has(fieldRoles, rk)) continue;
              if (optionalRoles.indexOf(rk) >= 0) continue;
              if (!has(cards[0], fieldRoles[rk])) roleMiss.push(rk + " -> " + fieldRoles[rk]);
            }
          }
          if (roleMiss.length) errors.push("field roles do not resolve to card fields: " + roleMiss.join(", "));
          out.schemaVersion = spec.schemaVersion;
          out.idRange = { min: lo, max: hi };
          out.idsInRange = outOfRange === 0 && nonInt === 0;
          out.rolesResolve = roleMiss.length === 0;
          out.ok = errors.length === 0;
        }
        return out;
      }
    };
    return pack;
  }

  NS.createContentPack = createContentPack;
})(window.HSKUtil = window.HSKUtil || {});
