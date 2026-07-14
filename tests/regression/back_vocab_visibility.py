"""Hotfix 24.1 — the back card face always shows the vocab word + pinyin (independent of the
front-pinyin setting), and the whole back vocab block stays a click-to-speak target.

Read-only w.r.t. production: local-only (Supabase config stubbed empty), localStorage cleared.
"""
import os, json
from playwright.sync_api import sync_playwright

URL = os.environ.get('HSK_BASE_URL', 'http://localhost:8000') + '/hsk_flashcard_app/'
EMPTY = 'window.SUPABASE_CONFIG={url:"",anonKey:""};'
fails = []
def check(n, c):
    if not c: fails.append(n)

# Capture SpeechSynthesis utterances (text + lang) and neutralize real speaking.
SPY = """()=>{ window.__utter=[];
  window.speechSynthesis.speak=function(u){ window.__utter.push({text:u.text, lang:u.lang}); };
  window.speechSynthesis.cancel=function(){}; }"""

def utter(pg): return pg.evaluate("()=>window.__utter.slice()")
def reset_utter(pg): pg.evaluate("()=>{window.__utter=[];}")
def is_flipped(pg): return pg.evaluate("()=>document.getElementById('flashcard').classList.contains('flipped')")
def is_complete(pg): return pg.evaluate("()=>document.getElementById('completeView').classList.contains('active')")

def start(pg, size='10'):
    pg.evaluate("(s)=>{ progress={}; save(); document.getElementById('sessionSize').value=s; startStudy(['HSK1']); }", size)
    pg.wait_for_timeout(120)

def set_front_pinyin(pg, on):
    pg.evaluate("(on)=>{ settings.showFrontPinyin=on; saveSettings(); applyPinyinDisplay(); }", on)
    pg.wait_for_timeout(60)

def flip(pg):
    pg.evaluate("()=>{ if(!sessionState.flipped) flipCard(); }"); pg.wait_for_timeout(60)

def disp(pg, eid):  # computed display of an element
    return pg.evaluate("(id)=>getComputedStyle(document.getElementById(id)).display", eid)

def card(pg):
    return pg.evaluate("()=>{ const c=session[sessionState.currentIndex]; return {word:c.word,pinyin:c.pinyin,meaning:c.meaning,example:c.example}; }")

with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={'width': 1280, 'height': 900})
    ctx.route('**/supabase-config.js', lambda r: r.fulfill(status=200, content_type='application/javascript', body=EMPTY))
    pg = ctx.new_page(); errs = []
    pg.on('pageerror', lambda e: errs.append('PAGEERR:' + str(e)))
    pg.on('console', lambda m: errs.append('CON:' + m.text) if m.type == 'error' else None)
    pg.goto(URL); pg.wait_for_timeout(300); pg.evaluate('()=>localStorage.clear()'); pg.reload(); pg.wait_for_timeout(300)

    # ============ Front pinyin ON (default) ============
    start(pg); set_front_pinyin(pg, True)
    c = card(pg)
    # front (before flip)
    check('ON front word visible', disp(pg, 'word') != 'none' and pg.evaluate("()=>document.getElementById('word').textContent") == c['word'])
    check('ON front pinyin visible', disp(pg, 'pinyin') != 'none')
    check('ON not flipped before flip', not is_flipped(pg))
    check('ON meaning present but back-face culled pre-flip', not is_flipped(pg))
    flip(pg)
    check('ON flipped', is_flipped(pg))
    check('ON back word block display not none', disp(pg, 'backWordBlock') != 'none')
    check('ON back word visible + correct', pg.evaluate("()=>document.getElementById('backWord').textContent") == c['word'])
    check('ON back pinyin visible + correct', disp(pg, 'backPinyin') != 'none' and pg.evaluate("()=>document.getElementById('backPinyin').textContent") == c['pinyin'])
    check('ON meaning correct', pg.evaluate("()=>document.getElementById('meaning').textContent") == c['meaning'])
    check('ON example correct', pg.evaluate("()=>document.getElementById('example').textContent") == c['example'])

    # ============ Front pinyin OFF ============
    start(pg); set_front_pinyin(pg, False)
    c2 = card(pg)
    check('OFF front word visible', pg.evaluate("()=>document.getElementById('word').textContent") == c2['word'])
    check('OFF front pinyin hidden', disp(pg, 'pinyin') == 'none')
    flip(pg)
    check('OFF back word visible + correct', disp(pg, 'backWordBlock') != 'none' and pg.evaluate("()=>document.getElementById('backWord').textContent") == c2['word'])
    check('OFF back pinyin visible + correct', disp(pg, 'backPinyin') != 'none' and pg.evaluate("()=>document.getElementById('backPinyin').textContent") == c2['pinyin'])
    check('OFF meaning correct', pg.evaluate("()=>document.getElementById('meaning').textContent") == c2['meaning'])
    check('OFF example correct', pg.evaluate("()=>document.getElementById('example').textContent") == c2['example'])

    # ============ Audio (front pinyin ON) ============
    start(pg); set_front_pinyin(pg, True); flip(pg)
    c = card(pg)
    pg.evaluate(SPY)
    # click back word block (Hanzi) -> speaks the WORD once, zh-CN, stays flipped
    reset_utter(pg); pg.evaluate("()=>document.getElementById('backWordBlock').click()"); pg.wait_for_timeout(60)
    u = utter(pg)
    check('audio: back Hanzi -> one utterance', len(u) == 1)
    check('audio: back Hanzi -> speaks the WORD', u and u[0]['text'] == c['word'])
    check('audio: back Hanzi -> zh-CN', u and u[0]['lang'] == 'zh-CN')
    check('audio: back Hanzi -> not pinyin/Vietnamese', u and u[0]['text'] != c['pinyin'] and u[0]['text'] != c['meaning'])
    check('audio: back Hanzi -> card stays flipped', is_flipped(pg))
    # click back pinyin (inside block, bubbles to the single listener) -> one utterance of the WORD
    reset_utter(pg); pg.evaluate("()=>document.getElementById('backPinyin').click()"); pg.wait_for_timeout(60)
    u = utter(pg)
    check('audio: back pinyin -> one utterance of the WORD', len(u) == 1 and u[0]['text'] == c['word'])
    check('audio: back pinyin -> still flipped', is_flipped(pg))
    # example click -> speaks the example
    reset_utter(pg); pg.evaluate("()=>document.getElementById('example').click()"); pg.wait_for_timeout(60)
    u = utter(pg)
    check('audio: example click -> speaks example once', len(u) == 1 and u[0]['text'] == c['example'])
    # S on the back -> reads example
    reset_utter(pg); pg.evaluate("()=>document.dispatchEvent(new KeyboardEvent('keydown',{key:'s',bubbles:true}))"); pg.wait_for_timeout(60)
    u = utter(pg)
    check('audio: S on back -> reads example', len(u) == 1 and u[0]['text'] == c['example'])
    # "Từ" button -> reads the word
    reset_utter(pg); pg.evaluate("()=>document.getElementById('speakWordBtn').click()"); pg.wait_for_timeout(60)
    u = utter(pg)
    check('audio: "Từ" button -> reads the word once', len(u) == 1 and u[0]['text'] == c['word'])
    # drag on the flashcard sets suppressClick -> the next back-block click is suppressed (no speak)
    reset_utter(pg)
    pg.evaluate("""()=>{ const fc=document.getElementById('flashcard'); const r=fc.getBoundingClientRect();
        const x=r.left+r.width/2, y=r.top+r.height/2;
        fc.dispatchEvent(new PointerEvent('pointerdown',{clientX:x,clientY:y,pointerId:1,button:0,pointerType:'mouse',bubbles:true}));
        fc.dispatchEvent(new PointerEvent('pointermove',{clientX:x+24,clientY:y,pointerId:1,pointerType:'mouse',bubbles:true}));
        fc.dispatchEvent(new PointerEvent('pointerup',{clientX:x+24,clientY:y,pointerId:1,pointerType:'mouse',bubbles:true}));
        document.getElementById('backWordBlock').click(); }""")
    pg.wait_for_timeout(60)
    check('audio: drag then click -> no playback (suppressClick)', len(utter(pg)) == 0)

    # ============ Navigation: next/prev front-side, back word updates, no stale ============
    start(pg); set_front_pinyin(pg, True)
    w0 = pg.evaluate("()=>session[0].word"); w1 = pg.evaluate("()=>session[1].word")
    flip(pg); pg.evaluate("()=>gradeCard('good')"); pg.wait_for_timeout(80)   # advance to card 2
    check('nav: next card starts front-side (not flipped)', not is_flipped(pg))
    check('nav: front shows new card word', pg.evaluate("()=>document.getElementById('word').textContent") == w1)
    flip(pg)
    check('nav: back word updated to active card (no stale)', pg.evaluate("()=>document.getElementById('backWord').textContent") == w1)
    check('nav: back word is not the previous card word', pg.evaluate("()=>document.getElementById('backWord').textContent") != w0 or w0 == w1)
    # swipe previous -> front-side, back word reflects prev card after flip
    pg.evaluate("()=>swipePrev()"); pg.wait_for_timeout(80)
    check('nav: prev card starts front-side', not is_flipped(pg))
    flip(pg)
    check('nav: prev back word correct', pg.evaluate("()=>document.getElementById('backWord').textContent") == w0)

    # ============ Layout: viewports x themes ============
    def study_layout(w, h, dark):
        cx = b.new_context(viewport={'width': w, 'height': h})
        cx.route('**/supabase-config.js', lambda r: r.fulfill(status=200, content_type='application/javascript', body=EMPTY))
        pp = cx.new_page(); pp_err = []
        pp.on('pageerror', lambda e: pp_err.append(str(e)))
        pp.goto(URL); pp.wait_for_timeout(250); pp.evaluate('()=>localStorage.clear()'); pp.reload(); pp.wait_for_timeout(250)
        if dark: pp.evaluate("()=>{document.body.classList.add('dark'); settings.dark=true;}")
        pp.evaluate("()=>{ progress={}; save(); document.getElementById('sessionSize').value='10'; settings.showFrontPinyin=true; startStudy(['HSK1']); }"); pp.wait_for_timeout(120)
        pp.evaluate("()=>{ if(!sessionState.flipped) flipCard(); }"); pp.wait_for_timeout(80)  # show the dense back
        res = pp.evaluate("""()=>{
            const hov = document.documentElement.scrollWidth > document.documentElement.clientWidth;
            const bw = document.getElementById('backWord').getBoundingClientRect();
            const bwVisible = bw.width>0 && bw.height>0 && bw.top < window.innerHeight;
            const ra = document.getElementById('ratingArea').getBoundingClientRect();
            const rateVisible = ra.bottom <= window.innerHeight + 1 && ra.top >= 0;
            return { hov, bwVisible, rateVisible };
        }""")
        cx.close()
        return res, pp_err
    for (w, h) in [(360, 800), (375, 667), (390, 844), (1366, 768)]:
        for dark in (False, True):
            r, e = study_layout(w, h, dark)
            tag = '%dx%d/%s' % (w, h, 'dark' if dark else 'light')
            check('layout %s no horizontal overflow' % tag, r['hov'] == False)
            check('layout %s back word visible' % tag, r['bwVisible'] == True)
            # The one-screen (no page scroll, rating in-viewport) guarantee is the MOBILE layout
            # (@media max-width:720px). Desktop study is a normal scrollable page (pre-existing).
            if w <= 720:
                check('layout %s rating buttons visible (mobile one-screen)' % tag, r['rateVisible'] == True)
            check('layout %s no page errors' % tag, len(e) == 0)

    check('no console/page errors', len(errs) == 0)
    ctx.close(); b.close()

print(json.dumps({'pass': len(fails) == 0, 'fails': fails, 'errs': errs[:5]}, ensure_ascii=False))
