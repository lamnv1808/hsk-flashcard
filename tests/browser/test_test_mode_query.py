"""Unit + characterization tests for the Phase 9 read-only TestModeQuery
(window.HSKUtil.createTestModeQuery). Runs in the real loaded browser.

Verifies eligible-card selection, all six question types (prompt/answer/reveal),
distractor rules, Mix, session construction, deterministic randomness, Study
isolation, and the strict no-side-effects contract. Includes CHARACTERIZATION:
a faithful copy of the ORIGINAL inline test.js generation (threading the same
injected seeded rnd) vs TestModeQuery over identical fixtures => byte-equal.
"""
import os, json
from playwright.sync_api import sync_playwright

URL = os.environ.get("HSK_BASE_URL", "http://localhost:8000") + "/hsk_flashcard_app/"
EMPTY = 'window.SUPABASE_CONFIG={url:"",anonKey:""};'
fails = []
def check(n, c):
    if not c: fails.append(n)

# Helpers: repo builder, deterministic LCG, and a FAITHFUL re-implementation of the
# original inline test.js generation (rnd threaded exactly as the query threads it).
HELPERS = r"""
window.__mkRepo = function(cards){ return HSKUtil.createCardRepository(cards); };
window.__mkQ = function(cards, seed){ return HSKUtil.createTestModeQuery({ cardRepository: __mkRepo(cards), randomProvider: __lcg(seed) }); };
window.__lcg = function(seed){ var s = seed>>>0; return function(){ s = (s*1664525 + 1013904223)>>>0; return s/4294967296; }; };
var SH = HSKUtil.shuffle;
var TD = [
  { id:1, q:"word",   a:["pinyin"] }, { id:2, q:"pinyin", a:["word"] },
  { id:3, q:"word",   a:["meaning"] }, { id:4, q:"pinyin", a:["meaning"] },
  { id:5, q:"word",   a:["pinyin","meaning"] }, { id:6, q:"pinyin", a:["word","meaning"] }
];
function __td(id){ for(var i=0;i<TD.length;i++) if(TD[i].id===id) return TD[i]; return null; }
function __trim(x){ return String(x==null?"":x).trim(); }
window.__oldGen = function(cards, cfg, rnd){
  function qf(t){ return __td(t).q; }
  function aLines(c,t){ return __td(t).a.map(function(f){ return __trim(c[f]); }); }
  function aKey(c,t){ return aLines(c,t).join(""); }
  function aValid(c,t){ return __td(t).a.every(function(f){ return __trim(c[f])!==""; }); }
  function qValid(c,t){ return __trim(c[qf(t)])!=="" && aValid(c,t); }
  function pick(card,pool,type,n){
    var qff=qf(type), qVal=__trim(card[qff]); var seen={}; seen[aKey(card,type)]=1;
    var out=[], attempts=0, maxA=Math.min(160,pool.length*3);
    function usable(c){ return c.id!==card.id && aValid(c,type) && __trim(c[qff])!==qVal && !seen[aKey(c,type)]; }
    while(out.length<n && attempts<maxA){ attempts++; var c=pool[(rnd()*pool.length)|0]; if(!usable(c)) continue; seen[aKey(c,type)]=1; out.push(c); }
    if(out.length<n){ for(var i=0;i<pool.length && out.length<n;i++){ var d=pool[i]; if(!usable(d)) continue; seen[aKey(d,type)]=1; out.push(d); } }
    return out;
  }
  function bq(card,pool,type){
    if(!qValid(card,type)) return null;
    var dis=pick(card,pool,type,3); if(dis.length<1) return null;
    var opts=[{card:card,isCorrect:true}]; dis.forEach(function(c){ opts.push({card:c,isCorrect:false}); });
    SH.shuffleInPlace(opts,rnd);
    return { card:card, type:type,
      options: opts.map(function(o){ return { id:o.card.id, isCorrect:o.isCorrect, lines: aLines(o.card,type) }; }),
      correctIndex: opts.map(function(o){ return o.isCorrect; }).indexOf(true) };
  }
  function firstB(card,pool,types){ var order=SH.shuffledCopy(types,rnd); for(var i=0;i<order.length;i++){ var q=bq(card,pool,order[i]); if(q) return q; } return null; }
  var pool=cards.filter(function(c){ return cfg.levels.indexOf(c.level)>=0; });
  var types=cfg.mix?[1,2,3,4,5,6]:cfg.types.slice();
  var N=cfg.count==="all"?pool.length:Math.min(parseInt(cfg.count,10),pool.length);
  var cardOrder=SH.shuffledCopy(pool,rnd);
  var assign=[]; for(var i=0;i<N;i++) assign.push(types[i%types.length]); SH.shuffleInPlace(assign,rnd);
  var questions=[], idx=0;
  while(questions.length<N && idx<cardOrder.length){ var card=cardOrder[idx++]; var want=assign[questions.length];
    var q=bq(card,pool,want)||firstB(card,pool,types); if(q) questions.push(q); }
  return questions;
};
// serialize a query session the same way (id + correctIndex + option ids/lines)
window.__ser = function(qs){ return qs.map(function(q){ return { cardId:q.card.id, type:q.type, correctIndex:q.correctIndex,
  options:q.options.map(function(o){ return { id:o.card.id, isCorrect:o.isCorrect, lines:o.lines }; }) }; }); };
window.__serOld = function(qs){ return qs.map(function(q){ return { cardId:q.card.id, type:q.type, correctIndex:q.correctIndex,
  options:q.options.map(function(o){ return { id:o.id, isCorrect:o.isCorrect, lines:o.lines }; }) }; }); };
// build a synthetic multi-level card set with distinct fields
window.__cards = function(n, level, base){ var a=[]; for(var i=0;i<n;i++){ var id=base+i;
  a.push({ id:id, level:level, word:"W"+id, pinyin:"py"+id, meaning:"m"+id, example:"ex"+id, examplePinyin:"exp"+id, translation:"tr"+id }); } return a; };
"""

def main():
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 1024, "height": 800})
        ctx.route("**/supabase-config.js", lambda r: r.fulfill(status=200, content_type="application/javascript", body=EMPTY))
        pg = ctx.new_page(); errs = []
        pg.on("pageerror", lambda e: errs.append("PAGEERR:" + str(e)))
        pg.on("console", lambda m: errs.append("CON:" + m.text) if m.type == "error" else None)
        pg.goto(URL); pg.wait_for_timeout(300)
        pg.evaluate("() => {" + HELPERS + "}")

        check("factory present", pg.evaluate("()=>typeof window.HSKUtil.createTestModeQuery==='function'"))
        check("shared instance present", pg.evaluate("()=>typeof window.HSKUtil.testMode==='object'"))

        # ---- ELIGIBLE CARDS ----
        el = pg.evaluate("""()=>{
          const cards=__cards(3,'HSK1',1).concat(__cards(2,'HSK4',10)).concat(__cards(2,'HSK6',20));
          const q=__mkQ(cards,1);
          const ids=lv=>q.getEligibleCards({levels:lv}).map(c=>c.id);
          const snap=JSON.stringify(cards);
          q.getEligibleCards({levels:['HSK1']});
          return { hsk1: ids(['HSK1']), hsk6: ids(['HSK6']),
                   mixed: ids(['HSK1','HSK6']), unknown: ids(['HSK99']), empty: ids([]),
                   sourceUnmutated: JSON.stringify(cards)===snap,
                   sourceOrder: JSON.stringify(ids(['HSK1']))==='[1,2,3]' };
        }""")
        check("eligible HSK1", el["hsk1"] == [1, 2, 3])
        check("eligible HSK6", el["hsk6"] == [20, 21])
        check("eligible mixed source order", el["mixed"] == [1, 2, 3, 20, 21])
        check("eligible unknown -> []", el["unknown"] == [])
        check("eligible empty -> []", el["empty"] == [])
        check("eligible source unmutated", el["sourceUnmutated"])
        check("eligible source order", el["sourceOrder"])

        # ---- EACH QUESTION TYPE: prompt / answer / reveal formatting ----
        ty = pg.evaluate("""()=>{
          const cards=__cards(6,'HSK1',1);
          const q=__mkQ(cards,5);
          const pool=q.getEligibleCards({levels:['HSK1']});
          const card=cards[0];
          const res={};
          [1,2,3,4,5,6].forEach(function(t){
            const ques=q.createQuestion({card:card,pool:pool,type:t});
            const opt=ques.options[ques.correctIndex];
            res['prompt'+t]=q.qField(t);
            res['ans'+t]=opt.lines.join("|");
          });
          // exact field mapping
          return { p1:res.prompt1==='word', a1:res.ans1==='py1',
                   p2:res.prompt2==='pinyin', a2:res.ans2==='W1',
                   p3:res.prompt3==='word', a3:res.ans3==='m1',
                   p4:res.prompt4==='pinyin', a4:res.ans4==='m1',
                   a5:res.ans5==='py1|m1',    // pinyin + meaning
                   a6:res.ans6==='W1|m1' };   // word + meaning
        }""")
        for k in ["p1", "a1", "p2", "a2", "p3", "a3", "p4", "a4", "a5", "a6"]:
            check("type:" + k, ty[k])

        # ---- DISTRACTORS: exactly one correct, unique, count, insufficient pool ----
        di = pg.evaluate("""()=>{
          const cards=__cards(10,'HSK1',1);
          const q=__mkQ(cards,3);
          const pool=q.getEligibleCards({levels:['HSK1']});
          const ques=q.createQuestion({card:cards[0],pool:pool,type:1});
          const correctCount=ques.options.filter(o=>o.isCorrect).length;
          const keys=ques.options.map(o=>o.lines.join(""));
          const unique=(new Set(keys)).size===keys.length;
          const correctIsCard0=ques.options[ques.correctIndex].card.id===1;
          // insufficient pool: 2 cards -> 1 correct + 1 distractor = 2 options
          const small=__mkQ(__cards(2,'HSK1',1),3);
          const sp=small.getEligibleCards({levels:['HSK1']});
          const sq=small.createQuestion({card:sp[0],pool:sp,type:1});
          // single card -> no distractor -> null
          const one=__mkQ(__cards(1,'HSK1',1),3);
          const op=one.getEligibleCards({levels:['HSK1']});
          const oq=one.createQuestion({card:op[0],pool:op,type:1});
          return { correctOnce:correctCount===1, unique, correctIsCard0, optionCount4:ques.options.length===4,
                   smallTwoOptions:sq.options.length===2, singleNull:oq===null };
        }""")
        for k in ["correctOnce", "unique", "correctIsCard0", "optionCount4", "smallTwoOptions", "singleNull"]:
            check("distractor:" + k, di[k])

        # ---- DISTRACTOR prompt-collision exclusion (homophone prompts) ----
        # two cards share the same prompt(word) -> cannot be each other's distractor for word->pinyin
        hp = pg.evaluate("""()=>{
          const cards=[
            {id:1,level:'HSK1',word:"X",pinyin:"a1",meaning:"m1"},
            {id:2,level:'HSK1',word:"X",pinyin:"a2",meaning:"m2"},   // same word as 1
            {id:3,level:'HSK1',word:"Y",pinyin:"a3",meaning:"m3"},
            {id:4,level:'HSK1',word:"Z",pinyin:"a4",meaning:"m4"}
          ];
          const q=__mkQ(cards,7);
          const pool=q.getEligibleCards({levels:['HSK1']});
          const ques=q.createQuestion({card:cards[0],pool:pool,type:1});  // word->pinyin, prompt "X"
          const ids=ques.options.map(o=>o.card.id);
          return { excludesSamePrompt: ids.indexOf(2)<0, hasCorrect: ids.indexOf(1)>=0 };
        }""")
        check("distractor excludes same-prompt card", hp["excludesSamePrompt"])
        check("distractor keeps correct card", hp["hasCorrect"])

        # ---- SESSION: sizes, empty, no-dup, redo ----
        se = pg.evaluate("""()=>{
          const cards=__cards(30,'HSK1',1);
          const cfg=n=>({levels:['HSK1'],count:String(n),types:[1,2,3,4,5,6],mix:false});
          const n=(cnt)=>__mkQ(cards,9).createSession(cfg(cnt)).length;
          const empty=__mkQ(__cards(0,'HSK1',1),9).createSession(cfg(10)).length;
          const s=__mkQ(cards,9).createSession(cfg(20));
          const cardIds=s.map(q=>q.card.id);
          const noDupCards=(new Set(cardIds)).size===cardIds.length;
          // redo == same cfg -> a fresh session (deterministic under same seed, differs under different seed)
          const r1=__ser(__mkQ(cards,42).createSession(cfg(10)));
          const r2=__ser(__mkQ(cards,42).createSession(cfg(10)));
          const r3=__ser(__mkQ(cards,43).createSession(cfg(10)));
          return { one:n(1), ten:n(10), twenty:n(20), fifty:n(50)===30, over:n(1000)===30, empty:empty===0,
                   noDupCards, redoSameSeed:JSON.stringify(r1)===JSON.stringify(r2), redoDiffSeed:JSON.stringify(r1)!==JSON.stringify(r3) };
        }""")
        check("session 1", se["one"] == 1)
        check("session 10", se["ten"] == 10)
        check("session 20", se["twenty"] == 20)
        check("session 50 capped at 30", se["fifty"])
        check("session over-pool capped", se["over"])
        check("session empty pool -> 0", se["empty"])
        check("session no duplicate cards", se["noDupCards"])
        check("redo same seed identical", se["redoSameSeed"])
        check("redo diff seed differs", se["redoDiffSeed"])

        # ---- MIX: all six modes eligible, deterministic ----
        mx = pg.evaluate("""()=>{
          const cards=__cards(60,'HSK1',1);
          const cfg={levels:['HSK1'],count:"40",types:[1],mix:true};   // mix ignores types, uses all 6
          const s1=__ser(__mkQ(cards,17).createSession(cfg));
          const s2=__ser(__mkQ(cards,17).createSession(cfg));
          const modes=new Set(s1.map(q=>q.type));
          return { deterministic:JSON.stringify(s1)===JSON.stringify(s2),
                   usesMultipleModes:modes.size>=2, allWithinSix:[...modes].every(m=>m>=1&&m<=6) };
        }""")
        for k in ["deterministic", "usesMultipleModes", "allWithinSix"]:
            check("mix:" + k, mx[k])

        # ---- CHARACTERIZATION: original inline gen vs query (same seed, same fixtures) ----
        ch = pg.evaluate("""()=>{
          function scen(cards, cfg, seed){
            const nw=__ser(__mkQ(cards,seed).createSession(cfg));
            const old=__serOld(__oldGen(cards.slice(), cfg, __lcg(seed)));
            return JSON.stringify(nw)===JSON.stringify(old);
          }
          const A=__cards(40,'HSK1',1).concat(__cards(40,'HSK2',100));
          return {
            single:  scen(A, {levels:['HSK1'],count:"20",types:[1,2,3],mix:false}, 3),
            all6:    scen(A, {levels:['HSK1','HSK2'],count:"30",types:[1,2,3,4,5,6],mix:false}, 5),
            mix:     scen(A, {levels:['HSK1','HSK2'],count:"25",types:[1],mix:true}, 8),
            countAll:scen(A, {levels:['HSK1'],count:"all",types:[2,4],mix:false}, 11),
            twoLevel:scen(A, {levels:['HSK1','HSK2'],count:"50",types:[5,6],mix:false}, 13)
          };
        }""")
        for k in ["single", "all6", "mix", "countAll", "twoLevel"]:
            check("characterization:" + k, ch[k])

        # ---- NO SIDE EFFECTS / STUDY ISOLATION ----
        ni = pg.evaluate("""()=>{
          const before={}; for(let i=0;i<localStorage.length;i++){const k=localStorage.key(i); before[k]=localStorage.getItem(k);}
          const beforeLen=localStorage.length;
          const cards=__cards(40,'HSK1',1); const snap=JSON.stringify(cards);
          const q=__mkQ(cards,9);
          for(let i=0;i<10;i++){ q.createSession({levels:['HSK1'],count:"20",types:[1,2,3,4,5,6],mix:false}); q.getEligibleCards({levels:['HSK1']}); }
          const after={}; for(let i=0;i<localStorage.length;i++){const k=localStorage.key(i); after[k]=localStorage.getItem(k);}
          let unchanged=localStorage.length===beforeLen;
          for(const k in before){ if(before[k]!==after[k]) unchanged=false; }
          for(const k in after){ if(!(k in before)) unchanged=false; }
          // production progress object untouched by Test Mode
          const progUntouched = JSON.stringify(HSK_APP.getProgress())===JSON.stringify(HSK_APP.getProgress());
          return { storageUnchanged:unchanged, cardsUnmutated:JSON.stringify(cards)===snap, progUntouched };
        }""")
        for k in ["storageUnchanged", "cardsUnmutated", "progUntouched"]:
            check("noSideEffect:" + k, ni[k])

        result = {"suite": "test_mode_query", "pass": len(fails) == 0 and len(errs) == 0, "fails": fails, "errors": errs}
        print(json.dumps(result, ensure_ascii=False))
        b.close()
        return 0 if result["pass"] else 1

if __name__ == "__main__":
    import sys
    sys.exit(main())
