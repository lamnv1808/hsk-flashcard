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

    # --------------------------------------------------------- fallback cases
    # Every one of these must still boot HSK with a full dataset. "Never boot
    # empty" is the invariant: an empty dataset looks like data loss to a user.
    for stored, label, expected_reason in [
        ("hsk", "stored hsk", "requested"),
        ("ielts", "unknown pack", "fallback-unknown-pack"),
        ("../evil", "malformed pack id", "fallback-malformed-request"),
        ("NOT A PACK", "malformed pack id (spaces)", "fallback-malformed-request"),
        ("", "empty string", "default-first-run"),
    ]:
        p, errs = boot(ctx, stored)
        got = p.evaluate("""() => ({
            active: window.HSKUtil.packBootShim.getActivePackId(),
            reason: window.HSKUtil.packBootShim.getBootReason(),
            cards:  window.HSKUtil.cards.count(),
            error:  window.HSKUtil.packBootShim.getError()
        })""")
        check(tag + "%s boots hsk" % label, got["active"] == "hsk")
        check(tag + "%s reason is %s" % (label, expected_reason),
              got["reason"] == expected_reason)
        check(tag + "%s is never empty" % label, got["cards"] == 5002)
        check(tag + "%s has no boot error" % label, got["error"] is None)
        check(tag + "%s has no console errors" % label, errs == [])
        p.close()

    # A non-string activePackId (corrupted storage) must behave as first run.
    p, errs = new_page(ctx)
    p.add_init_script(
        "try{localStorage.setItem('hsk_flashcard_settings_v2',"
        "JSON.stringify({activePackId:{oops:true}}));}catch(e){}")
    p.goto(BASE, wait_until="load")
    check(tag + "non-string activePackId boots hsk",
          p.evaluate("() => window.HSKUtil.packBootShim.getActivePackId()") == "hsk")
    check(tag + "non-string activePackId is never empty",
          p.evaluate("() => window.HSKUtil.cards.count()") == 5002)
    p.close()

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
