#!/usr/bin/env python3
"""Phase 24F: the catalog-driven course picker.

The picker renders ONLY validated launch-visible packs from packBootShim's
retained registry, and every selection goes through switchPack() -- the single
activePackId writer. Production ships one launch-visible course today, so the
one-pack path must stay completely inert: no dialog, no selector, no writes.

Multi-course behaviour is exercised with COHERENT synthetic packs served through
the real parser-time boot path. Fixtures are never named IELTS/TOEIC: no such
content exists yet and inventing it would be a product lie.
"""

import json
import os
import sys

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from test_pack_boot_parser_time import (  # noqa: E402
    COMPAT_ID, COMPAT_CARDS_PATH, COMPAT_MANIFEST_PATH,
    COMPAT_CARDS_JS, COMPAT_MANIFEST_JS, compat_pack_entry, synth_pack,
    read_real_catalog,
)

BASE = os.environ.get("HSK_BASE_URL", "http://localhost:8000") + "/hsk_flashcard_app/"
SETTINGS_KEY = "hsk_flashcard_settings_v2"
FAKE_ORIGIN = "https://fake-supabase.test"
LOCAL_ONLY = 'window.SUPABASE_CONFIG = { url: "", anonKey: "" };'
CLOUD = ('window.SUPABASE_CONFIG = { url: "%s", anonKey: "fake" };' % FAKE_ORIGIN)

import tempfile
# Screenshots are verification artefacts, not repo content: keep them out of
# the working tree so a test run never dirties the repository.
SHOTS = os.path.join(tempfile.gettempdir(), "flashedu_course_picker_shots")

fails = []
observed = []


def ascii_safe(text):
    """Render diagnostics so a default Windows cp1252 console cannot crash them.

    The app's UI strings are Vietnamese, so observed values legitimately carry
    non-ASCII (the inline switch error is "Khong the doi khoa hoc ..." with
    diacritics). Printing that straight to a cp1252 stdout raises
    UnicodeEncodeError AFTER every assertion has already run, turning a passing
    suite into a spurious failure -- and the exception tears the Playwright loop
    down mid-flight, which surfaced as a confusing CancelledError.

    Escaping rather than stripping keeps the information: a character that cp1252
    cannot represent appears as its \\uXXXX escape instead of being dropped.
    """
    return str(text).encode("ascii", "backslashreplace").decode("ascii")


def start_blackhole():
    """A local listener that ACCEPTS connections and never answers.

    The readiness-timeout case needs an initial pull that never settles. Doing
    that with a Playwright route means leaving a route handler un-fulfilled, and
    closing the page then cancels its future -- asyncio reports that as a
    CancelledError, which looks like a real fault but is pure teardown noise.
    Hanging at the socket layer instead keeps the scenario identical with no
    dangling handler at all.
    """
    import socket, threading
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(16)
    held = []

    def loop():
        while True:
            try:
                conn, _ = srv.accept()
                held.append(conn)          # hold it open, send nothing
            except OSError:
                break

    threading.Thread(target=loop, daemon=True).start()
    return srv.getsockname()[1], srv, held


def check(name, cond):
    if not cond:
        fails.append(name)


def build_page(ctx, packs=None, stored="__unset__", config=LOCAL_ONLY,
               payloads=True, routes=None, allow_origin=None):
    page = ctx.new_page()
    errors, escaped = [], []
    origin = BASE.rsplit("/hsk_flashcard_app/", 1)[0]
    page.on("pageerror", lambda e: errors.append("pageerror:" + str(e)))
    page.on("console", lambda m: errors.append("console:" + m.text)
            if m.type == "error" else None)
    page.on("request", lambda r: escaped.append(r.url)
            if not (r.url.startswith(origin) or r.url.startswith(FAKE_ORIGIN)
                    or (allow_origin and r.url.startswith(allow_origin))) else None)
    page.route("**/supabase-config.js", lambda route: route.fulfill(
        status=200, content_type="application/javascript", body=config))
    if packs is not None:
        cat = read_real_catalog()
        cat["packs"] = list(cat["packs"]) + list(packs)
        # The shipped catalog declares no appVersion; without one isCompatible()
        # fails closed and hides every pack declaring a minAppVersion. Pick a
        # version above compatpack's 1.0.0 and below futurepack's 99.0.0, so
        # "incompatible" remains a genuine case rather than an artefact.
        cat["appVersion"] = "2.5.0"
        body = "window.FLASHEDU_CATALOG = %s;\n" % json.dumps(cat)
        page.route("**/packs/catalog.js", lambda route: route.fulfill(
            status=200, content_type="application/javascript", body=body))
    if payloads:
        for rel, js in ((COMPAT_CARDS_PATH, COMPAT_CARDS_JS),
                        (COMPAT_MANIFEST_PATH, COMPAT_MANIFEST_JS)):
            page.route("**/" + rel, (lambda t: lambda route: route.fulfill(
                status=200, content_type="application/javascript", body=t))(js))
    if routes:
        page.route(FAKE_ORIGIN + "/**", routes)
    init = ["(() => { try {",
            "if (sessionStorage.getItem('__s')) return;",
            "sessionStorage.setItem('__s','1');"]
    if stored != "__unset__":
        init.append("localStorage.setItem(%s, %s);"
                    % (json.dumps(SETTINGS_KEY),
                       json.dumps(json.dumps({"activePackId": stored}))))
    init.append("} catch (e) {} })();")
    page.add_init_script("\n".join(init))
    page._errors, page._escaped = errors, escaped
    return page


def ui(page):
    return page.evaluate("""() => ({
        gateHidden: document.getElementById('courseGate').hidden,
        rowHidden: document.getElementById('courseSwitchRow').hidden,
        options: Array.prototype.map.call(
            document.querySelectorAll('#courseList .course-option'),
            b => b.getAttribute('data-pack')),
        current: (document.querySelector('#courseList [aria-current="true"]') || {})
                    .getAttribute ? document.querySelector('#courseList [aria-current="true"]').getAttribute('data-pack') : null,
        errorHidden: document.getElementById('courseError').hidden,
        errorText: document.getElementById('courseError').textContent,
        cancelHidden: document.getElementById('courseCancelBtn').hidden,
        active: window.HSKUtil.packBootShim.getActivePackId(),
        reason: window.HSKUtil.packBootShim.getBootReason(),
        settings: localStorage.getItem('hsk_flashcard_settings_v2')
    })""")


# ----------------------------------------------------------- single pack

def run_single_pack(ctx):
    """Production shape: one launch-visible course -> completely inert."""
    page = build_page(ctx, packs=None, payloads=False)
    page.goto(BASE, wait_until="load")
    page.wait_for_timeout(400)
    st = ui(page)
    check("single: no mandatory dialog", st["gateHidden"] is True)
    check("single: no course selector row", st["rowHidden"] is True)
    check("single: renders no course options", st["options"] == [])
    check("single: zero settings write at boot", st["settings"] is None)
    check("single: HSK still boots", page.evaluate("() => window.HSKUtil.cards.count()") == 5002)
    check("single: no console/page errors", page._errors == [])
    observed.append("single-pack: gateHidden=%s rowHidden=%s settings=%r"
                    % (st["gateHidden"], st["rowHidden"], st["settings"]))
    page.close()


# ------------------------------------------------------------ multi pack

def multi():
    """Two launch-visible courses, plus a hidden and an incompatible one."""
    return [compat_pack_entry("1.0.0"),
            synth_pack("hiddenpack", 5000000, False, "internal", "draft"),
            synth_pack("futurepack", 8000000, True, "launch", "launch",
                       min_app_version="99.0.0")]


def run_multi_valid(ctx):
    """A valid stored id boots normally and exposes the Home selector."""
    page = build_page(ctx, packs=multi(), stored=COMPAT_ID)
    page.goto(BASE, wait_until="load")
    page.wait_for_timeout(400)
    st = ui(page)
    check("multi/valid: boots the requested course", st["active"] == COMPAT_ID)
    check("multi/valid: reason is requested", st["reason"] == "requested")
    check("multi/valid: no mandatory dialog", st["gateHidden"] is True)
    check("multi/valid: Home selector is shown", st["rowHidden"] is False)
    check("multi/valid: no console errors", page._errors == [])

    # Opening the switcher lists exactly the validated launch-visible packs.
    page.click("#courseSwitchBtn")
    page.wait_for_timeout(200)
    st = ui(page)
    check("multi/valid: dialog opens", st["gateHidden"] is False)
    check("multi/valid: exactly the launch-visible courses are offered",
          sorted(st["options"]) == sorted(["hsk", COMPAT_ID]))
    check("multi/valid: hidden pack is absent", "hiddenpack" not in st["options"])
    check("multi/valid: incompatible pack is absent", "futurepack" not in st["options"])
    check("multi/valid: current course marked", st["current"] == COMPAT_ID)
    check("multi/valid: dismissible when not mandatory", st["cancelHidden"] is False)
    focused = page.evaluate("() => document.activeElement.className")
    check("multi/valid: focus moves into the dialog", "course-option" in (focused or ""))
    observed.append("multi/valid: options=%s current=%s" % (st["options"], st["current"]))
    page.close()


def run_multi_invalid_is_mandatory(ctx):
    """Absent / malformed / unknown / hidden / incompatible -> mandatory ask."""
    for stored, label, reason in [
        ("__unset__", "absent", "default-first-run"),
        ("../evil", "malformed", "fallback-malformed-request"),
        ("nosuchpack", "unknown", "fallback-unknown-pack"),
        ("hiddenpack", "hidden", "fallback-not-launch-visible"),
        ("futurepack", "incompatible", "fallback-incompatible-app-version"),
    ]:
        page = build_page(ctx, packs=multi(), stored=stored)
        page.goto(BASE, wait_until="load")
        page.wait_for_timeout(400)
        st = ui(page)
        before = json.dumps({"activePackId": stored}) if stored != "__unset__" else None
        check("mandatory/%s: dialog is shown" % label, st["gateHidden"] is False)
        check("mandatory/%s: reason is %s" % (label, reason), st["reason"] == reason)
        check("mandatory/%s: cannot be dismissed" % label, st["cancelHidden"] is True)
        check("mandatory/%s: storage not repaired" % label, st["settings"] == before)
        check("mandatory/%s: offers both courses" % label,
              sorted(st["options"]) == sorted(["hsk", COMPAT_ID]))
        # Escape must not close a mandatory dialog.
        page.keyboard.press("Escape")
        page.wait_for_timeout(150)
        check("mandatory/%s: Escape does not dismiss" % label,
              page.evaluate("() => document.getElementById('courseGate').hidden") is False)
        observed.append("mandatory/%s: reason=%s settings=%r"
                        % (label, st["reason"], st["settings"]))
        page.close()


def run_choose_different(ctx):
    """Choosing another course writes only activePackId and reloads coherently."""
    page = build_page(ctx, packs=multi(), stored="hsk")
    page.goto(BASE, wait_until="load")
    page.wait_for_timeout(300)
    page.click("#courseSwitchBtn")
    page.wait_for_timeout(200)
    page.click('#courseList [data-pack="%s"]' % COMPAT_ID)
    page.wait_for_timeout(2500)               # switch -> reload
    after = page.evaluate("""() => ({
        blob: JSON.parse(localStorage.getItem('hsk_flashcard_settings_v2') || 'null'),
        active: window.HSKUtil.packBootShim.getActivePackId(),
        packId: window.HSKUtil.contentPack.getPackId(),
        count: window.HSKUtil.cards.count(),
        hsk: typeof window.HSK_CARDS
    })""")
    check("choose: activePackId persisted", after["blob"]["activePackId"] == COMPAT_ID)
    check("choose: only activePackId in the blob",
          list(after["blob"].keys()) == ["activePackId"])
    check("choose: reloaded into the chosen course", after["active"] == COMPAT_ID)
    check("choose: coherent cards/manifest pair",
          after["packId"] == COMPAT_ID and after["count"] == 6
          and after["hsk"] == "undefined")
    observed.append("choose-different: blob=%s pack=%s count=%s"
                    % (after["blob"], after["packId"], after["count"]))
    page.close()


def run_choose_effective_default(ctx):
    """Explicitly picking the effective default persists it via switchPack."""
    page = build_page(ctx, packs=multi(), stored="__unset__")
    page.goto(BASE, wait_until="load")
    page.wait_for_timeout(400)
    st = ui(page)
    check("default-choice: starts mandatory with nothing stored",
          st["gateHidden"] is False and st["settings"] is None)
    page.click('#courseList [data-pack="hsk"]')     # the effective default
    page.wait_for_timeout(2500)                     # persistSame -> save -> reload
    after = page.evaluate("""() => ({
        blob: JSON.parse(localStorage.getItem('hsk_flashcard_settings_v2') || 'null'),
        gateHidden: document.getElementById('courseGate').hidden,
        active: window.HSKUtil.packBootShim.getActivePackId(),
        reason: window.HSKUtil.packBootShim.getBootReason()
    })""")
    check("default-choice: activePackId now persisted",
          after["blob"] and after["blob"].get("activePackId") == "hsk")
    check("default-choice: boot reason becomes requested",
          after["reason"] == "requested")
    check("default-choice: mandatory dialog gone after reload",
          after["gateHidden"] is True)
    check("default-choice: still the same course", after["active"] == "hsk")
    observed.append("default-choice: blob=%s reason=%s" % (after["blob"], after["reason"]))
    page.close()

    # And the plain same-pack call (no options) stays a zero-write no-op.
    page = build_page(ctx, packs=multi(), stored="hsk")
    page.goto(BASE, wait_until="load")
    page.wait_for_timeout(300)
    before = page.evaluate("(k) => localStorage.getItem(k)", SETTINGS_KEY)
    res = page.evaluate("() => window.HSKUtil.packBootShim.switchPack('hsk')")
    after = page.evaluate("(k) => localStorage.getItem(k)", SETTINGS_KEY)
    check("same-pack: legacy call is still a no-op",
          res["ok"] is True and res["changed"] is False and res["reason"] == "same-pack")
    check("same-pack: legacy call wrote nothing", after == before)
    # persistSame with a matching stored id is also a zero-write no-op.
    res2 = page.evaluate(
        "() => window.HSKUtil.packBootShim.switchPack('hsk', { persistSame: true })")
    check("same-pack: persistSame with matching stored id is a no-op",
          res2["changed"] is False)
    check("same-pack: persistSame wrote nothing",
          page.evaluate("(k) => localStorage.getItem(k)", SETTINGS_KEY) == before)
    observed.append("same-pack: legacy=%s persistSame=%s"
                    % (res["reason"], res2.get("reason")))
    page.close()


def run_failure_keeps_picker(ctx):
    """A failed switch preserves settings and leaves the dialog usable."""
    import time as _t

    port, srv, held = start_blackhole()
    hang_origin = "http://127.0.0.1:%d" % port
    cloud_hang = ('window.SUPABASE_CONFIG = { url: "%s", anonKey: "fake" };'
                  % hang_origin)
    try:
        page = build_page(ctx, packs=multi(), stored="__unset__",
                          config=cloud_hang, allow_origin=hang_origin)
        page.add_init_script(
            "try{localStorage.setItem('hsk_current_user',JSON.stringify({id:'u1',username:'u1'}));"
            "localStorage.setItem('hsk_session',JSON.stringify({access_token:'t',"
            "refresh_token:'r',expires_at:%d}));}catch(e){}" % int((_t.time() + 3600) * 1000))
        page.goto(BASE, wait_until="load")
        page.wait_for_timeout(500)
        key = page.evaluate("() => window.HSKUtil.packBootShim.getSettingsKey()")
        before = page.evaluate("(k) => localStorage.getItem(k)", key)
        page.click('#courseList [data-pack="%s"]' % COMPAT_ID)
        page.wait_for_timeout(7000)                 # 5s readiness cap + margin
        st = page.evaluate("""(k) => ({
            gateHidden: document.getElementById('courseGate').hidden,
            errorHidden: document.getElementById('courseError').hidden,
            errorText: document.getElementById('courseError').textContent,
            disabled: Array.prototype.every.call(
                document.querySelectorAll('#courseList .course-option'), b => b.disabled),
            settings: localStorage.getItem(k)
        })""", key)
        check("failure: dialog stays open", st["gateHidden"] is False)
        check("failure: an inline error is shown", st["errorHidden"] is False)
        check("failure: the error names the cause",
              "SYNC_NOT_READY" in (st["errorText"] or ""))
        check("failure: settings untouched", st["settings"] == before)
        check("failure: options are re-enabled for another try", st["disabled"] is False)
        check("failure: no request escaped", page._escaped == [])
        observed.append("failure: gateOpen=%s error=%r settingsUnchanged=%s"
                        % (not st["gateHidden"], (st["errorText"] or "")[:48],
                           st["settings"] == before))
        page.close()
    finally:
        for c in held:
            try: c.close()
            except OSError: pass
        try: srv.close()
        except OSError: pass


def run_visual(ctx):
    """Desktop and mobile rendering of the (test-only) multi-course dialog."""
    os.makedirs(SHOTS, exist_ok=True)
    for label, w, h in (("desktop", 1440, 900), ("mobile", 390, 844)):
        page = build_page(ctx, packs=multi(), stored="__unset__")
        page.set_viewport_size({"width": w, "height": h})
        page.goto(BASE, wait_until="load")
        page.wait_for_timeout(500)
        shot = os.path.join(SHOTS, "course_picker_%s.png" % label)
        page.screenshot(path=shot)
        box = page.evaluate("""() => {
            const c = document.querySelector('#courseGate .course-card');
            const r = c.getBoundingClientRect();
            return { top: r.top, left: r.left, right: r.right, bottom: r.bottom,
                     vw: innerWidth, vh: innerHeight,
                     scrollable: c.scrollHeight <= c.clientHeight + 1 };
        }""")
        check("visual/%s: dialog within viewport horizontally" % label,
              box["left"] >= 0 and box["right"] <= box["vw"] + 1)
        check("visual/%s: dialog not clipped vertically" % label,
              box["top"] >= 0 and box["bottom"] <= box["vh"] + 1)
        check("visual/%s: content fits without inner overflow" % label,
              box["scrollable"] is True)
        check("visual/%s: page does not scroll horizontally" % label,
              page.evaluate("() => document.documentElement.scrollWidth <= innerWidth + 1"))
        observed.append("visual/%s %dx%d: card=%.0f..%.0f of %d, shot=%s"
                        % (label, w, h, box["left"], box["right"], box["vw"],
                           os.path.basename(shot)))
        page.close()


def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for fn in (run_single_pack, run_multi_valid, run_multi_invalid_is_mandatory,
                   run_choose_different, run_choose_effective_default,
                   run_failure_keeps_picker, run_visual):
            ctx = browser.new_context(service_workers="block")
            fn(ctx)
            ctx.close()
        browser.close()
    for line in observed:
        print("OBSERVED " + ascii_safe(line))
    # json.dumps already escapes non-ASCII (ensure_ascii defaults to True); the
    # wrapper makes that guarantee explicit rather than incidental.
    print(ascii_safe(json.dumps(
        {"suite": "pack_course_picker", "pass": not fails,
         "failures": fails[:25],
         "skipped": ["webkit (browser binary not installed)"]})))
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
