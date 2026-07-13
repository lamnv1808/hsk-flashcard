"""Bookmarks/notes sync + two-user isolation (Phase 1). Uses a MOCKED Supabase
(request interception) — no real project is contacted. Verifies that bookmarks and
notes ride the existing settings-blob sync and stay isolated per account.
"""
import os, json
from playwright.sync_api import sync_playwright

URL = os.environ.get("HSK_BASE_URL", "http://localhost:8000") + "/hsk_flashcard_app/"
MOCK = "https://mock.supabase.co"
CFG = 'window.SUPABASE_CONFIG={url:"%s",anonKey:"anon"};' % MOCK
fails = []
def check(n, c):
    if not c: fails.append(n)

def setup(ctx, pushed):
    ctx.route("**/supabase-config.js", lambda r: r.fulfill(status=200, content_type="application/javascript", body=CFG))
    def reg(route):
        u = json.loads(route.request.post_data or "{}").get("username", "x")
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps({"user": {"id": "u-" + u, "username": u},
                                       "session": {"access_token": "at", "refresh_token": "rt", "expires_in": 3600}}))
    ctx.route(MOCK + "/functions/v1/register", reg)
    ctx.route(MOCK + "/functions/v1/login", reg)
    ctx.route(MOCK + "/auth/v1/token**", lambda r: r.fulfill(status=200, content_type="application/json",
              body=json.dumps({"access_token": "at", "refresh_token": "rt", "expires_in": 3600})))
    ctx.route(MOCK + "/rest/v1/card_progress**", lambda r: r.fulfill(status=200, content_type="application/json", body="[]")
              if r.request.method == "GET" else r.fulfill(status=204, body=""))
    ctx.route(MOCK + "/rest/v1/user_settings**", lambda r: r.fulfill(status=200, content_type="application/json", body="[]"))
    ctx.route(MOCK + "/rest/v1/rpc/**", lambda r: r.fulfill(status=204, body=""))          # catch-all FIRST
    def pushset(route):                                                                     # specific LAST -> wins
        data = json.loads(route.request.post_data or "{}").get("p_data", {})
        pushed["n"] += 1
        if data.get("bookmarks"): pushed["bookmark"] = True
        if data.get("notes"): pushed["note"] = True
        route.fulfill(status=204, body="")
    ctx.route(MOCK + "/rest/v1/rpc/sync_push_settings", pushset)

def main():
    pushed = {"n": 0, "bookmark": False, "note": False}
    with sync_playwright() as p:
        b = p.chromium.launch()
        # user A
        ctx = b.new_context(); setup(ctx, pushed); pg = ctx.new_page()
        pg.goto(URL); pg.wait_for_timeout(400)
        pg.fill("#auUser", "alice"); pg.fill("#auPin", "1111"); pg.click("#auSubmit"); pg.wait_for_selector("#profileBtn", timeout=8000)
        pg.evaluate("()=>{ startStudy(['HSK1']); const c=session[sessionState.currentIndex]; window.HSKMeta.toggleBookmark(c.id); var s=window.HSK_APP.getSettings(); s.notes={[c.id]:'note cua alice'}; window.saveSettings(); }")
        pg.wait_for_timeout(1600)   # debounced settings push
        keyA = pg.evaluate("()=>window.HSK_AUTH.settingsKey")
        aData = pg.evaluate("(k)=>JSON.parse(localStorage.getItem(k)||'{}')", keyA)
        check("A settings namespaced by uid", keyA.endswith("::u-alice"))
        check("A has bookmark", len(aData.get("bookmarks", [])) >= 1)
        check("A has note", bool(aData.get("notes")))
        ctx.close()
        # user B (fresh context => fresh localStorage)
        ctx2 = b.new_context(); setup(ctx2, pushed); pg2 = ctx2.new_page()
        pg2.goto(URL); pg2.wait_for_timeout(400)
        pg2.fill("#auUser", "bob"); pg2.fill("#auPin", "2222"); pg2.click("#auSubmit"); pg2.wait_for_selector("#profileBtn", timeout=8000)
        keyB = pg2.evaluate("()=>window.HSK_AUTH.settingsKey")
        bData = pg2.evaluate("(k)=>JSON.parse(localStorage.getItem(k)||'{}')", keyB)
        check("keys distinct A vs B", keyA != keyB)
        check("B has no bookmarks (isolated)", not bData.get("bookmarks"))
        check("B has no notes (isolated)", not bData.get("notes"))
        ctx2.close(); b.close()

    check("settings push fired with bookmarks", pushed["bookmark"])
    check("settings push fired with notes", pushed["note"])
    result = {"suite": "metadata_sync", "pass": len(fails) == 0, "fails": fails, "pushCount": pushed["n"]}
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["pass"] else 1

if __name__ == "__main__":
    import sys
    sys.exit(main())
