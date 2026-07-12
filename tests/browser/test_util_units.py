"""Unit tests for the Phase 2 pure utilities (window.HSKUtil.*), run in the real
loaded browser environment. Uses a UTC+7 timezone context to prove localDay stays
LOCAL and isoDay stays UTC (no accidental UTC conversion of local-day logic).
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
        # Non-UTC timezone so local vs UTC diverge across midnight.
        ctx = b.new_context(viewport={"width": 1024, "height": 800}, timezone_id="Asia/Ho_Chi_Minh")
        ctx.route("**/supabase-config.js", lambda r: r.fulfill(status=200, content_type="application/javascript", body=EMPTY))
        pg = ctx.new_page(); errs = []
        pg.on("pageerror", lambda e: errs.append("PAGEERR:" + str(e)))
        pg.on("console", lambda m: errs.append("CON:" + m.text) if m.type == "error" else None)
        pg.goto(URL); pg.wait_for_timeout(300)

        check("HSKUtil present", pg.evaluate("()=>typeof window.HSKUtil==='object'"))
        check("HSKUtil groups", pg.evaluate("()=>['date','levels','shuffle','cardIndex'].every(k=>window.HSKUtil[k])"))

        # ---- DATE ----
        d = pg.evaluate("""()=>{
          const D=HSKUtil.date;
          const at=new Date('2026-07-12T18:00:00Z'); // UTC 18:00 = 2026-07-13 01:00 local (UTC+7)
          return { local: D.localDay(at), iso: D.isoDay(at),
                   localNow: D.localDay(), isoNow: D.isoDay(),
                   isoNull: D.isoDay(null), isoUndef: D.isoDay(undefined),
                   isoBad: D.isoDay(new Date('nope')) };
        }""")
        check("localDay is LOCAL (2026-07-13)", d["local"] == "2026-07-13")
        check("isoDay is UTC (2026-07-12)", d["iso"] == "2026-07-12")
        check("local != UTC across midnight", d["local"] != d["iso"])
        import re
        check("localDay() no-arg valid", bool(re.match(r"^\d{4}-\d\d-\d\d$", d["localNow"])))
        check("isoDay() no-arg valid", bool(re.match(r"^\d{4}-\d\d-\d\d$", d["isoNow"])))
        check("isoDay(null)=='' (fallback)", d["isoNull"] == "")
        check("isoDay(undefined) -> today (default arg)", bool(re.match(r"^\d{4}-\d\d-\d\d$", d["isoUndef"])))
        check("isoDay(invalid)=='' (malformed)", d["isoBad"] == "")

        # ---- LEVELS ----
        lv = pg.evaluate("""()=>{
          const L=HSKUtil.levels;
          return { o1:L.levelOrder('HSK1'), o6:L.levelOrder('HSK6'), o10:L.levelOrder('HSK10'),
                   o7:L.levelOrder('HSK7'), oEmpty:L.levelOrder(''), oUnknown:L.levelOrder('foo'), oNull:L.levelOrder(null),
                   sorted:L.sortLevels(['HSK6','HSK1','HSK10','HSK2']),
                   dupSorted:L.sortLevels(['HSK2','HSK1','HSK2']),
                   fromCards:L.levelsFromCards(window.HSK_CARDS),
                   fromDup:L.levelsFromCards([{level:'HSK3'},{level:'HSK1'},{level:'HSK3'}]) };
        }""")
        check("levelOrder HSK1..6", lv["o1"] == 1 and lv["o6"] == 6)
        check("levelOrder HSK10 vs HSK2 (10>2)", lv["o10"] == 10)
        check("levelOrder future HSK7=7", lv["o7"] == 7)
        check("levelOrder empty/unknown/null -> 0", lv["oEmpty"] == 0 and lv["oUnknown"] == 0 and lv["oNull"] == 0)
        check("sortLevels numeric (HSK10 after HSK6)", lv["sorted"] == ["HSK1", "HSK2", "HSK6", "HSK10"])
        check("sortLevels keeps duplicates deterministically", lv["dupSorted"] == ["HSK1", "HSK2", "HSK2"])
        check("levelsFromCards == HSK1..6", lv["fromCards"] == ["HSK1", "HSK2", "HSK3", "HSK4", "HSK5", "HSK6"])
        check("levelsFromCards dedupes", lv["fromDup"] == ["HSK1", "HSK3"])

        # ---- SHUFFLE ----
        sh = pg.evaluate("""()=>{
          const S=HSKUtil.shuffle;
          const src=[1,2,3,4,5];
          const seq=[0.9,0.1,0.5,0.0,0.99]; let k=0; const rnd=()=>seq[(k++)%seq.length];
          k=0; const c1=S.shuffledCopy(src,rnd);
          k=0; const c2=S.shuffledCopy(src,rnd);
          const inPlaceArr=[1,2,3,4,5]; const ret=S.shuffleInPlace(inPlaceArr,rnd);
          return { copySameItems: c1.slice().sort((a,b)=>a-b).join(',')==='1,2,3,4,5',
                   copyLen: c1.length===5,
                   inputUnchanged: JSON.stringify(src)==='[1,2,3,4,5]',
                   deterministic: JSON.stringify(c1)===JSON.stringify(c2),
                   inPlaceSameRef: ret===inPlaceArr,
                   inPlaceSameItems: inPlaceArr.slice().sort((a,b)=>a-b).join(',')==='1,2,3,4,5',
                   empty: JSON.stringify(S.shuffledCopy([]))==='[]',
                   one: JSON.stringify(S.shuffledCopy([7]))==='[7]',
                   cardsNotMutated: (()=>{const before=window.HSK_CARDS[0]; S.shuffledCopy(window.HSK_CARDS); return window.HSK_CARDS[0]===before && window.HSK_CARDS.length===5002;})() };
        }""")
        for k in ["copySameItems", "copyLen", "inputUnchanged", "deterministic", "inPlaceSameRef",
                  "inPlaceSameItems", "empty", "one", "cardsNotMutated"]:
            check("shuffle:" + k, sh[k])

        # ---- CARD INDEX ----
        ci = pg.evaluate("""()=>{
          const C=HSKUtil.cardIndex; const cards=window.HSK_CARDS;
          const idx=C.buildCardById(cards);
          let allResolve=true; for(const c of cards){ if(C.getCardById(idx,c.id)!==c){ allResolve=false; break; } }
          const byLevel=C.buildCardsByLevel(cards);
          const counts={}; Object.keys(byLevel).forEach(k=>counts[k]=byLevel[k].length);
          const c0=cards[0]; const before=JSON.stringify(c0);
          C.buildCardById(cards); C.buildCardsByLevel(cards);
          return { size: idx.size, allResolve,
                   getById1: C.getCardById(idx,1)===cards.find(c=>c.id===1),
                   numericWorks: !!C.getCardById(idx,1),
                   stringMiss: C.getCardById(idx,'1')===undefined,
                   counts,
                   noMutation: JSON.stringify(cards[0])===before,
                   dupDetect: JSON.stringify(C.duplicateIds([{id:1},{id:1},{id:2}]))==='[1]',
                   noDupInReal: C.duplicateIds(cards).length===0 };
        }""")
        check("cardIndex size 5002", ci["size"] == 5002)
        check("cardIndex every id resolves to same card", ci["allResolve"])
        check("cardIndex getCardById numeric works", ci["numericWorks"] and ci["getById1"])
        check("cardIndex string id misses (numeric contract)", ci["stringMiss"])
        check("cardIndex level grouping counts", ci["counts"] == {"HSK1": 149, "HSK2": 150, "HSK3": 295, "HSK4": 600, "HSK5": 1295, "HSK6": 2513})
        check("cardIndex no card mutation", ci["noMutation"])
        check("cardIndex duplicate detection", ci["dupDetect"])
        check("cardIndex no dup in real data", ci["noDupInReal"])

        result = {"suite": "util_units", "pass": len(fails) == 0 and len(errs) == 0, "fails": fails, "errors": errs}
        print(json.dumps(result, ensure_ascii=False))
        b.close()
        return 0 if result["pass"] else 1

if __name__ == "__main__":
    import sys
    sys.exit(main())
