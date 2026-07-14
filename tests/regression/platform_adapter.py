"""Phase 24A — platform adapter + PIN modal (native-readiness).

Adapter: capability detection, SW registration gating (web registers / native no-op),
background hook (fires on hidden, not visible) that stops active speech. PIN modal: replaces
prompt() for change-PIN and delete-account, preserving the exact Edge Function calls, validation,
error meaning and success behavior; no reachable prompt() remains for these flows.

Read-only w.r.t. production: Part A local-only; Part B uses a stubbed config + mocked Supabase
endpoints (no real network, no production Supabase, no real user data).
"""
import os, json
from playwright.sync_api import sync_playwright

URL = os.environ.get('HSK_BASE_URL', 'http://localhost:8000') + '/hsk_flashcard_app/'
EMPTY = 'window.SUPABASE_CONFIG={url:"",anonKey:""};'
CONFIG = 'window.SUPABASE_CONFIG={url:"https://x.test",anonKey:"anon"};'
fails = []
def check(n, c):
    if not c: fails.append(n)

with sync_playwright() as p:
    b = p.chromium.launch()

    # ===================== Part A: platform adapter (local-only) =====================
    ctxA = b.new_context(viewport={'width': 1024, 'height': 800})
    ctxA.route('**/supabase-config.js', lambda r: r.fulfill(status=200, content_type='application/javascript', body=EMPTY))
    pgA = ctxA.new_page(); errsA = []
    pgA.on('pageerror', lambda e: errsA.append('PAGEERR:' + str(e)))
    pgA.on('console', lambda m: errsA.append('CON:' + m.text) if m.type == 'error' else None)
    pgA.goto(URL); pgA.wait_for_timeout(400)

    ad = pgA.evaluate("""()=>{
        const P = window.HSKUtil && HSKUtil.platform;
        const out = { present: !!P };
        if(!P) return out;
        out.isNativeWeb = P.isNative();
        out.platformWeb = P.platform();
        // native stub: registerServiceWorker must NOT register
        let nativeRegs = 0;
        const origReg = navigator.serviceWorker && navigator.serviceWorker.register;
        if(origReg) navigator.serviceWorker.register = function(){ nativeRegs++; return Promise.resolve({}); };
        window.Capacitor = { isNativePlatform: ()=>true, getPlatform: ()=>'android' };
        out.isNativeStub = P.isNative();
        out.platformStub = P.platform();
        P.registerServiceWorker('sw.js');
        out.nativeRegs = nativeRegs;
        delete window.Capacitor;
        // web: registerServiceWorker DOES call register; missing-SW / throwing register must not throw
        let webRegs = 0;
        if(origReg){ navigator.serviceWorker.register = function(){ webRegs++; throw new Error('boom'); }; }
        let threw = false;
        try { P.registerServiceWorker('sw.js'); } catch(_){ threw = true; }
        out.webRegs = webRegs; out.webThrew = threw;
        if(origReg) navigator.serviceWorker.register = origReg;
        out.noCapacitorThrows = (function(){ try { P.isNative(); P.platform(); return false; } catch(_){ return true; } })();
        return out;
    }""")
    check('A adapter present', ad.get('present'))
    check('A isNative()===false on web', ad.get('isNativeWeb') == False)
    check('A platform()==="web"', ad.get('platformWeb') == 'web')
    check('A native stub -> isNative true', ad.get('isNativeStub') == True)
    check('A native stub -> platform android', ad.get('platformStub') == 'android')
    check('A native -> registers NO service worker', ad.get('nativeRegs') == 0)
    check('A web -> calls register', ad.get('webRegs', 0) >= 1)
    check('A throwing register never throws out', ad.get('webThrew') == False)
    check('A missing Capacitor never throws', ad.get('noCapacitorThrows') == False)

    # web actually registered the SW once at boot
    regs = pgA.evaluate("()=>navigator.serviceWorker.getRegistrations().then(r=>r.length)")
    check('A web SW registered at boot (>=1)', regs >= 1)

    # onBackground: fires on hidden, not on visible, and unsubscribe works
    bg = pgA.evaluate("""()=>{
        let n=0; const unsub = HSKUtil.platform.onBackground(()=>n++);
        Object.defineProperty(document,'visibilityState',{configurable:true,get:()=>'hidden'});
        document.dispatchEvent(new Event('visibilitychange')); const afterHidden=n;
        Object.defineProperty(document,'visibilityState',{configurable:true,get:()=>'visible'});
        document.dispatchEvent(new Event('visibilitychange')); const afterVisible=n;
        unsub();
        Object.defineProperty(document,'visibilityState',{configurable:true,get:()=>'hidden'});
        document.dispatchEvent(new Event('visibilitychange')); const afterUnsub=n;
        return { afterHidden, afterVisible, afterUnsub };
    }""")
    check('A onBackground fires on hidden', bg['afterHidden'] == 1)
    check('A onBackground NOT on visible', bg['afterVisible'] == 1)
    check('A onBackground unsubscribe works', bg['afterUnsub'] == 1)

    # app-wired background hook stops active speech (body.speaking cleared on hidden, kept on visible)
    sp = pgA.evaluate("""()=>{
        document.body.classList.add('speaking');
        Object.defineProperty(document,'visibilityState',{configurable:true,get:()=>'hidden'});
        document.dispatchEvent(new Event('visibilitychange'));
        const speakingAfterHidden = document.body.classList.contains('speaking');
        document.body.classList.add('speaking');
        Object.defineProperty(document,'visibilityState',{configurable:true,get:()=>'visible'});
        document.dispatchEvent(new Event('visibilitychange'));
        const speakingAfterVisible = document.body.classList.contains('speaking');
        return { speakingAfterHidden, speakingAfterVisible };
    }""")
    check('A background stops speech (speaking cleared on hidden)', sp['speakingAfterHidden'] == False)
    check('A foreground does NOT auto-stop/play (speaking kept on visible)', sp['speakingAfterVisible'] == True)
    check('A no console/page errors', len(errsA) == 0)
    ctxA.close()

    # ===================== Part B: PIN modal (configured + logged-in mock) =====================
    ctxB = b.new_context(viewport={'width': 390, 'height': 844})
    ctxB.route('**/supabase-config.js', lambda r: r.fulfill(status=200, content_type='application/javascript', body=CONFIG))
    mstate = {'cp_fail': False, 'da_fail': False}
    def mock_supabase(route):
        u = route.request.url
        if 'functions/v1/change-pin' in u and mstate['cp_fail']:
            route.fulfill(status=400, content_type='application/json', body='{"error":"Sai mã PIN"}'); return
        if 'functions/v1/delete-account' in u and mstate['da_fail']:
            route.fulfill(status=400, content_type='application/json', body='{"error":"Sai mã PIN"}'); return
        body = '[]' if '/rest/v1' in u else '{}'
        route.fulfill(status=200, content_type='application/json', body=body)
    ctxB.route('https://x.test/**', mock_supabase)
    pgB = ctxB.new_page(); errsB = []
    reqs = {'change-pin': 0, 'delete-account': 0}
    def on_req(r):
        if 'functions/v1/change-pin' in r.url: reqs['change-pin'] += 1
        if 'functions/v1/delete-account' in r.url: reqs['delete-account'] += 1
    pgB.on('request', on_req)
    pgB.on('pageerror', lambda e: errsB.append('PAGEERR:' + str(e)))
    # Ignore browser network-level logging for the deliberately-injected 400 server-failure tests
    # (those are expected; we only care about JS/page errors).
    def on_con(m):
        if m.type == 'error' and 'Failed to load resource' not in m.text:
            errsB.append('CON:' + m.text)
    pgB.on('console', on_con)
    pgB.on('dialog', lambda d: d.accept())   # auto-accept alert() success/confirm
    pgB.goto(URL); pgB.wait_for_timeout(300)
    # seed a logged-in session, then reload so auth.js boots logged-in
    pgB.evaluate("""()=>{ localStorage.setItem('hsk_current_user', JSON.stringify({id:'u1',username:'tester'}));
        localStorage.setItem('hsk_session', JSON.stringify({access_token:'tok',refresh_token:'ref',expires_at: Date.now()+3600000})); }""")
    pgB.reload(); pgB.wait_for_timeout(400)
    check('B logged-in profile present', pgB.evaluate("()=>!!document.getElementById('profileBtn')"))
    check('B no reachable window.prompt spy will stay 0 (install spy)', True)
    pgB.evaluate("()=>{ window.__prompts=0; window.prompt=function(){ window.__prompts++; return null; }; }")

    def open_change_pin():
        pgB.evaluate("()=>document.getElementById('profileBtn').click()"); pgB.wait_for_timeout(50)  # show menu (items focusable)
        pgB.evaluate("""()=>{ const it=document.querySelector('[data-act=\"changepin\"]'); it.focus(); it.click(); }""")
        pgB.wait_for_timeout(80)
    def open_delete():
        pgB.evaluate("()=>document.getElementById('profileBtn').click()"); pgB.wait_for_timeout(50)
        pgB.evaluate("""()=>{ const it=document.querySelector('[data-act=\"delete\"]'); it.focus(); it.click(); }""")
        pgB.wait_for_timeout(80)
    def modal_open():
        return pgB.evaluate("()=>!!document.querySelector('.pin-modal-gate')")
    def set_field(key, val):
        pgB.evaluate("(a)=>{ document.getElementById('pin_'+a.k).value=a.v; }", {'k': key, 'v': val})
    def submit():
        pgB.evaluate("()=>{ const b=[...document.querySelectorAll('.pin-modal-actions .primary-btn')][0]; b.click(); }"); pgB.wait_for_timeout(120)
    def modal_msg():
        return pgB.evaluate("()=>{ const m=document.getElementById('pinModalMsg'); return m?m.textContent:''; }")

    # Change PIN opens without prompt
    open_change_pin()
    check('B change-PIN modal opens', modal_open())
    check('B change-PIN did not call prompt', pgB.evaluate("()=>window.__prompts") == 0)
    check('B modal is role=dialog aria-modal', pgB.evaluate("()=>{const d=document.querySelector('.pin-modal'); return d.getAttribute('role')==='dialog' && d.getAttribute('aria-modal')==='true';}"))
    # invalid current PIN -> no request, stays open
    set_field('old', '12'); set_field('new', '1234'); set_field('confirm', '1234'); submit()
    check('B invalid PIN -> no request', reqs['change-pin'] == 0)
    check('B invalid PIN -> modal stays open + error', modal_open() and 'chữ số' in modal_msg())
    # mismatch -> no request
    set_field('old', '1111'); set_field('new', '1234'); set_field('confirm', '5678'); submit()
    check('B mismatch -> no request', reqs['change-pin'] == 0)
    check('B mismatch -> error shown', 'không khớp' in modal_msg())
    # Escape cancels -> no request, modal removed
    pgB.evaluate("()=>{ document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true})); }"); pgB.wait_for_timeout(60)
    check('B Escape closes modal', not modal_open())
    check('B Escape -> no request', reqs['change-pin'] == 0)
    # valid change PIN -> exactly one change-pin request, no prompt
    open_change_pin(); set_field('old', '1111'); set_field('new', '2222'); set_field('confirm', '2222'); submit()
    pgB.wait_for_timeout(150)
    check('B valid change-PIN -> exactly one server request', reqs['change-pin'] == 1)
    check('B change-PIN never called prompt', pgB.evaluate("()=>window.__prompts") == 0)
    check('B change-PIN modal closed on success', not modal_open())
    # no PIN value leaked into storage
    leaked = pgB.evaluate("""()=>{ for(let i=0;i<localStorage.length;i++){ const v=localStorage.getItem(localStorage.key(i))||''; if(v.indexOf('2222')>=0) return true; } return false; }""")
    check('B PIN value not stored in localStorage', leaked == False)
    # cancel button -> no request; focus restored to trigger
    open_change_pin()
    check('B focus moved into modal (first PIN field)', pgB.evaluate("()=>document.activeElement && document.activeElement.id==='pin_old'"))
    pgB.evaluate("()=>{ [...document.querySelectorAll('.pin-modal-actions .secondary-btn')][0].click(); }"); pgB.wait_for_timeout(60)
    check('B cancel closes modal', not modal_open())
    # Finding 2: focus returns to the stable account control (#profileBtn), not <body>.
    check('B cancel restores focus to #profileBtn', pgB.evaluate("()=>document.activeElement===document.getElementById('profileBtn') && !document.querySelector('.pin-modal')"))

    # ---- Finding 1: duplicate-submit guard (Change PIN) ----
    def fill_valid_cp():
        set_field('old', '1111'); set_field('new', '2222'); set_field('confirm', '2222')
    open_change_pin(); fill_valid_cp(); before = reqs['change-pin']
    pgB.evaluate("()=>{ const b=[...document.querySelectorAll('.pin-modal-actions .primary-btn')][0]; b.click(); b.click(); }"); pgB.wait_for_timeout(200)
    check('B change-PIN rapid double-click -> exactly one request', reqs['change-pin'] - before == 1)
    open_change_pin(); fill_valid_cp(); before = reqs['change-pin']
    pgB.evaluate("()=>{ const i=document.getElementById('pin_old'); const e=()=>i.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true})); e(); e(); }"); pgB.wait_for_timeout(200)
    check('B change-PIN rapid double-Enter -> exactly one request', reqs['change-pin'] - before == 1)
    open_change_pin(); fill_valid_cp(); before = reqs['change-pin']
    pgB.evaluate("()=>{ document.getElementById('pin_old').dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true})); [...document.querySelectorAll('.pin-modal-actions .primary-btn')][0].click(); }"); pgB.wait_for_timeout(200)
    check('B change-PIN Enter+click -> exactly one request', reqs['change-pin'] - before == 1)
    open_change_pin(); fill_valid_cp()
    pend = pgB.evaluate("()=>{ const sb=[...document.querySelectorAll('.pin-modal-actions .primary-btn')][0]; const cb=[...document.querySelectorAll('.pin-modal-actions .secondary-btn')][0]; sb.click(); return {submit:sb.disabled, cancel:cb.disabled}; }")
    check('B pending keeps submit+cancel disabled', pend['submit'] == True and pend['cancel'] == True)
    pgB.wait_for_timeout(180)
    # server failure -> guard released -> exactly one retry
    mstate['cp_fail'] = True
    open_change_pin(); fill_valid_cp(); before = reqs['change-pin']; submit()
    check('B change-PIN server fail -> one request', reqs['change-pin'] - before == 1)
    check('B change-PIN server fail -> stays open + error + retryable', modal_open() and modal_msg() != '' and pgB.evaluate("()=>![...document.querySelectorAll('.pin-modal-actions .primary-btn')][0].disabled"))
    mstate['cp_fail'] = False
    before = reqs['change-pin']; submit(); pgB.wait_for_timeout(200)
    check('B change-PIN retry -> exactly one more request + closes', reqs['change-pin'] - before == 1 and not modal_open())
    # validation failure never permanently locks submission
    open_change_pin(); set_field('old', '12'); set_field('new', '2222'); set_field('confirm', '2222'); before = reqs['change-pin']; submit()
    check('B validation fail -> no request, not locked', reqs['change-pin'] - before == 0 and modal_open() and pgB.evaluate("()=>![...document.querySelectorAll('.pin-modal-actions .primary-btn')][0].disabled"))
    fill_valid_cp(); before = reqs['change-pin']; submit(); pgB.wait_for_timeout(200)
    check('B after validation fix -> exactly one request + closes', reqs['change-pin'] - before == 1 and not modal_open())
    # Escape restores focus to #profileBtn
    open_change_pin()
    pgB.evaluate("()=>document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}))"); pgB.wait_for_timeout(60)
    check('B Escape closes + restores focus to #profileBtn', (not modal_open()) and pgB.evaluate("()=>document.activeElement===document.getElementById('profileBtn')"))

    # Delete account: invalid -> no request; server fail -> retryable; rapid double-submit -> one request
    open_delete()
    check('B delete modal opens without prompt', modal_open() and pgB.evaluate("()=>window.__prompts")==0)
    set_field('pin', '9'); submit()
    check('B delete invalid PIN -> no request', reqs['delete-account'] == 0 and modal_open())
    # server failure -> guard released, modal retryable
    mstate['da_fail'] = True
    set_field('pin', '1234'); before = reqs['delete-account']; submit()
    check('B delete server fail -> one request', reqs['delete-account'] - before == 1)
    check('B delete server fail -> stays open + retryable', modal_open() and pgB.evaluate("()=>![...document.querySelectorAll('.pin-modal-actions .primary-btn')][0].disabled"))
    # capture prompt count BEFORE the successful (reloading) submit; assert no prompt ever used
    check('B delete flow never called prompt (pre-reload)', pgB.evaluate("()=>window.__prompts") == 0)
    # rapid double-click on a valid delete -> exactly ONE delete-account request (then reload)
    mstate['da_fail'] = False
    set_field('pin', '1234'); before = reqs['delete-account']
    pgB.evaluate("()=>{ const b=[...document.querySelectorAll('.pin-modal-actions .primary-btn')][0]; b.click(); b.click(); }")
    pgB.wait_for_timeout(350)   # success -> localLogout+alert+reload
    check('B delete rapid double-click -> exactly one request', reqs['delete-account'] - before == 1)

    check('B no console/page errors', len(errsB) == 0)
    ctxB.close()
    b.close()

print(json.dumps({'pass': len(fails) == 0, 'fails': fails, 'errsA': errsA[:4], 'errsB': errsB[:4]}, ensure_ascii=False))
