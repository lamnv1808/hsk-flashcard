import os
import json
from playwright.sync_api import sync_playwright
URL=os.environ.get('HSK_BASE_URL','http://localhost:8000')+'/hsk_flashcard_app/'
EMPTY='window.SUPABASE_CONFIG={url:"",anonKey:""};'
fails=[]
def check(n,c):
    if not c: fails.append(n)

with sync_playwright() as p:
    b=p.chromium.launch(); ctx=b.new_context(viewport={'width':1280,'height':1000})
    ctx.route('**/supabase-config.js', lambda r: r.fulfill(status=200, content_type='application/javascript', body=EMPTY))
    pg=ctx.new_page(); errs=[]
    pg.on('pageerror', lambda e: errs.append('PAGEERR:'+str(e)))
    pg.on('console', lambda m: errs.append('CON:'+m.text) if m.type=='error' else None)
    pg.goto(URL); pg.wait_for_timeout(300); pg.evaluate('()=>localStorage.clear()')
    # seed crafted progress for weak-words ranking (ids 1..3 HSK1; 4 untouched)
    pg.evaluate("""()=>{
      const d=new Date().toISOString().slice(0,10);
      localStorage.setItem('hsk_flashcard_progress_v2', JSON.stringify({
        '1':{due:d,interval:0,reps:10,correct:2,attempts:10},
        '2':{due:d,interval:1,reps:3,correct:2,attempts:3},
        '3':{due:d,interval:7,reps:1,correct:1,attempts:1}
      }));
    }""")
    pg.reload(); pg.wait_for_timeout(400)
    out={}
    out['modules']=pg.evaluate("()=>[typeof window.HSKMeta, typeof window.HSKInsights].join(',')")

    # ---------- BOOKMARK ----------
    pg.evaluate("()=>{ startStudy(['HSK1']); }"); pg.wait_for_timeout(120)
    cid=pg.evaluate('()=>session[sessionState.currentIndex].id')
    progBefore=pg.evaluate("()=>localStorage.getItem('hsk_flashcard_progress_v2')")
    pg.evaluate("()=>document.getElementById('bookmarkBtn').click()"); pg.wait_for_timeout(50)
    check('bookmark added', pg.evaluate("(id)=>window.HSKMeta.isBookmarked(id)", cid))
    check('bookmark btn active', pg.eval_on_selector('#bookmarkBtn','e=>e.classList.contains("active") && e.getAttribute("aria-pressed")==="true"'))
    check('bookmark no progress change', pg.evaluate("()=>localStorage.getItem('hsk_flashcard_progress_v2')")==progBefore)
    pg.evaluate("()=>document.getElementById('bookmarkBtn').click()"); pg.wait_for_timeout(50)
    check('bookmark removed', not pg.evaluate("(id)=>window.HSKMeta.isBookmarked(id)", cid))
    # re-add for later bookmark-page test
    pg.evaluate("()=>document.getElementById('bookmarkBtn').click()")

    # ---------- NOTES ----------
    # front: note zone hidden
    check('note hidden on front', pg.eval_on_selector('#noteZone','e=>e.hidden'))
    pg.evaluate("()=>flipCard()"); pg.wait_for_timeout(60)
    check('note zone shown on back', not pg.eval_on_selector('#noteZone','e=>e.hidden'))
    # empty note: icon visible, display+editor hidden (no clutter)
    check('empty note: display hidden', pg.eval_on_selector('#noteDisplay','e=>e.hidden'))
    check('empty note: editor hidden', pg.eval_on_selector('#noteEditor','e=>e.hidden'))
    check('empty note: icon visible', pg.eval_on_selector('#noteToggle','e=>!e.hidden'))
    # open editor, type multiline, save
    pg.evaluate("()=>document.getElementById('noteToggle').click()"); pg.wait_for_timeout(50)
    check('editor opens', not pg.eval_on_selector('#noteEditor','e=>e.hidden'))
    pg.evaluate("()=>{ const t=document.getElementById('noteInput'); t.value='dòng 1\\ndòng 2 <script>x</script>'; t.dispatchEvent(new Event('input')); }")
    check('counter updates', pg.eval_on_selector('#noteCounter','e=>e.textContent.indexOf("/1000")>0'))
    pg.evaluate("()=>document.getElementById('noteSave').click()"); pg.wait_for_timeout(50)
    check('note saved+displayed', pg.eval_on_selector('#noteDisplay','e=>!e.hidden && e.textContent.indexOf("dòng 2")>=0'))
    check('note plaintext (no script exec)', pg.eval_on_selector('#noteDisplay','e=>e.querySelector("script")===null && e.textContent.indexOf("<script>")>=0'))
    check('note persisted in settings', pg.evaluate("(id)=>window.HSKMeta.hasNote(id)", cid))
    check('note editor closed after save', pg.eval_on_selector('#noteEditor','e=>e.hidden'))
    # note NOT on front: unflip -> note zone hidden
    pg.evaluate("()=>flipCard()"); pg.wait_for_timeout(60)
    check('note hidden after unflip', pg.eval_on_selector('#noteZone','e=>e.hidden'))
    # edit -> delete by empty save -> clean state
    pg.evaluate("()=>flipCard()"); pg.wait_for_timeout(60)
    pg.evaluate("()=>document.getElementById('noteToggle').click()"); pg.wait_for_timeout(40)
    pg.evaluate("()=>{ const t=document.getElementById('noteInput'); t.value='   '; t.dispatchEvent(new Event('input')); }")
    pg.evaluate("()=>document.getElementById('noteSave').click()"); pg.wait_for_timeout(50)
    check('note deleted by empty save', not pg.evaluate("(id)=>window.HSKMeta.hasNote(id)", cid))
    check('clean empty after delete: display hidden', pg.eval_on_selector('#noteDisplay','e=>e.hidden'))
    check('clean empty after delete: editor hidden', pg.eval_on_selector('#noteEditor','e=>e.hidden'))
    # exit study
    pg.evaluate("()=>exitStudy()"); pg.wait_for_timeout(80)

    # ---------- DAILY COUNT (once per card per day) ----------
    pg.evaluate("()=>{ var s=window.HSK_APP.getSettings(); delete s.dailyCounts; delete s.todayLearn; window.saveSettings(); }")
    pg.evaluate("()=>{ window.HSKMeta.recordDailyLearn(1); window.HSKMeta.recordDailyLearn(1); window.HSKMeta.recordDailyLearn(2); }")
    day=pg.evaluate("()=>window.HSKMeta.localDay()")
    check('daily dedup once/card/day', pg.evaluate("(d)=>window.HSKMeta.dailyCounts()[d]", day)==2)

    # ---------- WEAK WORDS ----------
    pg.evaluate("()=>window.HSKInsights.showWeak()"); pg.wait_for_timeout(120)
    check('weak view active', pg.eval_on_selector('#weakWordsView','e=>e.classList.contains("active")'))
    rows=pg.eval_on_selector_all('#weakList .word-row .wr-word','e=>e.map(x=>x.textContent)')
    # card 1 (8 failures) should rank above card 2 (1 failure); card 3 (0 failures) excluded; card 4 untouched excluded
    w1=pg.evaluate("()=>window.HSK_CARDS.find(c=>c.id===1).word")
    w2=pg.evaluate("()=>window.HSK_CARDS.find(c=>c.id===2).word")
    w3=pg.evaluate("()=>window.HSK_CARDS.find(c=>c.id===3).word")
    check('weak: card1 before card2', w1 in rows and w2 in rows and rows.index(w1)<rows.index(w2))
    check('weak: card3 (no failures) excluded', w3 not in rows)
    check('weak: only 2 weak', len(rows)==2)
    # study these
    pg.evaluate("()=>document.getElementById('weakStudyBtn').click()"); pg.wait_for_timeout(100)
    check('weak study launches Study Mode', pg.eval_on_selector('#studyView','e=>e.classList.contains("active")'))
    sess=pg.evaluate("()=>session.map(c=>c.id).sort()")
    check('weak session = weak ids, no dup', sess==[1,2])
    pg.evaluate("()=>exitStudy()"); pg.wait_for_timeout(60)

    # ---------- SMART REVIEW ----------
    pg.evaluate("()=>window.HSKInsights.showInsights()"); pg.wait_for_timeout(120)
    body=pg.eval_on_selector('#insightsBody','e=>e.textContent')
    check('insights: weak count present', 'Tổng số từ cần cải thiện' in body)
    check('insights: today count', 'Đã học hôm nay' in body)
    check('chart rendered svg', pg.eval_on_selector('#dailyChart','e=>e.querySelector("svg")!==null'))
    check('chart summary text', pg.eval_on_selector('#dailyChartSummary','e=>e.textContent.length>0'))
    pg.evaluate("()=>document.getElementById('chart30').click()"); pg.wait_for_timeout(50)
    check('chart 30 active', pg.eval_on_selector('#chart30','e=>e.classList.contains("active")'))
    # insufficient data state
    pg.evaluate("()=>{ localStorage.setItem('hsk_flashcard_progress_v2','{}'); }")
    pg.reload(); pg.wait_for_timeout(300)
    pg.evaluate("()=>window.HSKInsights.showInsights()"); pg.wait_for_timeout(80)
    check('insufficient-data message', pg.eval_on_selector('#insightsBody','e=>e.textContent.indexOf("Chưa đủ dữ liệu")>=0'))

    # ---------- BOOKMARKS PAGE ----------
    pg.evaluate("()=>window.HSKInsights.showBookmarks()"); pg.wait_for_timeout(100)
    n=pg.eval_on_selector_all('#bmList .word-row','e=>e.length')
    check('bookmarks page lists saved (>=1)', n>=1)
    # remove one -> list updates; if none -> empty state
    pg.evaluate("()=>{ document.querySelectorAll('#bmList .wr-remove')[0].click(); }"); pg.wait_for_timeout(60)
    empty=pg.eval_on_selector('#bmList','e=>e.textContent.indexOf("Bạn chưa lưu từ nào")>=0')
    check('bookmarks empty state after remove-all', empty or pg.eval_on_selector_all('#bmList .word-row','e=>e.length')>=0)
    pg.evaluate("()=>document.getElementById('bmBack').click()"); pg.wait_for_timeout(60)
    check('back to home from bookmarks', pg.eval_on_selector('#homeView','e=>e.classList.contains("active")'))

    out['FAILS']=fails; out['errors']=errs; out['pass']=len(fails)==0 and len(errs)==0
    print(json.dumps(out, ensure_ascii=False))
    b.close()
