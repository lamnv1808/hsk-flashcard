#!/usr/bin/env python3
"""Phase 24E-B increment 3: parser-time pack boot wiring.

Proves the shipped app now boots HSK THROUGH the catalog/registry/planner
without changing what the user gets. The dangerous properties are the ordering
ones: the manifest adapter must never run before its cards payload, and the
eager load-time singletons (CardRepository, analytics, userMetadata, testMode)
must never observe an empty or half-filled dataset.

Local-only by construction: supabase-config.js is intercepted and served with
empty credentials, so auth.js takes its no-op branch and no request can reach
production Supabase. No real user data is used.
"""

import json
import os
import sys

from playwright.sync_api import sync_playwright

BASE = os.environ.get("HSK_BASE_URL", "http://localhost:8000") + "/hsk_flashcard_app/"
EMPTY_CONFIG = 'window.SUPABASE_CONFIG = { url: "", anonKey: "" };'

fails = []


def check(name, cond):
    if not cond:
        fails.append(name)


def new_page(ctx):
    """A page that is local-only and records console errors / page errors."""
    page = ctx.new_page()
    page.route("**/supabase-config.js", lambda route: route.fulfill(
        status=200, content_type="application/javascript", body=EMPTY_CONFIG))
    errors = []
    page.on("console", lambda m: errors.append("console:" + m.text)
            if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append("pageerror:" + str(e)))
    return page, errors


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
APP = os.path.join(ROOT, "hsk_flashcard_app")
HEX64 = "0" * 64


def read_real_catalog():
    """Parse the SHIPPED catalog as data. Never executed, never modified."""
    with open(os.path.join(APP, "packs", "catalog.js"), encoding="utf-8") as fh:
        src = fh.read()
    body = src[src.index("{", src.index("window.FLASHEDU_CATALOG")):].rstrip()
    return json.loads(body[:body.rindex("}") + 1])


def synth_pack(pack_id, id_min, visible, readiness, status, min_app_version=None):
    """A synthetic catalog entry. TEST-ONLY -- never written to any app file."""
    pack = {
        "packId": pack_id, "version": "1.0.0", "title": pack_id.upper(),
        "courseId": pack_id, "courseType": "general", "status": status,
        "languageProfile": {"target": "en"},
        "idRange": {"min": id_min, "max": id_min + 999999},
        "allocated": {"count": 0, "min": None, "max": None},
        "launch": {"visible": visible, "readiness": readiness},
        "sourceChecksum": "sha256:" + HEX64,
        "contentChecksum": "sha256:" + HEX64,
        "manifestPath": "packs/%s/%s-content-pack.js" % (pack_id, pack_id),
        "cardsPath": "packs/%s/%s-cards.js" % (pack_id, pack_id),
    }
    if min_app_version:
        pack["minAppVersion"] = min_app_version
    return pack


def catalog_page(ctx, extra_packs, app_version=None, stored=None, payloads=None):
    """Boot with a synthetic catalog served in place of the shipped one.

    The real packs/catalog.js on disk is untouched; only this page's request for
    it is fulfilled with the variant. `payloads` maps a synthetic pack's own
    runtime paths to test-only JavaScript, so a page that legitimately selects
    that pack executes THAT pack's cards and manifest.

    Everything else is production: index.html, pack-registry.js, pack-boot.js,
    pack-boot-shim.js, its document.write insertion points, content-pack.js and
    card-repository.js all run unmodified. Nothing here is mocked.
    """
    cat = read_real_catalog()
    cat["packs"] = list(cat["packs"]) + list(extra_packs)
    if app_version:
        cat["appVersion"] = app_version
    body = ("// test-only synthetic catalog\nwindow.FLASHEDU_CATALOG = %s;\n"
            % json.dumps(cat))

    page, errors = new_page(ctx)
    page.route("**/packs/catalog.js", lambda route: route.fulfill(
        status=200, content_type="application/javascript", body=body))

    for rel, js in (payloads or {}).items():
        page.route("**/" + rel,
                   (lambda text: lambda route: route.fulfill(
                       status=200, content_type="application/javascript",
                       body=text))(js))

    if stored is not None:
        page.add_init_script(
            "try{localStorage.setItem('hsk_flashcard_settings_v2',%s);}catch(e){}"
            % json.dumps(json.dumps({"activePackId": stored})))
    page.goto(BASE, wait_until="load")
    return page, errors


# --------------------------------------------------------------------------
# A COHERENT test-only pack. Catalog entry, cards payload and manifest all
# agree on packId, courseId, paths, idRange, allocated range and actual card
# ids. An earlier version of this suite aliased these paths onto the real HSK
# files, which meant the planner selected 'compatpack' while the executed
# manifest constructed 'hsk' with ids 1-5002 -- so the "one complete,
# non-mixed pack" claim was false even though the test was green. This fixture
# exists so that claim is actually true.
# --------------------------------------------------------------------------
COMPAT_ID = "compatpack"
COMPAT_RANGE = {"min": 7000000, "max": 7999999}
COMPAT_CARDS = [
    {"id": 7000000 + i, "level": "CP1" if i < 3 else "CP2",
     "word": "word%d" % i, "pinyin": "pron%d" % i, "meaning": "meaning%d" % i,
     "example": "example%d" % i, "examplePinyin": "exPron%d" % i,
     "translation": "exMeaning%d" % i}
    for i in range(6)
]
COMPAT_ALLOCATED = {"count": len(COMPAT_CARDS),
                    "min": COMPAT_CARDS[0]["id"],
                    "max": COMPAT_CARDS[-1]["id"]}
COMPAT_CARDS_PATH = "packs/%s/%s-cards.js" % (COMPAT_ID, COMPAT_ID)
COMPAT_MANIFEST_PATH = "packs/%s/%s-content-pack.js" % (COMPAT_ID, COMPAT_ID)

COMPAT_CARDS_JS = ("// test-only cards payload\nwindow.COMPATPACK_CARDS = %s;\n"
                   % json.dumps(COMPAT_CARDS))

# Mirrors the shape of packs/hsk/hsk-content-pack.js: it calls the REAL
# NS.createContentPack and publishes NS.contentPack, so ContentPack validation
# and CardRepository construction are exercised for real.
COMPAT_MANIFEST_JS = """
(function (NS) {
  "use strict";
  var CI = NS.cardIndex;
  var FIELD_ROLES = {
    primaryPrompt: "word", pronunciation: "pinyin", definition: "meaning",
    exampleText: "example", examplePronunciation: "examplePinyin",
    exampleTranslation: "translation", deck: "level", stableId: "id"
  };
  function deckProvider(cards) {
    var byDeck = CI.buildCardsByLevel(cards);
    var ids = [];
    for (var k in byDeck) if (Object.prototype.hasOwnProperty.call(byDeck, k)) ids.push(k);
    ids.sort();
    return ids.map(function (id, i) {
      return { id: id, order: i + 1, title: id, cardCount: byDeck[id].length };
    });
  }
  var pack = NS.createContentPack({
    id: "__ID__", version: "1.0.0", title: "__TITLE__",
    languages: { prompt: "en", meaning: "en" },
    capabilities: ["study", "srs", "test"],
    fieldRoles: FIELD_ROLES,
    testModes: [{ id: 1, label: "Word to meaning", q: "word", a: ["meaning"] }],
    deckProvider: deckProvider,
    getCards: function () { return window.COMPATPACK_CARDS || []; },
    schemaVersion: 1, packId: "__ID__", status: "launch",
    courseId: "__ID__", courseType: "general",
    languageProfile: { target: "en" },
    idRange: { min: __MIN__, max: __MAX__ }
  });
  NS.contentPack = pack;
})(window.HSKUtil = window.HSKUtil || {});
""".replace("__ID__", COMPAT_ID).replace("__TITLE__", COMPAT_ID.upper()) \
   .replace("__MIN__", str(COMPAT_RANGE["min"])) \
   .replace("__MAX__", str(COMPAT_RANGE["max"]))


def compat_pack_entry(min_app_version):
    """The catalog entry, built from the SAME constants as the payloads."""
    return {
        "packId": COMPAT_ID, "version": "1.0.0", "title": COMPAT_ID.upper(),
        "courseId": COMPAT_ID, "courseType": "general", "status": "launch",
        "languageProfile": {"target": "en"},
        "idRange": dict(COMPAT_RANGE),
        "allocated": dict(COMPAT_ALLOCATED),
        "launch": {"visible": True, "readiness": "launch"},
        "sourceChecksum": "sha256:" + HEX64,
        "contentChecksum": "sha256:" + HEX64,
        "manifestPath": COMPAT_MANIFEST_PATH,
        "cardsPath": COMPAT_CARDS_PATH,
        "minAppVersion": min_app_version,
    }


def boot_blob(ctx, blob):
    """Boot with an arbitrary settings blob written before the document parses."""
    page, errors = new_page(ctx)
    page.add_init_script(
        "try{localStorage.setItem('hsk_flashcard_settings_v2',%s);}catch(e){}"
        % json.dumps(json.dumps(blob)))
    page.goto(BASE, wait_until="load")
    return page, errors


def boot(ctx, active_pack_id="__unset__"):
    """Load the app with a given stored activePackId; return (page, errors)."""
    page, errors = new_page(ctx)
    if active_pack_id != "__unset__":
        # Seed the local-only settings blob BEFORE the document parses.
        page.add_init_script(
            "try{localStorage.setItem('hsk_flashcard_settings_v2',"
            "JSON.stringify(%s));}catch(e){}"
            % json.dumps({"activePackId": active_pack_id})
            if active_pack_id is not None else
            "try{localStorage.removeItem('hsk_flashcard_settings_v2');}catch(e){}")
    page.goto(BASE, wait_until="load")
    return page, errors


def run(browser_name, launcher):
    browser = launcher.launch()
    ctx = browser.new_context()
    tag = browser_name + ": "

    # ---------------------------------------------------------- normal boot
    page, errors = boot(ctx)

    check(tag + "no console/page errors on cold boot", errors == [])

    # The cards payload executed, and the adapter saw it.
    check(tag + "window.HSK_CARDS exists",
          page.evaluate("() => Array.isArray(window.HSK_CARDS)"))
    check(tag + "HSK_CARDS has 5002 cards",
          page.evaluate("() => window.HSK_CARDS.length") == 5002)

    # The eager CardRepository singleton -- built ONCE at load, directly from
    # the content pack -- proves the manifest ran AFTER a fully populated
    # payload. An empty/partial payload would surface here as a wrong count.
    check(tag + "CardRepository sees 5002 cards",
          page.evaluate("() => window.HSKUtil.cards.count()") == 5002)
    ids_ok = page.evaluate("""() => {
        var all = window.HSKUtil.cards.getAll();
        if (all.length !== 5002) return false;
        for (var i = 0; i < all.length; i++) if (all[i].id !== i + 1) return false;
        return true;
    }""")
    check(tag + "ids are contiguous 1..5002 in order", ids_ok)
    check(tag + "content pack constructed",
          page.evaluate("() => !!(window.HSKUtil.contentPack)"))
    check(tag + "pack id is hsk",
          page.evaluate("() => window.HSKUtil.contentPack.getPackId "
                        "? window.HSKUtil.contentPack.getPackId() "
                        ": window.HSKUtil.contentPack.id") == "hsk")

    # Deck identity/counts unchanged (six HSK decks, derived from the cards).
    decks = page.evaluate("() => window.HSKUtil.contentPack.getDeckIds()")
    check(tag + "six HSK decks in order",
          decks == ["HSK1", "HSK2", "HSK3", "HSK4", "HSK5", "HSK6"])
    counts = page.evaluate("() => window.HSKUtil.cards.countByLevel()")
    check(tag + "deck counts sum to 5002", sum(counts.values()) == 5002)

    # ------------------------------------------------- exactly one insertion
    inserted = page.evaluate("""() => {
        var out = { cards: 0, manifest: 0, all: [] };
        var s = document.querySelectorAll('script[src]');
        for (var i = 0; i < s.length; i++) {
            var src = s[i].getAttribute('src');
            out.all.push(src);
            if (src === 'data.js') out.cards++;
            if (src === 'packs/hsk/hsk-content-pack.js') out.manifest++;
        }
        return out;
    }""")
    check(tag + "exactly one cards payload inserted", inserted["cards"] == 1)
    check(tag + "exactly one manifest adapter inserted", inserted["manifest"] == 1)
    check(tag + "no duplicate script src anywhere",
          len(inserted["all"]) == len(set(inserted["all"])))

    # No mixed pack: nothing from any other pack was inserted.
    check(tag + "no foreign pack payload inserted",
          not any(s.startswith("packs/") and s != "packs/catalog.js" and
                  s != "packs/hsk/hsk-content-pack.js" for s in inserted["all"]))

    # ---------------------------------------------------- shim introspection
    shim = page.evaluate("""() => ({
        reason: window.HSKUtil.packBootShim.getBootReason(),
        active: window.HSKUtil.packBootShim.getActivePackId(),
        wrote:  window.HSKUtil.packBootShim.didWrite(),
        error:  window.HSKUtil.packBootShim.getError(),
        key:    window.HSKUtil.packBootShim.getSettingsKey()
    })""")
    check(tag + "first run resolves to hsk", shim["active"] == "hsk")
    check(tag + "first run reason recorded",
          shim["reason"] == "default-first-run")
    check(tag + "both payloads written exactly once",
          shim["wrote"] == {"cards": True, "manifest": True})
    check(tag + "no boot error", shim["error"] is None)
    check(tag + "local-only settings key when unconfigured",
          shim["key"] == "hsk_flashcard_settings_v2")

    # Re-invocation after parsing must be refused (no duplicate execution).
    again = page.evaluate("""() => ({
        cards: window.HSKUtil.packBootShim.writeCards(),
        manifest: window.HSKUtil.packBootShim.writeManifest()
    })""")
    check(tag + "writeCards refuses re-invocation", again["cards"] is False)
    check(tag + "writeManifest refuses re-invocation", again["manifest"] is False)
    check(tag + "re-invocation inserted nothing",
          page.evaluate("() => document.querySelectorAll("
                        "'script[src=\"data.js\"]').length") == 1)

    # ------------------------------------------------ study still front-side
    page.evaluate("() => { if (window.startStudy) startStudy(['HSK1']); }")
    page.wait_for_timeout(200)
    front_only = page.evaluate("""() => {
        var fc = document.getElementById('flashcard');
        if (!fc) return null;
        return { flipped: fc.classList.contains('flipped'),
                 word: (document.getElementById('word') || {}).textContent };
    }""")
    if front_only is not None:
        check(tag + "study starts front-side", front_only["flipped"] is False)
        check(tag + "front shows a card", bool(front_only["word"]))
    check(tag + "no errors after starting study", errors == [])
    page.close()

    # ---------------------------------------------------- activePackId matrix
    # The shim passes the stored value through RAW; planPackBoot owns the
    # classification. These cases pin the distinction that matters: an absent
    # setting is a clean first run, but a stored object/number/boolean is
    # CORRUPTED STORAGE and must be reported as such rather than laundered into
    # a first run. Every case must still boot one complete pack.
    for blob, label, expected_reason in [
        ({}, "missing property", "default-first-run"),
        ({"activePackId": None}, "null", "default-first-run"),
        ({"activePackId": ""}, "empty string", "default-first-run"),
        ({"activePackId": {"oops": True}}, "object", "fallback-malformed-request"),
        ({"activePackId": ["hsk"]}, "array", "fallback-malformed-request"),
        ({"activePackId": 42}, "number", "fallback-malformed-request"),
        ({"activePackId": True}, "boolean", "fallback-malformed-request"),
        ({"activePackId": "../evil"}, "malformed string", "fallback-malformed-request"),
        ({"activePackId": "NOT A PACK"}, "malformed string (spaces)",
         "fallback-malformed-request"),
        ({"activePackId": "ielts"}, "unknown valid string", "fallback-unknown-pack"),
        ({"activePackId": "hsk"}, "stored hsk", "requested"),
    ]:
        p, errs = boot_blob(ctx, blob)
        got = p.evaluate("""() => ({
            active: window.HSKUtil.packBootShim.getActivePackId(),
            reason: window.HSKUtil.packBootShim.getBootReason(),
            cards:  window.HSKUtil.cards.count(),
            error:  window.HSKUtil.packBootShim.getError(),
            wrote:  window.HSKUtil.packBootShim.didWrite(),
            payloads: document.querySelectorAll('script[src="data.js"]').length,
            manifests: document.querySelectorAll(
                'script[src="packs/hsk/hsk-content-pack.js"]').length
        })""")
        check(tag + "%s boots hsk" % label, got["active"] == "hsk")
        check(tag + "%s reason is %s" % (label, expected_reason),
              got["reason"] == expected_reason)
        check(tag + "%s is never empty" % label, got["cards"] == 5002)
        check(tag + "%s has no boot error" % label, got["error"] is None)
        check(tag + "%s has no console errors" % label, errs == [])
        # One complete pack, never partial and never doubled.
        check(tag + "%s wrote both payloads once" % label,
              got["wrote"] == {"cards": True, "manifest": True})
        check(tag + "%s inserted exactly one cards payload" % label,
              got["payloads"] == 1)
        check(tag + "%s inserted exactly one manifest" % label,
              got["manifests"] == 1)
        p.close()

    # ------------------------------------- hidden / incompatible / appVersion
    # A DEDICATED context with service workers blocked. Earlier boots in
    # `ctx` registered the v37 worker, which then serves the precached
    # packs/catalog.js cache-first and bypasses page.route entirely -- the
    # synthetic catalog would silently never be applied.
    sctx = browser.new_context(service_workers="block")
    # A hidden pack is present in the catalog but not offered.
    hidden = synth_pack("hiddenpack", 5000000, False, "internal", "draft")
    p, errs = catalog_page(sctx, [hidden], stored="hiddenpack")
    got = p.evaluate("""() => ({
        active: window.HSKUtil.packBootShim.getActivePackId(),
        reason: window.HSKUtil.packBootShim.getBootReason(),
        cards:  window.HSKUtil.cards.count()
    })""")
    check(tag + "hidden pack falls back to hsk", got["active"] == "hsk")
    check(tag + "hidden pack reason", got["reason"] == "fallback-not-launch-visible")
    check(tag + "hidden pack fallback is complete", got["cards"] == 5002)
    check(tag + "hidden pack boot has no console errors", errs == [])
    p.close()

    # A launch-visible pack that needs a NEWER app than the catalog declares.
    incompat = synth_pack("futurepack", 6000000, True, "launch", "launch",
                          min_app_version="99.0.0")
    p, errs = catalog_page(sctx, [incompat], app_version="1.0.0",
                           stored="futurepack")
    got = p.evaluate("""() => ({
        active: window.HSKUtil.packBootShim.getActivePackId(),
        reason: window.HSKUtil.packBootShim.getBootReason(),
        cards:  window.HSKUtil.cards.count()
    })""")
    check(tag + "incompatible pack falls back to hsk", got["active"] == "hsk")
    check(tag + "incompatible pack reason",
          got["reason"] == "fallback-incompatible-app-version")
    check(tag + "incompatible fallback is complete", got["cards"] == 5002)
    check(tag + "incompatible boot has no console errors", errs == [])
    p.close()

    # THE appVersion PROOF. This pack's minAppVersion is SATISFIED by the
    # catalog's appVersion, so it must be selectable. If the shim failed to
    # pass appVersion through, isCompatible() would fail closed on undefined
    # and this would come back as 'fallback-incompatible-app-version' instead
    # of 'requested' -- so this case, and only this case, distinguishes the two.
    compat = compat_pack_entry(min_app_version="1.0.0")
    p, errs = catalog_page(
        sctx, [compat], app_version="2.5.0", stored=COMPAT_ID,
        payloads={COMPAT_CARDS_PATH: COMPAT_CARDS_JS,
                  COMPAT_MANIFEST_PATH: COMPAT_MANIFEST_JS})

    got = p.evaluate("""() => {
        var shim = window.HSKUtil.packBootShim;
        var plan = shim.getPlan();
        var pack = window.HSKUtil.contentPack;
        var all  = window.HSKUtil.cards.getAll();
        return {
            active:   shim.getActivePackId(),
            reason:   shim.getBootReason(),
            error:    shim.getError(),
            expected: plan ? { cardsPath: plan.expected.cardsPath,
                               manifestPath: plan.expected.manifestPath } : null,
            packId:   pack.getPackId(),
            idRange:  pack.getIdRange(),
            validation: pack.validate(),
            count:    window.HSKUtil.cards.count(),
            ids:      all.map(function (c) { return c.id; }),
            hskCards: typeof window.HSK_CARDS
        };
    }""")

    # --- the planner selected it, using the forwarded appVersion -----------
    check(tag + "compatible pack IS selected", got["active"] == COMPAT_ID)
    check(tag + "compatible pack reason is requested", got["reason"] == "requested")
    check(tag + "compatible pack has no boot error", got["error"] is None)
    check(tag + "plan expects the compatpack cards path",
          got["expected"]["cardsPath"] == COMPAT_CARDS_PATH)
    check(tag + "plan expects the compatpack manifest path",
          got["expected"]["manifestPath"] == COMPAT_MANIFEST_PATH)

    # --- the pack that actually CONSTRUCTED is the one selected -----------
    check(tag + "constructed ContentPack is compatpack", got["packId"] == COMPAT_ID)
    check(tag + "ContentPack idRange equals the catalog range",
          got["idRange"] == COMPAT_RANGE)
    check(tag + "ContentPack validation is green",
          got["validation"].get("ok") is True)
    check(tag + "ContentPack validation reports no errors",
          got["validation"].get("errors") == [])

    # --- the cards that actually LOADED are the ones declared -------------
    check(tag + "CardRepository count equals catalog allocated.count",
          got["count"] == COMPAT_ALLOCATED["count"])
    check(tag + "every card id lies inside the compatpack idRange",
          all(COMPAT_RANGE["min"] <= i <= COMPAT_RANGE["max"] for i in got["ids"]))
    check(tag + "loaded ids match the declared allocated span",
          min(got["ids"]) == COMPAT_ALLOCATED["min"] and
          max(got["ids"]) == COMPAT_ALLOCATED["max"])

    # --- nothing from HSK came along --------------------------------------
    check(tag + "no HSK cards global exists", got["hskCards"] == "undefined")
    srcs = p.evaluate("""() => Array.prototype.map.call(
        document.querySelectorAll('script[src]'), s => s.getAttribute('src'))""")
    check(tag + "exactly one compatpack cards payload executed",
          srcs.count(COMPAT_CARDS_PATH) == 1)
    check(tag + "exactly one compatpack manifest executed",
          srcs.count(COMPAT_MANIFEST_PATH) == 1)
    check(tag + "no data.js script inserted", srcs.count("data.js") == 0)
    check(tag + "no HSK manifest script inserted",
          srcs.count("packs/hsk/hsk-content-pack.js") == 0)
    check(tag + "compatible pack boot has no console errors", errs == [])
    p.close()

    sctx.close()
    ctx.close()
    browser.close()


def run_offline(launcher):
    """Offline boot after the v37 service worker has cached the shell."""
    browser = launcher.launch()
    ctx = browser.new_context()
    page, errors = new_page(ctx)
    page.goto(BASE, wait_until="load")
    ok = page.evaluate("""() => new Promise(res => {
        if (!navigator.serviceWorker) return res(false);
        navigator.serviceWorker.ready.then(() => res(true));
        setTimeout(() => res(false), 10000);
    })""")
    check("service worker became ready", ok is True)
    if ok:
        # Give the precache time to settle, then reload with the network cut.
        page.wait_for_timeout(1500)
        ctx.set_offline(True)
        page.reload(wait_until="load")
        check("offline boot still yields 5002 cards",
              page.evaluate("() => window.HSKUtil.cards.count()") == 5002)
        check("offline boot resolves hsk",
              page.evaluate(
                  "() => window.HSKUtil.packBootShim.getActivePackId()") == "hsk")
        check("offline boot has no boot error",
              page.evaluate(
                  "() => window.HSKUtil.packBootShim.getError()") is None)
        ctx.set_offline(False)
    page.close()
    ctx.close()
    browser.close()


def main():
    skipped = []
    with sync_playwright() as pw:
        run("chromium", pw.chromium)

        # WebKit is run ONLY if its binary is already present. Installing it
        # would be a dependency download, which this phase forbids. The skip is
        # recorded explicitly so a green result never implies WebKit coverage.
        try:
            run("webkit", pw.webkit)
        except Exception as exc:
            if "Executable doesn't exist" in str(exc):
                skipped.append("webkit (browser binary not installed)")
            else:
                raise

        run_offline(pw.chromium)

    print(json.dumps({"suite": "pack_boot_parser_time",
                      "pass": not fails, "failures": fails[:20],
                      "skipped": skipped}))
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
