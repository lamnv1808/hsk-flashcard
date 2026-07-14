"""Phase 22B — Streak Semantics Correction.

A streak "day" is now activated by the FIRST unique Study card graded during the learner's local
calendar day (owned by metadata.js recordDailyLearn), NOT by starting a session. Local-day basis
(HSKUtil.date.localDay), additive settings.lastLearnDay anchor, legacy settings.lastStudy left inert,
one settings save, lazy migration that preserves an existing streak.

Read-only w.r.t. production: local-only (Supabase config stubbed empty), localStorage cleared.
"""
import os, json
from playwright.sync_api import sync_playwright

URL = os.environ.get('HSK_BASE_URL', 'http://localhost:8000') + '/hsk_flashcard_app/'
EMPTY = 'window.SUPABASE_CONFIG={url:"",anonKey:""};'
fails = []
def check(n, c):
    if not c: fails.append(n)

def new_page(ctx):
    pg = ctx.new_page(); errs = []
    pg.on('pageerror', lambda e: errs.append('PAGEERR:' + str(e)))
    pg.on('console', lambda m: errs.append('CON:' + m.text) if m.type == 'error' else None)
    pg.goto(URL); pg.wait_for_timeout(300); pg.evaluate('()=>localStorage.clear()'); pg.reload(); pg.wait_for_timeout(300)
    return pg, errs

def reset(pg):
    pg.evaluate('()=>localStorage.clear()'); pg.reload(); pg.wait_for_timeout(300)

def start(pg, size='10'):
    pg.evaluate("(s)=>{ progress={}; save(); document.getElementById('sessionSize').value=s; startStudy(['HSK1']); }", size)
    pg.wait_for_timeout(120)

def grade_current(pg, g):
    pg.evaluate("()=>{ if(!sessionState.flipped) flipCard(); }")
    pg.evaluate("(g)=>gradeCard(g)", g)

def streak(pg):
    return pg.evaluate("()=>{ const s=HSK_APP.getSettings(); return {st: (s.streak===undefined?null:s.streak), lld:(s.lastLearnDay===undefined?null:s.lastLearnDay), lastStudy:(s.lastStudy===undefined?null:s.lastStudy)}; }")

def days(pg):
    return pg.evaluate("""()=>{ const L=window.HSKUtil.date.localDay;
        const y=new Date(); y.setDate(y.getDate()-1);
        const o=new Date(); o.setDate(o.getDate()-5);
        const f=new Date(); f.setDate(f.getDate()+3);
        return { today:L(), yesterday:L(y), older:L(o), future:L(f) }; }""")

# Force the "new local day" activation branch and seed anchor/streak, then grade one new card.
def transition(pg, lastLearnDay, streak_val):
    reset(pg); start(pg)
    pg.evaluate("""(a)=>{ const s=HSK_APP.getSettings();
        if(a.lld===null) delete s.lastLearnDay; else s.lastLearnDay=a.lld;
        if(a.st===null) delete s.streak; else s.streak=a.st;
        s.todayLearn={day:'2000-01-01', ids:[]};   // stale -> next grade is 'first of a new local day'
        if(s.dailyCounts) delete s.dailyCounts; }""", {'lld': lastLearnDay, 'st': streak_val})
    grade_current(pg, 'good')
    return streak(pg)

with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={'width': 1280, 'height': 900})
    ctx.route('**/supabase-config.js', lambda r: r.fulfill(status=200, content_type='application/javascript', body=EMPTY))
    pg, errs = new_page(ctx)
    D = days(pg)

    # ================= Trigger behavior (start / skip / test / exit do NOT change streak) =================
    reset(pg); start(pg)
    s = streak(pg)
    check('level start: streak unchanged (absent)', s['st'] in (None, 0)); check('level start: no anchor', s['lld'] is None)
    reset(pg)
    fid = pg.evaluate("()=>cards.filter(c=>c.level==='HSK1')[0].id")
    pg.evaluate("(id)=>{ progress={}; save(); HSK_APP.startSession([id]); }", fid); pg.wait_for_timeout(100)
    s = streak(pg); check('explicit start: streak unchanged', s['st'] in (None, 0)); check('explicit start: no anchor', s['lld'] is None)
    # immediate exit
    reset(pg); start(pg); pg.evaluate("()=>exitStudy()"); pg.wait_for_timeout(60)
    s = streak(pg); check('immediate exit: streak unchanged', s['st'] in (None, 0)); check('immediate exit: no anchor', s['lld'] is None)
    # skip-only
    reset(pg); start(pg)
    for _ in range(3): pg.evaluate("()=>skipCard()"); pg.wait_for_timeout(20)
    s = streak(pg); check('skip-only: streak unchanged', s['st'] in (None, 0)); check('skip-only: no anchor', s['lld'] is None)
    # Test Mode does not change streak
    reset(pg)
    pg.evaluate("""()=>{ document.getElementById('openTestBtn').click();
        const m=document.getElementById('testMix'); m.checked=true; m.dispatchEvent(new Event('change'));
        document.getElementById('testStartBtn').click(); }"""); pg.wait_for_timeout(120)
    inquiz = pg.evaluate("()=>document.getElementById('testQuizView').classList.contains('active')")
    if inquiz:
        pg.evaluate("()=>{ const o=document.querySelector('#testOptions .test-option'); if(o) o.click(); }"); pg.wait_for_timeout(50)
        pg.evaluate("()=>{ const n=document.getElementById('testNextBtn'); if(n && !n.hidden) n.click(); }"); pg.wait_for_timeout(50)
    s = streak(pg); check('Test Mode entered', inquiz); check('Test Mode: streak unchanged', s['st'] in (None, 0)); check('Test Mode: no anchor', s['lld'] is None)

    # ================= First qualifying grade activates the day (each of the 4 grades) =================
    for g in ['again', 'hard', 'good', 'easy']:
        reset(pg); start(pg); grade_current(pg, g)
        s = streak(pg)
        check('first %s -> streak 1' % g, s['st'] == 1)
        check('first %s -> anchor today' % g, s['lld'] == D['today'])

    # second card same day -> unchanged; regrade/dup -> unchanged
    reset(pg); start(pg)
    grade_current(pg, 'good'); s1 = streak(pg)
    grade_current(pg, 'good'); s2 = streak(pg)   # 2nd distinct card, same day
    check('second card same day: streak stays 1', s1['st'] == 1 and s2['st'] == 1)
    pg.evaluate("()=>swipePrev()"); pg.wait_for_timeout(30)   # back to card index 0 (already counted)
    grade_current(pg, 'again'); s3 = streak(pg)
    check('regrade same card: streak unchanged', s3['st'] == 1)

    # explicit-session grade qualifies
    reset(pg)
    eid = pg.evaluate("()=>cards.filter(c=>c.level==='HSK1')[0].id")
    pg.evaluate("(id)=>{ progress={}; save(); HSK_APP.startSession([id]); }", eid); pg.wait_for_timeout(100)
    grade_current(pg, 'good'); s = streak(pg)
    check('explicit grade -> streak 1', s['st'] == 1 and s['lld'] == D['today'])

    # "Học tiếp" same day -> unchanged
    reset(pg); start(pg)
    for _ in range(10):
        if pg.evaluate("()=>document.getElementById('completeView').classList.contains('active')"): break
        grade_current(pg, 'good')
    after_first = streak(pg)
    pg.evaluate("()=>document.getElementById('continueStudyBtn').click()"); pg.wait_for_timeout(120)  # Keep Going
    grade_current(pg, 'good'); after_kg = streak(pg)
    check('Keep Going same day: streak stays 1', after_first['st'] == 1 and after_kg['st'] == 1)

    # ================= Sequence / anchor transitions =================
    r = transition(pg, None, None);        check('fresh (no anchor,no streak) -> 1', r['st'] == 1 and r['lld'] == D['today'])
    r = transition(pg, None, 5);           check('migration: absent anchor preserves streak 5', r['st'] == 5 and r['lld'] == D['today'])
    r = transition(pg, D['yesterday'], 5); check('yesterday -> +1 (6)', r['st'] == 6 and r['lld'] == D['today'])
    r = transition(pg, D['today'], 5);     check('already today -> unchanged (5)', r['st'] == 5 and r['lld'] == D['today'])
    r = transition(pg, D['older'], 5);     check('older -> reset to 1', r['st'] == 1 and r['lld'] == D['today'])
    r = transition(pg, D['future'], 5);    check('future anchor -> reset to 1 (safe)', r['st'] == 1)
    r = transition(pg, 'garbage', 5);      check('corrupt anchor -> reset to 1', r['st'] == 1)
    r = transition(pg, None, 0);           check('streak 0 + no anchor -> 1', r['st'] == 1)
    r = transition(pg, D['yesterday'], -3);check('corrupt streak (-3) normalizes -> +1 = 1', r['st'] == 1)
    r = transition(pg, D['yesterday'], 'x');check('corrupt streak (str) normalizes -> +1 = 1', r['st'] == 1)
    r = transition(pg, D['yesterday'], 2.9);check('float streak floors -> 2+1 = 3', r['st'] == 3)

    # lastStudy (legacy) is never written by the new path
    reset(pg); start(pg); grade_current(pg, 'good')
    check('legacy lastStudy remains untouched (absent)', streak(pg)['lastStudy'] is None)

    # ================= Save / dirty count =================
    reset(pg); start(pg)   # startStudy already did its own (pre-existing) size/levels save
    sc = pg.evaluate("""()=>{ const orig=window.saveSettings; window.__saves=0;
        window.saveSettings=function(){window.__saves++; return orig.apply(this,arguments);};
        if(!sessionState.flipped) flipCard(); gradeCard('good');           // first qualifying grade
        const afterFirst=window.__saves;
        swipePrev(); if(!sessionState.flipped) flipCard(); gradeCard('good'); // regrade same card (dup)
        const afterDup=window.__saves;
        window.saveSettings=orig;
        return { afterFirst, afterDup }; }""")
    check('first qualifying grade: exactly one settings save', sc['afterFirst'] == 1)
    check('same-card regrade: no additional settings save', sc['afterDup'] == 1)

    # ================= Persistence across reload (offline-shaped: localStorage only) =================
    reset(pg); start(pg); grade_current(pg, 'good')
    pg.reload(); pg.wait_for_timeout(300)
    s = streak(pg)
    check('reload persists streak 1', s['st'] == 1); check('reload persists anchor', s['lld'] == D['today'])

    # ================= Account isolation (streak lives in the account-scoped settings blob) =================
    iso = pg.evaluate("""()=>{ const s=HSK_APP.getSettings();
        return { inBlob: ('streak' in s) && ('lastLearnDay' in s) }; }""")
    check('streak+anchor stored in the (namespaced) settings blob', iso['inBlob'])

    # ================= Date-arithmetic property (local yesterday: no UTC serialization) =================
    dp = pg.evaluate("""()=>{ const L=window.HSKUtil.date.localDay;
        function yFrom(y,m,d){ const dt=new Date(y,m-1,d,12,0,0); dt.setDate(dt.getDate()-1); return L(dt); }
        return {
          month: yFrom(2025,3,1)===L(new Date(2025,1,28,12)),   // Mar 1 -> Feb 28
          leap:  yFrom(2024,3,1)===L(new Date(2024,1,29,12)),   // 2024 leap -> Feb 29
          year:  yFrom(2025,1,1)===L(new Date(2024,11,31,12)),  // Jan 1 -> Dec 31
          mid:   yFrom(2025,5,15)===L(new Date(2025,4,14,12)),  // ordinary
          leapMar1IsFeb29: yFrom(2024,3,1)==='2024-02-29' }; }""")
    for k in ['month', 'leap', 'year', 'mid', 'leapMar1IsFeb29']:
        check('date-arith:' + k, dp[k])

    check('no console/page errors', len(errs) == 0)
    ctx.close(); b.close()

print(json.dumps({'pass': len(fails) == 0, 'fails': fails, 'errs': errs[:5]}, ensure_ascii=False))
