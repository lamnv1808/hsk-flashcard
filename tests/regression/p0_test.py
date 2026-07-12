import os
import json, time
from playwright.sync_api import sync_playwright
URL=os.environ.get('HSK_BASE_URL','http://localhost:8000')+'/hsk_flashcard_app/'
EMPTY='window.SUPABASE_CONFIG={url:"",anonKey:""};'
fails=[]
def check(n,c):
    if not c: fails.append(n)

def backTransform(pg):
    return pg.evaluate("()=>getComputedStyle(document.querySelector('.card-back')).transform")
def frontWord(pg):
    return pg.eval_on_selector('#word','e=>e.textContent')

def advance_and_check(pg, label, action_fn, expect_index):
    # flip to back first (so an un-flip would animate if buggy)
    pg.evaluate("()=>{ if(!document.getElementById('flashcard').classList.contains('flipped')) flipCard(); }")
    pg.wait_for_timeout(120)
    check(label+' pre-flipped', pg.evaluate("()=>flipped===true"))
    action_fn()
    # sample immediately and after 130ms
    t0=backTransform(pg)
    idx0=pg.evaluate('()=>current')
    fl=pg.evaluate('()=>flipped')
    cls=pg.evaluate("()=>document.getElementById('flashcard').classList.contains('flipped')")
    w0=frontWord(pg)
    pg.wait_for_timeout(140)
    t1=backTransform(pg)
    # assertions
    check(label+' flipped=false', fl==False)
    check(label+' no .flipped class', cls==False)
    check(label+' back NOT animating (no leak)', t0==t1)
    # front shows the current session card's word
    curword=pg.evaluate('()=>session[current] && session[current].word')
    check(label+' front shows current word', w0==curword)
    check(label+' index advanced', idx0==expect_index)

with sync_playwright() as p:
    b=p.chromium.launch(); ctx=b.new_context(viewport={'width':1280,'height':900})
    ctx.route('**/supabase-config.js', lambda r: r.fulfill(status=200, content_type='application/javascript', body=EMPTY))
    pg=ctx.new_page(); errs=[]
    pg.on('pageerror', lambda e: errs.append('PAGEERR:'+str(e)))
    pg.on('console', lambda m: errs.append('CON:'+m.text) if m.type=='error' else None)
    pg.goto(URL); pg.wait_for_timeout(300); pg.evaluate('()=>localStorage.clear()'); pg.reload(); pg.wait_for_timeout(300)

    # a long session so we can advance many times
    pg.evaluate("()=>{ progress={}; save(); startStudy(['HSK1']); }")
    pg.wait_for_timeout(150)

    # grade via keyboard 1/2/3/4
    for i,k in enumerate(['1','2','3','4']):
        advance_and_check(pg, 'kbd-'+k, (lambda kk: (lambda: (pg.keyboard.press(kk), pg.wait_for_timeout(20))))(k), i+1)

    # grade via mouse click on rate buttons
    grades=['again','hard','good','easy']
    for i,g in enumerate(grades):
        advance_and_check(pg, 'click-'+g, (lambda gg: (lambda: (pg.evaluate("(gg)=>document.querySelector('.rate.'+gg).click()", gg), pg.wait_for_timeout(20))))(g), 5+i)

    # Next / skip (from flipped)
    advance_and_check(pg, 'skip', lambda: (pg.evaluate("()=>document.getElementById('nextBtn').click()"), pg.wait_for_timeout(20)), 9)

    # swipe next (call swipeNext) and swipe prev
    advance_and_check(pg, 'swipeNext', lambda: (pg.evaluate("()=>swipeNext()"), pg.wait_for_timeout(20)), 10)
    # swipe prev: from a flipped card, go back one -> index decreases
    pg.evaluate("()=>{ if(!document.getElementById('flashcard').classList.contains('flipped')) flipCard(); }"); pg.wait_for_timeout(120)
    idxb=pg.evaluate('()=>current')
    t0=backTransform(pg); pg.evaluate("()=>swipePrev()"); pg.wait_for_timeout(20)
    ta=backTransform(pg); w=frontWord(pg); pg.wait_for_timeout(140); tb=backTransform(pg)
    check('swipePrev flipped=false', pg.evaluate('()=>flipped')==False)
    check('swipePrev back not animating', ta==tb)
    check('swipePrev index decreased', pg.evaluate('()=>current')==idxb-1)
    check('swipePrev front word', w==pg.evaluate('()=>session[current].word'))

    # rapid repeated key presses on ONE flipped card -> advances EXACTLY once (no double-grade)
    pg.evaluate("()=>{ if(!document.getElementById('flashcard').classList.contains('flipped')) flipCard(); }"); pg.wait_for_timeout(120)
    idx=pg.evaluate('()=>current')
    for _ in range(5): pg.keyboard.press('3')
    pg.wait_for_timeout(200)
    check('rapid key advances exactly 1', pg.evaluate('()=>current')==idx+1)
    check('rapid front (not flipped)', pg.evaluate('()=>!document.getElementById("flashcard").classList.contains("flipped")'))
    # rapid mouse clicks on a rate button -> advances exactly once (buttons hide after first)
    pg.evaluate("()=>{ if(!document.getElementById('flashcard').classList.contains('flipped')) flipCard(); }"); pg.wait_for_timeout(120)
    idx2=pg.evaluate('()=>current')
    for _ in range(5): pg.evaluate("()=>document.querySelector('.rate.good').click()")
    pg.wait_for_timeout(150)
    check('rapid click advances exactly 1', pg.evaluate('()=>current')==idx2+1)

    # user flip STILL animates (regression: flip animation preserved)
    pg.evaluate("()=>{ if(document.getElementById('completeView').classList.contains('active')){ startStudy(['HSK1']); } }")
    pg.wait_for_timeout(100)
    pg.evaluate("()=>{ if(document.getElementById('flashcard').classList.contains('flipped')) flipCard(); }"); pg.wait_for_timeout(120)
    f0=pg.evaluate("()=>getComputedStyle(document.querySelector('.card-front')).transform")
    pg.evaluate("()=>flipCard()")  # flip to back -> should animate
    a0=pg.evaluate("()=>getComputedStyle(document.querySelector('.card-front')).transform")
    pg.wait_for_timeout(120)
    a1=pg.evaluate("()=>getComputedStyle(document.querySelector('.card-front')).transform")
    check('user flip still animates', a0!=a1)   # transform changes over time -> animating

    print(json.dumps({'FAILS':fails,'errors':errs,'pass':len(fails)==0 and len(errs)==0}, ensure_ascii=False))
    b.close()
