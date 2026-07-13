"""Unit + characterization tests for the Phase 7 read-only UserMetadataQuery
(window.HSKUtil.createUserMetadataQuery). Runs in the real loaded browser.

Verifies bookmark membership, bookmark-card resolution/order/dedup/level filter,
note read semantics, account isolation (provider swap), existing-write visibility,
and the strict no-side-effects contract. Includes CHARACTERIZATION comparisons:
faithful copies of the ORIGINAL inline metadata.js/insights.js reads vs the query
over identical fixtures => byte-equal.
"""
import os, json
from playwright.sync_api import sync_playwright

URL = os.environ.get("HSK_BASE_URL", "http://localhost:8000") + "/hsk_flashcard_app/"
EMPTY = 'window.SUPABASE_CONFIG={url:"",anonKey:""};'
fails = []
def check(n, c):
    if not c: fails.append(n)

HELPERS = r"""
window.__mkRepo = function(cards){ return HSKUtil.createCardRepository(cards); };
window.__mkMQ = function(cards, meta){
  return HSKUtil.createUserMetadataQuery({ cardRepository: __mkRepo(cards), metadataProvider: function(){ return meta; } });
};
// ORIGINAL inline reads (metadata.js / insights.js pre-Phase-7)
window.__trim = function(x){ return String(x==null?"":x).trim(); };
window.__oldBookmarks = function(s){ return Array.isArray(s.bookmarks) ? s.bookmarks : []; };
window.__oldIsBookmarked = function(s,id){ return __oldBookmarks(s).indexOf(id) >= 0; };
window.__oldNotesMap = function(s){ return (s.notes && typeof s.notes==="object") ? s.notes : {}; };
window.__oldGetNote = function(s,id){ var n=__oldNotesMap(s)[id]; return n ? String(n) : ""; };
window.__oldHasNote = function(s,id){ return __trim(__oldGetNote(s,id)) !== ""; };
window.__oldBookmarkCards = function(repo,s){ return repo.getManyByIds(__oldBookmarks(s).map(Number)).map(function(c){return c.id;}); };
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

        check("factory present", pg.evaluate("()=>typeof window.HSKUtil.createUserMetadataQuery==='function'"))
        check("shared instance present", pg.evaluate("()=>typeof window.HSKUtil.userMetadata==='object'"))

        # ---- CONSTRUCTION / PROVIDER ----
        con = pg.evaluate("""()=>{
          const cards=[{id:1,level:'HSK1'},{id:2,level:'HSK1'}];
          const holder={cur:{bookmarks:[1],notes:{1:'a'}}};
          const q=HSKUtil.createUserMetadataQuery({cardRepository:__mkRepo(cards), metadataProvider:()=>holder.cur});
          const before=q.isBookmarked(1);
          holder.cur={bookmarks:[2],notes:{}};            // replace container entirely
          const after=q.isBookmarked(1), after2=q.isBookmarked(2);
          const src={bookmarks:[1,2],notes:{1:'x'}}, snap=JSON.stringify(src);
          const q2=__mkMQ(cards,src);
          q2.getBookmarkIds(); q2.isBookmarked(1); q2.getBookmarkedCards(); q2.getNote(1); q2.hasNote(1); q2.getNotesMap(); q2.getCardMetadata(1);
          return {
            observesReplacement: before===true && after===false && after2===true,
            emptySource: (()=>{const e=__mkMQ(cards,{}); return e.getBookmarkIds().length===0 && e.getNote(1)==='' && e.hasNote(1)===false && e.getBookmarkedCards().length===0;})(),
            nullSource: (()=>{const e=HSKUtil.createUserMetadataQuery({cardRepository:__mkRepo(cards), metadataProvider:()=>null}); return e.getBookmarkIds().length===0 && e.isBookmarked(1)===false && e.getNote(1)==='';})(),
            sourceUnmutated: JSON.stringify(src)===snap
          };
        }""")
        for k in ["observesReplacement", "emptySource", "nullSource", "sourceUnmutated"]:
            check("construction:" + k, con[k])

        # ---- BOOKMARK MEMBERSHIP (+ characterization) ----
        mem = pg.evaluate("""()=>{
          const cards=[{id:1,level:'HSK1'},{id:2,level:'HSK1'},{id:3,level:'HSK2'},{id:5,level:'HSK2'}];
          const meta={bookmarks:[3,1,999,1]};    // 999 has no card; 1 duplicated
          const q=__mkMQ(cards,meta);
          const ids=[1,2,3,4,5,999];
          const charMatch=ids.every(id=>q.isBookmarked(id)===__oldIsBookmarked(meta,id));
          return { charMatch,
                   bookmarked1: q.isBookmarked(1)===true,
                   notBookmarked2: q.isBookmarked(2)===false,
                   missingCard4: q.isBookmarked(4)===false,
                   invalidStored999: q.isBookmarked(999)===true,     // stored, membership true even w/o card
                   stringIdBehaviour: q.isBookmarked('1')===false,    // strict indexOf (numbers) -> string misses
                   idsCopy: JSON.stringify(q.getBookmarkIds())==='[3,1,999,1]' };
        }""")
        for k in ["charMatch", "bookmarked1", "notBookmarked2", "missingCard4", "invalidStored999", "stringIdBehaviour", "idsCopy"]:
            check("membership:" + k, mem[k])

        # ---- BOOKMARK LIST (order/dedup/missing, + characterization, no mutation) ----
        lst = pg.evaluate("""()=>{
          const cards=[{id:1,level:'HSK1'},{id:2,level:'HSK1'},{id:3,level:'HSK2'},{id:5,level:'HSK2'}];
          const meta={bookmarks:[3,1,999,1]};
          const q=__mkMQ(cards,meta);
          const got=q.getBookmarkedCards().map(c=>c.id);
          const old=__oldBookmarkCards(__mkRepo(cards),meta);
          const snap=JSON.stringify(meta.bookmarks);
          q.getBookmarkedCards();  // must not mutate source
          const cardObj=cards[0], cardSnap=JSON.stringify(cardObj);
          return { char: JSON.stringify(got)===JSON.stringify(old),
                   order: JSON.stringify(got)==='[3,1,1]',     // insertion order, 999 skipped, dup kept
                   empty: __mkMQ(cards,{}).getBookmarkedCards().length===0,
                   one: JSON.stringify(__mkMQ(cards,{bookmarks:[5]}).getBookmarkedCards().map(c=>c.id))==='[5]',
                   count: q.countBookmarks()===3,
                   sourceUnmutated: JSON.stringify(meta.bookmarks)===snap,
                   cardUnmutated: JSON.stringify(cards[0])===cardSnap };
        }""")
        for k in ["char", "order", "empty", "one", "count", "sourceUnmutated", "cardUnmutated"]:
            check("list:" + k, lst[k])

        # ---- LEVEL FILTER ----
        lf = pg.evaluate("""()=>{
          const cards=[{id:1,level:'HSK1'},{id:2,level:'HSK4'},{id:3,level:'HSK6'},{id:4,level:'HSK1'}];
          const meta={bookmarks:[4,3,2,1]};
          const q=__mkMQ(cards,meta);
          const ids=o=>q.getBookmarkedCards(o).map(c=>c.id);
          return { all: JSON.stringify(ids())==='[4,3,2,1]',
                   allExplicit: JSON.stringify(ids({level:'all'}))==='[4,3,2,1]',
                   hsk1: JSON.stringify(ids({level:'HSK1'}))==='[4,1]',   // insertion order preserved
                   hsk6: JSON.stringify(ids({level:'HSK6'}))==='[3]',
                   unknown: JSON.stringify(ids({level:'HSK99'}))==='[]',
                   countHsk1: q.countBookmarks({level:'HSK1'})===2 };
        }""")
        for k in ["all", "allExplicit", "hsk1", "hsk6", "unknown", "countHsk1"]:
            check("levelFilter:" + k, lf[k])

        # ---- NOTES (+ characterization) ----
        nt = pg.evaluate("""()=>{
          const cards=[{id:1,level:'HSK1'}];
          const longNote='x'.repeat(1000), script='<script>alert(1)</'+'script>';
          const meta={notes:{2:'hello', 3:'   ', 5:'line1\\nline2', 7:longNote, 9:script}};
          const q=__mkMQ(cards,meta);
          const idsToCheck=[1,2,3,5,7,9];
          const charNote=idsToCheck.every(id=>q.getNote(id)===__oldGetNote(meta,id));
          const charHas=idsToCheck.every(id=>q.hasNote(id)===__oldHasNote(meta,id));
          return { charNote, charHas,
                   missing: q.getNote(1)==='' && q.hasNote(1)===false,
                   normal: q.getNote(2)==='hello' && q.hasNote(2)===true,
                   whitespaceText: q.getNote(3)==='   ',           // getNote returns raw whitespace
                   whitespaceNoIndicator: q.hasNote(3)===false,    // but hasNote trims -> false
                   multiline: q.getNote(5)==='line1\\nline2' && q.hasNote(5)===true,
                   long: q.getNote(7).length===1000,
                   scriptAsString: q.getNote(9)===script && typeof q.getNote(9)==='string',
                   mapCopy: (()=>{const m=q.getNotesMap(); m[2]='MUT'; return q.getNote(2)==='hello';})() };
        }""")
        for k in ["charNote", "charHas", "missing", "normal", "whitespaceText", "whitespaceNoIndicator", "multiline", "long", "scriptAsString", "mapCopy"]:
            check("notes:" + k, nt[k])

        # ---- CARD METADATA MODEL ----
        cm = pg.evaluate("""()=>{
          const cards=[{id:1,level:'HSK1'},{id:2,level:'HSK1'}];
          const q=__mkMQ(cards,{bookmarks:[1],notes:{1:'n'}});
          const a=q.getCardMetadata(1), b=q.getCardMetadata(2);
          return { a: a.cardId===1 && a.bookmarked===true && a.hasNote===true && a.note==='n',
                   b: b.cardId===2 && b.bookmarked===false && b.hasNote===false && b.note==='' };
        }""")
        check("cardMetadata bookmarked+note", cm["a"])
        check("cardMetadata plain", cm["b"])

        # ---- ACCOUNT ISOLATION ----
        ai = pg.evaluate("""()=>{
          const cards=[{id:1,level:'HSK1'},{id:2,level:'HSK1'}];
          const A={bookmarks:[1],notes:{1:'A-note'}};
          const B={bookmarks:[2],notes:{2:'B-note'}};
          const active={who:A};
          const q=HSKUtil.createUserMetadataQuery({cardRepository:__mkRepo(cards), metadataProvider:()=>active.who});
          const a1=q.isBookmarked(1)&&q.getNote(1)==='A-note'&&!q.isBookmarked(2);
          active.who=B; const bOk=q.isBookmarked(2)&&q.getNote(2)==='B-note'&&!q.isBookmarked(1)&&q.getNote(1)==='';
          active.who=A; const a2=q.isBookmarked(1)&&q.getNote(1)==='A-note';
          active.who={}; const localOnly=q.getBookmarkIds().length===0&&q.getNote(1)==='';
          return { a1, bOk, a2, localOnly };
        }""")
        for k in ["a1", "bOk", "a2", "localOnly"]:
            check("isolation:" + k, ai[k])

        # ---- EXISTING WRITE VISIBILITY (query is not the writer) ----
        wv = pg.evaluate("""()=>{
          const cards=[{id:1,level:'HSK1'},{id:2,level:'HSK1'}];
          const meta={bookmarks:[1],notes:{1:'first'}};
          const q=__mkMQ(cards,meta);
          const before=q.isBookmarked(2)===false && q.getNote(2)==='';
          // simulate the EXISTING metadata.js write path mutating the same object
          meta.bookmarks.push(2); meta.notes[2]='second';
          const after=q.isBookmarked(2)===true && q.getNote(2)==='second';
          // and a removal
          meta.bookmarks.splice(meta.bookmarks.indexOf(1),1); delete meta.notes[1];
          const removed=q.isBookmarked(1)===false && q.getNote(1)==='';
          return { before, after, removed };
        }""")
        for k in ["before", "after", "removed"]:
            check("writeVisibility:" + k, wv[k])

        # ---- NO SIDE EFFECTS (shared instance + real page localStorage) ----
        se = pg.evaluate("""()=>{
          const before={}; for(let i=0;i<localStorage.length;i++){const k=localStorage.key(i); before[k]=localStorage.getItem(k);}
          const beforeLen=localStorage.length;
          const cards=[]; for(let i=1;i<=30;i++) cards.push({id:i,level:'HSK1'});
          const meta={bookmarks:[1,2,3,999],notes:{1:'a',2:'b'}}; const snap=JSON.stringify(meta);
          const q=__mkMQ(cards,meta);
          for(let i=0;i<40;i++){ q.getBookmarkIds(); q.isBookmarked(1); q.getBookmarkedCards(); q.getBookmarkedCards({level:'HSK1'}); q.countBookmarks(); q.getNote(1); q.hasNote(2); q.getNotesMap(); q.getCardMetadata(3); }
          const after={}; for(let i=0;i<localStorage.length;i++){const k=localStorage.key(i); after[k]=localStorage.getItem(k);}
          let unchanged=localStorage.length===beforeLen;
          for(const k in before){ if(before[k]!==after[k]) unchanged=false; }
          for(const k in after){ if(!(k in before)) unchanged=false; }
          return { storageUnchanged:unchanged, metaUnmutated:JSON.stringify(meta)===snap };
        }""")
        for k in ["storageUnchanged", "metaUnmutated"]:
            check("sideEffect:" + k, se[k])

        # ---- SHARED INSTANCE mirrors live settings (bookmarks/notes nested there) ----
        shared = pg.evaluate("""()=>{
          const live = window.HSK_APP.getSettings();
          const q = HSKUtil.userMetadata;
          const b = Array.isArray(live.bookmarks) ? live.bookmarks : [];
          return { idsMirror: JSON.stringify(q.getBookmarkIds())===JSON.stringify(b) };
        }""")
        check("shared mirrors live settings bookmarks", shared["idsMirror"])

        result = {"suite": "user_metadata_query", "pass": len(fails) == 0 and len(errs) == 0, "fails": fails, "errors": errs}
        print(json.dumps(result, ensure_ascii=False))
        b.close()
        return 0 if result["pass"] else 1

if __name__ == "__main__":
    import sys
    sys.exit(main())
