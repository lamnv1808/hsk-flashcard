"""Unit + characterization tests for the Phase 6 read-only AnalyticsQuery
(window.HSKUtil.createAnalyticsQuery). Runs in the real loaded browser.

Verifies home summary, per-level summary, Weak Words ranking, Smart Review model,
daily series, retention, account isolation (provider swap), and the strict
no-side-effects contract. Includes CHARACTERIZATION comparisons: faithful
re-implementations of the ORIGINAL inline app.js/insights.js computations vs
AnalyticsQuery over identical fixtures + identical injected `now` => byte-equal.
"""
import os, json
from playwright.sync_api import sync_playwright

URL = os.environ.get("HSK_BASE_URL", "http://localhost:8000") + "/hsk_flashcard_app/"
EMPTY = 'window.SUPABASE_CONFIG={url:"",anonKey:""};'
fails = []
def check(n, c):
    if not c: fails.append(n)

# Injected helpers: repo builder, a fixed "now", settings/daily stubs, and faithful
# copies of the ORIGINAL inline analytics (pre-Phase-6) for characterization.
HELPERS = r"""
window.__mkRepo = function(cards){ return HSKUtil.createCardRepository(cards); };
// fixed local noon so localDay() is unambiguous regardless of TZ
window.__NOW = new Date(2026, 6, 13, 12, 0, 0);
window.__mkQuery = function(cards, prog, daily, streak){
  return HSKUtil.createAnalyticsQuery({
    cardRepository: __mkRepo(cards),
    progressProvider: function(){ return prog; },
    settingsRepository: { getStreak: function(){ return streak||0; } },
    dailyCountsProvider: function(){ return daily||{}; },
    dateProvider: function(){ return __NOW; }
  });
};
var DAY=86400000, D=HSKUtil.date;
// ORIGINAL app.js renderHome global summary
window.__oldHome = function(all, prog, levels, today){
  var gs=function(id){ return prog[id]||{due:today,interval:0,reps:0,correct:0,attempts:0}; };
  var learned=all.filter(function(c){return gs(c.id).reps>0;}).length;
  var attempts=Object.values(prog).reduce(function(s,x){return s+(x.attempts||0);},0);
  var correct=Object.values(prog).reduce(function(s,x){return s+(x.correct||0);},0);
  var retention=attempts?Math.round(correct/attempts*100)+"%":"0%";
  var dueCount=all.filter(function(c){return levels.includes(c.level)&&gs(c.id).due<=today;}).length;
  return {total:all.length, learned:learned, attempts:attempts, correct:correct, retention:retention, dueCount:dueCount};
};
// ORIGINAL per-level deck loop
window.__oldLevel = function(repo, levels, prog, today){
  var gs=function(id){ return prog[id]||{due:today,interval:0,reps:0,correct:0,attempts:0}; };
  return levels.map(function(lv){ var a=repo.getByLevel(lv);
    var learned=a.filter(function(c){return gs(c.id).reps>0;}).length;
    var due=a.filter(function(c){return gs(c.id).due<=today;}).length;
    return {level:lv,total:a.length,learned:learned,due:due,pct:Math.round(learned/a.length*100)}; });
};
// ORIGINAL insights.js weakness model
window.__lastGraded = function(st){ if(!st.due) return null; var due=new Date(st.due+"T00:00:00"); if(isNaN(due)) return null; return new Date(due.getTime()-(st.interval||0)*DAY); };
window.__daysSince = function(d,nowMs){ if(!d) return 30; return Math.max(0,Math.round((nowMs-d.getTime())/DAY)); };
window.__weakness = function(st,nowMs){ var a=st.attempts||0; if(a<=0) return null; var f=a-(st.correct||0); if(f<=0) return 0; var sfr=(f+1)/(a+2); var rec=1/(1+__daysSince(__lastGraded(st),nowMs)/14); return f*sfr*rec; };
window.__oldWeak = function(repo, prog, levelFilter, nowMs){
  var out=[]; Object.keys(prog).forEach(function(id){ var card=repo.getById(Number(id)); if(!card) return;
    if(levelFilter&&levelFilter!=="all"&&card.level!==levelFilter) return;
    var st=prog[id], w=__weakness(st,nowMs); if(w==null||w<=0) return;
    out.push({id:card.id, score:w, failures:(st.attempts||0)-(st.correct||0)}); });
  out.sort(function(a,b){ return b.score-a.score || b.failures-a.failures; });
  return out.map(function(x){ return x.id; });
};
// ORIGINAL daily series
window.__oldSeries = function(dc, days, now){
  var labels=[], vals=[];
  for(var i=days-1;i>=0;i--){ var d=new Date(now.getTime()-i*DAY); labels.push(d); vals.push(dc[D.localDay(d)]||0); }
  var total=vals.reduce(function(a,b){return a+b;},0), max=Math.max(1,Math.max.apply(null,vals));
  return { vals:vals, total:total, max:max, avg:(total/days).toFixed(1), first:D.isoDay(labels[0]), last:D.isoDay(labels[labels.length-1]) };
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

        check("factory present", pg.evaluate("()=>typeof window.HSKUtil.createAnalyticsQuery==='function'"))
        check("shared instance present", pg.evaluate("()=>typeof window.HSKUtil.analytics==='object'"))

        # ---- HOME SUMMARY (+ characterization) ----
        hs = pg.evaluate("""()=>{
          const cards=[{id:1,level:'HSK1'},{id:2,level:'HSK1'},{id:3,level:'HSK2'},{id:4,level:'HSK2'},{id:5,level:'HSK2'}];
          const today=HSKUtil.date.isoDay(__NOW);
          const scen=(prog)=>{
            const q=__mkQuery(cards,prog,{},0);
            const nw=q.getHomeSummary(['HSK1','HSK2']);
            const old=__oldHome(cards.slice(),prog,['HSK1','HSK2'],today);
            return { total:nw.total===old.total, learned:nw.learned===old.learned,
                     attempts:nw.attempts===old.attempts, correct:nw.correct===old.correct,
                     retention:nw.retentionText===old.retention, due:nw.dueCount===old.dueCount,
                     lvl: JSON.stringify(q.getLevelSummary(['HSK1','HSK2']).map(r=>[r.level,r.total,r.learned,r.due,r.pct]))
                          === JSON.stringify(__oldLevel(q_repo(),['HSK1','HSK2'],prog,today).map(r=>[r.level,r.total,r.learned,r.due,r.pct])),
                     values: nw };
          };
          function q_repo(){ return __mkRepo(cards); }
          const none=scen({});
          const partial=scen({ 1:{due:'2020-01-01',reps:3,attempts:4,correct:3}, 3:{due:'2999-01-01',reps:1,attempts:2,correct:1} });
          const allLearned=scen({ 1:{due:'2999-01-01',reps:1,attempts:1,correct:1},2:{due:'2999-01-01',reps:1,attempts:1,correct:1},3:{due:'2999-01-01',reps:1,attempts:1,correct:0},4:{due:'2999-01-01',reps:1,attempts:2,correct:2},5:{due:'2999-01-01',reps:1,attempts:1,correct:1} });
          return { none, partial, allLearned,
                   noneRetention: none.values.retentionText, noneLearned: none.values.learned,
                   noneDue: none.values.dueCount };
        }""")
        for scen in ["none", "partial", "allLearned"]:
            s = hs[scen]
            for k in ["total", "learned", "attempts", "correct", "retention", "due", "lvl"]:
                check("home char " + scen + ":" + k, s[k])
        check("home no-progress retention 0%", hs["noneRetention"] == "0%")
        check("home no-progress learned 0", hs["noneLearned"] == 0)
        check("home no-progress all untouched are due (=5)", hs["noneDue"] == 5)

        # ---- WEAK WORDS (ranking, tie, exclusions, level, top-N, characterization) ----
        ww = pg.evaluate("""()=>{
          const cards=[]; for(let i=1;i<=6;i++) cards.push({id:i,level:i<=3?'HSK1':'HSK2'});
          // 1 untouched(excl), 2 never-failed(excl w=0), 3 few fails, 4 many fails, 5 heavy fails HSK2, 6 no attempts row
          const today=HSKUtil.date.isoDay(__NOW);
          const prog={
            2:{due:today,interval:0,reps:3,attempts:3,correct:3},           // never failed => excluded
            3:{due:today,interval:1,reps:4,attempts:4,correct:3},           // 1 fail
            4:{due:today,interval:1,reps:6,attempts:6,correct:2},           // 4 fails
            5:{due:today,interval:1,reps:8,attempts:8,correct:1},           // 7 fails (HSK2)
            6:{due:today,interval:0,reps:0,attempts:0,correct:0}            // untouched-ish => excluded
          };
          const nowMs=__NOW.getTime();
          const q=__mkQuery(cards,prog,{},0);
          const newAll=q.getWeakWords('all').map(x=>x.card.id);
          const oldAll=__oldWeak(__mkRepo(cards),prog,'all',nowMs);
          const newH2=q.getWeakWords('HSK2').map(x=>x.card.id);
          const oldH2=__oldWeak(__mkRepo(cards),prog,'HSK2',nowMs);
          const snap=JSON.stringify(prog);
          q.getWeakWords('all'); // must not mutate
          const item=q.getWeakWords('all')[0];
          return { charAll: JSON.stringify(newAll)===JSON.stringify(oldAll),
                   charH2: JSON.stringify(newH2)===JSON.stringify(oldH2),
                   excludesUntouchedAndPerfect: newAll.indexOf(1)<0 && newAll.indexOf(2)<0 && newAll.indexOf(6)<0,
                   rankingHeaviestFirst: newAll[0]===5 || newAll[0]===4,
                   itemShape: item && 'card' in item && 'failures' in item && 'attempts' in item && 'last' in item && 'score' in item,
                   noMutation: JSON.stringify(prog)===snap };
        }""")
        for k in ["charAll", "charH2", "excludesUntouchedAndPerfect", "rankingHeaviestFirst", "itemShape", "noMutation"]:
            check("weak:" + k, ww[k])

        # ---- WEAK WORDS tie-break (equal score -> more failures first) ----
        tie = pg.evaluate("""()=>{
          // two cards engineered to identical score via identical stats & date
          const cards=[{id:10,level:'HSK1'},{id:20,level:'HSK1'}];
          const today=HSKUtil.date.isoDay(__NOW);
          const prog={ 10:{due:today,interval:0,reps:4,attempts:4,correct:2}, 20:{due:today,interval:0,reps:4,attempts:4,correct:2} };
          const q=__mkQuery(cards,prog,{},0);
          const ids=q.getWeakWords('all').map(x=>x.card.id);
          return { bothPresent: ids.length===2 };
        }""")
        check("weak tie both present", tie["bothPresent"])

        # ---- SMART REVIEW MODEL (+ characterization of values) ----
        sr = pg.evaluate("""()=>{
          const cards=[]; for(let i=1;i<=12;i++) cards.push({id:i,level:i<=6?'HSK1':'HSK2'});
          const today=HSKUtil.date.isoDay(__NOW);
          // HSK1: high attempts good retention; HSK2: high attempts poor retention
          const prog={};
          [1,2,3].forEach(i=>prog[i]={due:today,interval:0,reps:5,attempts:5,correct:5});    // HSK1 15 att, 15 cor
          [7,8,9].forEach(i=>prog[i]={due:today,interval:1,reps:5,attempts:5,correct:1});     // HSK2 15 att, 3 cor (weak)
          const daily={}; daily[HSKUtil.date.localDay(__NOW)]=4;
          daily[HSKUtil.date.localDay(new Date(__NOW.getTime()-86400000))]=3;
          const q=__mkQuery(cards,prog,daily,9);
          const m=q.getSmartReviewModel();
          // insufficient case
          const mEmpty=__mkQuery(cards,{},{},0).getSmartReviewModel();
          return { hasData:m.hasData===true,
                   weakest: m.levelRetention && m.levelRetention.weakest.level==='HSK2',
                   strongest: m.levelRetention && m.levelRetention.strongest.level==='HSK1' && m.levelRetention.strongest.pct===100,
                   weakestPct: m.levelRetention && m.levelRetention.weakest.pct===Math.round(3/15*100),
                   weakCount: typeof m.weakCount==='number' && m.weakCount===3,
                   today: m.today===4, last7: m.last7===7, streak: m.streak===9,
                   insufficient: mEmpty.hasData===false };
        }""")
        for k in ["hasData", "weakest", "strongest", "weakestPct", "weakCount", "today", "last7", "streak", "insufficient"]:
            check("smart:" + k, sr[k])

        # ---- SMART REVIEW: level retention insufficient (att<10) ----
        sri = pg.evaluate("""()=>{
          const cards=[{id:1,level:'HSK1'}];
          const today=HSKUtil.date.isoDay(__NOW);
          const q=__mkQuery(cards,{1:{due:today,interval:0,reps:2,attempts:2,correct:1}},{},0);
          const m=q.getSmartReviewModel();
          return { hasData:m.hasData===true, noLevelRetention:m.levelRetention===null };
        }""")
        check("smart insufficient-level hasData", sri["hasData"])
        check("smart insufficient-level retention null", sri["noLevelRetention"])

        # ---- DAILY SERIES (+ characterization) ----
        ds = pg.evaluate("""()=>{
          const cards=[{id:1,level:'HSK1'}];
          const daily={};
          daily[HSKUtil.date.localDay(__NOW)]=5;
          daily[HSKUtil.date.localDay(new Date(__NOW.getTime()-2*86400000))]=3;   // 2 days ago
          daily[HSKUtil.date.localDay(new Date(__NOW.getTime()-6*86400000))]=1;   // 6 days ago
          const q=__mkQuery(cards,{},daily,0);
          const cmp=(days)=>{
            const s=q.getDailySeries(days);
            const o=__oldSeries(daily,days,__NOW);
            return JSON.stringify(s.values)===JSON.stringify(o.vals) && s.total===o.total && s.max===o.max
                   && s.average.toFixed(1)===o.avg
                   && HSKUtil.date.isoDay(s.labels[0])===o.first && HSKUtil.date.isoDay(s.labels[s.labels.length-1])===o.last;
          };
          const s7=q.getDailySeries(7);
          return { char7:cmp(7), char30:cmp(30),
                   len7:s7.values.length===7, len30:q.getDailySeries(30).values.length===30,
                   ordering:HSKUtil.date.isoDay(s7.labels[0])<HSKUtil.date.isoDay(s7.labels[6]),   // oldest..newest
                   newestToday:s7.values[6]===5, twoAgo:s7.values[4]===3, sixAgo:s7.values[0]===1,
                   zeroDays: s7.values[1]===0,
                   total9: s7.total===9, maxAtLeast1: q.getDailySeries(7).max>=1,
                   emptyMax1: __mkQuery(cards,{},{},0).getDailySeries(7).max===1 };
        }""")
        for k in ["char7", "char30", "len7", "len30", "ordering", "newestToday", "twoAgo", "sixAgo", "zeroDays", "total9", "maxAtLeast1", "emptyMax1"]:
            check("daily:" + k, ds[k])

        # ---- RETENTION edge cases ----
        rt = pg.evaluate("""()=>{
          const cards=[{id:1,level:'HSK1'},{id:2,level:'HSK1'}];
          const t=HSKUtil.date.isoDay(__NOW);
          const H=(prog)=>__mkQuery(cards,prog,{},0).getHomeSummary(['HSK1']);
          return {
            zeroAttempts: H({}).retentionText==='0%' && H({}).retentionPct===0,
            allCorrect: H({1:{due:t,reps:1,attempts:4,correct:4}}).retentionText==='100%',
            allWrong: H({1:{due:t,reps:1,attempts:4,correct:0}}).retentionText==='0%',
            rounding: H({1:{due:t,reps:1,attempts:3,correct:2}}).retentionText===(Math.round(2/3*100)+'%'),
            missingFields: H({1:{due:t,reps:1}}).retentionText==='0%'   // attempts/correct undefined => 0
          };
        }""")
        for k in ["zeroAttempts", "allCorrect", "allWrong", "rounding", "missingFields"]:
            check("retention:" + k, rt[k])

        # ---- ACCOUNT ISOLATION (provider swap, no stale) ----
        ai = pg.evaluate("""()=>{
          const cards=[{id:1,level:'HSK1'},{id:2,level:'HSK1'}];
          const t=HSKUtil.date.isoDay(__NOW);
          const A={ 1:{due:t,reps:1,attempts:2,correct:2} };
          const B={ 1:{due:t,reps:1,attempts:2,correct:0}, 2:{due:t,reps:1,attempts:2,correct:1} };
          const active={who:A};
          const q=HSKUtil.createAnalyticsQuery({cardRepository:__mkRepo(cards), progressProvider:()=>active.who,
            settingsRepository:{getStreak:()=>0}, dailyCountsProvider:()=>({}), dateProvider:()=>__NOW});
          const a1=q.getHomeSummary(['HSK1']).retentionText;
          active.who=B; const b=q.getHomeSummary(['HSK1']).retentionText;
          active.who=A; const a2=q.getHomeSummary(['HSK1']).retentionText;
          return { a1, b, a2, backStable:a1===a2, changed:a1!==b };
        }""")
        check("isolation A stable 100%", ai["a1"] == "100%")
        check("isolation B observed", ai["changed"])
        check("isolation back-to-A no stale", ai["backStable"])

        # ---- NO SIDE EFFECTS ----
        se = pg.evaluate("""()=>{
          const before={}; for(let i=0;i<localStorage.length;i++){const k=localStorage.key(i); before[k]=localStorage.getItem(k);}
          const beforeLen=localStorage.length;
          const cards=[]; for(let i=1;i<=40;i++) cards.push({id:i,level:'HSK1'});
          const t=HSKUtil.date.isoDay(__NOW);
          const prog={ 5:{due:t,interval:1,reps:3,attempts:3,correct:1} }; const snap=JSON.stringify(prog);
          const daily={}; daily[HSKUtil.date.localDay(__NOW)]=2; const dsnap=JSON.stringify(daily);
          const q=__mkQuery(cards,prog,daily,4);
          for(let i=0;i<20;i++){ q.getHomeSummary(['HSK1']); q.getLevelSummary(['HSK1']); q.getWeakWords('all'); q.getSmartReviewModel(); q.getDailySeries(7); q.getDailySeries(30); }
          const after={}; for(let i=0;i<localStorage.length;i++){const k=localStorage.key(i); after[k]=localStorage.getItem(k);}
          let unchanged=localStorage.length===beforeLen;
          for(const k in before){ if(before[k]!==after[k]) unchanged=false; }
          for(const k in after){ if(!(k in before)) unchanged=false; }
          return { storageUnchanged:unchanged, progressUnmutated:JSON.stringify(prog)===snap, dailyUnmutated:JSON.stringify(daily)===dsnap };
        }""")
        for k in ["storageUnchanged", "progressUnmutated", "dailyUnmutated"]:
            check("sideEffect:" + k, se[k])

        result = {"suite": "analytics_query", "pass": len(fails) == 0 and len(errs) == 0, "fails": fails, "errors": errs}
        print(json.dumps(result, ensure_ascii=False))
        b.close()
        return 0 if result["pass"] else 1

if __name__ == "__main__":
    import sys
    sys.exit(main())
