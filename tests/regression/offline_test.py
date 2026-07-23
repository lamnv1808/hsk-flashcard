import os
import json
from playwright.sync_api import sync_playwright

URL = (os.environ.get('HSK_BASE_URL','http://localhost:8000')+'/hsk_flashcard_app/')
MOCK = "https://mock.supabase.co"
CONFIG_JS = 'window.SUPABASE_CONFIG={url:"%s",anonKey:"anon-mock-key"};' % MOCK

online = {"v": True}
pushed = []

def setup(ctx):
    ctx.route("**/supabase-config.js", lambda r: r.fulfill(status=200, content_type="application/javascript", body=CONFIG_JS))
    ctx.route(MOCK+"/functions/v1/login", lambda r: r.fulfill(status=200, content_type="application/json",
        body=json.dumps({"user":{"id":"u-off","username":"off"},"session":{"access_token":"at","refresh_token":"rt","expires_in":3600}})))
    ctx.route(MOCK+"/auth/v1/token**", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps({"access_token":"at","refresh_token":"rt","expires_in":3600})))
    ctx.route(MOCK+"/rest/v1/card_progress**", lambda r: (r.fulfill(status=200, content_type="application/json", body="[]") if r.request.method=="GET" else r.fulfill(status=204, body="")))
    ctx.route(MOCK+"/rest/v1/user_settings**", lambda r: r.fulfill(status=200, content_type="application/json", body="[]"))
    ctx.route(MOCK+"/rest/v1/rpc/sync_push_settings", lambda r: r.fulfill(status=204, body=""))
    def push(route):
        if not online["v"]:
            return route.abort("failed")           # simulate offline
        pushed.append(json.loads(route.request.post_data or "{}"))
        route.fulfill(status=204, body="")
    ctx.route(MOCK+"/rest/v1/rpc/sync_push_progress", push)

out={}
with sync_playwright() as p:
    b=p.chromium.launch(); ctx=b.new_context(); setup(ctx); pg=ctx.new_page()
    pg.goto(URL); pg.wait_for_timeout(400)
    pg.fill("#auUser","off"); pg.fill("#auPin","1234"); pg.click("#auSubmit")
    pg.wait_for_selector("#profileBtn", timeout=8000)

    # go offline, study 2 cards
    online["v"]=False
    pg.evaluate("() => { progress={}; save(); startStudy(['HSK1']); }")
    pg.evaluate("() => { flipCard(); gradeCard('good'); }")
    pg.evaluate("() => { flipCard(); gradeCard('hard'); }")
    pg.wait_for_timeout(1600)  # debounced push attempts -> fail -> stay queued
    out["queued_dirty"] = pg.evaluate("() => JSON.parse(localStorage.getItem('hsk_sync_dirty::u-off')||'[]').length")
    out["studied_locally"] = pg.evaluate("() => Object.keys(JSON.parse(localStorage.getItem('hsk_flashcard_progress_v2::u-off')||'{}')).length")
    out["nothing_pushed_offline"] = (len(pushed)==0)

    # reconnect -> fire online event -> flush
    online["v"]=True
    pg.evaluate("() => window.dispatchEvent(new Event('online'))")
    pg.wait_for_timeout(1200)
    out["dirty_after_reconnect"] = pg.evaluate("() => JSON.parse(localStorage.getItem('hsk_sync_dirty::u-off')||'[]').length")
    out["pushed_rows_total"] = sum(len(x.get("rows",[])) for x in pushed)
    ctx.close()

    # ===== Web RC hotfix: the explicit no-account choice must survive a warm
    # offline reload. This is the case the mandatory gate broke outright: login
    # needs the network, so a gated first-time visitor could never study offline.
    # Once the service worker has warmed, the precached (real) supabase-config.js
    # is what boots, so BOTH Supabase hosts are hard-blocked here and asserted
    # untouched -- the proof is that local-only mode makes no request at all.
    REAL = "https://evksxsrlhpkjvgsbvlhu.supabase.co"
    blocked = []
    def block(route):
        blocked.append(route.request.url); route.abort()

    ctx2 = b.new_context()
    ctx2.route("**/supabase-config.js", lambda r: r.fulfill(status=200,
               content_type="application/javascript", body=CONFIG_JS))
    ctx2.route(REAL + "/**", block)
    ctx2.route(MOCK + "/**", block)
    errs2 = []
    # First load with sw.js unavailable, so stale caches can be seeded BEFORE any
    # worker installs; the v43 activate handler must then delete every one of them.
    ctx2.route("**/sw.js", lambda r: r.abort())
    pg2 = ctx2.new_page(); pg2.on("pageerror", lambda e: errs2.append(str(e)))
    pg2.goto(URL); pg2.wait_for_timeout(500)
    out["lo_gate_shown"] = pg2.is_visible("#authGate")
    pg2.click("#auLocalOnly"); pg2.wait_for_timeout(400)
    out["lo_gate_gone"] = not pg2.is_visible("#authGate")

    STALE = ["hsk-flashcards-v36", "hsk-flashcards-v37", "hsk-flashcards-v38",
             "hsk-flashcards-v39", "hsk-flashcards-v40", "hsk-flashcards-v41"]
    pg2.evaluate("""async (names) => {
      for (const n of names) {
        const c = await caches.open(n);
        await c.put(new Request(location.origin + '/stale-' + n), new Response('stale'));
      } }""", STALE)
    out["lo_seeded_caches"] = pg2.evaluate("async () => (await caches.keys()).sort()")
    ctx2.unroute("**/sw.js")
    pg2.reload(); pg2.wait_for_timeout(700)
    # the choice must already have survived this ordinary reload
    out["lo_reload_gate"] = pg2.is_visible("#authGate")
    out["lo_reload_cta"] = pg2.is_visible("#accountCtaBtn")

    # warm the v43 precache
    warm = 0
    for _ in range(60):
        warm = pg2.evaluate("""async () => {
          const ks = await caches.keys();
          if (!ks.includes('hsk-flashcards-v43')) return 0;
          return (await (await caches.open('hsk-flashcards-v43')).keys()).length; }""")
        if warm >= 40:
            break
        pg2.wait_for_timeout(500)
    out["lo_warm_entries"] = warm
    for _ in range(40):
        keys = pg2.evaluate("async () => (await caches.keys()).sort()")
        if keys == ["hsk-flashcards-v43"]:
            break
        pg2.wait_for_timeout(300)
    out["lo_caches"] = keys
    out["lo_distinct_assets"] = pg2.evaluate("""async () => {
      const ks = await (await caches.open('hsk-flashcards-v43')).keys();
      return new Set(ks.map(r => r.url)).size; }""")

    pg2.evaluate("() => { progress={}; save(); startStudy(['HSK1']); flipCard(); gradeCard('good'); }")
    pg2.wait_for_timeout(400)
    before = pg2.evaluate("() => localStorage.getItem('hsk_flashcard_progress_v2')")

    ctx2.set_offline(True)
    pg2.reload(); pg2.wait_for_timeout(900)
    out["lo_offline"] = pg2.evaluate("() => navigator.onLine") is False
    out["lo_offline_gate"] = pg2.is_visible("#authGate")            # must stay False
    out["lo_offline_cta"] = pg2.is_visible("#accountCtaBtn")
    out["lo_offline_shell"] = pg2.evaluate("""() => ({
      cards: (window.HSK_CARDS || []).length,
      view: document.querySelector('.view.active').id,
      levels: document.querySelectorAll('#levelPicker .level-chip').length,
      localOnly: !!(window.HSK_AUTH && window.HSK_AUTH.localOnly),
      session: localStorage.getItem('hsk_session') })""")
    out["lo_progress_exact"] = (pg2.evaluate("() => localStorage.getItem('hsk_flashcard_progress_v2')") == before)
    # a full offline Study session still works and does not leak the answer
    pg2.evaluate("() => startStudy(['HSK1'])"); pg2.wait_for_timeout(300)
    out["lo_offline_no_leak"] = pg2.evaluate(
        "() => !document.getElementById('flashcard').classList.contains('flipped')")
    pg2.evaluate("() => { flipCard(); gradeCard('hard'); }")
    pg2.wait_for_timeout(400)
    out["lo_offline_graded"] = pg2.evaluate(
        "() => Object.keys(JSON.parse(localStorage.getItem('hsk_flashcard_progress_v2')||'{}')).length")
    out["lo_blocked_backend_calls"] = blocked
    out["lo_pageerrors"] = errs2
    ctx2.set_offline(False)
    ctx2.close()
    b.close()

out["pass"]=bool(out.get("queued_dirty")==2 and out.get("studied_locally")==2
                 and out.get("nothing_pushed_offline") and out.get("dirty_after_reconnect")==0
                 and out.get("pushed_rows_total")==2
                 # --- Web RC hotfix: durable local-only across a warm offline reload ---
                 and out.get("lo_gate_shown") and out.get("lo_gate_gone")
                 and len(out.get("lo_seeded_caches") or [])==6
                 and out.get("lo_reload_gate") is False and out.get("lo_reload_cta")
                 and out.get("lo_warm_entries")==40
                 and out.get("lo_distinct_assets")==40
                 and out.get("lo_caches")==["hsk-flashcards-v43"]
                 and out.get("lo_offline") and out.get("lo_offline_gate") is False
                 and out.get("lo_offline_cta")
                 and out.get("lo_offline_shell",{}).get("cards")==5002
                 and out.get("lo_offline_shell",{}).get("view")=="homeView"
                 and out.get("lo_offline_shell",{}).get("levels")==6
                 and out.get("lo_offline_shell",{}).get("localOnly") is True
                 and out.get("lo_offline_shell",{}).get("session") is None
                 and out.get("lo_progress_exact") and out.get("lo_offline_no_leak")
                 and out.get("lo_offline_graded")==2
                 and out.get("lo_blocked_backend_calls")==[]
                 and out.get("lo_pageerrors")==[])
print(json.dumps(out, ensure_ascii=False))
import sys as _sys; _sys.exit(0 if out.get("pass") else 1)
