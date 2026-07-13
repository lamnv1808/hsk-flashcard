"""Unit + characterization tests for the Phase 8 read-only ProgressRepository
(window.HSKUtil.createProgressRepository). Runs in the real loaded browser.

Verifies the get/default contract (incl. reading an untouched card creates no row),
has/touched, ids/entries/count, learned/due helpers, account isolation (provider
swap), existing-write visibility, and the strict no-side-effects contract. Includes
CHARACTERIZATION comparisons: faithful copies of the ORIGINAL inline getCardState()/
stateOf() + raw Object.keys/prog[id] reads vs the repository => byte-equal.
"""
import os, json
from playwright.sync_api import sync_playwright

URL = os.environ.get("HSK_BASE_URL", "http://localhost:8000") + "/hsk_flashcard_app/"
EMPTY = 'window.SUPABASE_CONFIG={url:"",anonKey:""};'
fails = []
def check(n, c):
    if not c: fails.append(n)

HELPERS = r"""
window.__mkRepo = function(prog){ return HSKUtil.createProgressRepository({ progressProvider: function(){ return prog; } }); };
// ORIGINAL inline reads (app.js getCardState / query stateOf)
window.__oldState = function(prog, id, today){ return prog[id] || { due: today, interval:0, reps:0, correct:0, attempts:0 }; };
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

        check("factory present", pg.evaluate("()=>typeof window.HSKUtil.createProgressRepository==='function'"))
        check("shared instance present", pg.evaluate("()=>typeof window.HSKUtil.progress==='object'"))

        # ---- CONSTRUCTION / PROVIDER ----
        con = pg.evaluate("""()=>{
          const holder={cur:{5:{due:'2020-01-01',interval:1,reps:2,correct:1,attempts:2}}};
          const r=HSKUtil.createProgressRepository({progressProvider:()=>holder.cur});
          const before=r.has(5);
          holder.cur={7:{due:'2021-01-01',reps:1}};       // replace container
          const after=r.has(5), after2=r.has(7);
          const src={1:{due:'2020-01-01',reps:1,attempts:1,correct:1}}, snap=JSON.stringify(src);
          const r2=__mkRepo(src);
          r2.getStored(1); r2.getOrDefault(1,'2026-07-13'); r2.getOrDefault(2,'2026-07-13'); r2.getCardIds(); r2.count(); r2.isLearned(1); r2.isDue(1,'2026-07-13');
          return {
            observesReplacement: before===true && after===false && after2===true,
            emptySource: (()=>{const e=__mkRepo({}); return e.count()===0 && e.getStored(1)===undefined && e.getCardIds().length===0;})(),
            nullSource: (()=>{const e=HSKUtil.createProgressRepository({progressProvider:()=>null}); return e.count()===0 && e.getStored(1)===undefined && e.has(1)===false;})(),
            sourceUnmutated: JSON.stringify(src)===snap
          };
        }""")
        for k in ["observesReplacement", "emptySource", "nullSource", "sourceUnmutated"]:
            check("construction:" + k, con[k])

        # ---- GET / DEFAULT (+ characterization, + no row created) ----
        gd = pg.evaluate("""()=>{
          const today='2026-07-13';
          const prog={ 3:{due:'2020-01-01',interval:5,reps:4,correct:3,attempts:4} };
          const r=__mkRepo(prog);
          const stored=r.getOrDefault(3,today), def=r.getOrDefault(99,today);
          // characterization vs inline getCardState/stateOf
          const charStored=JSON.stringify(stored)===JSON.stringify(__oldState(prog,3,today));
          const charDef=JSON.stringify(def)===JSON.stringify(__oldState(prog,99,today));
          // reading an untouched card must NOT create a stored row
          const beforeKeys=Object.keys(prog).length;
          r.getOrDefault(99,today); r.getStored(99); r.isDue(99,today); r.isLearned(99); r.has(99);
          const afterKeys=Object.keys(prog).length;
          return {
            charStored, charDef,
            storedIsLiveRow: stored===prog[3],                    // touched -> live reference
            defaultFields: def.due===today && def.interval===0 && def.reps===0 && def.correct===0 && def.attempts===0,
            defaultFreshEachCall: r.getOrDefault(99,today)!==r.getOrDefault(99,today),
            missingStored: r.getStored(99)===undefined,
            numericId: r.getStored(3)===prog[3],
            stringIdSameKey: r.getStored('3')===prog[3],          // number/string coerce to same key
            noRowCreated: beforeKeys===0 ? afterKeys===0 : (afterKeys===beforeKeys) && !('99' in prog)
          };
        }""")
        for k in ["charStored", "charDef", "storedIsLiveRow", "defaultFields", "defaultFreshEachCall", "missingStored", "numericId", "stringIdSameKey", "noRowCreated"]:
            check("getDefault:" + k, gd[k])

        # ---- HAS / TOUCHED ----
        ht = pg.evaluate("""()=>{
          const prog={ 1:{due:'2020-01-01',reps:1}, 2:{due:'2020-01-01',reps:0,attempts:0} };
          const r=__mkRepo(prog);
          return { has1: r.has(1)===true, hasTouched2: r.isTouched(2)===true,
                   missing: r.has(3)===false, touchedMissing: r.isTouched(3)===false,
                   protoSafe: r.has('hasOwnProperty')===false };
        }""")
        for k in ["has1", "hasTouched2", "missing", "touchedMissing", "protoSafe"]:
            check("has:" + k, ht[k])

        # ---- IDS / ENTRIES / COUNT ----
        ie = pg.evaluate("""()=>{
          const empty=__mkRepo({});
          const prog={ 10:{reps:1,attempts:1,correct:1}, 5:{reps:2,attempts:2,correct:1}, 20:{reps:0,attempts:0,correct:0} };
          const r=__mkRepo(prog);
          const ids=r.getCardIds();
          const charIds=JSON.stringify(ids)===JSON.stringify(Object.keys(prog));   // exact enumeration order
          const entries=r.getEntries();
          const charEntries=entries.length===3 && entries[0][0]===Object.keys(prog)[0] && entries[0][1]===prog[Object.keys(prog)[0]];
          const snap=JSON.stringify(prog); r.getCardIds(); r.getEntries();
          return { emptyIds: empty.getCardIds().length===0, emptyCount: empty.count()===0,
                   count: r.count()===3, charIds, charEntries,
                   sourceUnmutated: JSON.stringify(prog)===snap };
        }""")
        for k in ["emptyIds", "emptyCount", "count", "charIds", "charEntries", "sourceUnmutated"]:
            check("ids:" + k, ie[k])

        # ---- LEARNED / DUE HELPERS ----
        ld = pg.evaluate("""()=>{
          const today='2026-07-13';
          const prog={ 1:{due:'2020-01-01',reps:3,attempts:3,correct:2},  // learned, past due
                       2:{due:'2999-01-01',reps:1,attempts:1,correct:1},  // learned, future
                       3:{due:'2020-01-01',reps:0,attempts:0,correct:0} };// touched reps0, past due
          const r=__mkRepo(prog);
          return { learned1: r.isLearned(1)===true, learned2: r.isLearned(2)===true,
                   notLearned3: r.isLearned(3)===false, notLearnedUntouched: r.isLearned(99)===false,
                   duePast: r.isDue(1,today)===true, dueFuture: r.isDue(2,today)===false,
                   untouchedDueToday: r.isDue(99,today)===true };   // untouched default due=today
        }""")
        for k in ["learned1", "learned2", "notLearned3", "notLearnedUntouched", "duePast", "dueFuture", "untouchedDueToday"]:
            check("helpers:" + k, ld[k])

        # ---- ACCOUNT ISOLATION ----
        ai = pg.evaluate("""()=>{
          const today='2026-07-13';
          const A={ 1:{due:'2020-01-01',reps:3,attempts:3,correct:3} };
          const B={ 2:{due:'2020-01-01',reps:1,attempts:2,correct:0} };
          const active={who:A};
          const r=HSKUtil.createProgressRepository({progressProvider:()=>active.who});
          const a1=r.has(1)&&!r.has(2)&&r.count()===1;
          active.who=B; const bOk=r.has(2)&&!r.has(1)&&r.count()===1&&r.getStored(2).correct===0;
          active.who=A; const a2=r.has(1)&&r.getStored(1).reps===3;
          active.who={}; const localOnly=r.count()===0;
          return { a1, bOk, a2, localOnly };
        }""")
        for k in ["a1", "bOk", "a2", "localOnly"]:
            check("isolation:" + k, ai[k])

        # ---- EXISTING WRITE VISIBILITY (repo is not the writer) ----
        wv = pg.evaluate("""()=>{
          const today='2026-07-13';
          const prog={ 1:{due:'2020-01-01',reps:1,attempts:1,correct:1} };
          const r=__mkRepo(prog);
          const before=r.has(2)===false && r.getStored(2)===undefined;
          // simulate the EXISTING gradeCard write path mutating the same object
          prog[2]={due:today,interval:3,reps:1,attempts:1,correct:1};        // new row
          const added=r.has(2)===true && r.getStored(2).interval===3;
          prog[1].reps=5; prog[1].attempts=6; prog[1].correct=4;             // update existing
          const updated=r.getStored(1).reps===5 && r.isLearned(1)===true;
          delete prog[1];                                                     // reset a row
          const removed=r.has(1)===false;
          return { before, added, updated, removed };
        }""")
        for k in ["before", "added", "updated", "removed"]:
            check("writeVisibility:" + k, wv[k])

        # ---- NO SIDE EFFECTS ----
        se = pg.evaluate("""()=>{
          const before={}; for(let i=0;i<localStorage.length;i++){const k=localStorage.key(i); before[k]=localStorage.getItem(k);}
          const beforeLen=localStorage.length;
          const today='2026-07-13';
          const prog={ 5:{due:'2020-01-01',interval:1,reps:3,attempts:3,correct:1} }; const snap=JSON.stringify(prog);
          const r=__mkRepo(prog);
          for(let i=0;i<40;i++){ r.has(5); r.getStored(5); r.getOrDefault(5,today); r.getOrDefault(999,today); r.getCardIds(); r.getEntries(); r.count(); r.isLearned(5); r.isDue(999,today); }
          const after={}; for(let i=0;i<localStorage.length;i++){const k=localStorage.key(i); after[k]=localStorage.getItem(k);}
          let unchanged=localStorage.length===beforeLen;
          for(const k in before){ if(before[k]!==after[k]) unchanged=false; }
          for(const k in after){ if(!(k in before)) unchanged=false; }
          return { storageUnchanged:unchanged, progressUnmutated:JSON.stringify(prog)===snap, noPhantomRow:!('999' in prog) };
        }""")
        for k in ["storageUnchanged", "progressUnmutated", "noPhantomRow"]:
            check("sideEffect:" + k, se[k])

        result = {"suite": "progress_repository", "pass": len(fails) == 0 and len(errs) == 0, "fails": fails, "errors": errs}
        print(json.dumps(result, ensure_ascii=False))
        b.close()
        return 0 if result["pass"] else 1

if __name__ == "__main__":
    import sys
    sys.exit(main())
