"""Unit tests for the Phase 3 read-only CardRepository (window.HSKUtil.cards +
HSKUtil.createCardRepository). Runs in the real loaded browser. Verifies construction,
immutability, id semantics, level methods, and single-instantiation characteristics.
"""
import os, json
from playwright.sync_api import sync_playwright

URL = os.environ.get("HSK_BASE_URL", "http://localhost:8000") + "/hsk_flashcard_app/"
EMPTY = 'window.SUPABASE_CONFIG={url:"",anonKey:""};'
fails = []
def check(n, c):
    if not c: fails.append(n)

def main():
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 1024, "height": 800})
        ctx.route("**/supabase-config.js", lambda r: r.fulfill(status=200, content_type="application/javascript", body=EMPTY))
        pg = ctx.new_page(); errs = []
        pg.on("pageerror", lambda e: errs.append("PAGEERR:" + str(e)))
        pg.on("console", lambda m: errs.append("CON:" + m.text) if m.type == "error" else None)
        pg.goto(URL); pg.wait_for_timeout(300)

        check("repo present", pg.evaluate("()=>typeof window.HSKUtil.cards==='object' && typeof window.HSKUtil.createCardRepository==='function'"))

        # ---- CONSTRUCTION ----
        con = pg.evaluate("""()=>{
          const mk=HSKUtil.createCardRepository;
          const src=[{id:10,level:'HSK1',word:'a'},{id:20,level:'HSK2',word:'b'}];
          const before=JSON.stringify(src), c0=src[0], c0before=JSON.stringify(c0);
          const r=mk(src);
          r.getAll(); r.getById(10); r.getByLevel('HSK1'); r.getManyByIds([10,20]); r.countByLevel();
          return { sourceUnmutated: JSON.stringify(src)===before,
                   cardUnmutated: JSON.stringify(src[0])===c0before,
                   dupDetect: JSON.stringify(mk([{id:1},{id:1},{id:2}]).duplicateIds())==='[1]',
                   emptyCount: mk([]).count()===0,
                   emptyGetById: mk([]).getById(1)===undefined,
                   emptyLevels: JSON.stringify(mk([]).getLevels())==='[]',
                   sharedIs5002: HSKUtil.cards.count()===5002 };
        }""")
        for k in ["sourceUnmutated", "cardUnmutated", "dupDetect", "emptyCount", "emptyGetById", "emptyLevels", "sharedIs5002"]:
            check("construction:" + k, con[k])

        # ---- GET ALL ----
        ga = pg.evaluate("""()=>{
          const r=HSKUtil.cards, all=r.getAll();
          return { len: all.length, firstId: all[0].id, lastId: all[all.length-1].id,
                   sameRefAsSource: all===window.HSK_CARDS };
        }""")
        check("getAll len 5002", ga["len"] == 5002)
        check("getAll source order (first 1, last 5002)", ga["firstId"] == 1 and ga["lastId"] == 5002)
        check("getAll returns source ref (no clone)", ga["sameRefAsSource"])

        # ---- GET BY ID ----
        gb = pg.evaluate("""()=>{
          const r=HSKUtil.cards; let allResolve=true;
          for(let i=1;i<=5002;i++){ if(!r.getById(i)){ allResolve=false; break; } }
          return { allResolve,
                   first: r.getById(1)===window.HSK_CARDS.find(c=>c.id===1),
                   last: r.getById(5002)===window.HSK_CARDS.find(c=>c.id===5002),
                   missing: r.getById(999999)===undefined,
                   numeric: !!r.getById(1),
                   stringMiss: r.getById('1')===undefined,
                   stable: r.getById(1)===r.getById(1),
                   has1: r.has(1)===true, hasMissing: r.has(999999)===false };
        }""")
        for k in ["allResolve", "first", "last", "missing", "numeric", "stringMiss", "stable", "has1", "hasMissing"]:
            check("getById:" + k, gb[k])

        # ---- GET MANY BY IDS ----
        gm = pg.evaluate("""()=>{
          const r=HSKUtil.cards;
          const order=r.getManyByIds([3,1,2]).map(c=>c.id);
          const dups=r.getManyByIds([1,1]).map(c=>c.id);
          const miss=r.getManyByIds([1,999999,2]).map(c=>c.id);
          const input=[1,2]; const inCopy=input.slice(); r.getManyByIds(input);
          return { order: JSON.stringify(order)==='[3,1,2]',
                   dupsKept: JSON.stringify(dups)==='[1,1]',
                   missingSkipped: JSON.stringify(miss)==='[1,2]',
                   empty: JSON.stringify(r.getManyByIds([]))==='[]',
                   inputUnmutated: JSON.stringify(input)===JSON.stringify(inCopy) };
        }""")
        for k in ["order", "dupsKept", "missingSkipped", "empty", "inputUnmutated"]:
            check("getManyByIds:" + k, gm[k])

        # ---- LEVEL METHODS ----
        lv = pg.evaluate("""()=>{
          const r=HSKUtil.cards;
          const counts={}; r.getLevels().forEach(l=>counts[l]=r.getByLevel(l).length);
          const copy=r.getByLevel('HSK1'); copy.push({}); const afterMutate=r.getByLevel('HSK1').length;
          const syn=HSKUtil.createCardRepository([{id:1,level:'HSK7'},{id:2,level:'HSK2'},{id:3,level:'HSK7'}]);
          const mal=HSKUtil.createCardRepository([{id:5,level:'HSK1'},{}]);
          return { levels: r.getLevels(),
                   counts, countByLevel: r.countByLevel(),
                   firstHSK1Id: r.getByLevel('HSK1')[0].id,
                   unknownLevel: JSON.stringify(r.getByLevel('HSK99'))==='[]',
                   getByLevelIsCopy: afterMutate===149,
                   synLevels: syn.getLevels(), synHSK7Count: syn.getByLevel('HSK7').length,
                   malCount: mal.count(), malLevels: mal.getLevels() };
        }""")
        check("getLevels HSK1..6", lv["levels"] == ["HSK1", "HSK2", "HSK3", "HSK4", "HSK5", "HSK6"])
        check("getByLevel counts exact", lv["counts"] == {"HSK1": 149, "HSK2": 150, "HSK3": 295, "HSK4": 600, "HSK5": 1295, "HSK6": 2513})
        check("countByLevel exact", lv["countByLevel"] == {"HSK1": 149, "HSK2": 150, "HSK3": 295, "HSK4": 600, "HSK5": 1295, "HSK6": 2513})
        check("getByLevel preserves order (HSK1 first id 1)", lv["firstHSK1Id"] == 1)
        check("unknown level -> []", lv["unknownLevel"])
        check("getByLevel returns a copy (mutation isolated)", lv["getByLevelIsCopy"])
        check("synthetic future level HSK7 sorts after HSK2", lv["synLevels"] == ["HSK2", "HSK7"] and lv["synHSK7Count"] == 2)
        check("malformed cards handled (count 2, levels [HSK1])", lv["malCount"] == 2 and lv["malLevels"] == ["HSK1"])

        # ---- PERFORMANCE / SINGLE INSTANCE ----
        perf = pg.evaluate("""()=>{
          return { sharedSameInstance: HSKUtil.cards===HSKUtil.cards,
                   factoryDistinct: HSKUtil.createCardRepository([{id:1}])!==HSKUtil.createCardRepository([{id:1}]),
                   getAllNoClone: HSKUtil.cards.getAll()===window.HSK_CARDS };
        }""")
        for k in ["sharedSameInstance", "factoryDistinct", "getAllNoClone"]:
            check("perf:" + k, perf[k])

        result = {"suite": "card_repository", "pass": len(fails) == 0 and len(errs) == 0, "fails": fails, "errors": errs}
        print(json.dumps(result, ensure_ascii=False))
        b.close()
        return 0 if result["pass"] else 1

if __name__ == "__main__":
    import sys
    sys.exit(main())
