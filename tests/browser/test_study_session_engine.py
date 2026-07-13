"""Unit + characterization tests for the Phase 16 read-only StudySessionEngine
(window.HSKUtil.createStudySessionEngine). Runs in the real loaded browser.

Verifies session construction (delegates to StudySessionQuery), session/card read
models, answer-leak-safe front/back separation, settings/metadata/progress flag reads,
account/provider isolation, and the strict no-side-effects contract. Includes an
inline-vs-engine characterization of the display computations.
"""
import os, json
from playwright.sync_api import sync_playwright

URL = os.environ.get("HSK_BASE_URL", "http://localhost:8000") + "/hsk_flashcard_app/"
EMPTY = 'window.SUPABASE_CONFIG={url:"",anonKey:""};'
fails = []
def check(n, c):
    if not c: fails.append(n)

HELPERS = r"""
window.__mkCards = function(n, level, base){ var a=[]; for(var i=0;i<n;i++){ var id=base+i;
  a.push({ id:id, level:level, word:"W"+id, pinyin:"py"+id, meaning:"m"+id, example:"ex"+id, examplePinyin:"exp"+id, translation:"tr"+id }); } return a; };
// build an engine over synthetic cards + injectable progress/settings/metadata
window.__mkEngine = function(cards, prog, opts){
  opts = opts || {};
  var cardRepo = HSKUtil.createCardRepository(cards);
  var progRepo = HSKUtil.createProgressRepository({ progressProvider: function(){ return prog||{}; } });
  var settingsRepo = HSKUtil.createSettingsRepository(function(){ return opts.settings||{}; });
  var metaQuery = HSKUtil.createUserMetadataQuery({ cardRepository: cardRepo, metadataProvider: function(){ return opts.meta||{}; } });
  var sessionQuery = HSKUtil.createStudySessionQuery({ cardRepository: cardRepo, progressRepository: progRepo,
    dateProvider: function(){ return opts.today||'2026-07-13'; }, randomProvider: opts.rnd||function(){ return 0.5; } });
  return HSKUtil.createStudySessionEngine({
    contentPack: HSKUtil.contentPack, cardRepository: cardRepo, progressRepository: progRepo,
    settingsRepository: settingsRepo, studySessionQuery: sessionQuery, userMetadataQuery: metaQuery,
    dateProvider: function(){ return opts.today||'2026-07-13'; } });
};
// inline (original) display computations
window.__oldDeckLabel = function(cards){ return [...new Set(cards.map(x=>x.level))].join(" + "); };
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

        check("factory present", pg.evaluate("()=>typeof window.HSKUtil.createStudySessionEngine==='function'"))

        # ---- STANDARD SESSION (delegates to StudySessionQuery; sizes/levels) ----
        ss = pg.evaluate("""()=>{
          const cards=__mkCards(30,'HSK1',1).concat(__mkCards(30,'HSK2',100));
          const snap=JSON.stringify(cards);
          const e=__mkEngine(cards, {});   // empty progress -> all untouched (due+fresh)
          const n=size=>e.buildSession({levels:['HSK1'], sessionSize:size}).cards.length;
          const model=e.buildSession({levels:['HSK1'], sessionSize:'20'});
          const mixed=e.buildSession({levels:['HSK1','HSK2'], sessionSize:'all'}).cards.length;
          const empty=e.buildSession({levels:['HSK99'], sessionSize:'10'}).cards.length;
          return { ten:n('10'), twenty:n('20'), fifty:n('50')===30, all:n('all')===30,
                   modelShape: model.total===20 && model.currentIndex===0 && model.currentNumber===1 && model.completed===false,
                   mixed: mixed===60, empty: empty===0,
                   sourceUnmutated: JSON.stringify(cards)===snap,
                   order: JSON.stringify(model.cards.slice(0,3).map(c=>c.id))==='[1,2,3]' };
        }""")
        check("standard 10", ss["ten"] == 10)
        check("standard 20", ss["twenty"] == 20)
        check("standard 50 capped", ss["fifty"])
        check("standard all", ss["all"])
        check("standard model shape", ss["modelShape"])
        check("standard mixed levels", ss["mixed"])
        check("standard empty pool", ss["empty"])
        check("standard source unmutated", ss["sourceUnmutated"])
        check("standard order preserved", ss["order"])

        # ---- EXPLICIT SESSION (order/dups/missing/empty) ----
        ex = pg.evaluate("""()=>{
          const cards=__mkCards(5,'HSK1',1);   // ids 1..5
          const e=__mkEngine(cards, {});
          const ids=arr=>e.buildExplicitSession({cardIds:arr}).cards.map(c=>c.id);
          return { order: JSON.stringify(ids([3,1,2]))==='[3,1,2]',
                   dups: JSON.stringify(ids([1,1,2]))==='[1,2]',
                   missing: JSON.stringify(ids([1,999,2]))==='[1,2]',
                   empty: e.buildExplicitSession({cardIds:[]}).cards.length===0 };
        }""")
        for k in ["order", "dups", "missing", "empty"]:
            check("explicit:" + k, ex[k])

        # ---- DESCRIBE SESSION (first/middle/last/completed/empty + characterization) ----
        ds = pg.evaluate("""()=>{
          const cards=__mkCards(3,'HSK1',1).concat(__mkCards(2,'HSK2',100));  // 5 cards, 2 decks
          const e=__mkEngine(cards, {});
          const d=(i)=>e.describeSession({cards:cards, currentIndex:i});
          const first=d(0), mid=d(2), last=d(4), done=d(5), over=d(9);
          const empty=e.describeSession({cards:[], currentIndex:0});
          return {
            firstNum: first.currentNumber===1 && first.total===5 && first.completed===false && first.currentCard.id===1,
            midRemaining: mid.remaining===3 && mid.currentIndex===2 && mid.currentCard.id===3,
            lastNum: last.currentNumber===5 && last.completed===false && last.remaining===1,
            completed: done.completed===true && done.currentCard===null,
            overRange: over.completed===true && over.currentCard===null,
            emptyCompleted: empty.completed===true && empty.total===0 && empty.progressPct===0,
            deckLabelChar: first.deckLabel===__oldDeckLabel(cards),   // == inline distinct-join
            deckLabelValue: first.deckLabel==='HSK1 + HSK2',
            progressPct: mid.progressPct===(2/5)*100
          };
        }""")
        for k in ["firstNum", "midRemaining", "lastNum", "completed", "overRange", "emptyCompleted", "deckLabelChar", "deckLabelValue", "progressPct"]:
            check("describeSession:" + k, ds[k])

        # ---- DESCRIBE CARD (front/back, flags) + ANSWER-LEAK ----
        dc = pg.evaluate("""()=>{
          const cards=__mkCards(3,'HSK1',1);
          const prog={ 1:{due:'2020-01-01',interval:3,reps:2,correct:1,attempts:2} };   // card1 learned+overdue
          const meta={ bookmarks:[2], notes:{3:'my note'} };
          const e=__mkEngine(cards, prog, { settings:{showFrontPinyin:true}, meta:meta, today:'2026-07-13' });
          const c1=e.describeCard({card:cards[0], flipped:false});   // learned, due
          const c2=e.describeCard({card:cards[1], flipped:true});    // bookmarked
          const c3=e.describeCard({cardId:3, flipped:false});         // has note (by id)
          // front (unflipped) must NOT carry answer-side values
          const frontKeys=Object.keys(c1.front);
          const frontNoAnswer=frontKeys.indexOf('definition')<0 && frontKeys.indexOf('example')<0 && frontKeys.indexOf('translation')<0;
          const frontStr=JSON.stringify(c1.front);
          const noLeak=frontStr.indexOf('m1')<0 && frontStr.indexOf('ex1')<0 && frontStr.indexOf('tr1')<0;   // meaning/example/translation absent
          const snap=JSON.stringify(cards);
          e.describeCard({card:cards[0], flipped:true});   // must not mutate the card
          return {
            frontPrimary: c1.front.primary==='W1', frontPron: c1.front.pronunciation==='py1',
            backHasAnswer: c1.back.definition==='m1' && c1.back.example==='ex1' && c1.back.translation==='tr1',
            frontNoAnswer, noLeak,
            learned1: c1.learned===true, due1: c1.due===true,
            bookmarked2: c2.bookmarked===true && c1.bookmarked===false,
            note3: c3.hasNote===true && c3.note==='my note' && c1.hasNote===false,
            flippedEcho: c1.flipped===false && c2.flipped===true,
            cardUnmutated: JSON.stringify(cards)===snap,
            missingCard: e.describeCard({cardId:999})===null
          };
        }""")
        for k in ["frontPrimary", "frontPron", "backHasAnswer", "frontNoAnswer", "noLeak",
                  "learned1", "due1", "bookmarked2", "note3", "flippedEcho", "cardUnmutated", "missingCard"]:
            check("describeCard:" + k, dc[k])

        # ---- FRONT-PINYIN VISIBILITY + note whitespace + future due ----
        misc = pg.evaluate("""()=>{
          const cards=__mkCards(2,'HSK1',1);
          const eOff=__mkEngine(cards, {}, { settings:{showFrontPinyin:false}, meta:{notes:{1:'   '}} });
          const eOn=__mkEngine(cards, {2:{due:'2999-01-01',interval:5,reps:1,correct:1,attempts:1}}, { settings:{}, today:'2026-07-13' });
          const cOff=eOff.describeCard({card:cards[0], flipped:false});
          const cFuture=eOn.describeCard({card:cards[1], flipped:false});
          return {
            fpHidden: cOff.frontPinyinVisible===false,
            fpDefaultOn: eOn.describeCard({card:cards[0]}).frontPinyinVisible===true,   // undefined => true
            whitespaceNote: cOff.hasNote===false && cOff.note==='   ',                  // getNote raw, hasNote trims
            futureNotDue: cFuture.due===false, futureLearned: cFuture.learned===true
          };
        }""")
        for k in ["fpHidden", "fpDefaultOn", "whitespaceNote", "futureNotDue", "futureLearned"]:
            check("misc:" + k, misc[k])

        # ---- ACCOUNT / PROVIDER ISOLATION (progress + metadata swap) ----
        ai = pg.evaluate("""()=>{
          const cards=__mkCards(2,'HSK1',1);
          const A={prog:{1:{due:'2020-01-01',interval:3,reps:2,correct:1,attempts:2}}, meta:{bookmarks:[1]}};
          const B={prog:{}, meta:{bookmarks:[]}};
          const active={who:A};
          const cardRepo=HSKUtil.createCardRepository(cards);
          const e=HSKUtil.createStudySessionEngine({
            contentPack:HSKUtil.contentPack, cardRepository:cardRepo,
            progressRepository:HSKUtil.createProgressRepository({progressProvider:function(){return active.who.prog;}}),
            settingsRepository:HSKUtil.createSettingsRepository(function(){return {};}),
            studySessionQuery:HSKUtil.createStudySessionQuery({cardRepository:cardRepo, progressRepository:HSKUtil.createProgressRepository({progressProvider:function(){return active.who.prog;}}), dateProvider:function(){return '2026-07-13';}, randomProvider:function(){return 0.5;}}),
            userMetadataQuery:HSKUtil.createUserMetadataQuery({cardRepository:cardRepo, metadataProvider:function(){return active.who.meta;}}),
            dateProvider:function(){return '2026-07-13';} });
          const a1=e.describeCard({card:cards[0]});
          active.who=B; const bC=e.describeCard({card:cards[0]});
          active.who=A; const a2=e.describeCard({card:cards[0]});
          return { aLearnedBm: a1.learned===true && a1.bookmarked===true,
                   bClean: bC.learned===false && bC.bookmarked===false,
                   backToA: a2.learned===true && a2.bookmarked===true };
        }""")
        for k in ["aLearnedBm", "bClean", "backToA"]:
            check("isolation:" + k, ai[k])

        # ---- NO SIDE EFFECTS ----
        se = pg.evaluate("""()=>{
          const before={}; for(let i=0;i<localStorage.length;i++){const k=localStorage.key(i); before[k]=localStorage.getItem(k);}
          const beforeLen=localStorage.length;
          const cards=__mkCards(40,'HSK1',1); const snap=JSON.stringify(cards);
          const prog={5:{due:'2020-01-01',interval:1,reps:1,correct:1,attempts:1}}; const psnap=JSON.stringify(prog);
          const e=__mkEngine(cards, prog, { meta:{bookmarks:[3],notes:{4:'n'}} });
          for(let i=0;i<10;i++){ e.buildSession({levels:['HSK1'],sessionSize:'20'}); e.describeSession({cards:cards,currentIndex:5}); e.describeCard({card:cards[0],flipped:false}); e.describeCard({cardId:5,flipped:true}); }
          const after={}; for(let i=0;i<localStorage.length;i++){const k=localStorage.key(i); after[k]=localStorage.getItem(k);}
          let unchanged=localStorage.length===beforeLen;
          for(const k in before){ if(before[k]!==after[k]) unchanged=false; }
          for(const k in after){ if(!(k in before)) unchanged=false; }
          return { storageUnchanged:unchanged, cardsUnmutated:JSON.stringify(cards)===snap, progUnmutated:JSON.stringify(prog)===psnap };
        }""")
        for k in ["storageUnchanged", "cardsUnmutated", "progUnmutated"]:
            check("sideEffect:" + k, se[k])

        result = {"suite": "study_session_engine", "pass": len(fails) == 0 and len(errs) == 0, "fails": fails, "errors": errs}
        print(json.dumps(result, ensure_ascii=False))
        b.close()
        return 0 if result["pass"] else 1

if __name__ == "__main__":
    import sys
    sys.exit(main())
