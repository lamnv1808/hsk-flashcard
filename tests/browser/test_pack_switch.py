#!/usr/bin/env python3
"""Phase 24E-B.5B: the explicit validated pack switch API.

switchPack() is the FIRST AND ONLY writer of activePackId. Boot stays
read-only (locked by test_pack_settings_no_write.py); this suite locks the one
sanctioned write path.

The properties that actually matter are ordering properties, so they are proven
by observation, not by trusting a green result:

  * readiness BEFORE mutation -- pullSettings() replaces the settings blob
    wholesale and only accepts a server copy newer than SETTIME, so writing
    before the initial pull settles would suppress it and let the next push
    overwrite the account's bookmarks and notes.
  * audio stop and save happen exactly once, and reload happens exactly once.
  * every rejected target mutates nothing at all.

Counters live in sessionStorage because location.reload() destroys page state;
sessionStorage survives the reload and lets us count what happened across it.

No real Supabase or internet request is made: the fake origin is intercepted and
the suite asserts nothing escaped to any other host.
"""

import json
import os
import sys
import time

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# Reuse the coherent synthetic pack fixture rather than inventing a second one.
from test_pack_boot_parser_time import (  # noqa: E402
    COMPAT_ID, COMPAT_CARDS_PATH, COMPAT_MANIFEST_PATH,
    COMPAT_CARDS_JS, COMPAT_MANIFEST_JS, compat_pack_entry, synth_pack,
    read_real_catalog,
)

BASE = os.environ.get("HSK_BASE_URL", "http://localhost:8000") + "/hsk_flashcard_app/"
SETTINGS_BASE = "hsk_flashcard_settings_v2"
FAKE_ORIGIN = "https://fake-supabase.test"
CLOUD_CONFIG = ('window.SUPABASE_CONFIG = { url: "%s", anonKey: "fake-anon-key" };'
                % FAKE_ORIGIN)
LOCAL_ONLY_CONFIG = 'window.SUPABASE_CONFIG = { url: "", anonKey: "" };'

# Counts boots (=> reloads) and wraps the two globals the API must call exactly
# once. Installed before every document parse, so it survives the reload.
INSTRUMENT = """
(() => {
  var n = parseInt(sessionStorage.getItem('__boots') || '0', 10) + 1;
  sessionStorage.setItem('__boots', String(n));
  window.__WRITES = [];
  var proto = Object.getPrototypeOf(localStorage) || Storage.prototype;
  var si = proto.setItem, ri = proto.removeItem;
  proto.setItem = function (k, v) {
    window.__WRITES.push({ op: 'set', key: k }); return si.call(this, k, v);
  };
  proto.removeItem = function (k) {
    window.__WRITES.push({ op: 'remove', key: k }); return ri.call(this, k);
  };
  var f = window.fetch;
  window.fetch = function (input) {
    var u = (typeof input === 'string') ? input : (input && input.url) || '';
    if (u.indexOf('user_settings') >= 0) window.__WRITES.push({op:'fetch', key:'GET user_settings'});
    if (u.indexOf('sync_push_settings') >= 0) window.__WRITES.push({op:'fetch', key:'POST push_settings'});
    return f.apply(this, arguments);
  };
  function bump(k) {
    sessionStorage.setItem(k, String(parseInt(sessionStorage.getItem(k) || '0', 10) + 1));
  }
  // Wrap the globals once app.js has defined them.
  window.addEventListener('load', function () {
    if (typeof window.stopSpeech === 'function' && !window.stopSpeech.__wrapped) {
      var s = window.stopSpeech;
      window.stopSpeech = function () { bump('__stops'); return s.apply(this, arguments); };
      window.stopSpeech.__wrapped = true;
    }
    if (typeof window.saveSettings === 'function' && !window.saveSettings.__wrapped) {
      var v = window.saveSettings;
      window.saveSettings = function () { bump('__saves'); return v.apply(this, arguments); };
      window.saveSettings.__wrapped = true;
    }
  });
})();
"""

fails = []
observed = []


def check(name, cond):
    if not cond:
        fails.append(name)


def counters(page):
    return page.evaluate("""() => ({
        boots: parseInt(sessionStorage.getItem('__boots') || '0', 10),
        stops: parseInt(sessionStorage.getItem('__stops') || '0', 10),
        saves: parseInt(sessionStorage.getItem('__saves') || '0', 10)
    })""")


def make_ctx(browser):
    return browser.new_context(service_workers="block")


def build_page(ctx, seed=None, config=CLOUD_CONFIG, catalog_packs=None,
               app_version=None, routes=None):
    page = ctx.new_page()
    errors = []
    escaped = []
    page.on("console", lambda m: errors.append("console:" + m.text)
            if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append("pageerror:" + str(e)))
    origin = BASE.rsplit("/hsk_flashcard_app/", 1)[0]
    page.on("request", lambda r: escaped.append(r.url)
            if not (r.url.startswith(origin) or r.url.startswith(FAKE_ORIGIN))
            else None)

    page.route("**/supabase-config.js", lambda route: route.fulfill(
        status=200, content_type="application/javascript", body=config))

    if catalog_packs:
        cat = read_real_catalog()
        cat["packs"] = list(cat["packs"]) + list(catalog_packs)
        if app_version:
            cat["appVersion"] = app_version
        body = ("// test-only catalog\nwindow.FLASHEDU_CATALOG = %s;\n"
                % json.dumps(cat))
        page.route("**/packs/catalog.js", lambda route: route.fulfill(
            status=200, content_type="application/javascript", body=body))

    # The synthetic pack's own coherent payloads.
    for rel, js in ((COMPAT_CARDS_PATH, COMPAT_CARDS_JS),
                    (COMPAT_MANIFEST_PATH, COMPAT_MANIFEST_JS)):
        page.route("**/" + rel, (lambda t: lambda route: route.fulfill(
            status=200, content_type="application/javascript", body=t))(js))

    if routes:
        page.route(FAKE_ORIGIN + "/**", routes)

    if seed:
        # add_init_script re-runs on EVERY navigation. An unguarded seed would
        # re-write the pre-switch settings right after the switch-triggered
        # reload and silently undo the write under test. Seed once per page.
        lines = ["(() => { try {",
                 "if (sessionStorage.getItem('__seeded')) return;",
                 "sessionStorage.setItem('__seeded', '1');"]
        for k, v in seed.items():
            lines.append("localStorage.setItem(%s, %s);" % (json.dumps(k), json.dumps(v)))
        lines.append("} catch (e) {} })();")
        page.add_init_script("\n".join(lines))
    page.add_init_script(INSTRUMENT)
    page._errors = errors
    page._escaped = escaped
    return page


def account_seed(uid, settings_raw, with_session=True):
    seed = {
        SETTINGS_BASE + "::" + uid: settings_raw,
        "hsk_current_user": json.dumps({"id": uid, "username": uid}),
    }
    if with_session:
        seed["hsk_session"] = json.dumps({
            "access_token": "fake", "refresh_token": "fr",
            "expires_at": int((time.time() + 3600) * 1000),
        })
    return seed


def cloud_routes(server_blob, updated_at, pushed_sink,
                 settings_delay_ms=0, hang_settings=False,
                 push_mode="ok"):
    def handler(route):
        url = route.request.url
        if "user_settings" in url:
            if hang_settings:
                return  # never fulfilled -> readiness never settles
            if settings_delay_ms:
                time.sleep(settings_delay_ms / 1000.0)
            return route.fulfill(status=200, content_type="application/json",
                                 body=json.dumps([{"data": server_blob,
                                                   "updated_at": updated_at}]))
        if "card_progress" in url:
            return route.fulfill(status=200, content_type="application/json",
                                 body="[]")
        if "sync_push_settings" in url:
            try:
                pushed_sink.append(json.loads(route.request.post_data or "{}"))
            except Exception:
                pushed_sink.append({})
            if push_mode == "reject":
                return route.abort()
            if push_mode == "hang":
                return
            return route.fulfill(status=200, content_type="application/json",
                                 body="{}")
        return route.fulfill(status=200, content_type="application/json", body="{}")
    return handler


# ------------------------------------------------------------------ tests

def run_validation_classes(ctx):
    """Every rejected target: exact code, zero mutation, zero side effect."""
    hidden = synth_pack("hiddenpack", 5000000, False, "internal", "draft")
    incompat = synth_pack("futurepack", 6000000, True, "launch", "launch",
                          min_app_version="99.0.0")
    compat = compat_pack_entry("1.0.0")
    seeded = '{"activePackId":"hsk","dark":false,"streak":0,"note":""}'

    cases = [
        ("../evil", "MALFORMED_PACK_ID", "malformed"),
        ("NOT A PACK", "MALFORMED_PACK_ID", "malformed spaces"),
        ("nosuchpack", "UNKNOWN_PACK", "unknown"),
        ("hiddenpack", "PACK_HIDDEN", "hidden"),
        ("futurepack", "PACK_INCOMPATIBLE", "incompatible"),
    ]
    for target, code, label in cases:
        page = build_page(ctx, seed={SETTINGS_BASE: seeded},
                          config=LOCAL_ONLY_CONFIG,
                          catalog_packs=[hidden, incompat, compat],
                          app_version="2.5.0")
        page.goto(BASE, wait_until="load")
        res = page.evaluate("(t) => window.HSKUtil.packBootShim.switchPack(t)", target)
        c = counters(page)
        check("invalid %s -> ok false" % label, res["ok"] is False)
        check("invalid %s -> code %s" % (label, code), res.get("code") == code)
        check("invalid %s made no settings write" % label,
              page.evaluate("(k) => localStorage.getItem(k)", SETTINGS_BASE) == seeded)
        check("invalid %s did not stop audio" % label, c["stops"] == 0)
        check("invalid %s did not save" % label, c["saves"] == 0)
        check("invalid %s did not reload" % label, c["boots"] == 1)
        check("invalid %s created no SETTIME" % label,
              page.evaluate("() => Object.keys(localStorage)"
                            ".filter(k => k.indexOf('hsk_sync_settime') === 0)") == [])
        page.close()

    # same effective pack: complete no-op, and a malformed stored value is NOT
    # repaired (that would be an unrequested settings write).
    page = build_page(ctx, seed={SETTINGS_BASE: '{"activePackId":"../evil"}'},
                      config=LOCAL_ONLY_CONFIG, catalog_packs=[compat],
                      app_version="2.5.0")
    page.goto(BASE, wait_until="load")
    res = page.evaluate("() => window.HSKUtil.packBootShim.switchPack('hsk')")
    c = counters(page)
    check("same-pack -> ok true, changed false",
          res["ok"] is True and res["changed"] is False)
    check("same-pack -> reason same-pack", res.get("reason") == "same-pack")
    check("same-pack did not repair the malformed stored value",
          page.evaluate("(k) => localStorage.getItem(k)", SETTINGS_BASE)
          == '{"activePackId":"../evil"}')
    check("same-pack zero side effects",
          c["stops"] == 0 and c["saves"] == 0 and c["boots"] == 1)
    page.close()


def run_valid_switch_local_only(ctx):
    """Local-only: one mutation, one save, one stop, one reload, coherent boot."""
    compat = compat_pack_entry("1.0.0")
    seeded = ('{"activePackId":"hsk","dark":false,"streak":0,"note":"",'
              '"bookmarks":[7,8],"notes":{"7":"keep"},"dailyGoal":30,'
              '"futureKey":{"deep":[1,2]}}')
    page = build_page(ctx, seed={SETTINGS_BASE: seeded},
                      config=LOCAL_ONLY_CONFIG, catalog_packs=[compat],
                      app_version="2.5.0")
    page.goto(BASE, wait_until="load")
    check("local-only: sync absent",
          page.evaluate("() => typeof window.HSKSync") == "undefined")

    page.evaluate("(t) => { window.__res = null;"
                  " window.HSKUtil.packBootShim.switchPack(t)"
                  "   .then(r => { window.__res = r; }); }", COMPAT_ID)
    page.wait_for_timeout(2500)   # allow the reload to complete

    blob = page.evaluate("(k) => JSON.parse(localStorage.getItem(k))", SETTINGS_BASE)
    c = counters(page)
    check("local switch persisted activePackId", blob["activePackId"] == COMPAT_ID)
    check("local switch preserved dark=false", blob["dark"] is False)
    check("local switch preserved streak=0", blob["streak"] == 0)
    check("local switch preserved empty string", blob["note"] == "")
    check("local switch preserved bookmarks", blob["bookmarks"] == [7, 8])
    check("local switch preserved notes", blob["notes"] == {"7": "keep"})
    check("local switch preserved dailyGoal", blob["dailyGoal"] == 30)
    check("local switch preserved unknown nested key",
          blob["futureKey"] == {"deep": [1, 2]})
    check("local switch changed only activePackId",
          set(blob.keys()) == {"activePackId", "dark", "streak", "note",
                               "bookmarks", "notes", "dailyGoal", "futureKey"})
    check("local switch saved exactly once", c["saves"] == 1)
    check("local switch stopped audio exactly once", c["stops"] == 1)
    check("local switch reloaded exactly once", c["boots"] == 2)

    # The reload booted the SELECTED pack, coherently, with no HSK mixed in.
    after = page.evaluate("""() => ({
        active: window.HSKUtil.packBootShim.getActivePackId(),
        reason: window.HSKUtil.packBootShim.getBootReason(),
        packId: window.HSKUtil.contentPack.getPackId(),
        count:  window.HSKUtil.cards.count(),
        hsk:    typeof window.HSK_CARDS
    })""")
    check("reload boots the selected pack", after["active"] == COMPAT_ID)
    check("reload reason is requested", after["reason"] == "requested")
    check("reload constructed the selected ContentPack", after["packId"] == COMPAT_ID)
    check("reload loaded the selected pack's cards", after["count"] == 6)
    check("reload mixed in no HSK payload", after["hsk"] == "undefined")
    srcs = page.evaluate("""() => Array.prototype.map.call(
        document.querySelectorAll('script[src]'), s => s.getAttribute('src'))""")
    check("reload inserted no data.js", srcs.count("data.js") == 0)
    check("no console errors across switch", page._errors == [])
    check("no external request", page._escaped == [])
    page.close()


def run_readiness_and_flush(ctx):
    """Readiness ordering, flush outcomes, and fail-closed timeout."""
    compat = compat_pack_entry("1.0.0")
    server = {"activePackId": "hsk", "bookmarks": [12, 34], "dailyGoal": 30,
              "streak": 7, "notes": {"12": "server"}, "srv": {"keep": True}}
    stale = '{"activePackId":"hsk","marker":"stale-local"}'
    uid = "switchuser"
    skey = SETTINGS_BASE + "::" + uid
    settime = "hsk_sync_settime::" + uid

    # --- A: switch issued immediately; readiness must delay the write --------
    pushed = []
    page = build_page(ctx, seed=account_seed(uid, stale),
                      catalog_packs=[compat], app_version="2.5.0",
                      routes=cloud_routes(server, "2020-01-01T00:00:00.000Z",
                                          pushed, settings_delay_ms=900))
    page.goto(BASE, wait_until="load")
    page.evaluate("(t) => { window.HSKUtil.packBootShim.switchPack(t); }", COMPAT_ID)
    page.wait_for_timeout(6000)

    blob = page.evaluate("(k) => JSON.parse(localStorage.getItem(k))", skey)
    check("readiness: server bookmarks survived the switch",
          blob.get("bookmarks") == [12, 34])
    check("readiness: server notes survived", blob.get("notes") == {"12": "server"})
    check("readiness: server dailyGoal survived", blob.get("dailyGoal") == 30)
    check("readiness: server streak survived", blob.get("streak") == 7)
    check("readiness: unknown server field survived", blob.get("srv") == {"keep": True})
    check("readiness: stale local blob did not win",
          blob.get("marker") != "stale-local")
    check("readiness: the switch still applied", blob.get("activePackId") == COMPAT_ID)
    check("readiness: reloaded once", counters(page)["boots"] == 2)
    check("readiness: settings push confirmed", len(pushed) >= 1)
    if pushed:
        last = pushed[-1].get("p_data", {})
        check("readiness: push carried the merged blob with the new pack",
              last.get("activePackId") == COMPAT_ID
              and last.get("bookmarks") == [12, 34])
    observed.append("A readiness+merge: bookmarks=%s active=%s boots=%d pushes=%d"
                    % (blob.get("bookmarks"), blob.get("activePackId"),
                       counters(page)["boots"], len(pushed)))
    check("readiness: no external request", page._escaped == [])
    page.close()

    # --- B: push rejected -> reload anyway, choice retained for later retry --
    pushed_b = []
    page = build_page(ctx, seed=account_seed(uid, stale),
                      catalog_packs=[compat], app_version="2.5.0",
                      routes=cloud_routes(server, "2020-01-01T00:00:00.000Z",
                                          pushed_b, push_mode="reject"))
    page.goto(BASE, wait_until="load")
    page.evaluate("(t) => { window.__r = null;"
                  " window.HSKUtil.packBootShim.switchPack(t)"
                  "  .then(r => { sessionStorage.setItem('__pushed', String(r.pushed)); }); }",
                  COMPAT_ID)
    page.wait_for_timeout(6000)
    blob = page.evaluate("(k) => JSON.parse(localStorage.getItem(k))", skey)
    check("push-reject: local choice persisted", blob.get("activePackId") == COMPAT_ID)
    check("push-reject: SETTIME retained for later retry",
          page.evaluate("(k) => localStorage.getItem(k)", settime) is not None)
    check("push-reject: reloaded anyway", counters(page)["boots"] == 2)
    check("push-reject: reported pushed=false",
          page.evaluate("() => sessionStorage.getItem('__pushed')") in ("false", None))
    observed.append("B push-reject: active=%s boots=%d"
                    % (blob.get("activePackId"), counters(page)["boots"]))
    page.close()

    # --- C: readiness never settles -> SYNC_NOT_READY, fail closed ----------
    page = build_page(ctx, seed=account_seed(uid, stale),
                      catalog_packs=[compat], app_version="2.5.0",
                      routes=cloud_routes(server, "2020-01-01T00:00:00.000Z",
                                          [], hang_settings=True))
    page.goto(BASE, wait_until="load")
    res = page.evaluate("(t) => window.HSKUtil.packBootShim.switchPack(t)", COMPAT_ID)
    c = counters(page)
    check("timeout: code is SYNC_NOT_READY", res.get("code") == "SYNC_NOT_READY")
    check("timeout: ok is false", res["ok"] is False)
    check("timeout: no write", page.evaluate("(k) => localStorage.getItem(k)", skey) == stale)
    check("timeout: no audio stop", c["stops"] == 0)
    check("timeout: no save", c["saves"] == 0)
    check("timeout: no reload", c["boots"] == 1)
    observed.append("C readiness-timeout: code=%s boots=%d stops=%d"
                    % (res.get("code"), c["boots"], c["stops"]))
    page.close()


def run_reentrancy_and_listener(ctx):
    compat = compat_pack_entry("1.0.0")
    other = synth_pack("otherpack", 8000000, True, "launch", "launch")
    seeded = '{"activePackId":"hsk"}'
    page = build_page(ctx, seed={SETTINGS_BASE: seeded},
                      config=LOCAL_ONLY_CONFIG, catalog_packs=[compat, other],
                      app_version="2.5.0")
    page.goto(BASE, wait_until="load")
    res = page.evaluate("""(ids) => {
        var shim = window.HSKUtil.packBootShim;
        var p1 = shim.switchPack(ids[0]);
        var p2 = shim.switchPack(ids[0]);      // same target
        var p3 = shim.switchPack(ids[1]);      // different target
        return Promise.resolve(p3).then(function (r3) {
            return { same: p1 === p2, third: r3 };
        });
    }""", [COMPAT_ID, "otherpack"])
    check("reentrancy: same target reuses the in-flight promise", res["same"] is True)
    check("reentrancy: different target -> SWITCH_IN_PROGRESS",
          res["third"].get("code") == "SWITCH_IN_PROGRESS")
    page.wait_for_timeout(2500)
    c = counters(page)
    check("reentrancy: exactly one save", c["saves"] == 1)
    check("reentrancy: exactly one audio stop", c["stops"] == 1)
    check("reentrancy: exactly one reload", c["boots"] == 2)
    check("reentrancy: the first target won",
          page.evaluate("() => window.HSKUtil.packBootShim.getActivePackId()") == COMPAT_ID)
    observed.append("D reentrancy: saves=%d stops=%d boots=%d"
                    % (c["saves"], c["stops"], c["boots"]))
    page.close()

    # start() is idempotent: repeated calls register the online listener once.
    uid = "listeneruser"
    page = build_page(ctx, seed=account_seed(uid, '{"activePackId":"hsk"}'),
                      catalog_packs=[compat], app_version="2.5.0",
                      routes=cloud_routes({"activePackId": "hsk"},
                                          "2000-01-01T00:00:00.000Z", []))
    page.goto(BASE, wait_until="load")
    page.wait_for_timeout(1500)
    same = page.evaluate("""() => {
        var a = window.HSKSync.start();
        var b = window.HSKSync.start();
        return a === b;
    }""")
    check("start() is idempotent (one shared promise)", same is True)
    check("whenReady() returns one shared promise",
          page.evaluate("() => window.HSKSync.whenReady() === window.HSKSync.whenReady()")
          is True)
    page.close()


def run_account_isolation(ctx):
    compat = compat_pack_entry("1.0.0")
    legacy = '{"activePackId":"hsk","marker":"legacy"}'
    blob_b = '{"activePackId":"hsk","marker":"account-b"}'
    seed = account_seed("accta", '{"activePackId":"hsk","marker":"account-a"}')
    seed[SETTINGS_BASE] = legacy
    seed[SETTINGS_BASE + "::acctb"] = blob_b

    page = build_page(ctx, seed=seed, catalog_packs=[compat], app_version="2.5.0",
                      routes=cloud_routes({"activePackId": "hsk", "marker": "srv"},
                                          "2000-01-01T00:00:00.000Z", []))
    page.goto(BASE, wait_until="load")
    page.evaluate("(t) => { window.HSKUtil.packBootShim.switchPack(t); }", COMPAT_ID)
    page.wait_for_timeout(6000)
    check("isolation: account A switched",
          page.evaluate("(k) => JSON.parse(localStorage.getItem(k)).activePackId",
                        SETTINGS_BASE + "::accta") == COMPAT_ID)
    check("isolation: account B untouched",
          page.evaluate("(k) => localStorage.getItem(k)",
                        SETTINGS_BASE + "::acctb") == blob_b)
    check("isolation: legacy global untouched",
          page.evaluate("(k) => localStorage.getItem(k)", SETTINGS_BASE) == legacy)
    check("isolation: no external request", page._escaped == [])
    page.close()


def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for fn in (run_validation_classes, run_valid_switch_local_only,
                   run_readiness_and_flush, run_reentrancy_and_listener,
                   run_account_isolation):
            ctx = make_ctx(browser)
            fn(ctx)
            ctx.close()
        browser.close()

    for line in observed:
        print("OBSERVED " + line)
    print(json.dumps({"suite": "pack_switch", "pass": not fails,
                      "failures": fails[:25],
                      "skipped": ["webkit (browser binary not installed)"]}))
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
