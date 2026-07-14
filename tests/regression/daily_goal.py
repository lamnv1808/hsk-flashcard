"""Phase 22A — Daily Goal (additive, display-only).

Covers the dailyGoal settings contract, the LOCKED daily-count semantics (unchanged),
Home rendering states, and the goal-aware completion screen. Read-only w.r.t. production:
local-only (Supabase config stubbed empty), localStorage cleared per section.

Daily progress semantics are NOT changed by this phase — this suite characterizes them to
prove the display reads them correctly.
"""
import os, json
from playwright.sync_api import sync_playwright

URL = os.environ.get('HSK_BASE_URL', 'http://localhost:8000') + '/hsk_flashcard_app/'
EMPTY = 'window.SUPABASE_CONFIG={url:"",anonKey:""};'
fails = []
def check(n, c):
    if not c: fails.append(n)

def count(pg):
    return pg.evaluate("()=>(window.HSKMeta && HSKMeta.dailyCounts()[HSKMeta.localDay()])||0")
def grade_current(pg, g):
    pg.evaluate("()=>{ if(!sessionState.flipped) flipCard(); }")
    pg.evaluate("(g)=>gradeCard(g)", g)
def is_complete(pg):
    return pg.evaluate("()=>document.getElementById('completeView').classList.contains('active')")
def reset(pg):
    pg.evaluate('()=>localStorage.clear()'); pg.reload(); pg.wait_for_timeout(300)

def new_page(ctx):
    pg = ctx.new_page(); errs = []
    pg.on('pageerror', lambda e: errs.append('PAGEERR:' + str(e)))
    pg.on('console', lambda m: errs.append('CON:' + m.text) if m.type == 'error' else None)
    pg.goto(URL); pg.wait_for_timeout(300); pg.evaluate('()=>localStorage.clear()'); pg.reload(); pg.wait_for_timeout(300)
    return pg, errs

with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={'width': 1280, 'height': 900})
    ctx.route('**/supabase-config.js', lambda r: r.fulfill(status=200, content_type='application/javascript', body=EMPTY))
    pg, errs = new_page(ctx)

    # ================= Settings contract via the live app =================
    sc = pg.evaluate("""()=>({
        absent: settingsRepo.getDailyGoal(),
        typeIsNumber: typeof settingsRepo.getDailyGoal()==='number'
    })""")
    check('settings absent -> 20', sc['absent'] == 20)
    check('settings returns number', sc['typeIsNumber'])
    # changing the select persists a numeric value and saves exactly once (render never writes)
    sv = pg.evaluate("""()=>{
        const orig=window.saveSettings; window.__saves=0;
        window.saveSettings=function(){window.__saves++; return orig.apply(this,arguments);};
        renderHome(); renderDailyGoal(); renderDailyGoal();       // pure renders -> no writes
        const savesAfterRender=window.__saves;
        const sel=document.getElementById('dailyGoalSelect');
        sel.value='30'; sel.dispatchEvent(new Event('change'));   // one user change
        const savesAfterChange=window.__saves;
        window.saveSettings=orig;
        return { savesAfterRender, savesAfterChange, stored: settings.dailyGoal, goal: settingsRepo.getDailyGoal(), selVal: sel.value };
    }""")
    check('render performs no settings write', sv['savesAfterRender'] == 0)
    check('one save per goal change', sv['savesAfterChange'] == 1)
    check('goal persisted numeric 30', sv['stored'] == 30 and sv['goal'] == 30)
    check('select reflects goal 30', sv['selVal'] == '30')

    # ================= LOCKED counting semantics (display reads these) =================
    reset(pg)
    pg.evaluate("()=>{ progress={}; save(); document.getElementById('sessionSize').value='10'; }")
    pg.evaluate("()=>startStudy(['HSK1'])"); pg.wait_for_timeout(120)
    ids = pg.evaluate("()=>session.slice(0,6).map(c=>c.id)")
    grade_current(pg, 'again');  check('again counts (1)', count(pg) == 1)
    grade_current(pg, 'hard');   check('hard counts (2)',  count(pg) == 2)
    grade_current(pg, 'good');   check('good counts (3)',  count(pg) == 3)
    grade_current(pg, 'easy');   check('easy counts (4)',  count(pg) == 4)   # now at index 4
    pg.evaluate("()=>skipCard()"); check('skip does not count (4)', count(pg) == 4)  # index 5
    # regrade an already-counted card (index 3) -> no double count
    pg.evaluate("()=>{ swipePrev(); swipePrev(); }"); pg.wait_for_timeout(30)  # index 3
    check('at a previously graded card', pg.evaluate("()=>sessionState.currentIndex")==3)
    grade_current(pg, 'again'); check('regrade does not double-count (4)', count(pg) == 4)  # index 4
    # a brand-new card (index 4, was skipped, never graded) -> counts
    grade_current(pg, 'good'); check('new card counts (5)', count(pg) == 5)  # index 5
    # undo (skip a graded card) leaves the monotonic count unchanged
    pg.evaluate("()=>swipePrev()"); pg.wait_for_timeout(30)                  # index 4 (graded good)
    pg.evaluate("()=>skipCard()"); check('undo does not decrement (5)', count(pg) == 5)

    # explicit session (Weak/Bookmark path) contributes; a fresh id increments, a repeat does not
    fresh = pg.evaluate("()=>cards.filter(c=>c.level==='HSK2')[0].id")
    pg.evaluate("(id)=>HSK_APP.startSession([id])", fresh); pg.wait_for_timeout(80)
    grade_current(pg, 'good'); check('explicit session counts (6)', count(pg) == 6)
    pg.evaluate("(id)=>HSK_APP.startSession([id])", fresh); pg.wait_for_timeout(80)
    grade_current(pg, 'easy'); check('same card again same day -> no double (6)', count(pg) == 6)

    # Test Mode does NOT contribute (spy on the only writer + compare the count)
    tm = pg.evaluate("""()=>{
        const before=(HSKMeta.dailyCounts()[HSKMeta.localDay()])||0;
        const orig=HSKMeta.recordDailyLearn; window.__rdl=0;
        HSKMeta.recordDailyLearn=function(){window.__rdl++; return orig.apply(this,arguments);};
        document.getElementById('openTestBtn').click();
        const mix=document.getElementById('testMix'); mix.checked=true; mix.dispatchEvent(new Event('change'));
        document.getElementById('testStartBtn').click();
        return { before, quiz: document.getElementById('testQuizView').classList.contains('active') };
    }""")
    pg.wait_for_timeout(120)
    if tm['quiz']:
        pg.evaluate("()=>{ const o=document.querySelector('#testOptions .test-option'); if(o) o.click(); }"); pg.wait_for_timeout(60)
        pg.evaluate("()=>{ const n=document.getElementById('testNextBtn'); if(n && !n.hidden) n.click(); }"); pg.wait_for_timeout(60)
    tmres = pg.evaluate("()=>({ rdl: window.__rdl, now: (HSKMeta.dailyCounts()[HSKMeta.localDay()])||0 })")
    check('Test Mode entered quiz', tm['quiz'])
    check('Test Mode does not call recordDailyLearn', tmres['rdl'] == 0)
    check('Test Mode leaves daily count unchanged (6)', tmres['now'] == 6)

    # ================= Home rendering states =================
    reset(pg)
    def home_dg(pg):
        return pg.evaluate("""()=>{
            const bar=document.getElementById('dailyGoalBar');
            return { text: document.getElementById('dailyGoalText').textContent,
                     fill: document.getElementById('dailyGoalBarFill').style.width,
                     sel: document.getElementById('dailyGoalSelect').value,
                     amax: bar.getAttribute('aria-valuemax'), anow: bar.getAttribute('aria-valuenow'),
                     amin: bar.getAttribute('aria-valuemin'), role: bar.getAttribute('role'),
                     atext: bar.getAttribute('aria-valuetext') };
        }""")
    pg.evaluate("()=>{ progress={}; if(settings.dailyCounts) delete settings.dailyCounts; renderHome(); }")
    z = home_dg(pg)
    check('home 0/20 text', z['text'] == '0/20 thẻ'); check('home 0% fill', z['fill'] == '0%')
    check('home role progressbar', z['role'] == 'progressbar'); check('home aria min 0', z['amin'] == '0')
    check('home aria max 20', z['amax'] == '20'); check('home aria now 0', z['anow'] == '0')
    check('home aria text 0/20', z['atext'] == '0 trên 20 thẻ')
    # partial (goal 20, learned 17 -> valid capped range, uncapped valuetext, no completion)
    pg.evaluate("()=>{ settings.dailyCounts={[HSKMeta.localDay()]:17}; settings.dailyGoal=20; renderHome(); }")
    pr = home_dg(pg)
    check('home partial 17/20', pr['text'] == '17/20 thẻ'); check('home partial 85% fill', pr['fill'] == '85%')
    check('home partial aria now 17', pr['anow'] == '17'); check('home partial aria max 20', pr['amax'] == '20')
    check('home partial aria text (no completion)', pr['atext'] == '17 trên 20 thẻ')
    # reached (goal 10, learned 10 -> valuenow==max, completion in valuetext)
    pg.evaluate("()=>{ settings.dailyCounts={[HSKMeta.localDay()]:10}; settings.dailyGoal=10; renderHome(); }")
    rc = home_dg(pg)
    check('home reached 10/10', rc['text'] == '10/10 thẻ'); check('home reached 100% fill', rc['fill'] == '100%')
    check('home select 10', rc['sel'] == '10'); check('home reached aria max 10', rc['amax'] == '10')
    check('home reached aria now 10', rc['anow'] == '10')
    check('home reached aria text completion', rc['atext'] == '10 trên 10 thẻ, đã hoàn thành mục tiêu')
    # exceeded (goal 20, learned 25 -> real value visible, bar capped, aria capped, uncapped valuetext)
    pg.evaluate("()=>{ settings.dailyCounts={[HSKMeta.localDay()]:25}; settings.dailyGoal=20; renderHome(); }")
    ex = home_dg(pg)
    check('home exceeded 25/20 (visible uncapped)', ex['text'] == '25/20 thẻ')
    check('home exceeded bar capped 100%', ex['fill'] == '100%')
    check('home exceeded aria now capped to 20', ex['anow'] == '20')
    check('home exceeded aria max 20', ex['amax'] == '20')
    check('home exceeded aria text uncapped + completion', ex['atext'] == '25 trên 20 thẻ, đã hoàn thành mục tiêu')

    # ---- DOM placement (Finding 1) + single-ID contract ----
    dom = pg.evaluate("""()=>{
        const F=Node.DOCUMENT_POSITION_FOLLOWING;
        const hero=document.querySelector('#homeView .hero');
        const panel=document.getElementById('dailyGoalPanel');
        const chon=[...document.querySelectorAll('#homeView .section-title h3')].find(h=>h.textContent.trim()==='Chọn bộ học');
        const chonSection=chon?chon.closest('.section-title'):null;
        const ids=['dailyGoalPanel','dailyGoalSelect','dailyGoalText','dailyGoalBar','dailyGoalBarFill'];
        const counts={}; ids.forEach(id=>counts[id]=document.querySelectorAll('#'+id).length);
        return {
            panelAfterHero: !!(hero && panel && (hero.compareDocumentPosition(panel)&F)),
            panelBeforeChon: !!(panel && chonSection && (panel.compareDocumentPosition(chonSection)&F)),
            counts
        };
    }""")
    check('panel is after the hero', dom['panelAfterHero'])
    check('panel is before "Chọn bộ học"', dom['panelBeforeChon'])
    for _id in ['dailyGoalPanel','dailyGoalSelect','dailyGoalText','dailyGoalBar','dailyGoalBarFill']:
        check('exactly one #' + _id, dom['counts'][_id] == 1)

    # ---- Reduced motion (Finding 3): the fill transition is disabled under reduce ----
    rm_ctx = b.new_context(viewport={'width': 390, 'height': 844}, reduced_motion='reduce')
    rm_ctx.route('**/supabase-config.js', lambda r: r.fulfill(status=200, content_type='application/javascript', body=EMPTY))
    rm_pg = rm_ctx.new_page(); rm_pg.goto(URL); rm_pg.wait_for_timeout(300)
    rm = rm_pg.evaluate("()=>getComputedStyle(document.getElementById('dailyGoalBarFill')).transitionDuration")
    check('reduced-motion disables dg-bar fill transition', rm in ('0s', '0'))
    rm_ctx.close()
    # invalid stored value -> fallback 20 after reload
    pg.evaluate("""()=>{ const s=JSON.parse(localStorage.getItem('hsk_flashcard_settings_v2')||'{}'); s.dailyGoal=15; localStorage.setItem('hsk_flashcard_settings_v2', JSON.stringify(s)); }""")
    pg.reload(); pg.wait_for_timeout(300)
    inv = pg.evaluate("()=>({ goal: settingsRepo.getDailyGoal(), sel: document.getElementById('dailyGoalSelect').value })")
    check('invalid stored 15 -> goal 20', inv['goal'] == 20); check('invalid stored -> select 20', inv['sel'] == '20')
    # local-only persistence across reload
    pg.evaluate("()=>{ const sel=document.getElementById('dailyGoalSelect'); sel.value='50'; sel.dispatchEvent(new Event('change')); }")
    pg.reload(); pg.wait_for_timeout(300)
    per = pg.evaluate("()=>({ goal: settingsRepo.getDailyGoal(), sel: document.getElementById('dailyGoalSelect').value })")
    check('local-only reload persists goal 50', per['goal'] == 50 and per['sel'] == '50')
    # account A -> B -> A isolation (provider swap mirrors account switch: live blob replaced)
    iso = pg.evaluate("""()=>{
        const mk=HSKUtil.createSettingsRepository;
        const A={dailyGoal:50}, B={dailyGoal:10}; const live={who:A};
        const r=mk(()=>live.who);
        const a1=r.getDailyGoal(); live.who=B; const b=r.getDailyGoal(); live.who=A; const a2=r.getDailyGoal();
        return { a1, b, a2 };
    }""")
    check('isolation A=50', iso['a1'] == 50); check('isolation B=10', iso['b'] == 10); check('isolation back-to-A=50', iso['a2'] == 50)

    # ================= Completion (goal-aware, no duplicate) =================
    reset(pg)
    pg.evaluate("()=>{ progress={}; save(); document.getElementById('sessionSize').value='10'; }")
    pg.evaluate("()=>{ const sel=document.getElementById('dailyGoalSelect'); sel.value='20'; sel.dispatchEvent(new Event('change')); }")
    pg.evaluate("()=>startStudy(['HSK1'])"); pg.wait_for_timeout(120)
    for _ in range(10):
        if is_complete(pg): break
        grade_current(pg, 'good')
    hb = pg.evaluate("()=>document.getElementById('completeHabit').innerHTML")
    learned_now = count(pg)
    check('completion reached', is_complete(pg))
    check('no duplicate "Đã học hôm nay"', hb.count('Đã học hôm nay') == 1)
    check('completion shows N/G', ('%d/20' % learned_now) in hb)
    check('completion has goal progressbar', 'complete-goalbar' in hb and 'role="progressbar"' in hb)
    check('acknowledgment hidden below goal', 'complete-goal-done' not in hb)  # 10 < 20
    # Phase 21 gating intact: level session with due remaining -> continue shown
    check('P21 continue still shown (levels+due)', pg.evaluate("()=>document.getElementById('continueStudyBtn').hidden")==False)
    # reached/exceeded-goal acknowledgment + valid capped completion ARIA: force learned > goal,
    # finish an explicit session (fresh2 grade increments today's count to >20).
    pg.evaluate("()=>{ settings.dailyCounts={[HSKMeta.localDay()]:25}; settings.dailyGoal=20; }")
    fresh2 = pg.evaluate("()=>cards.filter(c=>c.level==='HSK3')[0].id")
    pg.evaluate("(id)=>HSK_APP.startSession([id])", fresh2); pg.wait_for_timeout(80)
    grade_current(pg, 'good'); pg.wait_for_timeout(60)
    hb2 = pg.evaluate("()=>document.getElementById('completeHabit').innerHTML")
    learned2 = count(pg)  # >= 25 (was 25, fresh2 is new -> counted)
    check('acknowledgment visible at/above goal', 'complete-goal-done' in hb2 and 'Đã hoàn thành mục tiêu hôm nay.' in hb2)
    check('explicit continue hidden', pg.evaluate("()=>document.getElementById('continueStudyBtn').hidden")==True)
    check('explicit: single today item', hb2.count('Đã học hôm nay') == 1)
    check('completion shows uncapped learned/20', ('%d/20' % learned2) in hb2)
    cbar = pg.evaluate("""()=>{ const el=document.querySelector('#completeHabit .complete-goalbar');
        return el ? { amax: el.getAttribute('aria-valuemax'), anow: el.getAttribute('aria-valuenow'),
                      amin: el.getAttribute('aria-valuemin'), atext: el.getAttribute('aria-valuetext'),
                      fill: el.querySelector('span').style.width } : null; }""")
    check('completion goalbar present', cbar is not None)
    check('completion aria max = goal 20', cbar['amax'] == '20')
    check('completion aria now capped to 20', cbar['anow'] == '20')
    check('completion aria min 0', cbar['amin'] == '0')
    check('completion aria text uncapped + completion', cbar['atext'] == ('%d trên 20 thẻ, đã hoàn thành mục tiêu' % learned2))
    check('completion bar capped 100%', cbar['fill'] == '100%')

    check('no console/page errors', len(errs) == 0)
    ctx.close(); b.close()

print(json.dumps({'pass': len(fails) == 0, 'fails': fails, 'errs': errs[:5]}, ensure_ascii=False))
