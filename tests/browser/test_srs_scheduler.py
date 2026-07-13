"""Unit + characterization tests for the Phase 18 pure SRS scheduler
(window.HSKUtil.createSrsScheduler / HSKUtil.srsScheduler.computeNext). Runs in the
real loaded browser.

Verifies the extracted computeNext is byte-identical to the original inline srsNextState
across a full grade/state/date matrix, exact sequences, date boundaries, input
immutability (state + Date not mutated), and the current quirks. The frozen SRS goldens
(srs_characterization) remain the release gate and are NOT modified.
"""
import os, json
from playwright.sync_api import sync_playwright

URL = os.environ.get("HSK_BASE_URL", "http://localhost:8000") + "/hsk_flashcard_app/"
EMPTY = 'window.SUPABASE_CONFIG={url:"",anonKey:""};'
fails = []
def check(n, c):
    if not c: fails.append(n)

# A faithful copy of the ORIGINAL inline srsNextState (mutate-in-place) for characterization.
HELPERS = r"""
window.__oldSrs = function(s, grade, now){
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
// run BOTH implementations over identical inputs, return serialized results (fresh copies each)
window.__compare = function(state, grade, isoNow){
  var cn = HSKUtil.srsScheduler.computeNext(JSON.parse(JSON.stringify(state)), grade, new Date(isoNow));
  var old = __oldSrs(JSON.parse(JSON.stringify(state)), grade, new Date(isoNow));
  return { newR: JSON.stringify(cn), oldR: JSON.stringify(old) };
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

        check("factory present", pg.evaluate("()=>typeof window.HSKUtil.createSrsScheduler==='function'"))
        check("singleton present", pg.evaluate("()=>typeof window.HSKUtil.srsScheduler.computeNext==='function'"))

        # ---- CHARACTERIZATION MATRIX: computeNext == srsNextState for every input ----
        cm = pg.evaluate("""()=>{
          const now='2026-07-13T09:00:00.000Z';
          const states=[
            {due:'2026-07-13',interval:0,reps:0,correct:0,attempts:0},   // untouched default
            {due:'2020-01-01',interval:1,reps:1,correct:1,attempts:1},   // interval 1
            {due:'2020-01-01',interval:2,reps:2,correct:1,attempts:2},   // interval 2
            {due:'2020-01-01',interval:6,reps:4,correct:3,attempts:4},   // overdue learned
            {due:'2999-01-01',interval:10,reps:2,correct:2,attempts:2},  // future-due
            {due:'2020-01-01',interval:63,reps:8,correct:8,attempts:8},  // large interval
            {due:'2020-01-01',interval:0,reps:0,correct:0,attempts:0,extra:'keep'}  // extra field
          ];
          const grades=['again','hard','good','easy','xyz'];   // incl. unknown
          let allEqual=true, firstDiff=null;
          states.forEach(st=>grades.forEach(g=>{
            const r=__compare(st, g, now);
            if(r.newR!==r.oldR){ allEqual=false; if(!firstDiff) firstDiff={st:JSON.stringify(st),g:g,newR:r.newR,oldR:r.oldR}; }
          }));
          return { allEqual, firstDiff };
        }""")
        check("characterization matrix all-equal", cm["allEqual"])
        if not cm["allEqual"]:
            fails.append("matrix diff: " + json.dumps(cm["firstDiff"]))

        # ---- EXACT FIELD VALUES (untouched card, fixed UTC now) ----
        fv = pg.evaluate("""()=>{
          const S=()=>({due:'2026-07-13',interval:0,reps:0,correct:0,attempts:0});
          const N=()=>new Date('2026-07-13T09:00:00.000Z');
          const cn=HSKUtil.srsScheduler.computeNext;
          const again=cn(S(),'again',N()), hard=cn(S(),'hard',N()), good=cn(S(),'good',N()), easy=cn(S(),'easy',N());
          return {
            again: again.interval===0 && again.due==='2026-07-13' && again.reps===1 && again.attempts===1 && again.correct===0,
            hard:  hard.interval===1 && hard.due==='2026-07-14' && hard.correct===0,
            good:  good.interval===3 && good.due==='2026-07-16' && good.correct===1,
            easy:  easy.interval===7 && easy.due==='2026-07-20' && easy.correct===1
          };
        }""")
        for k in ["again", "hard", "good", "easy"]:
            check("fresh fields:" + k, fv[k])

        # ---- INTERVAL PROGRESSION SEQUENCES (exact each step) ----
        seq = pg.evaluate("""()=>{
          const cn=HSKUtil.srsScheduler.computeNext;
          function run(grades){ var s={due:'2026-07-13',interval:0,reps:0,correct:0,attempts:0}; var now=new Date('2026-07-13T09:00:00.000Z');
            var steps=[]; grades.forEach(g=>{ s=cn(s,g,new Date(now.getTime())); steps.push(s.interval); }); return {last:s, ivals:steps}; }
          const good=run(['good','good','good']);      // 3,6,12
          const easy=run(['easy','easy','easy']);      // 7,21,63
          const hard=run(['hard','hard','hard']);      // 1,1,1
          const mix=run(['good','hard','easy','again']); // 3 -> 4(round(3*1.2)=4? 3.6->4) -> 12(round(4*3)=12) -> 0
          return {
            good: JSON.stringify(good.ivals)==='[3,6,12]' && good.last.reps===3 && good.last.correct===3,
            easy: JSON.stringify(easy.ivals)==='[7,21,63]' && easy.last.correct===3,
            hard: JSON.stringify(hard.ivals)==='[1,1,1]' && hard.last.correct===0,
            mix: JSON.stringify(mix.ivals)==='[3,4,12,0]' && mix.last.reps===4 && mix.last.correct===2
          };
        }""")
        for k in ["good", "easy", "hard", "mix"]:
            check("sequence:" + k, seq[k])

        # ---- DATE BOUNDARIES (month/year/leap rollover; same-day again) ----
        db = pg.evaluate("""()=>{
          const cn=HSKUtil.srsScheduler.computeNext;
          const S=iv=>({due:'x',interval:iv,reps:1,correct:1,attempts:1});
          // end of month: good(+3) from Jan 30 -> Feb 02
          const eom=cn(S(0),'good',new Date('2026-01-30T09:00:00Z')).due;
          // end of year: easy(+7) from Dec 28 -> Jan 04 next year
          const eoy=cn(S(0),'easy',new Date('2026-12-28T09:00:00Z')).due;
          // leap year: hard(+1) from Feb 28 2028 -> Feb 29
          const leap=cn(S(0),'hard',new Date('2028-02-28T09:00:00Z')).due;
          // same-day again (+1 min, midday -> same day)
          const sameDay=cn(S(5),'again',new Date('2026-07-13T12:00:00Z')).due;
          // again near UTC midnight (+1 min crosses to next day)
          const cross=cn(S(5),'again',new Date('2026-07-13T23:59:30Z')).due;
          return { eom:eom==='2026-02-02', eoy:eoy==='2027-01-04', leap:leap==='2028-02-29',
                   sameDay:sameDay==='2026-07-13', crossMidnight:cross==='2026-07-14' };
        }""")
        for k in ["eom", "eoy", "leap", "sameDay", "crossMidnight"]:
            check("dateBoundary:" + k, db[k])

        # ---- IMMUTABILITY: input state + Date not mutated ----
        im = pg.evaluate("""()=>{
          const cn=HSKUtil.srsScheduler.computeNext;
          const state={due:'2020-01-01',interval:6,reps:4,correct:3,attempts:4};
          const stateSnap=JSON.stringify(state);
          const now=new Date('2026-07-13T09:00:00.000Z');
          const nowMs=now.getTime();
          const out=cn(state,'good',now);
          return { stateUnmutated: JSON.stringify(state)===stateSnap,
                   dateUnmutated: now.getTime()===nowMs,
                   newObject: out!==state,
                   extraPreserved: JSON.stringify(cn({due:'x',interval:0,reps:0,correct:0,attempts:0,tag:'z'},'good',new Date('2026-07-13T09:00:00Z')).tag)==='"z"' };
        }""")
        for k in ["stateUnmutated", "dateUnmutated", "newObject", "extraPreserved"]:
            check("immutability:" + k, im[k])

        # ---- QUIRKS: unknown grade -> easy math, no correct++ ; missing fields ----
        qk = pg.evaluate("""()=>{
          const cn=HSKUtil.srsScheduler.computeNext;
          const N=()=>new Date('2026-07-13T09:00:00.000Z');
          const unknown=cn({due:'x',interval:0,reps:0,correct:0,attempts:0},'wat',N());
          const missing=cn({due:'x'},'good',N());   // missing interval/reps/correct/attempts
          return {
            unknownEasyMath: unknown.interval===7 && unknown.correct===0 && unknown.reps===1,
            missingDefaults: missing.interval===3 && missing.reps===1 && missing.attempts===1 && missing.correct===1
          };
        }""")
        for k in ["unknownEasyMath", "missingDefaults"]:
            check("quirk:" + k, qk[k])

        result = {"suite": "srs_scheduler", "pass": len(fails) == 0 and len(errs) == 0, "fails": fails, "errors": errs}
        print(json.dumps(result, ensure_ascii=False))
        b.close()
        return 0 if result["pass"] else 1

if __name__ == "__main__":
    import sys
    sys.exit(main())
