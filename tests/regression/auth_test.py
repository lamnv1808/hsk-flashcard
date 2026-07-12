import os
import json
from playwright.sync_api import sync_playwright

URL = (os.environ.get('HSK_BASE_URL','http://localhost:8000')+'/hsk_flashcard_app/')
MOCK = "https://mock.supabase.co"
CONFIG_JS = 'window.SUPABASE_CONFIG={url:"%s",anonKey:"anon-mock-key"};' % MOCK

pushed = []   # rpc sync_push_progress bodies

def setup_routes(ctx):
    # Serve a configured supabase-config.js (real file stays blank in the repo)
    def cfg(route):
        route.fulfill(status=200, content_type="application/javascript", body=CONFIG_JS)
    ctx.route("**/supabase-config.js", cfg)

    def register(route):
        body = json.loads(route.request.post_data or "{}")
        u = body.get("username","x")
        route.fulfill(status=200, content_type="application/json",
            body=json.dumps({"user":{"id":"u-"+u,"username":u},
                             "session":{"access_token":"at-"+u,"refresh_token":"rt-"+u,"expires_in":3600}}))
    ctx.route(MOCK+"/functions/v1/register", register)

    def login(route):
        body = json.loads(route.request.post_data or "{}")
        u = body.get("username","x"); pin = body.get("pin","")
        if u == "locked":
            return route.fulfill(status=429, content_type="application/json", body=json.dumps({"error":"too many attempts, try again later"}))
        if pin == "0000":
            return route.fulfill(status=401, content_type="application/json", body=json.dumps({"error":"invalid credentials"}))
        route.fulfill(status=200, content_type="application/json",
            body=json.dumps({"user":{"id":"u-"+u,"username":u},
                             "session":{"access_token":"at-"+u,"refresh_token":"rt-"+u,"expires_in":3600}}))
    ctx.route(MOCK+"/functions/v1/login", login)

    def push_prog(route):
        pushed.append(json.loads(route.request.post_data or "{}"))
        route.fulfill(status=204, body="")
    ctx.route(MOCK+"/rest/v1/rpc/sync_push_progress", push_prog)
    ctx.route(MOCK+"/rest/v1/rpc/sync_push_settings", lambda r: r.fulfill(status=204, body=""))
    # REST reads: empty datasets
    ctx.route(MOCK+"/rest/v1/card_progress**", lambda r: r.fulfill(status=200, content_type="application/json", body="[]") if r.request.method=="GET" else r.fulfill(status=204, body=""))
    ctx.route(MOCK+"/rest/v1/user_settings**", lambda r: r.fulfill(status=200, content_type="application/json", body="[]"))
    ctx.route(MOCK+"/auth/v1/token**", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps({"access_token":"at-refreshed","refresh_token":"rt2","expires_in":3600})))

out = {}
with sync_playwright() as p:
    b = p.chromium.launch()

    # ---------- Scenario A: gate + register + study + isolation ----------
    ctx = b.new_context(viewport={"width":1280,"height":900})
    setup_routes(ctx)
    pg = ctx.new_page()
    errs=[]; pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(URL); pg.wait_for_timeout(500)
    out["gate_shown"] = pg.is_visible("#authGate")
    out["configured"] = pg.evaluate("() => window.HSK_AUTH && window.HSK_AUTH.configured")

    # Register minh/1234
    pg.click('.auth-tab[data-tab="register"]')
    pg.fill("#auUser","minh"); pg.fill("#auPin","1234"); pg.fill("#auPin2","1234")
    pg.click("#auSubmit")
    pg.wait_for_selector("#profileBtn", timeout=8000)
    out["after_register_userId"] = pg.evaluate("() => window.HSK_AUTH.userId")
    out["gate_gone"] = not pg.is_visible("#authGate")

    # Study one card as minh
    pg.evaluate("() => { progress={}; save(); startStudy(['HSK1']); flipCard(); }")
    minh_card = pg.evaluate("() => session[0].id")
    pg.evaluate("() => gradeCard('good')")
    pg.wait_for_timeout(1600)  # let debounced push fire
    out["minh_store"] = pg.evaluate("() => Object.keys(JSON.parse(localStorage.getItem('hsk_flashcard_progress_v2::u-minh')||'{}')).length")
    out["push_only_modified"] = (len(pushed)>0 and all(len(b.get("rows",[]))==1 for b in pushed))

    # Logout -> gate
    pg.evaluate("() => { localStorage.removeItem('hsk_session'); localStorage.removeItem('hsk_current_user'); }")
    pg.reload(); pg.wait_for_timeout(500)
    out["logout_gate"] = pg.is_visible("#authGate")

    # Login as lan/5678
    pg.fill("#auUser","lan"); pg.fill("#auPin","5678"); pg.click("#auSubmit")
    pg.wait_for_selector("#profileBtn", timeout=8000)
    out["after_login_userId"] = pg.evaluate("() => window.HSK_AUTH.userId")
    pg.evaluate("() => { startStudy(['HSK2']); flipCard(); gradeCard('easy'); }")
    pg.wait_for_timeout(300)
    # isolation: both stores exist and are keyed separately
    out["isolation"] = pg.evaluate("""() => {
      const a=localStorage.getItem('hsk_flashcard_progress_v2::u-minh');
      const c=localStorage.getItem('hsk_flashcard_progress_v2::u-lan');
      return !!a && !!c && a!==c;
    }""")
    ctx.close()

    # ---------- Scenario B: failed login + lockout ----------
    ctx2 = b.new_context(); setup_routes(ctx2); pg2 = ctx2.new_page()
    pg2.goto(URL); pg2.wait_for_timeout(400)
    pg2.fill("#auUser","someone"); pg2.fill("#auPin","0000"); pg2.click("#auSubmit")
    pg2.wait_for_timeout(500)
    out["bad_login_msg"] = pg2.text_content("#auMsg")
    pg2.fill("#auUser","locked"); pg2.fill("#auPin","1111"); pg2.click("#auSubmit")
    pg2.wait_for_timeout(500)
    out["lockout_msg"] = pg2.text_content("#auMsg")
    ctx2.close()

    # ---------- Scenario C: migration prompt ----------
    ctx3 = b.new_context(); setup_routes(ctx3); pg3 = ctx3.new_page()
    pg3.goto(URL); pg3.wait_for_timeout(300)
    # seed legacy progress BEFORE logging in
    pg3.evaluate("() => localStorage.setItem('hsk_flashcard_progress_v2', JSON.stringify({'1':{due:'2025-01-01',interval:3,reps:1,correct:1,attempts:1},'2':{due:'2025-01-01',interval:7,reps:1,correct:1,attempts:1}}))")
    pg3.fill("#auUser","migrator"); pg3.fill("#auPin","4321"); pg3.click("#auSubmit")
    pg3.wait_for_selector(".migrate-gate", timeout=8000)
    out["migrate_prompt"] = pg3.is_visible(".migrate-gate")
    pg3.click('.migrate-gate [data-a="import"]')
    pg3.wait_for_timeout(1200)
    out["migrated_store"] = pg3.evaluate("() => Object.keys(JSON.parse(localStorage.getItem('hsk_flashcard_progress_v2::u-migrator')||'{}')).length")
    out["legacy_preserved"] = pg3.evaluate("() => !!localStorage.getItem('hsk_flashcard_progress_v2')")
    out["pageerrors"] = errs
    ctx3.close()
    b.close()

print(json.dumps(out, ensure_ascii=False))
