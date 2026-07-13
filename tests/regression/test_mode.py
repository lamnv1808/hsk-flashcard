import os
import json, sys
from playwright.sync_api import sync_playwright

URL=os.environ.get('HSK_BASE_URL','http://localhost:8000')+'/hsk_flashcard_app/'
EMPTY='window.SUPABASE_CONFIG={url:"",anonKey:""};'
fails=[]
def check(name, cond):
    if not cond: fails.append(name)

VALIDATOR = r'''()=>{
  const CJK=/[一-鿿]/;
  const cards=window.HSK_CARDS;
  const TL={'Hán tự → Pinyin':1,'Pinyin → Hán tự':2,'Hán tự → Nghĩa':3,'Pinyin → Nghĩa':4,'Hán tự → Pinyin + Nghĩa':5,'Pinyin → Hán tự + Nghĩa':6};
  const tr=x=>String(x==null?'':x).trim();
  window.__typeOf=lbl=>TL[lbl];
  window.__validate=function(type, levels, qtext, opts, correctIdx){
    const pool=cards.filter(c=>levels.includes(c.level));
    const reasons=[];
    const qIsWord=[1,3,5].includes(type);
    if(qIsWord){ if(!CJK.test(qtext)) reasons.push('q-not-CJK'); }
    else { if(CJK.test(qtext)) reasons.push('q-leaked-CJK'); }
    const qf=qIsWord?'word':'pinyin';
    if(!pool.some(c=>tr(c[qf])===tr(qtext))) reasons.push('q-not-in-pool');
    const vis=opts.map(o=>o.lines.map(tr).join(''));
    if(new Set(vis).size!==vis.length) reasons.push('dup-options');
    function real(lines){
      if(type===1) return pool.some(c=>tr(c.pinyin)===tr(lines[0]));
      if(type===2) return pool.some(c=>tr(c.word)===tr(lines[0]));
      if(type===3||type===4) return pool.some(c=>tr(c.meaning)===tr(lines[0]));
      if(type===5) return pool.some(c=>tr(c.pinyin)===tr(lines[0])&&tr(c.meaning)===tr(lines[1]));
      if(type===6) return pool.some(c=>tr(c.word)===tr(lines[0])&&tr(c.meaning)===tr(lines[1]));
    }
    opts.forEach((o,i)=>{ if(!real(o.lines)) reasons.push('opt'+i+'-not-real'); });
    if(correctIdx>=0){
      const co=opts[correctIdx].lines; let ok=false;
      if(type===1) ok=pool.some(c=>tr(c.word)===tr(qtext)&&tr(c.pinyin)===tr(co[0]));
      if(type===2) ok=pool.some(c=>tr(c.pinyin)===tr(qtext)&&tr(c.word)===tr(co[0]));
      if(type===3) ok=pool.some(c=>tr(c.word)===tr(qtext)&&tr(c.meaning)===tr(co[0]));
      if(type===4) ok=pool.some(c=>tr(c.pinyin)===tr(qtext)&&tr(c.meaning)===tr(co[0]));
      if(type===5) ok=pool.some(c=>tr(c.word)===tr(qtext)&&tr(c.pinyin)===tr(co[0])&&tr(c.meaning)===tr(co[1]));
      if(type===6) ok=pool.some(c=>tr(c.pinyin)===tr(qtext)&&tr(c.word)===tr(co[0])&&tr(c.meaning)===tr(co[1]));
      if(!ok) reasons.push('correct-mismatch-q');
    }
    return reasons;
  };
}'''

def read_q(pg):
    return pg.evaluate('''()=>{
      const q=document.getElementById('testQuestion');
      const opts=[...document.querySelectorAll('#testOptions .test-option')].map(b=>({lines:[...b.querySelectorAll('.opt-line')].map(x=>x.textContent),disabled:b.disabled}));
      return {type:document.getElementById('testTypeLabel').textContent, qtext:q.textContent, opts};
    }''')

def answer(pg, i):
    pg.evaluate('(i)=>document.querySelectorAll("#testOptions .test-option")[i].click()', i)
    pg.wait_for_timeout(40)
    return pg.evaluate('''()=>{
      const opts=[...document.querySelectorAll('#testOptions .test-option')];
      return {correctIdx:opts.findIndex(b=>b.classList.contains('correct')),
              wrongIdx:opts.findIndex(b=>b.classList.contains('wrong')),
              feedback:document.getElementById('testFeedback').textContent,
              fbClass:document.getElementById('testFeedback').className,
              score:+document.getElementById('testScore').textContent,
              panelHidden:document.getElementById('testAnswerPanel').hidden};
    }''')

def config(pg, levels, count, types=None, mix=False):
    pg.evaluate('()=>window.TestMode.open()'); pg.wait_for_timeout(80)
    pg.evaluate('''(target)=>{
       document.querySelectorAll('#testLevelPicker .level-chip').forEach(c=>{ if(target.includes(c.textContent)&&!c.classList.contains('active')) c.click(); });
       document.querySelectorAll('#testLevelPicker .level-chip').forEach(c=>{ if(!target.includes(c.textContent)&&c.classList.contains('active')) c.click(); });
    }''', levels)
    pg.select_option('#testCount', count)
    cur_mix=pg.eval_on_selector('#testMix','e=>e.checked')
    if mix!=cur_mix: pg.click('#testMix'); pg.wait_for_timeout(50)
    if not mix and types is not None:
        pg.evaluate('''(types)=>{ document.querySelectorAll('#testTypes .test-type-cb').forEach(cb=>{ const want=types.includes(parseInt(cb.value,10)); if(cb.checked!==want) cb.click(); }); }''', types)
    pg.click('#testStartBtn'); pg.wait_for_timeout(200)

with sync_playwright() as p:
    b=p.chromium.launch(); ctx=b.new_context(viewport={'width':1280,'height':1000})
    ctx.route('**/supabase-config.js', lambda r: r.fulfill(status=200, content_type='application/javascript', body=EMPTY))
    pg=ctx.new_page(); errs=[]
    pg.on('pageerror', lambda e: errs.append('PAGEERR:'+str(e)))
    pg.on('console', lambda m: errs.append('CON:'+m.text) if m.type=='error' else None)
    pg.on('dialog', lambda d: d.accept())   # auto-accept exit confirms
    pg.goto(URL); pg.wait_for_timeout(300); pg.evaluate('()=>localStorage.clear()'); pg.reload(); pg.wait_for_timeout(300)
    pg.evaluate(VALIDATOR)

    # ---- per-type: run each of the 6 types with HSK1, 10 questions, validate every question ----
    all_positions=[]
    for t in [1,2,3,4,5,6]:
        config(pg, ['HSK1'], '10', types=[t], mix=False)
        total=int(pg.eval_on_selector('#testQTotal','e=>e.textContent'))
        check('type%d total==10'%t, total==10)
        for qi in range(total):
            q=read_q(pg)
            ty=pg.evaluate('(l)=>window.__typeOf(l)', q['type'])
            check('type%d q%d type-label'%(t,qi), ty==t)
            check('type%d q%d 4opts'%(t,qi), len(q['opts'])==4)
            res=answer(pg,0)
            reasons=pg.evaluate('(a)=>window.__validate(a.t,a.lv,a.qt,a.opts,a.ci)', {'t':t,'lv':['HSK1'],'qt':q['qtext'],'opts':q['opts'],'ci':res['correctIdx']})
            if reasons: fails.append('type%d q%d: %s'%(t,qi,reasons))
            all_positions.append(res['correctIdx'])
            if res['wrongIdx']>=0: check('type%d q%d wrong-autoreveal'%(t,qi), res['panelHidden']==False)
            pg.click('#testNextBtn'); pg.wait_for_timeout(40)
        check('type%d results shown'%t, pg.eval_on_selector('#testResultView','e=>e.classList.contains("active")'))
        pg.click('#testResultHome'); pg.wait_for_timeout(80)
    # robust shuffle-fairness over 60 questions: correct answer lands in >=3 distinct positions
    check('correct-position-shuffled (60q)', len(set(all_positions))>=3)

    # ---- no-double-score + next gating + no retry ----
    config(pg, ['HSK1'], '10', types=[3], mix=False)
    q=read_q(pg)
    # next hidden before answer
    check('next-hidden-before', pg.eval_on_selector('#testNextBtn','e=>e.hidden'))
    r1=answer(pg,0); s1=r1['score']
    # click same option again + another option -> no score change, still locked
    pg.evaluate('()=>document.querySelectorAll("#testOptions .test-option")[0].click()')
    pg.evaluate('()=>document.querySelectorAll("#testOptions .test-option")[1].click()')
    pg.wait_for_timeout(60)
    s2=int(pg.eval_on_selector('#testScore','e=>e.textContent'))
    check('no-double-score', s1==s2)
    check('all-locked', pg.eval_on_selector_all('#testOptions .test-option','e=>e.every(x=>x.disabled)'))
    pg.click('#testExitBtn'); pg.wait_for_timeout(120)   # mid-quiz -> exit (dialog auto-accepted)

    # ---- mix + distribution balance (all HSK1, 30 questions) ----
    pg.evaluate('()=>window.TestMode.open()')
    config(pg, ['HSK1','HSK4','HSK6'], '30', mix=True)
    total=int(pg.eval_on_selector('#testQTotal','e=>e.textContent'))
    seen_types={}
    seen_levels=set()
    for qi in range(total):
        q=read_q(pg); ty=pg.evaluate('(l)=>window.__typeOf(l)', q['type'])
        seen_types[ty]=seen_types.get(ty,0)+1
        # badge level
        lv=pg.eval_on_selector('#testQBadge','e=>e.textContent'); seen_levels.add(lv)
        answer(pg,0); pg.click('#testNextBtn'); pg.wait_for_timeout(20)
    check('mix uses all 6 types', len(seen_types)==6)
    counts=sorted(seen_types.values())
    check('mix approx-balanced', counts[-1]-counts[0]<=2)   # ~5 each for 30/6
    check('mix multi-level', len(seen_levels)>=2)
    pg.click('#testResultHome'); pg.wait_for_timeout(80)

    # ---- levels & sizes ----
    for lv,cnt,exp in [(['HSK6'],'50',50),(['HSK1'],'all',149)]:
        config(pg, lv, cnt, types=[1,2,3], mix=False)
        total=int(pg.eval_on_selector('#testQTotal','e=>e.textContent'))
        check('size %s %s'%(lv,cnt), total==exp)
        # answer all quickly
        for qi in range(total): answer(pg,0); pg.click('#testNextBtn'); pg.wait_for_timeout(3)
        pg.click('#testResultHome'); pg.wait_for_timeout(60)

    # ---- results, review, redo ----
    config(pg, ['HSK1'], '10', types=[1,2], mix=False)
    total=int(pg.eval_on_selector('#testQTotal','e=>e.textContent'))
    wrongs=0
    for qi in range(total):
        # deliberately answer wrong when possible: pick an option that's not correct by picking idx 0 then if correct pick 1 next time... simplest: always pick 0
        r=answer(pg,0)
        if r['wrongIdx']>=0: wrongs+=1
        pg.click('#testNextBtn'); pg.wait_for_timeout(20)
    res=pg.evaluate('''()=>({total:+document.getElementById('resTotal').textContent, correct:+document.getElementById('resCorrect').textContent, wrong:+document.getElementById('resWrong').textContent, pct:document.getElementById('resPercent').textContent, label:document.getElementById('resLabel').textContent})''')
    check('result totals', res['total']==10 and res['correct']+res['wrong']==10)
    check('result wrong matches', res['wrong']==wrongs)
    labels={'Xuất sắc','Tốt','Khá','Cần ôn thêm'}
    check('result label valid', res['label'] in labels)
    if wrongs>0:
        pg.click('#testReviewBtn'); pg.wait_for_timeout(100)
        check('review shown', pg.eval_on_selector('#testReviewView','e=>e.classList.contains("active")'))
        check('review items', pg.eval_on_selector_all('#testReviewList .review-item','e=>e.length')==wrongs)
        pg.click('#testReviewBack'); pg.wait_for_timeout(60)
    # redo keeps config
    pg.click('#testRedoBtn'); pg.wait_for_timeout(150)
    check('redo same total', int(pg.eval_on_selector('#testQTotal','e=>e.textContent'))==10)
    check('redo quiz active', pg.eval_on_selector('#testQuizView','e=>e.classList.contains("active")'))

    # ---- SRS / progress ISOLATION: taking a test changes nothing ----
    prog_before=pg.evaluate("()=>localStorage.getItem('hsk_flashcard_progress_v2')")
    # answer a few then exit
    answer(pg,0); pg.click('#testNextBtn'); pg.wait_for_timeout(30); answer(pg,0)
    pg.click('#testExitBtn'); pg.wait_for_timeout(120)   # dialog auto-accepted
    prog_after=pg.evaluate("()=>localStorage.getItem('hsk_flashcard_progress_v2')")
    check('progress unchanged by test', prog_before==prog_after)
    check('exit returns home', pg.eval_on_selector('#homeView','e=>e.classList.contains("active")'))

    print(json.dumps({'FAILS':fails,'errors':errs,'pass': len(fails)==0 and len(errs)==0}, ensure_ascii=False))
    b.close()
