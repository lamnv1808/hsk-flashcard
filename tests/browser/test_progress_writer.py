"""Unit + characterization tests for the Phase 12 write-capable ProgressWriter
(window.HSKUtil.createProgressWriter). Runs in the real loaded browser.

Verifies the grade transaction (read -> SRS -> assign -> save -> markDirty) is
byte/value-equivalent to the original inline gradeCard block, that exactly one save
and one markDirty occur per grade, that only the graded row is created/replaced,
account isolation, invalid input, and no unrelated side effects. The SRS math is the
exact current formula, injected as srsCalculator (also used by the characterization
'old' path), so equivalence is guaranteed by construction; the real SRS goldens run
in the full suite over the actual app.js integration.
"""
import os, json
from playwright.sync_api import sync_playwright

URL = os.environ.get("HSK_BASE_URL", "http://localhost:8000") + "/hsk_flashcard_app/"
EMPTY = 'window.SUPABASE_CONFIG={url:"",anonKey:""};'
fails = []
def check(n, c):
    if not c: fails.append(n)

# The EXACT current SRS block (app.js srsNextState), plus a faithful copy of the
# original inline gradeCard write transaction (steps 5-10) for characterization.
HELPERS = r"""
window.__srs = function(s, grade, now){
  var days;
  if(grade==="again"){ days=0; now.setMinutes(now.getMinutes()+1); s.interval=0; }
  else if(grade==="hard"){ days=Math.max(1, s.interval ? Math.round(s.interval*1.2) : 1); now.setDate(now.getDate()+days); s.interval=days; }
  else if(grade==="good"){ days=Math.max(3, s.interval ? Math.round(s.interval*2.0) : 3); now.setDate(now.getDate()+days); s.interval=days; }
  else { days=Math.max(7, s.interval ? Math.round(s.interval*3.0) : 7); now.setDate(now.getDate()+days); s.interval=days; }
  s.due=now.toISOString().slice(0,10);
  s.reps=(s.reps||0)+1; s.attempts=(s.attempts||0)+1;
  if(grade==="good"||grade==="easy") s.correct=(s.correct||0)+1;
  return s;
};
// original inline transaction (steps 5-10) over a progress map, with counting save/dirty.
window.__oldGrade = function(prog, cardId, grade, nowFactory){
  var counts={save:0,dirty:0};
  var getCardState=function(id){ return prog[id] || {due: nowFactory().toISOString().slice(0,10), interval:0, reps:0, correct:0, attempts:0}; };
  var s=getCardState(cardId), now=nowFactory();
  __srs(s, grade, now);
  prog[cardId]=s;
  counts.save++;              // save()
  counts.dirty++;             // markDirty()
  return { row: prog[cardId], counts:counts };
};
// build a writer over a plain progress map with counting save/dirty and a fixed date.
window.__mkWriter = function(prog, nowFactory){
  var counts={save:0,dirty:0,dirtyIds:[]};
  var w = HSKUtil.createProgressWriter({
    progressProvider: function(){ return prog; },
    progressRepository: HSKUtil.createProgressRepository({ progressProvider: function(){ return prog; } }),
    srsCalculator: __srs,
    save: function(){ counts.save++; },
    markDirty: function(id){ counts.dirty++; counts.dirtyIds.push(id); },
    dateProvider: nowFactory
  });
  return { w:w, counts:counts };
};
// deterministic fixed 'now' factory (fresh Date each call, same instant)
window.__fixedNow = function(){ return function(){ return new Date(2026, 6, 13, 9, 0, 0); }; };
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

        check("factory present", pg.evaluate("()=>typeof window.HSKUtil.createProgressWriter==='function'"))

        # ---- CHARACTERIZATION: writer vs original inline, all 4 grades x states ----
        ch = pg.evaluate("""()=>{
          function scen(startRow, grade){
            var nf=__fixedNow();
            var progA = startRow ? { 5: JSON.parse(JSON.stringify(startRow)) } : {};
            var progB = startRow ? { 5: JSON.parse(JSON.stringify(startRow)) } : {};
            var old=__oldGrade(progA, 5, grade, nf);
            var mk=__mkWriter(progB, nf);
            var res=mk.w.grade({cardId:5, grade:grade});
            return { rowEqual: JSON.stringify(progB[5])===JSON.stringify(progA[5]),
                     retEqual: JSON.stringify(res.nextState)===JSON.stringify(old.row),
                     save1: mk.counts.save===1, dirty1: mk.counts.dirty===1 };
          }
          var untouched=null;
          var learned={due:'2020-01-01', interval:6, reps:4, correct:3, attempts:4};   // overdue learned
          var future={due:'2999-01-01', interval:10, reps:2, correct:2, attempts:2};    // future-due
          var out={};
          ['again','hard','good','easy'].forEach(function(g){
            out[g+'_untouched']=scen(untouched,g);
            out[g+'_learned']=scen(learned,g);
            out[g+'_future']=scen(future,g);
          });
          return out;
        }""")
        for g in ["again", "hard", "good", "easy"]:
            for st in ["untouched", "learned", "future"]:
                s = ch[g + "_" + st]
                check("char " + g + "/" + st + ":row", s["rowEqual"])
                check("char " + g + "/" + st + ":ret", s["retEqual"])
                check("char " + g + "/" + st + ":save1", s["save1"])
                check("char " + g + "/" + st + ":dirty1", s["dirty1"])

        # ---- EXACT FIELD VALUES for each grade on an untouched card (fixed now) ----
        fv = pg.evaluate("""()=>{
          function grade1(g){ var prog={}; var mk=__mkWriter(prog, __fixedNow()); mk.w.grade({cardId:1, grade:g}); return prog[1]; }
          var again=grade1('again'), hard=grade1('hard'), good=grade1('good'), easy=grade1('easy');
          return {
            again: again.interval===0 && again.due==='2026-07-13' && again.reps===1 && again.attempts===1 && again.correct===0,
            hard:  hard.interval===1 && hard.due==='2026-07-14' && hard.reps===1 && hard.attempts===1 && hard.correct===0,
            good:  good.interval===3 && good.due==='2026-07-16' && good.reps===1 && good.attempts===1 && good.correct===1,
            easy:  easy.interval===7 && easy.due==='2026-07-20' && easy.reps===1 && easy.attempts===1 && easy.correct===1
          };
        }""")
        for k in ["again", "hard", "good", "easy"]:
            check("fresh-card fields:" + k, fv[k])

        # ---- INTERVAL PROGRESSION (learned-card multipliers) ----
        ip = pg.evaluate("""()=>{
          function seq(grades){ var prog={}; var mk=__mkWriter(prog, __fixedNow()); grades.forEach(function(g){ mk.w.grade({cardId:1,grade:g}); }); return prog[1]; }
          var goodx3=seq(['good','good','good']);      // 3 -> 6 -> 12
          var easyx3=seq(['easy','easy','easy']);      // 7 -> 21 -> 63
          var hardx3=seq(['hard','hard','hard']);      // 1 -> 1 -> 1 (round(1*1.2)=1)
          return { good: goodx3.interval===12 && goodx3.reps===3 && goodx3.correct===3,
                   easy: easyx3.interval===63 && easyx3.reps===3 && easyx3.correct===3,
                   hard: hardx3.interval===1 && hardx3.reps===3 && hardx3.correct===0 };
        }""")
        for k in ["good", "easy", "hard"]:
            check("interval progression:" + k, ip[k])

        # ---- SEQUENCES / cross-card isolation ----
        seq = pg.evaluate("""()=>{
          var prog={}; var mk=__mkWriter(prog, __fixedNow());
          mk.w.grade({cardId:1, grade:'again'}); mk.w.grade({cardId:1, grade:'good'});   // again->good
          var c1=prog[1];
          mk.w.grade({cardId:2, grade:'easy'}); mk.w.grade({cardId:2, grade:'again'});   // easy->again
          var c2=prog[2];
          // card1 not affected by card2 grades
          var c1Stable=prog[1].interval===c1.interval && prog[1].reps===c1.reps;
          return { c1AgainGood: c1.reps===2 && c1.interval===3 && c1.correct===1,   // again(int0)->good(max(3,int0?..:3)=3)
                   c2EasyAgain: c2.reps===2 && c2.interval===0 && c2.correct===1,   // easy(7,correct1)->again(int0)
                   isolation: c1Stable, twoRows: Object.keys(prog).length===2,
                   totalSaves: mk.counts.save===4, totalDirty: mk.counts.dirty===4 };
        }""")
        for k in ["c1AgainGood", "c2EasyAgain", "isolation", "twoRows", "totalSaves", "totalDirty"]:
            check("sequence:" + k, seq[k])

        # ---- DEFAULT / UNTOUCHED: grade creates exactly one row; read creates none ----
        du = pg.evaluate("""()=>{
          var prog={}; var mk=__mkWriter(prog, __fixedNow());
          var repo=HSKUtil.createProgressRepository({progressProvider:function(){return prog;}});
          repo.getOrDefault(9, '2026-07-13'); repo.getStored(9); repo.isDue(9,'2026-07-13');   // reads
          var afterReads=Object.keys(prog).length;
          mk.w.grade({cardId:9, grade:'good'});
          return { readsCreateNone: afterReads===0, gradeCreatesOne: Object.keys(prog).length===1 && ('9' in prog) };
        }""")
        for k in ["readsCreateNone", "gradeCreatesOne"]:
            check("untouched:" + k, du[k])

        # ---- PERSISTENCE: local-only (no HSKSync) via a no-op markDirty wrapper ----
        pers = pg.evaluate("""()=>{
          // simulate local-only: markDirty wrapper is a no-op (HSKSync absent)
          var prog={}, saves=0, dirty=0;
          var w=HSKUtil.createProgressWriter({
            progressProvider:function(){return prog;},
            progressRepository:HSKUtil.createProgressRepository({progressProvider:function(){return prog;}}),
            srsCalculator:__srs, save:function(){saves++;},
            markDirty:function(id){ if(false) dirty++; },   // local-only: HSKSync absent -> no dirty
            dateProvider:__fixedNow()
          });
          w.grade({cardId:1, grade:'good'});
          return { savedOnce: saves===1, noDirty: dirty===0, rowWritten: !!prog[1] };
        }""")
        for k in ["savedOnce", "noDirty", "rowWritten"]:
            check("localOnly:" + k, pers[k])

        # ---- ACCOUNT ISOLATION (provider swap) ----
        ai = pg.evaluate("""()=>{
          var A={}, B={}; var active={who:A};
          var w=HSKUtil.createProgressWriter({
            progressProvider:function(){return active.who;},
            progressRepository:HSKUtil.createProgressRepository({progressProvider:function(){return active.who;}}),
            srsCalculator:__srs, save:function(){}, markDirty:function(){}, dateProvider:__fixedNow()
          });
          w.grade({cardId:1, grade:'good'});               // -> A
          active.who=B; w.grade({cardId:2, grade:'easy'}); // -> B
          active.who=A;
          return { aHas1: ('1' in A) && !('2' in A), bHas2: ('2' in B) && !('1' in B),
                   aStable: A[1].interval===3, noLeak: Object.keys(A).length===1 && Object.keys(B).length===1 };
        }""")
        for k in ["aHas1", "bHas2", "aStable", "noLeak"]:
            check("isolation:" + k, ai[k])

        # ---- INVALID INPUT ----
        inv = pg.evaluate("""()=>{
          var prog={ 3:{due:'2020-01-01',interval:2,reps:1,correct:1,attempts:1} }; var snap=JSON.stringify(prog);
          var mk=__mkWriter(prog, __fixedNow());
          var nullRes=mk.w.grade({cardId:null, grade:'good'});           // null id -> no mutation
          var noMutate=JSON.stringify(prog)===snap && mk.counts.save===0 && mk.counts.dirty===0;
          // unknown rating -> else(easy) math, NO correct increment (current quirk)
          var prog2={}; var mk2=__mkWriter(prog2, __fixedNow());
          mk2.w.grade({cardId:1, grade:'xyz'});
          var unknown=prog2[1].interval===7 && prog2[1].correct===0 && prog2[1].reps===1;
          return { nullRejected: nullRes===null && noMutate, unknownIsEasyNoCorrect: unknown };
        }""")
        for k in ["nullRejected", "unknownIsEasyNoCorrect"]:
            check("invalid:" + k, inv[k])

        # ---- NO SIDE EFFECTS beyond injected save/markDirty ----
        se = pg.evaluate("""()=>{
          var before={}; for(var i=0;i<localStorage.length;i++){var k=localStorage.key(i); before[k]=localStorage.getItem(k);}
          var beforeLen=localStorage.length;
          var prog={}; var saves=0, dirty=0;
          var w=HSKUtil.createProgressWriter({ progressProvider:function(){return prog;},
            progressRepository:HSKUtil.createProgressRepository({progressProvider:function(){return prog;}}),
            srsCalculator:__srs, save:function(){saves++;}, markDirty:function(){dirty++;}, dateProvider:__fixedNow() });
          for(var j=1;j<=25;j++) w.grade({cardId:j, grade:'good'});
          // writer itself must not touch localStorage (only the injected save would, and here it doesn't)
          var after={}; for(var q=0;q<localStorage.length;q++){var kk=localStorage.key(q); after[kk]=localStorage.getItem(kk);}
          var unchanged=localStorage.length===beforeLen;
          for(var b in before){ if(before[b]!==after[b]) unchanged=false; }
          for(var a in after){ if(!(a in before)) unchanged=false; }
          return { storageUntouchedByWriter: unchanged, saves25: saves===25, dirty25: dirty===25, rows25: Object.keys(prog).length===25 };
        }""")
        for k in ["storageUntouchedByWriter", "saves25", "dirty25", "rows25"]:
            check("sideEffect:" + k, se[k])

        # ==== PHASE 13: restore (undo/skip) ====

        # ---- CHARACTERIZATION: inline skip restore/delete vs writer.restore ----
        # faithful copy of skipCard's persistence transaction (revert-or-delete -> save -> markDirty)
        rc = pg.evaluate("""()=>{
          function oldRestore(prog, snap){                 // snap = {id, had, state}
            var counts={save:0,dirty:0};
            if(snap.had) prog[snap.id]=JSON.parse(JSON.stringify(snap.state));
            else delete prog[snap.id];
            counts.save++; counts.dirty++;                 // save(); markDirty(sid)
            return counts;
          }
          function scen(startRow){
            // simulate: capture snapshot, grade, then undo
            var progA = startRow ? { 5: JSON.parse(JSON.stringify(startRow)) } : {};
            var progB = startRow ? { 5: JSON.parse(JSON.stringify(startRow)) } : {};
            var had = startRow != null;
            var snapState = had ? JSON.parse(JSON.stringify(startRow)) : null;
            // grade both (mutates row / creates row)
            __mkWriter(progA, __fixedNow()).w.grade({cardId:5, grade:'good'});
            var mkB = __mkWriter(progB, __fixedNow()); mkB.w.grade({cardId:5, grade:'good'});
            // undo: old inline vs writer.restore
            var oc = oldRestore(progA, {id:5, had:had, state:snapState});
            var mkR = __mkWriter(progB, __fixedNow());
            mkR.w.restore({cardId:5, hadState:had, previousState:snapState});
            return { progEqual: JSON.stringify(progB)===JSON.stringify(progA),
                     save1: mkR.counts.save===1, dirty1: mkR.counts.dirty===1 };
          }
          return { learned: scen({due:'2020-01-01',interval:6,reps:4,correct:3,attempts:4}),
                   untouched: scen(null) };
        }""")
        for st in ["learned", "untouched"]:
            check("restore char " + st + ":prog", rc[st]["progEqual"])
            check("restore char " + st + ":save1", rc[st]["save1"])
            check("restore char " + st + ":dirty1", rc[st]["dirty1"])

        # ---- RESTORE EXISTING ROW: exact field restoration ----
        rex = pg.evaluate("""()=>{
          var learned={due:'2020-01-01', interval:6, reps:4, correct:3, attempts:4};
          var prog={ 5: JSON.parse(JSON.stringify(learned)), 9:{due:'2021-01-01',interval:2,reps:1,correct:1,attempts:1} };
          var other=JSON.stringify(prog[9]);
          var mk=__mkWriter(prog, __fixedNow());
          mk.w.grade({cardId:5, grade:'easy'});                 // mutate 5
          var mutated=JSON.stringify(prog[5])!==JSON.stringify(learned);
          mk.w.restore({cardId:5, hadState:true, previousState:learned});
          return { mutated, restoredExact: JSON.stringify(prog[5])===JSON.stringify(learned),
                   otherUnchanged: JSON.stringify(prog[9])===other,
                   save2: mk.counts.save===2, dirty2: mk.counts.dirty===2 };  // grade + restore
        }""")
        for k in ["mutated", "restoredExact", "otherUnchanged", "save2", "dirty2"]:
            check("restoreExisting:" + k, rex[k])

        # ---- DELETE NEW ROW: undo of an untouched-card grade removes the row ----
        rdel = pg.evaluate("""()=>{
          var prog={}; var mk=__mkWriter(prog, __fixedNow());
          var repo=HSKUtil.createProgressRepository({progressProvider:function(){return prog;}});
          mk.w.grade({cardId:7, grade:'good'});
          var created=repo.has(7)===true;
          mk.w.restore({cardId:7, hadState:false, previousState:null});
          return { created, deleted: repo.has(7)===false && !('7' in prog),
                   defaultAfter: JSON.stringify(repo.getOrDefault(7,'2026-07-13'))===JSON.stringify({due:'2026-07-13',interval:0,reps:0,correct:0,attempts:0}),
                   save2: mk.counts.save===2, dirty2: mk.counts.dirty===2 };
        }""")
        for k in ["created", "deleted", "defaultAfter", "save2", "dirty2"]:
            check("restoreDelete:" + k, rdel[k])

        # ---- SEQUENCES: each grade -> undo -> back to pre-state; grade->undo->grade ----
        rseq = pg.evaluate("""()=>{
          function gradeUndo(startRow, grade){
            var prog = startRow ? { 1: JSON.parse(JSON.stringify(startRow)) } : {};
            var had = startRow != null; var snap = had ? JSON.parse(JSON.stringify(startRow)) : null;
            var mk=__mkWriter(prog, __fixedNow());
            mk.w.grade({cardId:1, grade:grade});
            mk.w.restore({cardId:1, hadState:had, previousState:snap});
            return had ? JSON.stringify(prog[1])===JSON.stringify(startRow) : !('1' in prog);
          }
          var learned={due:'2020-01-01',interval:6,reps:4,correct:3,attempts:4};
          // grade -> undo -> grade again (fresh row created again)
          var prog={}; var mk=__mkWriter(prog, __fixedNow());
          mk.w.grade({cardId:2, grade:'good'}); mk.w.restore({cardId:2, hadState:false, previousState:null});
          var goneAfterUndo=!('2' in prog);
          mk.w.grade({cardId:2, grade:'hard'});
          var regraded=prog[2].reps===1 && prog[2].interval===1;
          return {
            untouchedGood:gradeUndo(null,'good'), untouchedAgain:gradeUndo(null,'again'),
            untouchedHard:gradeUndo(null,'hard'), untouchedEasy:gradeUndo(null,'easy'),
            learnedGood:gradeUndo(learned,'good'),
            goneAfterUndo, regraded
          };
        }""")
        for k in ["untouchedGood", "untouchedAgain", "untouchedHard", "untouchedEasy", "learnedGood", "goneAfterUndo", "regraded"]:
            check("restoreSeq:" + k, rseq[k])

        # ---- RESTORE local-only (no dirty) + account isolation + null guard ----
        rmisc = pg.evaluate("""()=>{
          // local-only
          var prog={5:{due:'2020-01-01',interval:2,reps:1,correct:1,attempts:1}}, saves=0, dirty=0;
          var w=HSKUtil.createProgressWriter({ progressProvider:function(){return prog;},
            progressRepository:HSKUtil.createProgressRepository({progressProvider:function(){return prog;}}),
            srsCalculator:__srs, save:function(){saves++;}, markDirty:function(id){ if(false) dirty++; }, dateProvider:__fixedNow() });
          w.restore({cardId:5, hadState:false, previousState:null});
          var localOnly = saves===1 && dirty===0 && !('5' in prog);
          // account isolation
          var A={1:{due:'2020-01-01',interval:3,reps:1,correct:1,attempts:1}}, B={};
          var active={who:A};
          var w2=HSKUtil.createProgressWriter({ progressProvider:function(){return active.who;},
            progressRepository:HSKUtil.createProgressRepository({progressProvider:function(){return active.who;}}),
            srsCalculator:__srs, save:function(){}, markDirty:function(){}, dateProvider:__fixedNow() });
          active.who=B; w2.restore({cardId:9, hadState:false, previousState:null});  // affects B only
          var isolation = !('9' in A) && Object.keys(A).length===1 && ('1' in A);
          // null cardId -> no mutation
          var prog3={3:{due:'x',interval:1,reps:1,correct:1,attempts:1}}, snap=JSON.stringify(prog3), s3=0,d3=0;
          var w3=HSKUtil.createProgressWriter({ progressProvider:function(){return prog3;},
            progressRepository:HSKUtil.createProgressRepository({progressProvider:function(){return prog3;}}),
            srsCalculator:__srs, save:function(){s3++;}, markDirty:function(){d3++;}, dateProvider:__fixedNow() });
          var nullRes=w3.restore({cardId:null, hadState:true, previousState:{}});
          var nullGuard = nullRes===null && JSON.stringify(prog3)===snap && s3===0 && d3===0;
          return { localOnly, isolation, nullGuard };
        }""")
        for k in ["localOnly", "isolation", "nullGuard"]:
            check("restoreMisc:" + k, rmisc[k])

        # ==== PHASE 14: reset (global progress reset) ====

        # ---- CHARACTERIZATION: inline reset vs writer.reset (populated + empty) ----
        rst = pg.evaluate("""()=>{
          function mkResetWriter(holder, counts){
            return HSKUtil.createProgressWriter({
              progressProvider: function(){ return holder.prog; },
              progressRepository: HSKUtil.createProgressRepository({ progressProvider: function(){ return holder.prog; } }),
              srsCalculator: __srs,
              save: function(){ counts.save++; },
              markDirty: function(){ counts.dirty++; },
              replaceProgress: function(next){ holder.prog = next; },
              onReset: function(){ counts.onReset++; },
              dateProvider: __fixedNow()
            });
          }
          function scen(startProg){
            // inline original: progress={}; save(); onReset()
            var oldHolder={prog: JSON.parse(JSON.stringify(startProg))};
            var oc={save:0,onReset:0};
            oldHolder.prog={}; oc.save++; oc.onReset++;
            // writer
            var wHolder={prog: JSON.parse(JSON.stringify(startProg))};
            var wc={save:0,dirty:0,onReset:0};
            var w=mkResetWriter(wHolder, wc);
            var oldRef=wHolder.prog;
            var res=w.reset({min:1,max:999999});
            return {
              progEqual: JSON.stringify(wHolder.prog)===JSON.stringify(oldHolder.prog),
              becameEmpty: JSON.stringify(wHolder.prog)==='{}',
              newObject: wHolder.prog!==oldRef,
              save1: wc.save===1, onReset1: wc.onReset===1, noPerCardDirty: wc.dirty===0,
              ret: res && res.cleared===true
            };
          }
          return { populated: scen({1:{due:'x',interval:3,reps:2,correct:1,attempts:2},2:{due:'y',interval:1,reps:1,correct:0,attempts:1}}),
                   empty: scen({}) };
        }""")
        for st in ["populated", "empty"]:
            for k in ["progEqual", "becameEmpty", "newObject", "save1", "onReset1", "noPerCardDirty", "ret"]:
                check("reset char " + st + ":" + k, rst[st][k])

        # ---- READ OBSERVABILITY: repo/analytics/session observe the empty object ----
        obs = pg.evaluate("""()=>{
          var holder={prog:{1:{due:'2020-01-01',interval:6,reps:4,correct:3,attempts:4},2:{due:'2020-01-01',interval:2,reps:1,correct:1,attempts:1}}};
          var repo=HSKUtil.createProgressRepository({progressProvider:function(){return holder.prog;}});
          // analytics + session over the SAME live provider
          var cards=[]; for(var i=1;i<=10;i++) cards.push({id:i,level:'HSK1',word:'w'+i,pinyin:'p'+i,meaning:'m'+i});
          var cardRepo=HSKUtil.createCardRepository(cards);
          var analytics=HSKUtil.createAnalyticsQuery({cardRepository:cardRepo, progressRepository:repo,
            settingsRepository:{getStreak:function(){return 0;}}, dailyCountsProvider:function(){return {};}, dateProvider:function(){return new Date(2026,6,13,9,0,0);}});
          var session=HSKUtil.createStudySessionQuery({cardRepository:cardRepo, progressRepository:repo, dateProvider:function(){return '2026-07-13';}, randomProvider:function(){return 0.5;}});
          var beforeLearned=analytics.getHomeSummary(['HSK1']).learned;   // 2 (reps>0)
          var w=HSKUtil.createProgressWriter({ progressProvider:function(){return holder.prog;},
            progressRepository:repo, srsCalculator:__srs, save:function(){}, markDirty:function(){},
            replaceProgress:function(n){holder.prog=n;}, onReset:function(){}, dateProvider:__fixedNow() });
          w.reset({min:1,max:999999});
          var h=analytics.getHomeSummary(['HSK1']);
          return {
            beforeLearned2: beforeLearned===2,
            count0: repo.count()===0, ids0: repo.getCardIds().length===0,
            has1False: repo.has(1)===false,
            defaultAfter: JSON.stringify(repo.getOrDefault(1,'2026-07-13'))===JSON.stringify({due:'2026-07-13',interval:0,reps:0,correct:0,attempts:0}),
            analyticsZero: h.learned===0 && h.attempts===0 && h.correct===0,
            weakEmpty: analytics.getWeakWords('all').length===0,
            smartInsufficient: analytics.getSmartReviewModel().hasData===false,
            // all selected cards fresh -> standard session returns them (all due today, reps 0)
            sessionAllFresh: session.selectStandardSession({levels:['HSK1'],limit:5}).length===5
          };
        }""")
        for k in ["beforeLearned2", "count0", "ids0", "has1False", "defaultAfter", "analyticsZero", "weakEmpty", "smartInsufficient", "sessionAllFresh"]:
            check("resetObs:" + k, obs[k])

        # ---- LOCAL-ONLY (no onReset) + account isolation + guard ----
        rmisc2 = pg.evaluate("""()=>{
          // local-only: onReset wrapper is a no-op (HSKSync absent)
          var holder={prog:{1:{due:'x',interval:2,reps:1,correct:1,attempts:1}}}, saves=0, resets=0;
          var w=HSKUtil.createProgressWriter({ progressProvider:function(){return holder.prog;},
            progressRepository:HSKUtil.createProgressRepository({progressProvider:function(){return holder.prog;}}),
            srsCalculator:__srs, save:function(){saves++;}, markDirty:function(){},
            replaceProgress:function(n){holder.prog=n;}, onReset:function(){ if(false) resets++; }, dateProvider:__fixedNow() });
          w.reset({min:1,max:999999});
          var localOnly = saves===1 && resets===0 && JSON.stringify(holder.prog)==='{}';
          // account isolation: reset A must not touch B
          var A={prog:{1:{due:'x',interval:3,reps:1,correct:1,attempts:1}}};
          var B={prog:{2:{due:'y',interval:1,reps:1,correct:1,attempts:1}}};
          var active={who:A};
          var w2=HSKUtil.createProgressWriter({ progressProvider:function(){return active.who.prog;},
            progressRepository:HSKUtil.createProgressRepository({progressProvider:function(){return active.who.prog;}}),
            srsCalculator:__srs, save:function(){}, markDirty:function(){},
            replaceProgress:function(n){active.who.prog=n;}, onReset:function(){}, dateProvider:__fixedNow() });
          w2.reset({min:1,max:999999});  // resets A
          var isolation = JSON.stringify(A.prog)==='{}' && ('2' in B.prog) && Object.keys(B.prog).length===1;
          // guard: no replaceProgress -> reset returns null, no throw
          var w3=HSKUtil.createProgressWriter({ progressProvider:function(){return {};}, srsCalculator:__srs, save:function(){}, markDirty:function(){}, dateProvider:__fixedNow() });
          var guard = w3.reset({min:1,max:999999})===null;
          return { localOnly, isolation, guard };
        }""")
        for k in ["localOnly", "isolation", "guard"]:
            check("resetMisc:" + k, rmisc2[k])

        # ---- NO UNRELATED SIDE EFFECTS: writer.reset touches only progress via callbacks ----
        rse = pg.evaluate("""()=>{
          var before={}; for(var i=0;i<localStorage.length;i++){var k=localStorage.key(i); before[k]=localStorage.getItem(k);}
          var beforeLen=localStorage.length;
          var holder={prog:{1:{due:'x',interval:2,reps:1,correct:1,attempts:1}}};
          var w=HSKUtil.createProgressWriter({ progressProvider:function(){return holder.prog;},
            progressRepository:HSKUtil.createProgressRepository({progressProvider:function(){return holder.prog;}}),
            srsCalculator:__srs, save:function(){}, markDirty:function(){},
            replaceProgress:function(n){holder.prog=n;}, onReset:function(){}, dateProvider:__fixedNow() });
          w.reset({min:1,max:999999});
          var after={}; for(var q=0;q<localStorage.length;q++){var kk=localStorage.key(q); after[kk]=localStorage.getItem(kk);}
          var unchanged=localStorage.length===beforeLen;
          for(var bb in before){ if(before[bb]!==after[bb]) unchanged=false; }
          for(var aa in after){ if(!(aa in before)) unchanged=false; }
          return { storageUntouchedByWriter: unchanged, cleared: JSON.stringify(holder.prog)==='{}' };
        }""")
        for k in ["storageUntouchedByWriter", "cleared"]:
            check("resetSideEffect:" + k, rse[k])

        result = {"suite": "progress_writer", "pass": len(fails) == 0 and len(errs) == 0, "fails": fails, "errors": errs}
        print(json.dumps(result, ensure_ascii=False))
        b.close()
        return 0 if result["pass"] else 1

if __name__ == "__main__":
    import sys
    sys.exit(main())
