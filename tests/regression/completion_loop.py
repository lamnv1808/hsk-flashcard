"""Phase 21 — rich end-of-session completion screen + "Học tiếp" loop.

Characterizes the additive completion UX:
  - grade breakdown counts (again/hard/good/easy/skip, and ungraded if any)
  - due-remaining, today-learned, streak display
  - continue-button gating (levels+due -> shown; levels+0-due -> hidden + soft msg;
    explicit session -> hidden)
  - continue behavior (reuses startStudy path, same levels, size respected, next card
    front-side / no answer leak)

Read-only w.r.t. production: local-only (Supabase config stubbed empty), localStorage cleared.
"""
import os, json
from playwright.sync_api import sync_playwright

URL = os.environ.get('HSK_BASE_URL', 'http://localhost:8000') + '/hsk_flashcard_app/'
EMPTY = 'window.SUPABASE_CONFIG={url:"",anonKey:""};'
fails = []
def check(n, c):
    if not c: fails.append(n)

def is_complete(pg):
    return pg.evaluate("()=>document.getElementById('completeView').classList.contains('active')")
def is_study(pg):
    return pg.evaluate("()=>document.getElementById('studyView').classList.contains('active')")
def cb(pg, cls):
    return pg.evaluate("(cls)=>{const e=document.querySelector('#completeBreakdown .'+cls+' strong');return e?e.textContent:null;}", cls)
def cont_hidden(pg):
    return pg.evaluate("()=>document.getElementById('continueStudyBtn').hidden")
def cont_text(pg):
    return pg.evaluate("()=>document.getElementById('continueStudyBtn').textContent")
def habit_html(pg):
    return pg.evaluate("()=>document.getElementById('completeHabit').innerHTML")

def flip_grade(pg, g):
    pg.evaluate("()=>{ if(!sessionState.flipped) flipCard(); }")
    pg.evaluate("(g)=>gradeCard(g)", g)
def do_skip(pg):
    pg.evaluate("()=>skipCard()")

def drive_all_good(pg, maxn=80):
    for _ in range(maxn):
        if is_complete(pg): return
        flip_grade(pg, 'good')

with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={'width': 1280, 'height': 900})
    ctx.route('**/supabase-config.js', lambda r: r.fulfill(status=200, content_type='application/javascript', body=EMPTY))
    pg = ctx.new_page(); errs = []
    pg.on('pageerror', lambda e: errs.append('PAGEERR:' + str(e)))
    pg.on('console', lambda m: errs.append('CON:' + m.text) if m.type == 'error' else None)
    pg.goto(URL); pg.wait_for_timeout(300); pg.evaluate('()=>localStorage.clear()'); pg.reload(); pg.wait_for_timeout(300)

    # ---------- Test 1: level-based session, known grade mix, due remaining ----------
    pg.evaluate("()=>{ progress={}; save(); }")
    pg.evaluate("()=>{ document.getElementById('sessionSize').value='10'; }")
    pg.evaluate("()=>startStudy(['HSK1'])"); pg.wait_for_timeout(120)
    check('T1 session size 10', pg.evaluate("()=>session.length")==10)
    seq = ['again','hard','good','easy','skip','good','good','easy','hard','again']
    for a in seq:
        if a == 'skip': do_skip(pg)
        else: flip_grade(pg, a)
    pg.wait_for_timeout(60)
    check('T1 reached completion', is_complete(pg))
    # breakdown (again2 hard2 good3 easy2 skip1)
    check('T1 again=2', cb(pg,'cb-again')=='2')
    check('T1 hard=2', cb(pg,'cb-hard')=='2')
    check('T1 good=3', cb(pg,'cb-good')=='3')
    check('T1 easy=2', cb(pg,'cb-easy')=='2')
    check('T1 skip=1', cb(pg,'cb-skip')=='1')
    # summary sentence preserved (10 seen, 9 graded, 5 good, 1 skipped)
    ctext = pg.evaluate("()=>document.getElementById('completeText').textContent")
    check('T1 summary text', ('10 th' in ctext and 'chấm điểm 9' in ctext and 'nhớ tốt 5' in ctext and 'bỏ qua 1' in ctext))
    # due-remaining shown and matches an independent dueCards read (>0)
    due = pg.evaluate("()=>dueCards(['HSK1']).length")
    check('T1 due remaining > 0', due > 0)
    hh = habit_html(pg)
    check('T1 habit shows due-remaining number', str(due) in hh and 'Còn cần ôn' in hh)
    # Phase 22A: the "today" item is goal-aware (learned/goal); fresh localStorage -> goal 20.
    check('T1 habit shows learned today = 9/20', 'Đã học hôm nay' in hh and '9/20' in hh)
    check('T1 habit shows streak = 1', 'Chuỗi ngày' in hh and '>1<' in hh)
    # continue shown, N = min(size, due) = 10
    check('T1 continue visible', cont_hidden(pg)==False)
    check('T1 continue text = Học tiếp 10 thẻ', cont_text(pg)=='Học tiếp 10 thẻ')
    check('T1 no all-clear msg', 'complete-allclear' not in hh)

    # ---------- Test 4: continue behavior (reuses startStudy path) ----------
    pg.evaluate("()=>document.getElementById('continueStudyBtn').click()"); pg.wait_for_timeout(120)
    check('T4 back in study view', is_study(pg))
    check('T4 next card front-side (not flipped)', pg.evaluate("()=>sessionState.flipped")==False)
    check('T4 no .flipped class (no answer leak)', pg.evaluate("()=>!document.getElementById('flashcard').classList.contains('flipped')"))
    check('T4 card index 1', pg.evaluate("()=>sessionState.currentIndex")==0)
    check('T4 same levels (HSK1)', pg.evaluate("()=>studySource && studySource.type==='levels' && studySource.levels.join(',')==='HSK1'"))
    check('T4 size respected (<=10)', pg.evaluate("()=>session.length")<=10)
    check('T4 front shows a session word', pg.evaluate("()=>document.getElementById('word').textContent")==pg.evaluate("()=>session[0].word"))

    # ---------- Test 2: explicit session -> no same-level continue ----------
    ids = pg.evaluate("()=>cards.filter(c=>c.level==='HSK1').slice(0,3).map(c=>c.id)")
    pg.evaluate("(ids)=>HSK_APP.startSession(ids)", ids); pg.wait_for_timeout(100)
    check('T2 explicit session started', is_study(pg) and pg.evaluate("()=>studySource.type")=='explicit')
    drive_all_good(pg)
    check('T2 reached completion', is_complete(pg))
    check('T2 continue HIDDEN for explicit', cont_hidden(pg)==True)
    check('T2 home button present', pg.evaluate("()=>!!document.getElementById('homeBtn')"))
    check('T2 breakdown rendered', cb(pg,'cb-good') is not None)

    # ---------- Test 3: level session, no due remaining -> soft msg, no continue ----------
    pg.evaluate("""()=>{ progress={}; cards.filter(c=>c.level==='HSK1').forEach(function(c){
        progress[c.id]={due:'2999-01-01',interval:30,reps:3,correct:3,attempts:3}; }); save(); }""")
    pg.evaluate("()=>{ document.getElementById('sessionSize').value='10'; }")
    pg.evaluate("()=>startStudy(['HSK1'])"); pg.wait_for_timeout(120)
    drive_all_good(pg)  # grade whatever the session contains -> all HSK1 stay future-due
    check('T3 reached completion', is_complete(pg))
    due3 = pg.evaluate("()=>dueCards(['HSK1']).length")
    check('T3 due remaining == 0', due3 == 0)
    check('T3 continue HIDDEN when 0 due', cont_hidden(pg)==True)
    check('T3 soft all-clear message shown', 'complete-allclear' in habit_html(pg))
    check('T3 home button is primary', pg.evaluate("()=>document.getElementById('homeBtn').className")=='primary-btn')

    check('no console/page errors', len(errs) == 0)
    ctx.close(); b.close()

print(json.dumps({'pass': len(fails) == 0, 'fails': fails, 'errs': errs[:5]}, ensure_ascii=False))
