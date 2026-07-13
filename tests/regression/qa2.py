import os
import json
from playwright.sync_api import sync_playwright
URL=os.environ.get('HSK_BASE_URL','http://localhost:8000')+'/hsk_flashcard_app/'; EMPTY='window.SUPABASE_CONFIG={url:"",anonKey:""};'
fails=[]
def check(n,c):
    if not c: fails.append(n)
def activeViews(pg):
    return pg.evaluate("()=>[...document.querySelectorAll('.view')].filter(v=>v.classList.contains('active')).map(v=>v.id)")

with sync_playwright() as p:
    b=p.chromium.launch(); ctx=b.new_context(viewport={'width':1280,'height':950})
    ctx.route('**/supabase-config.js', lambda r: r.fulfill(status=200, content_type='application/javascript', body=EMPTY))
    pg=ctx.new_page(); errs=[]
    pg.on('pageerror', lambda e: errs.append('PAGEERR:'+str(e)))
    pg.on('console', lambda m: errs.append('CON:'+m.text) if m.type=='error' else None)
    pg.goto(URL); pg.wait_for_timeout(300); pg.evaluate('()=>localStorage.clear()')
    pg.evaluate('''()=>{ const d=new Date().toISOString().slice(0,10);
      localStorage.setItem('hsk_flashcard_progress_v2', JSON.stringify({'1':{due:d,interval:0,reps:6,correct:1,attempts:6},'2':{due:d,interval:1,reps:3,correct:2,attempts:3}})); }''')
    pg.reload(); pg.wait_for_timeout(300)

    # --- Bug A fix: weak-study shows ONLY studyView ---
    pg.evaluate('()=>window.HSKInsights.showWeak()'); pg.wait_for_timeout(80)
    pg.evaluate("()=>document.getElementById('weakStudyBtn').click()"); pg.wait_for_timeout(120)
    check('weak-study only studyView', activeViews(pg)==['studyView'])
    # weak-study SRS updates normally: grade a card, progress changes
    p_before=pg.evaluate("()=>localStorage.getItem('hsk_flashcard_progress_v2')")
    cid=pg.evaluate('()=>session[sessionState.currentIndex].id')
    pg.evaluate('()=>flipCard()'); pg.evaluate("()=>gradeCard('good')"); pg.wait_for_timeout(60)
    check('weak-study grading updates SRS', pg.evaluate("()=>localStorage.getItem('hsk_flashcard_progress_v2')")!=p_before)
    # daily count incremented by custom-session grade
    day=pg.evaluate('()=>window.HSKMeta.localDay()')
    check('custom-session grade counts daily', pg.evaluate('(d)=>window.HSKMeta.dailyCounts()[d]||0', day)>=1)
    pg.evaluate('()=>exitStudy()'); pg.wait_for_timeout(60)
    check('exit -> only homeView', activeViews(pg)==['homeView'])

    # --- Bug A fix: bookmark-study only studyView ---
    pg.evaluate("()=>{ window.HSKMeta.toggleBookmark(1); window.HSKMeta.toggleBookmark(2); }")
    pg.evaluate('()=>window.HSKInsights.showBookmarks()'); pg.wait_for_timeout(80)
    pg.evaluate("()=>document.getElementById('bmStudyBtn').click()"); pg.wait_for_timeout(120)
    check('bm-study only studyView', activeViews(pg)==['studyView'])
    check('bm-study session=bookmarks', sorted(pg.evaluate('()=>session.map(c=>c.id)'))==[1,2])
    pg.evaluate('()=>exitStudy()'); pg.wait_for_timeout(60)

    # --- bmStudy with empty filter -> no blank screen (stays on bookmarks) ---
    pg.evaluate('()=>window.HSKInsights.showBookmarks()'); pg.wait_for_timeout(60)
    # filter to a level with no bookmarks (bookmarks are HSK1; pick HSK6)
    pg.evaluate("()=>{ const s=document.getElementById('bmLevel'); s.value='HSK6'; s.dispatchEvent(new Event('change')); }"); pg.wait_for_timeout(60)
    pg.evaluate("()=>document.getElementById('bmStudyBtn').click()"); pg.wait_for_timeout(80)
    av=activeViews(pg)
    check('empty-filter study no blank (bookmarks stays or nothing broken)', 'studyView' not in av and len(av)>=1)

    # --- chart fill resolves (style) ---
    pg.evaluate('()=>window.HSKInsights.showInsights()'); pg.wait_for_timeout(80)
    check('chart fill accent', pg.evaluate("()=>{const r=document.querySelector('#dailyChart svg rect'); return r?getComputedStyle(r).fill:'';}")=='rgb(185, 28, 28)')
    pg.evaluate("()=>document.getElementById('insightsBack').click()"); pg.wait_for_timeout(50)

    # --- NOTE edge cases ---
    pg.evaluate("()=>{ startStudy(['HSK1']); }"); pg.wait_for_timeout(80)
    a=pg.evaluate('()=>session[sessionState.currentIndex].id')
    # set a note on card A, flip to see it
    pg.evaluate('()=>flipCard()'); pg.wait_for_timeout(50)
    pg.evaluate("()=>document.getElementById('noteToggle').click()")
    pg.evaluate("()=>{ const t=document.getElementById('noteInput'); t.value='note A'; t.dispatchEvent(new Event('input')); }")
    pg.evaluate("()=>document.getElementById('noteSave').click()"); pg.wait_for_timeout(50)
    check('note A shows', pg.eval_on_selector('#noteDisplay','e=>e.textContent')=='note A')
    # open editor, type unsaved, then UNFLIP -> editor closes, unsaved discarded
    pg.evaluate("()=>document.getElementById('noteToggle').click()")
    pg.evaluate("()=>{ const t=document.getElementById('noteInput'); t.value='UNSAVED'; t.dispatchEvent(new Event('input')); }")
    pg.evaluate('()=>flipCard()'); pg.wait_for_timeout(50)  # unflip
    check('note zone hidden on unflip', pg.eval_on_selector('#noteZone','e=>e.hidden'))
    pg.evaluate('()=>flipCard()'); pg.wait_for_timeout(50)  # flip back
    check('unsaved discarded, note A intact', pg.eval_on_selector('#noteDisplay','e=>e.textContent')=='note A')
    check('editor closed after reflip', pg.eval_on_selector('#noteEditor','e=>e.hidden'))
    # advance to next card (no note) -> clean empty
    pg.evaluate("()=>gradeCard('good')"); pg.wait_for_timeout(60)
    pg.evaluate('()=>flipCard()'); pg.wait_for_timeout(50)
    check('next card clean empty note', pg.eval_on_selector('#noteDisplay','e=>e.hidden') and pg.eval_on_selector('#noteEditor','e=>e.hidden'))
    check('next card has no note text', pg.evaluate('(id)=>!window.HSKMeta.hasNote(id)', pg.evaluate('()=>session[sessionState.currentIndex].id')))
    # note maxlength enforcement (>1000 truncated)
    pg.evaluate("()=>{ const c=session[sessionState.currentIndex]; var s=window.HSK_APP.getSettings(); s.notes=s.notes||{}; window.HSKMeta.toggleBookmark; }")
    long='x'*1500
    pg.evaluate("()=>document.getElementById('noteToggle').click()")
    pg.evaluate("(v)=>{ const t=document.getElementById('noteInput'); t.value=v; t.dispatchEvent(new Event('input')); }", long)
    pg.evaluate("()=>document.getElementById('noteSave').click()"); pg.wait_for_timeout(50)
    savedLen=pg.evaluate("()=>{ const id=session[sessionState.currentIndex].id; return window.HSKMeta.getNote(id).length; }")
    check('note truncated <=1000', savedLen<=1000)

    # --- bookmark reflects per-card when navigating ---
    pg.evaluate('()=>exitStudy()'); pg.wait_for_timeout(40)
    pg.evaluate("()=>{ var s=window.HSK_APP.getSettings(); s.bookmarks=[]; window.saveSettings(); progress={}; save(); startStudy(['HSK1']); }"); pg.wait_for_timeout(60)
    id0=pg.evaluate('()=>session[sessionState.currentIndex].id')
    pg.evaluate("()=>document.getElementById('bookmarkBtn').click()"); pg.wait_for_timeout(30)  # bookmark card 0
    star0=pg.eval_on_selector('#bookmarkBtn','e=>e.textContent')
    pg.evaluate('()=>flipCard()'); pg.evaluate("()=>gradeCard('good')"); pg.wait_for_timeout(60)  # next card
    star1=pg.eval_on_selector('#bookmarkBtn','e=>e.textContent')
    check('bookmark star per-card (on then off)', star0=='★' and star1=='☆')

    print(json.dumps({'FAILS':fails,'errors':errs,'pass':len(fails)==0 and len(errs)==0}, ensure_ascii=False)); b.close()
