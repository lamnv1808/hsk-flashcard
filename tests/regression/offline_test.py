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
    b.close()

print(json.dumps(out, ensure_ascii=False))
