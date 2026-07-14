"""Unit tests for the Phase 4 read-only SettingsRepository
(window.HSKUtil.createSettingsRepository + HSKUtil.settings). Runs in the real
loaded browser. Verifies provider lifecycle (source replacement observed, no
stale cache => account isolation), generic get semantics, exact normalization of
each typed getter, and the strict no-side-effects (no localStorage write / no
dirty mark / no source mutation) contract.
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

        check("factory present", pg.evaluate("()=>typeof window.HSKUtil.createSettingsRepository==='function'"))
        check("shared instance present", pg.evaluate("()=>typeof window.HSKUtil.settings==='object'"))

        # ---- CONSTRUCTION / PROVIDER LIFECYCLE ----
        con = pg.evaluate("""()=>{
          const mk=HSKUtil.createSettingsRepository;
          // provider over a mutable holder => must observe source REPLACEMENT
          const holder={cur:{streak:5}};
          const r=mk(()=>holder.cur);
          const before=r.getStreak();
          holder.cur={streak:9};                 // replace the object entirely
          const after=r.getStreak();
          // source object must never be mutated by reads
          const src={selectedLevels:['HSK2'],autoReadWord:true,streak:3};
          const snap=JSON.stringify(src);
          const r2=mk(()=>src);
          r2.getAll(); r2.get('streak'); r2.getSelectedLevels(); r2.getSpeechRate();
          r2.getFrontPinyinEnabled(); r2.getAutoReadWordEnabled(); r2.getStreak();
          return {
            observesReplacement: before===5 && after===9,
            emptySource: mk(()=>({})).getStreak()===0 && mk(()=>({})).getSessionSize()==='20',
            nullSource: mk(()=>null).getStreak()===0 && JSON.stringify(mk(()=>null).getSelectedLevels())==='["HSK1"]',
            undefinedSource: mk(()=>undefined).getFrontPinyinEnabled()===true,
            nonFnProvider: mk({streak:7}).getStreak()===7,     // plain object provider
            sourceUnmutated: JSON.stringify(src)===snap,
            getAllLive: (()=>{const h={cur:{a:1}}; const rr=mk(()=>h.cur); const g1=rr.getAll(); h.cur={a:2}; return rr.getAll().a===2 && g1.a===1;})()
          };
        }""")
        for k in ["observesReplacement","emptySource","nullSource","undefinedSource","nonFnProvider","sourceUnmutated","getAllLive"]:
            check("construction:" + k, con[k])

        # ---- GENERIC GET ----
        gg = pg.evaluate("""()=>{
          const mk=HSKUtil.createSettingsRepository;
          const s={present:'x', f:false, z:0, empty:'', nul:null};
          const r=mk(()=>s);
          return {
            existing: r.get('present','fb')==='x',
            missingFallback: r.get('nope','fb')==='fb',
            missingNoFallback: r.get('nope')===undefined,
            explicitFalse: r.get('f',true)===false,       // explicit false NOT replaced
            explicitZero: r.get('z',99)===0,              // explicit 0 NOT replaced
            emptyString: r.get('empty','fb')==='',        // empty string preserved
            nullFallback: r.get('nul','fb')==='fb',        // null -> fallback (current semantics)
            hasTrue: r.has('present')===true,
            hasFalseKeyExists: r.has('f')===true,          // key present even though value false
            hasMissing: r.has('nope')===false
          };
        }""")
        for k in ["existing","missingFallback","missingNoFallback","explicitFalse","explicitZero","emptyString","nullFallback","hasTrue","hasFalseKeyExists","hasMissing"]:
            check("get:" + k, gg[k])

        # ---- SELECTED LEVELS ----
        sl = pg.evaluate("""()=>{
          const mk=HSKUtil.createSettingsRepository;
          const valid={selectedLevels:['HSK3','HSK1']};
          const rv=mk(()=>valid);
          const got=rv.getSelectedLevels();
          got.push('MUT');                                  // returned copy must be isolated
          return {
            current: JSON.stringify(rv.getSelectedLevels())==='["HSK3","HSK1"]',
            missing: JSON.stringify(mk(()=>({})).getSelectedLevels())==='["HSK1"]',
            empty: JSON.stringify(mk(()=>({selectedLevels:[]})).getSelectedLevels())==='["HSK1"]',
            futureLevel: JSON.stringify(mk(()=>({selectedLevels:['HSK7']})).getSelectedLevels())==='["HSK7"]',
            orderPreserved: JSON.stringify(rv.getSelectedLevels())==='["HSK3","HSK1"]',
            sourceArrayUnmutated: JSON.stringify(valid.selectedLevels)==='["HSK3","HSK1"]'
          };
        }""")
        for k in ["current","missing","empty","futureLevel","orderPreserved","sourceArrayUnmutated"]:
            check("selectedLevels:" + k, sl[k])

        # ---- SPEECH RATE ----
        sr = pg.evaluate("""()=>{
          const mk=HSKUtil.createSettingsRepository;
          const R=v=>mk(()=>({speechRate:v})).getSpeechRate();
          return {
            all: R(0.5)===0.5 && R(0.75)===0.75 && R(1)===1 && R(1.25)===1.25 && R(1.5)===1.5,
            missing: mk(()=>({})).getSpeechRate()===1,
            legacy07: R(0.7)===1,
            legacy085: R(0.85)===1,
            invalid: R('fast')===1 && R(3)===1 && R(0)===1,
            stringNumeric: R('1.25')===1.25              // "1.25" -> 1.25 (Number() coercion, matches normSpeechRate)
          };
        }""")
        for k in ["all","missing","legacy07","legacy085","invalid","stringNumeric"]:
            check("speechRate:" + k, sr[k])

        # ---- BOOLEAN SETTINGS ----
        bl = pg.evaluate("""()=>{
          const mk=HSKUtil.createSettingsRepository;
          const fp=v=>mk(()=>({showFrontPinyin:v})).getFrontPinyinEnabled();
          const aw=v=>mk(()=>({autoReadWord:v})).getAutoReadWordEnabled();
          const ae=v=>mk(()=>({autoReadExample:v})).getAutoReadExampleEnabled();
          const dk=v=>mk(()=>({dark:v})).getDarkEnabled();
          return {
            fpDefaultTrue: mk(()=>({})).getFrontPinyinEnabled()===true,   // undefined => true
            fpExplicitFalse: fp(false)===false,                          // explicit false wins over true default
            fpTrue: fp(true)===true,
            awDefaultFalse: mk(()=>({})).getAutoReadWordEnabled()===false,
            awTrue: aw(true)===true, awExplicitFalse: aw(false)===false,
            aeDefaultFalse: mk(()=>({})).getAutoReadExampleEnabled()===false,
            aeTrue: ae(true)===true,
            darkDefaultFalse: mk(()=>({})).getDarkEnabled()===false,
            darkTrue: dk(true)===true, darkExplicitFalse: dk(false)===false
          };
        }""")
        for k in ["fpDefaultTrue","fpExplicitFalse","fpTrue","awDefaultFalse","awTrue","awExplicitFalse","aeDefaultFalse","aeTrue","darkDefaultFalse","darkTrue","darkExplicitFalse"]:
            check("bool:" + k, bl[k])

        # ---- SESSION SIZE ----
        ss = pg.evaluate("""()=>{
          const mk=HSKUtil.createSettingsRepository;
          return {
            present: mk(()=>({sessionSize:'50'})).getSessionSize()==='50',
            all: mk(()=>({sessionSize:'all'})).getSessionSize()==='all',
            missing: mk(()=>({})).getSessionSize()==='20',
            empty: mk(()=>({sessionSize:''})).getSessionSize()==='20'   // matches `|| "20"`
          };
        }""")
        for k in ["present","all","missing","empty"]:
            check("sessionSize:" + k, ss[k])

        # ---- DAILY GOAL (Phase 22A: allowed [10,20,30,50]; default 20) ----
        dgl = pg.evaluate("""()=>{
          const mk=HSKUtil.createSettingsRepository;
          const G=v=>mk(()=>({dailyGoal:v})).getDailyGoal();
          const src={dailyGoal:'30'}; const snap=JSON.stringify(src);
          const r=mk(()=>src); r.getDailyGoal();
          return {
            allowed: G(10)===10 && G(20)===20 && G(30)===30 && G(50)===50,
            missing: mk(()=>({})).getDailyGoal()===20,
            nullSrc: mk(()=>null).getDailyGoal()===20,
            numericStrings: G('10')===10 && G('20')===20 && G('30')===30 && G('50')===50,
            unsupported: G(15)===20 && G(0)===20 && G(100)===20 && G(-20)===20,
            corrupt: G('fast')===20 && G(null)===20 && G(undefined)===20 && G(NaN)===20 && G({})===20,
            sourceUnmutated: JSON.stringify(src)===snap,
            typeIsNumber: typeof mk(()=>({dailyGoal:'30'})).getDailyGoal()==='number'
          };
        }""")
        for k in ["allowed","missing","nullSrc","numericStrings","unsupported","corrupt","sourceUnmutated","typeIsNumber"]:
            check("dailyGoal:" + k, dgl[k])

        # ---- ACCOUNT ISOLATION (provider reflects active object; no stale cache) ----
        ai = pg.evaluate("""()=>{
          const mk=HSKUtil.createSettingsRepository;
          const A={streak:1,selectedLevels:['HSK1'],autoReadWord:true};
          const B={streak:2,selectedLevels:['HSK5'],autoReadWord:false};
          const active={who:A};                       // simulates login/switch swapping the live blob
          const r=mk(()=>active.who);
          const a1=r.getStreak(), aw1=r.getAutoReadWordEnabled();
          active.who=B; const b=r.getStreak(), lvB=JSON.stringify(r.getSelectedLevels()), awB=r.getAutoReadWordEnabled();
          active.who=A; const a2=r.getStreak();       // back to A -> no stale B
          active.who={};  const localOnly=r.getStreak();   // local-only namespace (empty) -> default
          return { aFirst:a1===1&&aw1===true, bAfter:b===2&&lvB==='["HSK5"]'&&awB===false,
                   backToA:a2===1, noBLeakIntoLocal:localOnly===0 };
        }""")
        for k in ["aFirst","bAfter","backToA","noBLeakIntoLocal"]:
            check("isolation:" + k, ai[k])

        # ---- NO SIDE EFFECTS (no storage write, no dirty mark, no source mutation) ----
        se = pg.evaluate("""()=>{
          // snapshot ALL localStorage before hammering the shared instance's reads
          const before={}; for(let i=0;i<localStorage.length;i++){const k=localStorage.key(i); before[k]=localStorage.getItem(k);}
          const beforeLen=localStorage.length;
          const r=HSKUtil.settings;
          for(let i=0;i<50;i++){ r.getAll(); r.get('streak',0); r.getSelectedLevels(); r.getSessionSize();
            r.getSpeechRate(); r.getFrontPinyinEnabled(); r.getAutoReadWordEnabled(); r.getAutoReadExampleEnabled();
            r.getStreak(); r.getDarkEnabled(); r.has('dark'); }
          const after={}; for(let i=0;i<localStorage.length;i++){const k=localStorage.key(i); after[k]=localStorage.getItem(k);}
          let unchanged = localStorage.length===beforeLen;
          for(const k in before){ if(before[k]!==after[k]) unchanged=false; }
          for(const k in after){ if(!(k in before)) unchanged=false; }
          // reads must not create a dirty queue
          const noDirty = !Object.keys(after).some(k=>k.indexOf('hsk_sync_dirty')>=0 && (before[k]===undefined));
          return { storageUnchanged: unchanged, noDirtyKeyCreated: noDirty };
        }""")
        for k in ["storageUnchanged","noDirtyKeyCreated"]:
            check("sideEffect:" + k, se[k])

        # ---- SHARED INSTANCE reads the live app settings ----
        shared = pg.evaluate("""()=>{
          // HSK_APP.getSettings() is the live blob; shared repo must mirror it.
          const live = window.HSK_APP.getSettings();
          const r = HSKUtil.settings;
          return { mirrorsFrontPinyin: r.getFrontPinyinEnabled()===(live.showFrontPinyin!==false),
                   mirrorsStreak: r.getStreak()===(live.streak||0) };
        }""")
        for k in ["mirrorsFrontPinyin","mirrorsStreak"]:
            check("shared:" + k, shared[k])

        result = {"suite": "settings_repository", "pass": len(fails) == 0 and len(errs) == 0, "fails": fails, "errors": errs}
        print(json.dumps(result, ensure_ascii=False))
        b.close()
        return 0 if result["pass"] else 1

if __name__ == "__main__":
    import sys
    sys.exit(main())
