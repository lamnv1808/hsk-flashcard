#!/usr/bin/env python3
"""Phase 24E Exit closure: reset is active-pack scoped and durably retryable.

Reset used to delete every row the user owned in every course, and it was not
durable: if the cloud delete failed the local rows were already gone, the server
rows survived, and because meta was cleared the next pullProgress saw
`!localTime` for each of them and restored the deleted progress.

Sentinels: active HSK ids 1 / 2500 / 5002 inside the declared ownership range
1-999999, and foreign ids 7000000-7000005 belonging to another pack. Every
assertion below is about which of those survive.

Fake Supabase origin only; the suite asserts no request escapes to another host.
"""

import json
import os
import sys
import time

from playwright.sync_api import sync_playwright

BASE = os.environ.get("HSK_BASE_URL", "http://localhost:8000") + "/hsk_flashcard_app/"
FAKE_ORIGIN = "https://fake-supabase.test"
CLOUD_CONFIG = ('window.SUPABASE_CONFIG = { url: "%s", anonKey: "fake-anon-key" };'
                % FAKE_ORIGIN)
LOCAL_ONLY_CONFIG = 'window.SUPABASE_CONFIG = { url: "", anonKey: "" };'

ACTIVE_IDS = [1, 2500, 5002]
FOREIGN_IDS = [7000000, 7000001, 7000002, 7000003, 7000004, 7000005]

fails = []
observed = []


def check(name, cond):
    if not cond:
        fails.append(name)


def row(due="2026-01-01"):
    return {"due": due, "interval": 3, "reps": 2, "correct": 2, "attempts": 3}


def progress_blob():
    p = {}
    for i in ACTIVE_IDS + FOREIGN_IDS:
        p[str(i)] = row()
    return json.dumps(p)


def meta_blob():
    m = {}
    for i in ACTIVE_IDS + FOREIGN_IDS:
        m[str(i)] = "2026-01-01T00:00:00.000Z"
    return json.dumps(m)


def build_page(ctx, seed, config=CLOUD_CONFIG, routes=None):
    page = ctx.new_page()
    escaped = []
    origin = BASE.rsplit("/hsk_flashcard_app/", 1)[0]
    page.on("request", lambda r: escaped.append(r.url)
            if not (r.url.startswith(origin) or r.url.startswith(FAKE_ORIGIN)) else None)
    page.on("dialog", lambda d: d.accept())          # the reset confirmation
    page.route("**/supabase-config.js", lambda route: route.fulfill(
        status=200, content_type="application/javascript", body=config))
    if routes:
        page.route(FAKE_ORIGIN + "/**", routes)
    lines = ["(() => { try {",
             "if (sessionStorage.getItem('__seeded')) return;",
             "sessionStorage.setItem('__seeded','1');"]
    for k, v in seed.items():
        lines.append("localStorage.setItem(%s, %s);" % (json.dumps(k), json.dumps(v)))
    lines.append("} catch (e) {} })();")
    page.add_init_script("\n".join(lines))
    page._escaped = escaped
    return page


def account_seed(uid):
    return {
        "hsk_flashcard_progress_v2::" + uid: progress_blob(),
        "hsk_sync_dirty::" + uid: json.dumps(ACTIVE_IDS + FOREIGN_IDS),
        "hsk_sync_meta::" + uid: meta_blob(),
        "hsk_current_user": json.dumps({"id": uid, "username": uid}),
        "hsk_session": json.dumps({
            "access_token": "fake", "refresh_token": "fr",
            "expires_at": int((time.time() + 3600) * 1000)}),
    }


def ids_in(page, key):
    v = page.evaluate("(k) => JSON.parse(localStorage.getItem(k) || '{}')", key)
    return sorted(int(x) for x in v.keys())


def do_reset(page):
    page.click("#resetBtn")
    page.wait_for_timeout(1200)


# ------------------------------------------------------------- local-only

def run_local_scope(ctx):
    page = build_page(ctx, {"hsk_flashcard_progress_v2": progress_blob()},
                      config=LOCAL_ONLY_CONFIG)
    page.goto(BASE, wait_until="load")
    check("local: sync inert", page.evaluate("() => typeof window.HSKSync") == "undefined")
    do_reset(page)
    left = ids_in(page, "hsk_flashcard_progress_v2")
    check("local: active rows removed", not any(i in left for i in ACTIVE_IDS))
    check("local: foreign rows survive", left == FOREIGN_IDS)
    observed.append("A local-only: surviving=%s" % left)

    # Idempotent: a second reset changes nothing further.
    do_reset(page)
    check("local: second reset is idempotent",
          ids_in(page, "hsk_flashcard_progress_v2") == FOREIGN_IDS)
    check("local: no external request", page._escaped == [])
    page.close()


def run_invalid_range(ctx):
    """A missing/malformed range must mutate nothing and issue no request."""
    page = build_page(ctx, {"hsk_flashcard_progress_v2": progress_blob()},
                      config=LOCAL_ONLY_CONFIG)
    page.goto(BASE, wait_until="load")
    before = page.evaluate("(k) => localStorage.getItem(k)", "hsk_flashcard_progress_v2")
    res = page.evaluate("""() => {
        // Reach the writer through the same construction app.js uses, so this
        // exercises the real contract rather than a stub.
        var w = window.HSKUtil.createProgressWriter({
            progressProvider: () => ({"1": {reps: 1}}),
            progressRepository: window.HSKUtil.createProgressRepository(
                { progressProvider: () => ({"1": {reps: 1}}) }),
            srsCalculator: window.HSKUtil.srsScheduler.computeNext,
            save: () => { window.__saved = (window.__saved || 0) + 1; },
            markDirty: () => {},
            dateProvider: () => new Date(),
            replaceProgress: () => { window.__replaced = (window.__replaced || 0) + 1; },
            onReset: () => { window.__onreset = (window.__onreset || 0) + 1; }
        });
        var out = {};
        out.missing   = w.reset();
        out.notObject = w.reset("nope");
        out.nan       = w.reset({min: NaN, max: 10});
        out.inverted  = w.reset({min: 10, max: 1});
        out.float     = w.reset({min: 1.5, max: 10});
        out.infinite  = w.reset({min: 1, max: Infinity});
        out.saved     = window.__saved || 0;
        out.replaced  = window.__replaced || 0;
        out.onreset   = window.__onreset || 0;
        return out;
    }""")
    for key in ("notObject", "nan", "inverted", "float", "infinite"):
        check("invalid range (%s) does not clear" % key,
              res[key] is not None and res[key].get("cleared") is False)
    check("missing range does not clear",
          res["missing"] is not None and res["missing"].get("cleared") is False)
    check("invalid range: never saved", res["saved"] == 0)
    check("invalid range: never replaced", res["replaced"] == 0)
    check("invalid range: never called onReset", res["onreset"] == 0)
    check("invalid range: stored progress untouched",
          page.evaluate("(k) => localStorage.getItem(k)", "hsk_flashcard_progress_v2") == before)
    observed.append("B invalid-range: saved=%d replaced=%d onreset=%d"
                    % (res["saved"], res["replaced"], res["onreset"]))
    page.close()


# ------------------------------------------------------------------ cloud

class FakeCloud(object):
    """Mutable fake server: a bounded DELETE actually removes rows, so a later
    GET can prove that reset rows do not come back."""

    def __init__(self, delete_mode="ok"):
        self.rows = {i: {"card_id": i, "due": "2026-01-01", "interval": 3,
                         "reps": 2, "correct": 2, "attempts": 3,
                         "updated_at": "2020-01-01T00:00:00.000Z"}
                     for i in ACTIVE_IDS + FOREIGN_IDS}
        self.delete_mode = delete_mode
        self.log = []                      # ordered (METHOD, path-ish) pairs

    def handler(self, route):
        req = route.request
        url, method = req.url, req.method
        if "card_progress" in url and method == "DELETE":
            self.log.append(("DELETE", url.split("card_progress")[-1]))
            if self.delete_mode == "fail":
                return route.abort()
            lo, hi = parse_bounds(url)
            if lo is not None:
                for i in list(self.rows):
                    if lo <= i <= hi:
                        del self.rows[i]
            return route.fulfill(status=204, body="")
        if "card_progress" in url and method == "GET":
            self.log.append(("GET", "card_progress"))
            return route.fulfill(status=200, content_type="application/json",
                                 body=json.dumps(list(self.rows.values())))
        if "user_settings" in url:
            self.log.append((method, "user_settings"))
            return route.fulfill(status=200, content_type="application/json",
                                 body="[]")
        self.log.append((method, "other"))
        return route.fulfill(status=200, content_type="application/json", body="{}")


def parse_bounds(url):
    lo = hi = None
    for part in url.split("?")[-1].split("&"):
        if part.startswith("card_id=gte."):
            lo = int(part.split("gte.")[1])
        if part.startswith("card_id=lte."):
            hi = int(part.split("lte.")[1])
    return (lo, hi) if lo is not None and hi is not None else (None, None)


def reseed_sync_state(page, uid):
    """The app's initial start()/flush() legitimately pushes and clears the
    pre-seeded dirty ids, so re-seed the sentinels immediately before reset."""
    page.evaluate("""(a) => {
        localStorage.setItem('hsk_sync_dirty::' + a.uid, JSON.stringify(a.ids));
        localStorage.setItem('hsk_sync_meta::' + a.uid, JSON.stringify(a.meta));
    }""", {"uid": uid, "ids": ACTIVE_IDS + FOREIGN_IDS,
           "meta": {str(i): "2026-01-01T00:00:00.000Z"
                    for i in ACTIVE_IDS + FOREIGN_IDS}})


def run_cloud_bounded(ctx):
    uid = "accta"
    cloud = FakeCloud()
    page = build_page(ctx, account_seed(uid), routes=cloud.handler)
    page.goto(BASE, wait_until="load")
    page.wait_for_timeout(1500)
    reseed_sync_state(page, uid)
    do_reset(page)
    page.wait_for_timeout(1500)

    dels = [u for (m, u) in cloud.log if m == 'DELETE' and 'gte.' in u]
    check("cloud: a bounded DELETE was issued", len(dels) >= 1)
    if dels:
        u = dels[-1]
        check("cloud: DELETE has lower bound gte.1", "card_id=gte.1&" in u or u.endswith("gte.1"))
        check("cloud: DELETE has upper bound lte.999999", "card_id=lte.999999" in u)
        check("cloud: DELETE is never gte.0", "gte.0" not in u)
    left = ids_in(page, "hsk_flashcard_progress_v2::" + uid)
    check("cloud: foreign progress survives", left == FOREIGN_IDS)
    dirty = page.evaluate("(k) => JSON.parse(localStorage.getItem(k))", "hsk_sync_dirty::" + uid)
    check("cloud: foreign dirty ids survive", sorted(dirty) == FOREIGN_IDS)
    check("cloud: active dirty ids removed", not any(i in dirty for i in ACTIVE_IDS))
    meta = page.evaluate("(k) => JSON.parse(localStorage.getItem(k))", "hsk_sync_meta::" + uid)
    check("cloud: foreign meta timestamps survive",
          sorted(int(k) for k in meta.keys()) == FOREIGN_IDS)
    check("cloud: foreign meta values byte-identical",
          all(v == "2026-01-01T00:00:00.000Z" for v in meta.values()))
    check("cloud: pending marker cleared after success",
          page.evaluate("(k) => localStorage.getItem(k)",
                        "hsk_sync_pending_reset::" + uid) is None)
    check("cloud: server active rows deleted",
          all(i not in cloud.rows for i in ACTIVE_IDS))
    check("cloud: server foreign rows survive",
          sorted(cloud.rows) == FOREIGN_IDS)
    observed.append("C cloud-ok: order=%s url=%s local=%s dirty=%s serverLeft=%s"
                    % (cloud.log[:6], dels[-1] if dels else None, left,
                       sorted(dirty), sorted(cloud.rows)))
    check("cloud: no external request", page._escaped == [])
    page.close()


def run_failed_delete_then_retry(ctx):
    """Failed DELETE stays pending across navigation, blocks the progress GET,
    then retries cleanly with no resurrection."""
    uid = "accta"
    cloud = FakeCloud(delete_mode="fail")
    page = build_page(ctx, account_seed(uid), routes=cloud.handler)
    page.goto(BASE, wait_until="load")
    page.wait_for_timeout(1500)
    reseed_sync_state(page, uid)
    do_reset(page)
    page.wait_for_timeout(1500)

    pending = page.evaluate("(k) => JSON.parse(localStorage.getItem(k) || 'null')",
                            "hsk_sync_pending_reset::" + uid)
    check("fail: pending marker retained", pending == {"min": 1, "max": 999999})
    check("fail: local active rows gone",
          ids_in(page, "hsk_flashcard_progress_v2::" + uid) == FOREIGN_IDS)
    check("fail: server still holds the active rows",
          all(i in cloud.rows for i in ACTIVE_IDS))
    # Reset itself must have preserved the foreign sync state.
    check("fail: foreign dirty ids preserved by reset",
          sorted(page.evaluate("(k) => JSON.parse(localStorage.getItem(k))",
                               "hsk_sync_dirty::" + uid)) == FOREIGN_IDS)
    m = page.evaluate("(k) => JSON.parse(localStorage.getItem(k))", "hsk_sync_meta::" + uid)
    check("fail: foreign meta preserved by reset",
          sorted(int(k) for k in m) == FOREIGN_IDS
          and all(v == "2026-01-01T00:00:00.000Z" for v in m.values()))
    observed.append("D delete-fail: pending=%s order=%s serverLeft=%s"
                    % (pending, cloud.log[:8], sorted(cloud.rows)))
    page.close()

    # --- reload in the SAME context while DELETE still fails ---------------
    # start() runs pullProgress, which must attempt the owed DELETE FIRST and
    # abort the pull when it cannot be completed.
    cloud2 = FakeCloud(delete_mode="fail")
    cloud2.rows = dict(cloud.rows)
    page = build_page(ctx, {}, routes=cloud2.handler)
    page.goto(BASE, wait_until="load")
    page.wait_for_timeout(2500)
    methods = [m for (m, _u) in cloud2.log]
    check("blocked: a DELETE was attempted", "DELETE" in methods)
    check("blocked: no progress GET while the reset is unresolved",
          not any(u == "card_progress" and m == "GET" for (m, u) in cloud2.log))
    check("blocked: reset rows did not resurrect",
          ids_in(page, "hsk_flashcard_progress_v2::" + uid) == FOREIGN_IDS)
    check("blocked: marker still pending",
          page.evaluate("(k) => JSON.parse(localStorage.getItem(k) || 'null')",
                        "hsk_sync_pending_reset::" + uid) == {"min": 1, "max": 999999})
    observed.append("E blocked-pull: order=%s local=%s"
                    % (cloud2.log[:8], ids_in(page, "hsk_flashcard_progress_v2::" + uid)))
    page.close()

    # --- now let the DELETE succeed ---------------------------------------
    cloud3 = FakeCloud()
    cloud3.rows = dict(cloud.rows)
    page = build_page(ctx, {}, routes=cloud3.handler)
    page.goto(BASE, wait_until="load")
    page.wait_for_timeout(3000)
    check("retry: marker cleared after success",
          page.evaluate("(k) => localStorage.getItem(k)",
                        "hsk_sync_pending_reset::" + uid) is None)
    check("retry: server active rows deleted",
          all(i not in cloud3.rows for i in ACTIVE_IDS))
    check("retry: server foreign rows survive", sorted(cloud3.rows) == FOREIGN_IDS)
    check("retry: local rows still not resurrected",
          ids_in(page, "hsk_flashcard_progress_v2::" + uid) == FOREIGN_IDS)
    observed.append("F retry: order=%s serverLeft=%s local=%s"
                    % (cloud3.log[:8], sorted(cloud3.rows),
                       ids_in(page, "hsk_flashcard_progress_v2::" + uid)))
    check("retry: no external request", page._escaped == [])
    page.close()


def run_account_isolation(ctx):
    seed = account_seed("accta")
    seed["hsk_flashcard_progress_v2::acctb"] = progress_blob()
    seed["hsk_sync_dirty::acctb"] = json.dumps(ACTIVE_IDS + FOREIGN_IDS)
    cloud = FakeCloud()
    page = build_page(ctx, seed, routes=cloud.handler)
    page.goto(BASE, wait_until="load")
    page.wait_for_timeout(1500)
    reseed_sync_state(page, "accta")
    do_reset(page)
    page.wait_for_timeout(1500)
    b_rows = ids_in(page, "hsk_flashcard_progress_v2::acctb")
    check("accounts: B progress untouched", b_rows == sorted(ACTIVE_IDS + FOREIGN_IDS))
    check("accounts: B dirty untouched",
          sorted(page.evaluate("(k) => JSON.parse(localStorage.getItem(k))",
                               "hsk_sync_dirty::acctb")) == sorted(ACTIVE_IDS + FOREIGN_IDS))
    check("accounts: A active rows gone",
          ids_in(page, "hsk_flashcard_progress_v2::accta") == FOREIGN_IDS)
    observed.append("G accounts: A=%s B=%s"
                    % (ids_in(page, "hsk_flashcard_progress_v2::accta"), b_rows))
    page.close()


def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for fn in (run_local_scope, run_invalid_range, run_cloud_bounded,
                   run_failed_delete_then_retry, run_account_isolation):
            ctx = browser.new_context(service_workers="block")
            fn(ctx)
            ctx.close()
        browser.close()
    for line in observed:
        print("OBSERVED " + line)
    print(json.dumps({"suite": "pack_reset_scope", "pass": not fails,
                      "failures": fails[:25]}))
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
