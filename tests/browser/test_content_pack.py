"""Unit + characterization tests for the Phase 10 read-only ContentPack contract
(window.HSKUtil.createContentPack) and the HSK adapter (window.HSKUtil.contentPack).
Runs in the real loaded browser.

Verifies the generic contract, HSK-pack metadata/decks/counts/validation, that
CardRepository initialized from the active pack is byte-equivalent to initializing
directly from HSK_CARDS, that the pack's testModes match TestModeQuery's built-in
defs, and the strict no-side-effects contract.
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

        check("factory present", pg.evaluate("()=>typeof window.HSKUtil.createContentPack==='function'"))
        check("active pack present", pg.evaluate("()=>typeof window.HSKUtil.contentPack==='object'"))

        # ---- GENERIC CONTRACT (synthetic packs) ----
        gc = pg.evaluate("""()=>{
          const mk=HSKUtil.createContentPack;
          const cards=[{id:1,lvl:'D1',w:'a'},{id:2,lvl:'D1',w:'b'},{id:3,lvl:'D2',w:'c'}];
          const snap=JSON.stringify(cards);
          const good=mk({ id:'p1', version:'1.0.0', title:'T',
            fieldRoles:{primaryPrompt:'w', deck:'lvl', stableId:'id'},
            deckProvider:function(cs){ return [{id:'D1',order:1,title:'D1',cardCount:2},{id:'D2',order:2,title:'D2',cardCount:1}]; },
            getCards:function(){ return cards; } });
          const v=good.validate();
          // returned decks are copies (mutating them doesn't corrupt the pack)
          const d=good.getDecks(); d.push({id:'X'}); const stillTwo=good.getDecks().length===2;
          // missing id
          const noId=mk({ getCards:()=>cards, fieldRoles:{stableId:'id',deck:'lvl',primaryPrompt:'w'}, deckProvider:()=>[] }).validate();
          // duplicate deck id
          const dupDeck=mk({ id:'p', getCards:()=>cards, fieldRoles:{stableId:'id',deck:'lvl',primaryPrompt:'w'},
            decks:[{id:'D1'},{id:'D1'},{id:'D2'}] }).validate();
          // card references undeclared deck
          const badRef=mk({ id:'p', getCards:()=>cards, fieldRoles:{stableId:'id',deck:'lvl',primaryPrompt:'w'},
            decks:[{id:'D1'}] }).validate();   // D2 not declared
          // duplicate stable id
          const dupId=mk({ id:'p', getCards:()=>[{id:1,lvl:'D1'},{id:1,lvl:'D1'}], fieldRoles:{stableId:'id',deck:'lvl',primaryPrompt:'w'}, decks:[{id:'D1'}] }).validate();
          // missing required role -> warning
          const noRole=mk({ id:'p', getCards:()=>cards, fieldRoles:{stableId:'id',deck:'lvl'}, decks:[{id:'D1'},{id:'D2'}] }).validate();
          return {
            goodOk: v.ok===true && v.cards===3 && v.decks===2 && v.idsUnique===true && v.deckRefsValid===true,
            deckOrder: JSON.stringify(good.getDeckIds())==='["D1","D2"]',
            decksCopied: stillTwo,
            sourceUnmutated: JSON.stringify(cards)===snap,
            role: good.getRole('primaryPrompt')==='w',
            noIdFails: noId.ok===false && noId.errors.some(e=>e.indexOf('id')>=0),
            dupDeckFails: dupDeck.ok===false,
            badRefFails: badRef.ok===false && badRef.deckRefsValid===false,
            dupIdFails: dupId.ok===false && dupId.idsUnique===false,
            missingRoleWarns: noRole.warnings.some(w=>w.indexOf('primaryPrompt')>=0)
          };
        }""")
        for k in ["goodOk", "deckOrder", "decksCopied", "sourceUnmutated", "role", "noIdFails", "dupDeckFails", "badRefFails", "dupIdFails", "missingRoleWarns"]:
            check("generic:" + k, gc[k])

        # ---- HSK PACK metadata / decks / counts / validation ----
        hk = pg.evaluate("""()=>{
          const p=HSKUtil.contentPack;
          const decks=p.getDecks();
          const counts={}; decks.forEach(d=>counts[d.id]=d.cardCount);
          const v=p.validate();
          return {
            id:p.getId(), version:p.getVersion(), title:p.getTitle(),
            deckIds:p.getDeckIds(),
            deckOrders: decks.map(d=>d.order),
            counts, total: p.getCards().length,
            roles: p.getFieldRoles(),
            languages: p.getLanguages(),
            hasStudy: p.hasCapability('study'), hasTest: p.hasCapability('test'),
            valOk: v.ok, valIdsUnique: v.idsUnique, valDeckRefs: v.deckRefsValid, valErrors: v.errors
          };
        }""")
        check("hsk id", hk["id"] == "hsk")
        check("hsk version", hk["version"] == "1.0.0")
        check("hsk title present", isinstance(hk["title"], str) and len(hk["title"]) > 0)
        check("hsk 6 decks in order", hk["deckIds"] == ["HSK1", "HSK2", "HSK3", "HSK4", "HSK5", "HSK6"])
        check("hsk deck orders 1..6", hk["deckOrders"] == [1, 2, 3, 4, 5, 6])
        check("hsk per-deck counts exact", hk["counts"] == {"HSK1": 149, "HSK2": 150, "HSK3": 295, "HSK4": 600, "HSK5": 1295, "HSK6": 2513})
        check("hsk total 5002", hk["total"] == 5002)
        check("hsk field roles exact", hk["roles"] == {
            "primaryPrompt": "word", "pronunciation": "pinyin", "definition": "meaning",
            "exampleText": "example", "examplePronunciation": "examplePinyin",
            "exampleTranslation": "translation", "deck": "level", "stableId": "id"})
        check("hsk languages", hk["languages"] == {"prompt": "zh", "reading": "pinyin", "meaning": "vi", "audio": "zh-CN"})
        check("hsk capabilities study+test", hk["hasStudy"] and hk["hasTest"])
        check("hsk validation ok", hk["valOk"] and hk["valIdsUnique"] and hk["valDeckRefs"] and hk["valErrors"] == [])

        # ---- HSK IDs 1..5002 unique & stable ----
        ids = pg.evaluate("""()=>{
          const cards=HSKUtil.contentPack.getCards();
          const set=new Set(cards.map(c=>c.id));
          let contiguous=true; for(let i=1;i<=5002;i++){ if(!set.has(i)){ contiguous=false; break; } }
          return { count:cards.length, unique:set.size===cards.length, contiguous,
                   first:cards[0].id, last:cards[cards.length-1].id };
        }""")
        check("hsk ids unique", ids["unique"])
        check("hsk ids 1..5002 contiguous", ids["contiguous"])
        check("hsk source order first 1 last 5002", ids["first"] == 1 and ids["last"] == 5002)

        # ---- CARD REPOSITORY EQUIVALENCE: pack-init vs direct HSK_CARDS-init ----
        eq = pg.evaluate("""()=>{
          const fromPack=HSKUtil.cards;                                   // production repo (pack-initialized)
          const fromRaw=HSKUtil.createCardRepository(window.HSK_CARDS);   // direct init
          const sameGetAllRef = fromPack.getAll()===window.HSK_CARDS && fromRaw.getAll()===window.HSK_CARDS;
          const sameCount = fromPack.count()===fromRaw.count() && fromPack.count()===5002;
          const sameLevels = JSON.stringify(fromPack.getLevels())===JSON.stringify(fromRaw.getLevels());
          const sameByLevel = JSON.stringify(fromPack.countByLevel())===JSON.stringify(fromRaw.countByLevel());
          let sameById=true; for(let i=1;i<=5002;i+=137){ if(fromPack.getById(i)!==fromRaw.getById(i)){ sameById=false; break; } }
          const sameGetByLevel = JSON.stringify(fromPack.getByLevel('HSK3').map(c=>c.id))===JSON.stringify(fromRaw.getByLevel('HSK3').map(c=>c.id));
          const packCardsAreSource = HSKUtil.contentPack.getCards()===window.HSK_CARDS;
          return { sameGetAllRef, sameCount, sameLevels, sameByLevel, sameById, sameGetByLevel, packCardsAreSource };
        }""")
        for k in ["sameGetAllRef", "sameCount", "sameLevels", "sameByLevel", "sameById", "sameGetByLevel", "packCardsAreSource"]:
            check("repoEquiv:" + k, eq[k])

        # ---- TEST MODE MAPPING equivalence (pack testModes == TestModeQuery defs) ----
        tm = pg.evaluate("""()=>{
          const packModes=HSKUtil.contentPack.getTestModes();
          const queryDefs=HSKUtil.testMode.getTypeDefs();
          return { equal: JSON.stringify(packModes)===JSON.stringify(queryDefs),
                   six: packModes.length===6 };
        }""")
        check("testmode pack defs == query defs", tm["equal"])
        check("testmode 6 modes", tm["six"])

        # ---- NO SIDE EFFECTS ----
        se = pg.evaluate("""()=>{
          const before={}; for(let i=0;i<localStorage.length;i++){const k=localStorage.key(i); before[k]=localStorage.getItem(k);}
          const beforeLen=localStorage.length;
          const p=HSKUtil.contentPack;
          const srcSnapLen=window.HSK_CARDS.length, firstId=window.HSK_CARDS[0].id;
          for(let i=0;i<30;i++){ p.getCards(); p.getDecks(); p.getFieldRoles(); p.getLanguages(); p.getCapabilities(); p.getTestModes(); p.validate(); }
          const after={}; for(let i=0;i<localStorage.length;i++){const k=localStorage.key(i); after[k]=localStorage.getItem(k);}
          let unchanged=localStorage.length===beforeLen;
          for(const k in before){ if(before[k]!==after[k]) unchanged=false; }
          for(const k in after){ if(!(k in before)) unchanged=false; }
          return { storageUnchanged:unchanged, sourceUnmutated: window.HSK_CARDS.length===srcSnapLen && window.HSK_CARDS[0].id===firstId };
        }""")
        for k in ["storageUnchanged", "sourceUnmutated"]:
            check("sideEffect:" + k, se[k])

        result = {"suite": "content_pack", "pass": len(fails) == 0 and len(errs) == 0, "fails": fails, "errors": errs}
        print(json.dumps(result, ensure_ascii=False))
        b.close()
        return 0 if result["pass"] else 1

if __name__ == "__main__":
    import sys
    sys.exit(main())
