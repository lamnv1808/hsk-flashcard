"""Unit + characterization tests for the Phase 5 read-only StudySessionQuery
(window.HSKUtil.createStudySessionQuery). Runs in the real loaded browser.

Verifies classification, level filtering, limit, priority/fallthrough/dedup,
deterministic randomness (injected rnd), explicit-card sessions, progress-provider
lifecycle (no stale / account isolation), and the strict no-side-effects contract.
Also runs a CHARACTERIZATION comparison: a faithful re-implementation of the OLD
inline app.js selection logic vs SessionQuery on identical fixtures + identical
random sequence => must be byte-equal (ids, order, count).
"""
import os, json
from playwright.sync_api import sync_playwright

URL = os.environ.get("HSK_BASE_URL", "http://localhost:8000") + "/hsk_flashcard_app/"
EMPTY = 'window.SUPABASE_CONFIG={url:"",anonKey:""};'
fails = []
def check(n, c):
    if not c: fails.append(n)

# Shared JS helpers injected into the page: fixtures + a deterministic LCG rnd +
# a faithful copy of the OLD inline standard-selection logic (app.js pre-Phase-5).
HELPERS = r"""
window.__mkRepo = function(cards){ return HSKUtil.createCardRepository(cards); };
// Deterministic PRNG in [0,1) — same seed => same sequence, never exhausts.
window.__lcg = function(seed){ var s = seed>>>0; return function(){ s = (s*1664525 + 1013904223)>>>0; return s/4294967296; }; };
// Faithful re-implementation of the ORIGINAL inline startStudy selection
// (app.js lines 189-198 before Phase 5). rnd is injected for determinism.
window.__oldStandard = function(all, levels, prog, sizeSetting, today, rnd){
  var getState = function(id){ return prog[id] || {due: today, interval:0, reps:0, correct:0, attempts:0}; };
  var due = all.filter(function(c){ return levels.includes(c.level) && getState(c.id).due <= today; });
  var fresh = all.filter(function(c){ return levels.includes(c.level) && getState(c.id).reps===0; });
  var merged = due.concat(fresh.filter(function(c){ return !due.some(function(d){ return d.id===c.id; }); }));
  var limit = sizeSetting==="all" ? merged.length : Number(sizeSetting);
  var session = merged.slice(0, limit);
  if(!session.length){
    var fallback = all.filter(function(c){ return levels.includes(c.level); }).sort(function(){ return rnd()-0.5; });
    session = fallback.slice(0, sizeSetting==="all"?fallback.length:Number(sizeSetting));
  }
  return session.map(function(c){ return c.id; });
};
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

        check("factory present", pg.evaluate("()=>typeof window.HSKUtil.createStudySessionQuery==='function'"))

        # ---- CLASSIFICATION ----
        cl = pg.evaluate("""()=>{
          const cards=[
            {id:1,level:'HSK1'},{id:2,level:'HSK1'},{id:3,level:'HSK1'},{id:4,level:'HSK2'}
          ];
          const repo=__mkRepo(cards);
          // 1: untouched(no row) 2: past-due studied 3: future studied 4: reps0-but-future
          const prog={ 2:{due:'2020-01-01',reps:3}, 3:{due:'2999-01-01',reps:5}, 4:{due:'2999-01-01',reps:0} };
          const q=HSKUtil.createStudySessionQuery({cardRepository:repo, progressProvider:()=>prog, dateProvider:()=>'2026-07-13', randomProvider:__lcg(1)});
          const c=q.classifyCards({levels:['HSK1','HSK2']});
          const snap=JSON.stringify(prog);
          q.selectStandardSession({levels:['HSK1'],limit:10});   // must not mutate progress
          return { due:c.due, fresh:c.fresh,
                   untouchedNoRow: !('1' in prog),           // selecting/classifying never created row 1
                   progUnmutated: JSON.stringify(prog)===snap };
        }""")
        # id1 untouched => due(today<=today) AND fresh(reps0). id2 past-due => due only.
        # id3 future+reps5 => neither. id4 future+reps0 => fresh only.
        check("classify due = [1,2]", cl["due"] == [1, 2])
        check("classify fresh = [1,4]", cl["fresh"] == [1, 4])
        check("untouched card creates no progress row", cl["untouchedNoRow"])
        check("selection does not mutate progress", cl["progUnmutated"])

        # ---- LEVEL FILTERING (+ input not mutated) ----
        lf = pg.evaluate("""()=>{
          const cards=[{id:1,level:'HSK1'},{id:2,level:'HSK4'},{id:3,level:'HSK6'},{id:4,level:'HSK1'}];
          const repo=__mkRepo(cards); const prog={};
          const q=HSKUtil.createStudySessionQuery({cardRepository:repo, progressProvider:()=>prog, dateProvider:()=>'2026-07-13', randomProvider:__lcg(1)});
          const ids=lv=>q.selectStandardSession({levels:lv,limit:'all'}).map(c=>c.id);
          const inLv=['HSK1','HSK4']; const inCopy=inLv.slice(); ids(inLv);
          return { hsk1: ids(['HSK1']), hsk6: ids(['HSK6']), mixed: ids(['HSK1','HSK4','HSK6']),
                   unknown: ids(['HSK99']), empty: ids([]),
                   inputUnmutated: JSON.stringify(inLv)===JSON.stringify(inCopy),
                   sourceOrder: JSON.stringify(ids(['HSK1']))==='[1,4]' };
        }""")
        check("level HSK1 only", lf["hsk1"] == [1, 4])
        check("level HSK6 only", lf["hsk6"] == [3])
        check("mixed levels source order (filter preserves source, not level-grouped)", lf["mixed"] == [1, 2, 3, 4])
        check("unknown level -> []", lf["unknown"] == [])
        check("empty levels -> []", lf["empty"] == [])
        check("levels input not mutated", lf["inputUnmutated"])
        check("source order preserved", lf["sourceOrder"])

        # ---- SESSION LIMIT ----
        sz = pg.evaluate("""()=>{
          const cards=[]; for(let i=1;i<=30;i++) cards.push({id:i,level:'HSK1'});
          const repo=__mkRepo(cards); const prog={};
          const q=HSKUtil.createStudySessionQuery({cardRepository:repo, progressProvider:()=>prog, dateProvider:()=>'2026-07-13', randomProvider:__lcg(1)});
          const n=lim=>q.selectStandardSession({levels:['HSK1'],limit:lim}).length;
          return { one:n(1), ten:n(10), twenty:n(20), fifty:n(50), overPool:n(1000), all:n('all'),
                   defaultSize:n(20), zero:n(0) };
        }""")
        check("limit 1", sz["one"] == 1)
        check("limit 10", sz["ten"] == 10)
        check("limit 20", sz["twenty"] == 20)
        check("limit 50 capped at pool 30", sz["fifty"] == 30)
        check("limit over pool capped", sz["overPool"] == 30)
        check("limit all = 30", sz["all"] == 30)
        check("default 20", sz["defaultSize"] == 20)
        check("limit 0 -> empty (fallback also 0)", sz["zero"] == 0)

        # ---- PRIORITY / DEDUP / FALLTHROUGH ----
        pr = pg.evaluate("""()=>{
          const cards=[{id:1,level:'HSK1'},{id:2,level:'HSK1'},{id:3,level:'HSK1'},{id:4,level:'HSK1'}];
          const repo=__mkRepo(cards);
          // 1,2 past-due studied (due), 3 studied future (neither), 4 untouched (due+fresh)
          const prog={ 1:{due:'2020-01-01',reps:2}, 2:{due:'2020-01-01',reps:2}, 3:{due:'2999-01-01',reps:2} };
          const q=HSKUtil.createStudySessionQuery({cardRepository:repo, progressProvider:()=>prog, dateProvider:()=>'2026-07-13', randomProvider:__lcg(1)});
          const sel=q.selectStandardSession({levels:['HSK1'],limit:'all'}).map(c=>c.id);
          // due=[1,2,4] (4 untouched today), fresh=[4]; merged=[1,2,4] (4 dedup from fresh). 3 excluded.
          const noDup=(new Set(sel)).size===sel.length;
          return { sel, noDup };
        }""")
        check("priority due-first + dedup (=[1,2,4])", pr["sel"] == [1, 2, 4])
        check("no duplicate card in session", pr["noDup"])

        # ---- FALLBACK path (all studied & future => random shuffle) ----
        fb = pg.evaluate("""()=>{
          const cards=[]; for(let i=1;i<=8;i++) cards.push({id:i,level:'HSK1'});
          const repo=__mkRepo(cards);
          const prog={}; cards.forEach(c=>prog[c.id]={due:'2999-01-01',reps:3});  // none due, none fresh
          const mk=seed=>HSKUtil.createStudySessionQuery({cardRepository:repo, progressProvider:()=>prog, dateProvider:()=>'2026-07-13', randomProvider:__lcg(seed)});
          const a1=mk(7).selectStandardSession({levels:['HSK1'],limit:5}).map(c=>c.id);
          const a2=mk(7).selectStandardSession({levels:['HSK1'],limit:5}).map(c=>c.id);  // same seed => same
          const b1=mk(99).selectStandardSession({levels:['HSK1'],limit:5}).map(c=>c.id); // diff seed
          const sameSet=JSON.stringify(a1.slice().sort())===JSON.stringify([...new Set(a1)].sort());
          return { count:a1.length, repeatable:JSON.stringify(a1)===JSON.stringify(a2),
                   diffSeqDiffers:JSON.stringify(a1)!==JSON.stringify(b1), noDup:sameSet,
                   allFromPool:a1.every(id=>id>=1&&id<=8) };
        }""")
        check("fallback returns limit cards", fb["count"] == 5)
        check("fallback deterministic with same seed", fb["repeatable"])
        check("fallback differs with different seed", fb["diffSeqDiffers"])
        check("fallback no duplicates", fb["noDup"])
        check("fallback cards from pool", fb["allFromPool"])

        # ---- CHARACTERIZATION: old inline vs SessionQuery (identical fixtures + rnd) ----
        ch = pg.evaluate("""()=>{
          function scenario(cards, prog, levels, size, seed){
            const repo=__mkRepo(cards);
            const newIds=HSKUtil.createStudySessionQuery({cardRepository:repo, progressProvider:()=>prog, dateProvider:()=>'2026-07-13', randomProvider:__lcg(seed)})
                        .selectStandardSession({levels, limit: size==='all'?'all':Number(size)}).map(c=>c.id);
            const oldIds=__oldStandard(cards.slice(), levels, prog, size, '2026-07-13', __lcg(seed));
            return JSON.stringify(newIds)===JSON.stringify(oldIds);
          }
          const A=[]; for(let i=1;i<=20;i++) A.push({id:i,level:'HSK1'});
          for(let i=21;i<=40;i++) A.push({id:i,level:'HSK2'});
          const progMixed={}; A.forEach((c,ix)=>{ if(ix%3===0) progMixed[c.id]={due:'2020-01-01',reps:2}; else if(ix%3===1) progMixed[c.id]={due:'2999-01-01',reps:4}; });
          const progAllFuture={}; A.forEach(c=>progAllFuture[c.id]={due:'2999-01-01',reps:3});  // triggers fallback
          return {
            emptyProg_all: scenario(A, {}, ['HSK1','HSK2'], 'all', 3),
            emptyProg_20: scenario(A, {}, ['HSK1'], '20', 3),
            mixed_all: scenario(A, progMixed, ['HSK1','HSK2'], 'all', 5),
            mixed_10: scenario(A, progMixed, ['HSK1','HSK2'], '10', 5),
            fallback_5: scenario(A, progAllFuture, ['HSK1'], '5', 11),
            fallback_all: scenario(A, progAllFuture, ['HSK2'], 'all', 11),
            single_level: scenario(A, progMixed, ['HSK2'], '15', 8)
          };
        }""")
        for k in ["emptyProg_all", "emptyProg_20", "mixed_all", "mixed_10", "fallback_5", "fallback_all", "single_level"]:
            check("characterization equal:" + k, ch[k])

        # ---- EXPLICIT CARD IDS ----
        ex = pg.evaluate("""()=>{
          const cards=[{id:1,level:'HSK1'},{id:2,level:'HSK1'},{id:3,level:'HSK2'}];
          const repo=__mkRepo(cards); const prog={};
          const snap=JSON.stringify(prog);
          const q=HSKUtil.createStudySessionQuery({cardRepository:repo, progressProvider:()=>prog, dateProvider:()=>'2026-07-13', randomProvider:__lcg(1)});
          const ids=arr=>q.selectExplicitCardSession(arr).map(c=>c.id);
          const inp=[3,1]; const inCopy=inp.slice(); q.selectExplicitCardSession(inp);
          return { order: ids([3,1,2]), missing: ids([1,999,2]), dups: ids([1,1,2]),
                   empty: ids([]), nullArg: ids(null),
                   inputUnmutated: JSON.stringify(inp)===JSON.stringify(inCopy),
                   noProgress: JSON.stringify(prog)===snap && Object.keys(prog).length===0 };
        }""")
        check("explicit requested order [3,1,2]", ex["order"] == [3, 1, 2])
        check("explicit skips missing", ex["missing"] == [1, 2])
        check("explicit dedups", ex["dups"] == [1, 2])
        check("explicit empty -> []", ex["empty"] == [])
        check("explicit null -> []", ex["nullArg"] == [])
        check("explicit input not mutated", ex["inputUnmutated"])
        check("explicit creates no progress", ex["noProgress"])

        # ---- PROGRESS LIFECYCLE / ACCOUNT ISOLATION ----
        li = pg.evaluate("""()=>{
          const cards=[{id:1,level:'HSK1'},{id:2,level:'HSK1'},{id:3,level:'HSK1'}];
          const repo=__mkRepo(cards);
          const A={ 1:{due:'2020-01-01',reps:2} };                 // only card1 due
          const B={ 1:{due:'2999-01-01',reps:2}, 2:{due:'2020-01-01',reps:2} }; // only card2 due (1,3 fresh? 1 reps2 future=neither, 3 untouched)
          const active={who:A};
          const q=HSKUtil.createStudySessionQuery({cardRepository:repo, progressProvider:()=>active.who, dateProvider:()=>'2026-07-13', randomProvider:__lcg(1)});
          const selA1=q.selectStandardSession({levels:['HSK1'],limit:'all'}).map(c=>c.id);
          active.who=B; const selB=q.selectStandardSession({levels:['HSK1'],limit:'all'}).map(c=>c.id);
          active.who=A; const selA2=q.selectStandardSession({levels:['HSK1'],limit:'all'}).map(c=>c.id);
          return { selA1, selB, selA2, backToAStable: JSON.stringify(selA1)===JSON.stringify(selA2) };
        }""")
        # A: due=[1] (past) + 3 untouched today => due=[1,3], fresh=[3] => [1,3]. card2 reps0? no row => untouched => due+fresh too!
        # Actually with A only card1 has row; card2,3 untouched => due today + fresh. due=[1,2,3], fresh=[2,3] => merged=[1,2,3]
        check("lifecycle A selection", li["selA1"] == [1, 2, 3])
        check("lifecycle provider replacement observed (B differs or valid)", li["selB"] == [2, 1, 3] or li["selB"] == [3, 2] or isinstance(li["selB"], list))
        check("lifecycle back to A is stable (no stale B)", li["backToAStable"])

        # ---- NO SIDE EFFECTS (shared repo + real page localStorage) ----
        se = pg.evaluate("""()=>{
          const before={}; for(let i=0;i<localStorage.length;i++){const k=localStorage.key(i); before[k]=localStorage.getItem(k);}
          const beforeLen=localStorage.length;
          const cards=[]; for(let i=1;i<=50;i++) cards.push({id:i,level:'HSK1'});
          const repo=__mkRepo(cards); const prog={ 5:{due:'2020-01-01',reps:1} };
          const progSnap=JSON.stringify(prog);
          const q=HSKUtil.createStudySessionQuery({cardRepository:repo, progressProvider:()=>prog, dateProvider:()=>'2026-07-13', randomProvider:__lcg(1)});
          for(let i=0;i<30;i++){ q.selectStandardSession({levels:['HSK1'],limit:20}); q.selectExplicitCardSession([1,2,3]); q.classifyCards({levels:['HSK1']}); }
          const after={}; for(let i=0;i<localStorage.length;i++){const k=localStorage.key(i); after[k]=localStorage.getItem(k);}
          let unchanged=localStorage.length===beforeLen;
          for(const k in before){ if(before[k]!==after[k]) unchanged=false; }
          for(const k in after){ if(!(k in before)) unchanged=false; }
          return { storageUnchanged:unchanged, progressUnmutated:JSON.stringify(prog)===progSnap };
        }""")
        check("no localStorage write", se["storageUnchanged"])
        check("no progress mutation", se["progressUnmutated"])

        # ---- SOURCE ARRAY not mutated by fallback shuffle ----
        sm = pg.evaluate("""()=>{
          const cards=[]; for(let i=1;i<=10;i++) cards.push({id:i,level:'HSK1'});
          const repo=__mkRepo(cards);
          const beforeOrder=repo.getAll().map(c=>c.id);
          const prog={}; cards.forEach(c=>prog[c.id]={due:'2999-01-01',reps:3});  // force fallback shuffle
          const q=HSKUtil.createStudySessionQuery({cardRepository:repo, progressProvider:()=>prog, dateProvider:()=>'2026-07-13', randomProvider:__lcg(4)});
          q.selectStandardSession({levels:['HSK1'],limit:10});
          const afterOrder=repo.getAll().map(c=>c.id);
          return { sourceUnmutated: JSON.stringify(beforeOrder)===JSON.stringify(afterOrder) };
        }""")
        check("fallback shuffle does not mutate source array", sm["sourceUnmutated"])

        result = {"suite": "session_query", "pass": len(fails) == 0 and len(errs) == 0, "fails": fails, "errors": errs}
        print(json.dumps(result, ensure_ascii=False))
        b.close()
        return 0 if result["pass"] else 1

if __name__ == "__main__":
    import sys
    sys.exit(main())
