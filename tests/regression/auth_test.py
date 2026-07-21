import os
import json
from playwright.sync_api import sync_playwright

URL = (os.environ.get('HSK_BASE_URL','http://localhost:8000')+'/hsk_flashcard_app/')
MOCK = "https://mock.supabase.co"
CONFIG_JS = 'window.SUPABASE_CONFIG={url:"%s",anonKey:"anon-mock-key"};' % MOCK

pushed = []   # rpc sync_push_progress bodies


def ascii_safe(text):
    """Render the result line so a default Windows cp1252 console cannot crash it.

    This suite legitimately observes Vietnamese UI strings (the local-only action
    reads "Hoc khong can tai khoan" with diacritics, and the login/lockout
    messages carry them too). Printing those straight to a cp1252 stdout raises
    UnicodeEncodeError AFTER every assertion has already run, turning a passing
    suite into a spurious failure -- `tests/run_regression.py` only hides it by
    forcing PYTHONIOENCODING=utf-8.

    Escaping rather than stripping keeps the information: a character cp1252
    cannot represent appears as its \\uXXXX escape instead of being dropped.
    Same helper as tests/browser/test_pack_course_picker.py.
    """
    return str(text).encode("ascii", "backslashreplace").decode("ascii")


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
    ctx3.close()

    # ================= Web RC hotfix: explicit local-only access =================
    # A CONFIGURED deployment must offer Login / Register / "no account" instead of
    # trapping every anonymous visitor behind a non-dismissible gate. These scenarios
    # prove the no-account path is real (base keys, no session, no sync, no request),
    # durable across reloads, reversible into an account, and never automatic.

    # ---------- Scenario D: the chooser offers all three actions ----------
    ctx4 = b.new_context(viewport={"width": 1280, "height": 900}); setup_routes(ctx4)
    pg4 = ctx4.new_page(); pg4.on("pageerror", lambda e: errs.append("D:" + str(e)))
    seen4 = []                      # every request this context makes
    ctx4.on("request", lambda r: seen4.append(r.url))
    pg4.goto(URL); pg4.wait_for_timeout(500)
    out["D_gate_shown"] = pg4.is_visible("#authGate")
    out["D_actions_visible"] = (pg4.is_visible('.auth-tab[data-tab="login"]')
                                and pg4.is_visible('.auth-tab[data-tab="register"]')
                                and pg4.is_visible("#auSubmit")
                                and pg4.is_visible("#auLocalOnly"))
    out["D_local_label"] = (pg4.text_content("#auLocalOnly") or "").strip()
    # keyboard reachable: a real focusable <button> inside the dialog
    out["D_local_keyboard"] = pg4.evaluate("""() => {
      const b = document.getElementById('auLocalOnly');
      if (!b || b.tagName !== 'BUTTON' || b.disabled) return false;
      b.focus();
      return document.activeElement === b && b.tabIndex >= 0;
    }""")
    # a byte of pre-existing local progress must survive the choice untouched
    pg4.evaluate("() => localStorage.setItem('hsk_flashcard_progress_v2', JSON.stringify({'7':{due:'2025-05-05',interval:5,reps:2,correct:2,attempts:3}}))")
    before_bytes = pg4.evaluate("() => localStorage.getItem('hsk_flashcard_progress_v2')")

    # ---------- Scenario E: choosing "no account" ----------
    pg4.click("#auLocalOnly"); pg4.wait_for_timeout(400)
    out["E_gate_gone"] = not pg4.is_visible("#authGate")
    out["E_body_unlocked"] = pg4.evaluate("() => !document.body.classList.contains('auth-locked')")
    out["E_auth_state"] = pg4.evaluate("""() => {
      const a = window.HSK_AUTH || {};
      return { configured: !!a.configured, localOnly: !!a.localOnly,
               hasUserId: 'userId' in a, hasUsername: 'username' in a,
               hasProgressKey: 'progressKey' in a, hasSettingsKey: 'settingsKey' in a };
    }""")
    out["E_keys"] = pg4.evaluate("""() => ({
      progressKey: window.HSKUtil.authContext.getProgressKey(),
      settingsKey: window.HSKUtil.authContext.getSettingsKey(),
      canSync: window.HSKUtil.authContext.canSync(),
      authenticated: window.HSKUtil.authContext.isAuthenticated() })""")
    out["E_storage"] = pg4.evaluate("""() => ({
      mode: localStorage.getItem('hsk_auth_mode_v1'),
      session: localStorage.getItem('hsk_session'),
      user: localStorage.getItem('hsk_current_user'),
      syncKeys: Object.keys(localStorage).filter(k => k.indexOf('hsk_sync') === 0) })""")
    out["E_progress_preserved"] = (pg4.evaluate("() => localStorage.getItem('hsk_flashcard_progress_v2')") == before_bytes)
    out["E_account_cta"] = pg4.is_visible("#accountCtaBtn")
    out["E_no_backend_request"] = [u for u in seen4 if MOCK in u]

    # ---------- Scenario E2: local-only Study, persistence, no answer leak ----------
    out["E2_cards"] = pg4.evaluate("() => (window.HSK_CARDS || []).length")
    pg4.evaluate("() => { progress={}; save(); startStudy(['HSK1']); flipCard(); }")
    graded_id = pg4.evaluate("() => session[0].id")
    pg4.evaluate("() => gradeCard('good')")
    pg4.wait_for_timeout(400)
    out["E2_no_leak_after_grade"] = pg4.evaluate(
        "() => !document.getElementById('flashcard').classList.contains('flipped')")
    before_progress = pg4.evaluate("() => localStorage.getItem('hsk_flashcard_progress_v2')")
    out["E2_graded_one"] = pg4.evaluate("() => Object.keys(JSON.parse(localStorage.getItem('hsk_flashcard_progress_v2')||'{}')).length")
    pg4.reload(); pg4.wait_for_timeout(600)
    out["E2_gate_after_reload"] = pg4.is_visible("#authGate")          # must stay False
    out["E2_cta_after_reload"] = pg4.is_visible("#accountCtaBtn")
    out["E2_progress_exact"] = (pg4.evaluate("() => localStorage.getItem('hsk_flashcard_progress_v2')") == before_progress)
    out["E2_card_state_kept"] = pg4.evaluate(
        "(id) => { const p = window.HSK_APP.getProgress()[String(id)]; return !!(p && p.reps >= 1); }", graded_id)
    out["E2_still_local"] = pg4.evaluate(
        "() => !!(window.HSK_AUTH.localOnly) && !window.HSK_AUTH.userId && !localStorage.getItem('hsk_session')")
    out["E2_no_backend_request"] = [u for u in seen4 if MOCK in u]
    # no answer leak on the first card of a fresh post-reload session either
    pg4.evaluate("() => startStudy(['HSK1'])")
    pg4.wait_for_timeout(300)
    out["E2_no_leak_after_reload"] = pg4.evaluate(
        "() => !document.getElementById('flashcard').classList.contains('flipped')")

    # ---------- Scenario F: opting into an account from local-only ----------
    pg4.click("#accountCtaBtn"); pg4.wait_for_timeout(400)
    out["F_gate_reopened"] = pg4.is_visible("#authGate")
    out["F_local_action_still_there"] = pg4.is_visible("#auLocalOnly")   # never trapped
    pg4.fill("#auUser", "opted"); pg4.fill("#auPin", "2468"); pg4.click("#auSubmit")
    pg4.wait_for_selector("#profileBtn", timeout=8000)
    out["F_after_login"] = pg4.evaluate("""() => ({
      userId: window.HSK_AUTH.userId,
      mode: localStorage.getItem('hsk_auth_mode_v1'),
      localOnly: !!window.HSK_AUTH.localOnly,
      progressKey: window.HSKUtil.authContext.getProgressKey(),
      cta: !!document.getElementById('accountCtaBtn') })""")
    pg4.evaluate("() => { startStudy(['HSK2']); flipCard(); gradeCard('easy'); }")
    pg4.wait_for_timeout(400)
    out["F_isolation"] = pg4.evaluate("""() => {
      const base = localStorage.getItem('hsk_flashcard_progress_v2');
      const acct = localStorage.getItem('hsk_flashcard_progress_v2::u-opted');
      return !!base && !!acct && base !== acct;
    }""")
    ctx4.close()

    # ---------- Scenario G: a fresh context is still always asked ----------
    ctx5 = b.new_context(); setup_routes(ctx5)
    pg5 = ctx5.new_page(); pg5.on("pageerror", lambda e: errs.append("G:" + str(e)))
    pg5.goto(URL); pg5.wait_for_timeout(500)
    out["G_fresh_context_gate"] = pg5.is_visible("#authGate")
    out["G_no_mode_key"] = pg5.evaluate("() => localStorage.getItem('hsk_auth_mode_v1')")
    out["G_needs_auth"] = pg5.evaluate("() => !!(window.HSK_AUTH && window.HSK_AUTH.needsAuth)")
    ctx5.close()

    out["pageerrors"] = errs
    b.close()

out["pass"]=bool(out.get("pageerrors")==[] and out.get("gate_shown") and out.get("gate_gone")
                 and out.get("isolation") and out.get("logout_gate") and out.get("migrate_prompt")
                 and out.get("legacy_preserved") and out.get("push_only_modified") and out.get("migrated_store")==2
                 # --- Web RC hotfix: explicit local-only access ---
                 and out.get("D_gate_shown") and out.get("D_actions_visible")
                 and out.get("D_local_keyboard") and out.get("D_local_label")
                 and out.get("E_gate_gone") and out.get("E_body_unlocked")
                 and out.get("E_auth_state") == {"configured": True, "localOnly": True,
                                                 "hasUserId": False, "hasUsername": False,
                                                 "hasProgressKey": False, "hasSettingsKey": False}
                 and out.get("E_keys") == {"progressKey": "hsk_flashcard_progress_v2",
                                           "settingsKey": "hsk_flashcard_settings_v2",
                                           "canSync": False, "authenticated": False}
                 and out.get("E_storage", {}).get("mode") == "local"
                 and out.get("E_storage", {}).get("session") is None
                 and out.get("E_storage", {}).get("user") is None
                 and out.get("E_storage", {}).get("syncKeys") == []
                 and out.get("E_progress_preserved") and out.get("E_account_cta")
                 and out.get("E_no_backend_request") == []
                 and out.get("E2_cards") == 5002 and out.get("E2_graded_one") == 1
                 and out.get("E2_no_leak_after_grade") and out.get("E2_no_leak_after_reload")
                 and out.get("E2_gate_after_reload") is False and out.get("E2_cta_after_reload")
                 and out.get("E2_progress_exact") and out.get("E2_card_state_kept")
                 and out.get("E2_still_local") and out.get("E2_no_backend_request") == []
                 and out.get("F_gate_reopened") and out.get("F_local_action_still_there")
                 and out.get("F_after_login", {}).get("userId") == "u-opted"
                 and out.get("F_after_login", {}).get("mode") is None
                 and out.get("F_after_login", {}).get("localOnly") is False
                 and out.get("F_after_login", {}).get("progressKey") == "hsk_flashcard_progress_v2::u-opted"
                 and out.get("F_after_login", {}).get("cta") is False
                 and out.get("F_isolation")
                 and out.get("G_fresh_context_gate") and out.get("G_needs_auth")
                 and out.get("G_no_mode_key") is None)
# json.dumps already escapes non-ASCII (ensure_ascii defaults to True); the
# wrapper makes that guarantee explicit rather than incidental.
print(ascii_safe(json.dumps(out)))
import sys as _sys; _sys.exit(0 if out.get("pass") else 1)
