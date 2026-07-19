#!/usr/bin/env python3
"""Phase 24E-B.4B: the active-pack contract performs NO settings write.

Booting resolves an active pack by READING localStorage and nothing else. The
architecture decision this suite locks is that boot must never add, remove,
repair or rewrite a settings value, and must never touch the sync timestamp.

Why this is a data-safety property, not a tidiness one
-----------------------------------------------------
Bookmarks, notes, dailyGoal and streak all live inside the settings blob, and
settings are pushed WHOLE (docs/architecture/SYNC_CONTRACT.md). A settings
write goes through app.js saveSettings(), which calls HSKSync.onSettingsChanged()
and sets SETTIME = now (sync.js:160). pullSettings() only accepts the server
blob when `!localT || srv.updated_at > localT` (sync.js:129). So a write during
boot makes local look newer than the server, the pull is skipped, and the next
debounced push overwrites the cloud with this device's blob -- silently
destroying the account's bookmarks and notes on a fresh device.

The cloud-race test below reproduces exactly that scenario against fake local
routes and asserts the server blob survives.

Nothing here is mocked: production packBootShim, planPackBoot,
createPackRegistry, app.js, auth.js and sync.js all run unmodified. No real
Supabase or internet request is made -- the fake origin is intercepted, and the
suite asserts no request escaped to any other host.
"""

import json
import os
import sys
import time

from playwright.sync_api import sync_playwright

BASE = os.environ.get("HSK_BASE_URL", "http://localhost:8000") + "/hsk_flashcard_app/"
SETTINGS_BASE = "hsk_flashcard_settings_v2"
FAKE_ORIGIN = "https://fake-supabase.test"

LOCAL_ONLY_CONFIG = 'window.SUPABASE_CONFIG = { url: "", anonKey: "" };'
CLOUD_CONFIG = ('window.SUPABASE_CONFIG = { url: "%s", anonKey: "fake-anon-key" };'
                % FAKE_ORIGIN)

# Records every localStorage write and every settings fetch, IN ORDER, so the
# ordering claim ("no SETTIME write before the pull") is provable in-page.
INSTRUMENT = """
(() => {
  window.__WRITES = [];
  var proto = Object.getPrototypeOf(localStorage) || Storage.prototype;
  var setItem = proto.setItem, removeItem = proto.removeItem;
  proto.setItem = function (k, v) {
    window.__WRITES.push({ op: 'set', key: k });
    return setItem.call(this, k, v);
  };
  proto.removeItem = function (k) {
    window.__WRITES.push({ op: 'remove', key: k });
    return removeItem.call(this, k);
  };
  var f = window.fetch;
  window.fetch = function (input) {
    var url = (typeof input === 'string') ? input : (input && input.url) || '';
    if (url.indexOf('user_settings') >= 0) {
      window.__WRITES.push({ op: 'fetch', key: 'GET user_settings' });
    }
    if (url.indexOf('sync_push_settings') >= 0) {
      window.__WRITES.push({ op: 'fetch', key: 'POST sync_push_settings' });
    }
    return f.apply(this, arguments);
  };
})();
"""

fails = []


def check(name, cond):
    if not cond:
        fails.append(name)


def seed_script(entries):
    """Write exact raw strings into localStorage before anything else runs."""
    lines = ["(() => { try {"]
    for key, raw in entries.items():
        lines.append("localStorage.setItem(%s, %s);"
                     % (json.dumps(key), json.dumps(raw)))
    lines.append("} catch (e) {} })();")
    return "\n".join(lines)


def make_page(ctx, seed=None, config=LOCAL_ONLY_CONFIG, external=None):
    page = ctx.new_page()
    page.route("**/supabase-config.js", lambda route: route.fulfill(
        status=200, content_type="application/javascript", body=config))

    errors = []
    page.on("console", lambda m: errors.append("console:" + m.text)
            if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append("pageerror:" + str(e)))

    # Any request to a host other than the local test server or the fake
    # origin is a containment failure.
    escaped = []
    page.on("request", lambda r: escaped.append(r.url)
            if not (r.url.startswith(BASE.rsplit("/hsk_flashcard_app/", 1)[0])
                    or r.url.startswith(FAKE_ORIGIN)) else None)
    if external is not None:
        external.extend([])  # keep reference semantics simple
    page._escaped = escaped

    # Seed FIRST, then instrument, so seeding is not counted as a write.
    if seed:
        page.add_init_script(seed_script(seed))
    page.add_init_script(INSTRUMENT)
    return page, errors


def settings_writes(page, key):
    return page.evaluate(
        "(k) => window.__WRITES.filter(w => w.key === k && w.op !== 'fetch')", key)


def raw(page, key):
    return page.evaluate("(k) => localStorage.getItem(k)", key)


# --------------------------------------------------------------- local-only

def run_no_write_matrix(ctx):
    # Each case seeds an EXACT raw string; boot must leave it byte-identical.
    cases = [
        (None, "absent settings key", "default-first-run"),
        ('{}', "missing activePackId", "default-first-run"),
        ('{"activePackId":null}', "null activePackId", "default-first-run"),
        ('{"activePackId":""}', "empty activePackId", "default-first-run"),
        ('{"activePackId":"../evil"}', "malformed activePackId",
         "fallback-malformed-request"),
        ('{"activePackId":{"a":1}}', "object activePackId",
         "fallback-malformed-request"),
        ('{"activePackId":"ielts"}', "unknown activePackId",
         "fallback-unknown-pack"),
        ('{"activePackId":"hsk"}', "valid activePackId", "requested"),
        # Types that a naive "normalize on boot" would corrupt.
        ('{"activePackId":"hsk","dark":false,"streak":0,"note":"",'
         '"futureKey":{"deep":[1,2]},"selectedLevels":["HSK2"]}',
         "unknown keys and falsy values", "requested"),
    ]
    for seeded, label, expected_reason in cases:
        seed = {SETTINGS_BASE: seeded} if seeded is not None else None
        page, errors = make_page(ctx, seed=seed)
        page.goto(BASE, wait_until="load")

        after = raw(page, SETTINGS_BASE)
        check("no-write: %s stays byte-identical" % label, after == seeded)
        check("no-write: %s performed no settings write" % label,
              settings_writes(page, SETTINGS_BASE) == [])

        # No sync timestamp may be created by boot.
        settime_keys = page.evaluate(
            "() => Object.keys(localStorage).filter("
            "k => k.indexOf('hsk_sync_settime') === 0)")
        check("no-write: %s created no SETTIME" % label, settime_keys == [])

        got = page.evaluate("""() => ({
            active: window.HSKUtil.packBootShim.getActivePackId(),
            reason: window.HSKUtil.packBootShim.getBootReason(),
            cards:  window.HSKUtil.cards.count()
        })""")
        check("no-write: %s resolves hsk" % label, got["active"] == "hsk")
        check("no-write: %s reason is %s" % (label, expected_reason),
              got["reason"] == expected_reason)
        check("no-write: %s still boots 5002 cards" % label, got["cards"] == 5002)
        check("no-write: %s has no console errors" % label, errors == [])
        check("no-write: %s made no external request" % label,
              page._escaped == [])
        page.close()

    # Types and unknown keys survive with identity intact.
    seeded = ('{"activePackId":"hsk","dark":false,"streak":0,"note":"",'
              '"futureKey":{"deep":[1,2]}}')
    page, _ = make_page(ctx, seed={SETTINGS_BASE: seeded})
    page.goto(BASE, wait_until="load")
    parsed = page.evaluate("(k) => JSON.parse(localStorage.getItem(k))",
                           SETTINGS_BASE)
    check("preservation: false stays boolean false", parsed["dark"] is False)
    check("preservation: 0 stays number 0",
          parsed["streak"] == 0 and not isinstance(parsed["streak"], bool))
    check("preservation: empty string preserved", parsed["note"] == "")
    check("preservation: unknown nested key preserved",
          parsed["futureKey"] == {"deep": [1, 2]})
    page.close()


# ---------------------------------------------------------- account isolation

def run_account_isolation(ctx):
    legacy = '{"activePackId":"hsk","marker":"legacy-global"}'
    blob_a = '{"activePackId":"hsk","marker":"account-a"}'
    blob_b = '{"activePackId":"ielts","marker":"account-b"}'

    def seed_for(user_id):
        # No hsk_session: sync.js starts, accessToken() throws "no session",
        # start() catches it -- so the account path is exercised with zero
        # network traffic.
        return {
            SETTINGS_BASE: legacy,
            SETTINGS_BASE + "::accta": blob_a,
            SETTINGS_BASE + "::acctb": blob_b,
            "hsk_current_user": json.dumps({"id": user_id, "username": user_id}),
        }

    for user_id, expect_key, expect_reason in [
        ("accta", SETTINGS_BASE + "::accta", "requested"),
        ("acctb", SETTINGS_BASE + "::acctb", "fallback-unknown-pack"),
    ]:
        page, errors = make_page(ctx, seed=seed_for(user_id), config=CLOUD_CONFIG)
        page.goto(BASE, wait_until="load")
        page.wait_for_timeout(500)

        key = page.evaluate("() => window.HSKUtil.packBootShim.getSettingsKey()")
        check("isolation: %s uses its namespaced key" % user_id,
              key == expect_key)
        check("isolation: %s reason is %s" % (user_id, expect_reason),
              page.evaluate(
                  "() => window.HSKUtil.packBootShim.getBootReason()")
              == expect_reason)
        check("isolation: %s still boots 5002 cards" % user_id,
              page.evaluate("() => window.HSKUtil.cards.count()") == 5002)

        # Every blob, including the two this account does not own, is untouched.
        check("isolation: %s leaves legacy global untouched" % user_id,
              raw(page, SETTINGS_BASE) == legacy)
        check("isolation: %s leaves account A blob untouched" % user_id,
              raw(page, SETTINGS_BASE + "::accta") == blob_a)
        check("isolation: %s leaves account B blob untouched" % user_id,
              raw(page, SETTINGS_BASE + "::acctb") == blob_b)
        for k in (SETTINGS_BASE, SETTINGS_BASE + "::accta",
                  SETTINGS_BASE + "::acctb"):
            check("isolation: %s wrote nothing to %s" % (user_id, k),
                  settings_writes(page, k) == [])
        check("isolation: %s made no external request" % user_id,
              page._escaped == [])
        check("isolation: %s has no console errors" % user_id, errors == [])
        page.close()


# -------------------------------------------------------------- cloud race

def run_cloud_race(ctx):
    """A newer server blob must survive a boot that saw a stale local blob."""
    uid = "raceuser"
    skey = SETTINGS_BASE + "::" + uid
    settime_key = "hsk_sync_settime::" + uid

    stale_local = '{"activePackId":"hsk","marker":"stale-local"}'
    server_blob = {
        "activePackId": "hsk",
        "bookmarks": [12, 34, 56],
        "notes": {"12": "server note"},
        "dailyGoal": 30,
        "streak": 7,
        "futureUnknown": {"keep": True},
    }
    server_updated_at = "2099-01-01T00:00:00.000Z"

    pushed = []

    def route_supabase(route):
        url = route.request.url
        if "user_settings" in url:
            return route.fulfill(status=200, content_type="application/json",
                                 body=json.dumps([{"data": server_blob,
                                                   "updated_at": server_updated_at}]))
        if "card_progress" in url:
            return route.fulfill(status=200, content_type="application/json",
                                 body="[]")
        if "sync_push_settings" in url:
            try:
                pushed.append(json.loads(route.request.post_data or "{}"))
            except Exception:
                pushed.append({})
            return route.fulfill(status=200, content_type="application/json",
                                 body="{}")
        return route.fulfill(status=200, content_type="application/json",
                             body="{}")

    seed = {
        skey: stale_local,
        "hsk_current_user": json.dumps({"id": uid, "username": uid}),
        "hsk_session": json.dumps({
            "access_token": "fake-token", "refresh_token": "fake-refresh",
            # milliseconds, comfortably in the future -> no refresh call
            "expires_at": int((time.time() + 3600) * 1000),
        }),
    }
    page, errors = make_page(ctx, seed=seed, config=CLOUD_CONFIG)
    page.route(FAKE_ORIGIN + "/**", route_supabase)
    page.goto(BASE, wait_until="load")

    # Let start() pull, reloadState(), then the 1200 ms debounced flush run.
    page.wait_for_timeout(4000)

    writes = page.evaluate("() => window.__WRITES")
    keys = [w["key"] for w in writes]

    # THE ORDERING PROOF: no SETTIME write may precede the settings pull.
    check("race: settings pull happened", "GET user_settings" in keys)
    if "GET user_settings" in keys:
        pull_at = keys.index("GET user_settings")
        before = [w for w in writes[:pull_at]
                  if w["op"] != "fetch" and w["key"] == settime_key]
        check("race: boot did not advance SETTIME before the pull", before == [])

    # The newer server blob wins and is fully intact.
    after = page.evaluate("(k) => JSON.parse(localStorage.getItem(k))", skey)
    check("race: server blob accepted", after == server_blob)
    check("race: bookmarks survived", after.get("bookmarks") == [12, 34, 56])
    check("race: notes survived", after.get("notes") == {"12": "server note"})
    check("race: dailyGoal survived", after.get("dailyGoal") == 30)
    check("race: streak survived", after.get("streak") == 7)
    check("race: unknown server field survived",
          after.get("futureUnknown") == {"keep": True})
    check("race: stale local blob did NOT win",
          after.get("marker") != "stale-local")
    check("race: SETTIME adopted the server timestamp",
          raw(page, settime_key) == server_updated_at)

    # Any push that happened must carry the ACCEPTED blob, never the stale one.
    for i, body in enumerate(pushed):
        data = body.get("p_data")
        check("race: push #%d did not send the stale blob" % i,
              not (isinstance(data, dict) and data.get("marker") == "stale-local"))
        check("race: push #%d carried the accepted blob" % i, data == server_blob)

    check("race: no external request escaped", page._escaped == [])
    check("race: no console errors", errors == [])
    page.close()


def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        # Service workers are blocked so the config/route interception is not
        # bypassed by the precached v37 shell.
        ctx = browser.new_context(service_workers="block")
        run_no_write_matrix(ctx)
        run_account_isolation(ctx)
        run_cloud_race(ctx)
        ctx.close()
        browser.close()

    print(json.dumps({"suite": "pack_settings_no_write",
                      "pass": not fails, "failures": fails[:25]}))
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
