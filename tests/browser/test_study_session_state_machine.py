"""Unit + characterization tests for the Phase 19 pure StudySessionStateMachine
(window.HSKUtil.createStudySessionStateMachine).

FOUNDATION PHASE: the module is NOT loaded by production index.html; this test injects
it via add_script_tag after the app loads (production runtime is byte-unchanged). It
verifies the pure transition contract, exhaustive answer-leak (every card-changing
transition lands flipped=false), immutability, and byte-equal characterization against a
faithful inline model of app.js's session-state mutations. No side effects.
"""
import os, json
from playwright.sync_api import sync_playwright

URL = os.environ.get("HSK_BASE_URL", "http://localhost:8000") + "/hsk_flashcard_app/"
EMPTY = 'window.SUPABASE_CONFIG={url:"",anonKey:""};'
fails = []
def check(n, c):
    if not c: fails.append(n)

# faithful inline model of app.js's session-state mutations (start/flip/grade/skip/prev),
# and helpers to run BOTH the state machine and the inline model over an event sequence.
HELPERS = r"""
window.__status = function(ids, cur){ return (ids.length===0 || cur>=ids.length) ? "completed":"studying"; };
// inline model: mutable {cardIds,current,flipped,grades} mirroring app.js
window.__inlineStart = function(ids){ ids=(ids||[]).slice(); return {cardIds:ids, current:0, flipped:false, grades:[]}; };
window.__inlineApply = function(s, ev){
  if(ev.t==="flip"){ s.flipped=!s.flipped; }
  else if(ev.t==="grade"){ if(!s.flipped) return s; s.grades[s.current]=ev.g; s.current++; s.flipped=false; }
  else if(ev.t==="skip"){ s.grades[s.current]="skip"; s.current++; s.flipped=false; }
  else if(ev.t==="prev"){ if(s.current>0){ s.current--; s.flipped=false; } }
  else if(ev.t==="advance"){ s.current++; s.flipped=false; }
  return s;
};
// serialize each model into the SAME canonical shape for comparison
window.__serInline = function(s){ return JSON.stringify({ cardIds:s.cardIds, currentIndex:s.current, flipped:s.flipped, gradesByIndex:s.grades, status:__status(s.cardIds, s.current) }); };
window.__serSM = function(st){ return JSON.stringify({ cardIds:st.cardIds, currentIndex:st.currentIndex, flipped:st.flipped, gradesByIndex:st.gradesByIndex, status:st.status }); };
// run a sequence through both; return step-by-step equality
window.__runSeq = function(ids, events){
  var sm = HSKUtil.createStudySessionStateMachine();
  var stSM = sm.startSession({cardIds:ids});
  var stIn = __inlineStart(ids);
  var eqStart = __serSM(stSM)===__serInline(stIn);
  var allEqual = eqStart, firstDiff=null;
  events.forEach(function(ev){
    if(ev.t==="flip") stSM=sm.flip(stSM);
    else if(ev.t==="grade") stSM=sm.grade(stSM, ev.g);
    else if(ev.t==="skip") stSM=sm.skip(stSM);
    else if(ev.t==="prev") stSM=sm.prev(stSM);
    else if(ev.t==="advance") stSM=sm.advance(stSM);
    __inlineApply(stIn, ev);
    if(__serSM(stSM)!==__serInline(stIn)){ allEqual=false; if(!firstDiff) firstDiff={ev:ev, sm:__serSM(stSM), inl:__serInline(stIn)}; }
  });
  return { allEqual:allEqual, firstDiff:firstDiff, finalSM:__serSM(stSM) };
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
        # FOUNDATION: inject the (not-production-loaded) module, then the helpers
        pg.add_script_tag(url="core/sessions/study-session-state-machine.js")
        pg.evaluate("() => {" + HELPERS + "}")

        check("factory present (test-injected)", pg.evaluate("()=>typeof window.HSKUtil.createStudySessionStateMachine==='function'"))

        # ---- INITIAL STATE ----
        init = pg.evaluate("""()=>{
          const sm=HSKUtil.createStudySessionStateMachine();
          const s=sm.createInitialState();
          return { shape: JSON.stringify(s)==='{"cardIds":[],"currentIndex":0,"flipped":false,"gradesByIndex":[],"status":"idle"}' };
        }""")
        check("initial idle shape", init["shape"])

        # ---- START ----
        st = pg.evaluate("""()=>{
          const sm=HSKUtil.createStudySessionStateMachine();
          const ids=[3,1,2,1];   // explicit order + duplicate preserved (upstream already deduped as needed)
          const inCopy=ids.slice();
          const s=sm.startSession({cardIds:ids});
          const one=sm.startSession({cardIds:[9]});
          const empty=sm.startSession({cardIds:[]});
          return {
            order: JSON.stringify(s.cardIds)==='[3,1,2,1]', currentIndex0: s.currentIndex===0,
            flippedFalse: s.flipped===false, noGrades: s.gradesByIndex.length===0, studying: s.status==="studying",
            oneStudying: one.status==="studying", emptyCompleted: empty.status==="completed",
            inputUnmutated: JSON.stringify(ids)===JSON.stringify(inCopy),
            arrayCopied: s.cardIds!==ids
          };
        }""")
        for k in ["order", "currentIndex0", "flippedFalse", "noGrades", "studying", "oneStudying", "emptyCompleted", "inputUnmutated", "arrayCopied"]:
            check("start:" + k, st[k])

        # ---- FLIP ----
        fl = pg.evaluate("""()=>{
          const sm=HSKUtil.createStudySessionStateMachine();
          const s0=sm.startSession({cardIds:[1,2]});
          const s1=sm.flip(s0), s2=sm.flip(s1);
          return { toBack: s1.flipped===true, toFront: s2.flipped===false,
                   idxUnchanged: s1.currentIndex===0 && s1.cardIds===s0.cardIds,
                   inputUnchanged: s0.flipped===false, newObject: s1!==s0 };
        }""")
        for k in ["toBack", "toFront", "idxUnchanged", "inputUnchanged", "newObject"]:
            check("flip:" + k, fl[k])

        # ---- GRADE / NEXT (all grades, guard, completion, no advance without flip) ----
        gr = pg.evaluate("""()=>{
          const sm=HSKUtil.createStudySessionStateMachine();
          function g(gr){ let s=sm.startSession({cardIds:[1,2]}); s=sm.flip(s); s=sm.grade(s,gr); return s; }
          const good=g('good'), again=g('again'), hard=g('hard'), easy=g('easy'), unk=g('xyz');
          // no-op when not flipped
          let nf=sm.startSession({cardIds:[1,2]}); const nfr=sm.grade(nf,'good');
          // completion after last card
          let s=sm.startSession({cardIds:[1]}); s=sm.flip(s); s=sm.grade(s,'good');
          return {
            recordAdvance: good.gradesByIndex[0]==='good' && good.currentIndex===1 && good.flipped===false,
            allGrades: again.gradesByIndex[0]==='again' && hard.gradesByIndex[0]==='hard' && easy.gradesByIndex[0]==='easy' && unk.gradesByIndex[0]==='xyz',
            noFlipNoop: JSON.stringify(nfr)===JSON.stringify(nf) && nfr.currentIndex===0,
            completed: s.status==="completed" && s.currentIndex===1,
            nextFront: good.flipped===false
          };
        }""")
        for k in ["recordAdvance", "allGrades", "noFlipNoop", "completed", "nextFront"]:
            check("grade:" + k, gr[k])

        # ---- SKIP ----
        sk = pg.evaluate("""()=>{
          const sm=HSKUtil.createStudySessionStateMachine();
          let s=sm.startSession({cardIds:[1,2,3]});
          const sk1=sm.skip(s);                    // skip ungraded (not flipped)
          let f=sm.flip(s); const sk2=sm.skip(f);  // skip after flip
          let last=sm.startSession({cardIds:[1]}); last=sm.skip(last);
          return { skipRecords: sk1.gradesByIndex[0]==='skip' && sk1.currentIndex===1 && sk1.flipped===false,
                   skipAfterFlip: sk2.gradesByIndex[0]==='skip' && sk2.flipped===false,
                   lastCompleted: last.status==="completed" };
        }""")
        for k in ["skipRecords", "skipAfterFlip", "lastCompleted"]:
            check("skip:" + k, sk[k])

        # ---- PREV / navigation ----
        pv = pg.evaluate("""()=>{
          const sm=HSKUtil.createStudySessionStateMachine();
          let s=sm.startSession({cardIds:[1,2,3]}); s=sm.flip(s); s=sm.grade(s,'good');  // now index1
          const back=sm.prev(s);       // -> index0, front
          const atFirst=sm.prev(sm.startSession({cardIds:[1,2]}));   // index0 -> no-op
          // prev from completed
          let done=sm.startSession({cardIds:[1]}); done=sm.flip(done); done=sm.grade(done,'good');  // completed idx1
          const fromDone=sm.prev(done);
          return { backIndex: back.currentIndex===0 && back.flipped===false && back.status==="studying",
                   firstGuard: atFirst.currentIndex===0,
                   fromCompleted: fromDone.currentIndex===0 && fromDone.status==="studying" && fromDone.flipped===false };
        }""")
        for k in ["backIndex", "firstGuard", "fromCompleted"]:
            check("prev:" + k, pv[k])

        # ---- EXHAUSTIVE ANSWER-LEAK: every card-changing transition -> flipped=false ----
        al = pg.evaluate("""()=>{
          const sm=HSKUtil.createStudySessionStateMachine();
          let s=sm.startSession({cardIds:[1,2,3]});
          const checks=[];
          checks.push(s.flipped===false);                    // start
          s=sm.flip(s);                                       // flip -> back
          const afterGrade=sm.grade(s,'good'); checks.push(afterGrade.flipped===false);  // grade -> next front
          let s2=sm.flip(sm.startSession({cardIds:[1,2,3]}));
          checks.push(sm.skip(s2).flipped===false);           // skip -> next front
          checks.push(sm.advance(sm.flip(sm.startSession({cardIds:[1,2]}))).flipped===false);  // advance -> front
          let g=sm.grade(sm.flip(sm.startSession({cardIds:[1,2]})),'good');
          checks.push(sm.prev(g).flipped===false);            // prev -> front
          checks.push(sm.startSession({cardIds:[5,6]}).flipped===false);   // restart -> front
          return { allFront: checks.every(x=>x===true), n: checks.length };
        }""")
        check("answer-leak: every card-change lands front", al["allFront"] and al["n"] == 6)

        # ---- IMMUTABILITY ----
        im = pg.evaluate("""()=>{
          const sm=HSKUtil.createStudySessionStateMachine();
          const s=sm.flip(sm.startSession({cardIds:[1,2,3]}));
          const snap=JSON.stringify(s); const gradesRef=s.gradesByIndex; const idsRef=s.cardIds;
          const g=sm.grade(s,'good');
          return { inputUnchanged: JSON.stringify(s)===snap,
                   gradesUnchanged: s.gradesByIndex===gradesRef && s.gradesByIndex.length===0,
                   idsUnchanged: s.cardIds===idsRef,
                   newGradesArray: g.gradesByIndex!==gradesRef,
                   deterministic: __serSM(sm.grade(sm.flip(sm.startSession({cardIds:[1,2]})),'good'))===__serSM(sm.grade(sm.flip(sm.startSession({cardIds:[1,2]})),'good')) };
        }""")
        for k in ["inputUnchanged", "gradesUnchanged", "idsUnchanged", "newGradesArray", "deterministic"]:
            check("immutability:" + k, im[k])

        # ---- CHARACTERIZATION vs inline app.js session model (sequences) ----
        seqs = [
            ([1, 2, 3], [{"t": "flip"}, {"t": "grade", "g": "good"}, {"t": "flip"}, {"t": "grade", "g": "hard"}]),      # start->flip->grade->next x2
            ([1, 2, 3], [{"t": "flip"}, {"t": "grade", "g": "good"}, {"t": "prev"}, {"t": "flip"}, {"t": "grade", "g": "easy"}]),  # grade->next->undo->regrade
            ([1, 2, 3], [{"t": "skip"}, {"t": "skip"}, {"t": "flip"}, {"t": "grade", "g": "again"}]),                    # skip->skip->grade
            ([1], [{"t": "flip"}, {"t": "grade", "g": "good"}]),                                                        # last card completion
            ([1], [{"t": "flip"}, {"t": "grade", "g": "good"}, {"t": "prev"}]),                                          # undo after completion
            ([], [{"t": "flip"}, {"t": "skip"}]),                                                                        # empty session
            ([7, 8, 9, 10], [{"t": "flip"}, {"t": "grade", "g": "good"}, {"t": "skip"}, {"t": "flip"}, {"t": "grade", "g": "hard"}, {"t": "prev"}, {"t": "prev"}]),  # mixed long
        ]
        for i, (ids, events) in enumerate(seqs):
            r = pg.evaluate("([ids,ev])=>__runSeq(ids, ev)", [ids, events])
            check("characterization seq %d" % i, r["allEqual"])
            if not r["allEqual"]:
                fails.append("seq %d diff: %s" % (i, json.dumps(r["firstDiff"])))

        # ---- NO SIDE EFFECTS (storage/DOM untouched by transitions) ----
        se = pg.evaluate("""()=>{
          const before={}; for(let i=0;i<localStorage.length;i++){const k=localStorage.key(i); before[k]=localStorage.getItem(k);}
          const beforeLen=localStorage.length;
          const sm=HSKUtil.createStudySessionStateMachine();
          let s=sm.startSession({cardIds:[1,2,3,4,5]});
          for(let i=0;i<30;i++){ s=sm.flip(s); s=sm.grade(s,'good'); s=sm.skip(s); s=sm.prev(s); s=sm.advance(s); }
          const after={}; for(let i=0;i<localStorage.length;i++){const k=localStorage.key(i); after[k]=localStorage.getItem(k);}
          let unchanged=localStorage.length===beforeLen;
          for(const k in before){ if(before[k]!==after[k]) unchanged=false; }
          for(const k in after){ if(!(k in before)) unchanged=false; }
          return { storageUnchanged: unchanged };
        }""")
        check("no side effects: storage unchanged", se["storageUnchanged"])

        result = {"suite": "study_session_state_machine", "pass": len(fails) == 0 and len(errs) == 0, "fails": fails, "errors": errs}
        print(json.dumps(result, ensure_ascii=False))
        b.close()
        return 0 if result["pass"] else 1

if __name__ == "__main__":
    import sys
    sys.exit(main())
