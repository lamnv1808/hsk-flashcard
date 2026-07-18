"""Phase 24C — Content Pack v1 contract, integer ID-range invariant, HSK v1 adapter.

Covers: legacy back-compat (no schemaVersion => unchanged behavior), strict v1 mode
(malformed manifests fail closed at construction and are NEVER downgraded to legacy),
id-range validation, deck/role validation, input immutability (no card cloning/reordering),
and exact HSK equivalence (5,002 cards, ids 1..5002, decks, roles, test modes, live source).

Read-only w.r.t. production: local-only (Supabase config stubbed empty).
"""
import json
import os
from playwright.sync_api import sync_playwright

URL = os.environ.get("HSK_BASE_URL", "http://localhost:8000") + "/hsk_flashcard_app/"
EMPTY = 'window.SUPABASE_CONFIG={url:"",anonKey:""};'
fails = []
def check(n, c):
    if not c: fails.append(n)

# A minimal VALID v1 manifest builder used by the rejection cases (JS source).
BASE = """
  const cards=[{id:5,lvl:'D1',w:'a'},{id:6,lvl:'D2',w:'b'}];
  const base=()=>({
    schemaVersion:1, packId:'demo', version:'1.0.0', status:'launch', title:'Demo',
    courseId:'demo', courseType:'general',
    languageProfile:{ target:'en-GB' },
    fieldRoles:{ stableId:'id', deck:'lvl', primaryPrompt:'w' },
    idRange:{ min:1, max:1000 },
    getCards:()=>cards, decks:[{id:'D1'},{id:'D2'}]
  });
  const mk=HSKUtil.createContentPack;
  const rejects=(mut)=>{ const s=base(); mut(s); try{ mk(s); return false; }catch(e){ return true; } };
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

        # ================= LEGACY MODE (no schemaVersion) =================
        lg = pg.evaluate("""()=>{
          const mk=HSKUtil.createContentPack;
          const cards=[{id:1,lvl:'D1',w:'a'},{id:2,lvl:'D2',w:'b'}];
          const p=mk({ id:'legacy', version:'0.1', title:'L',
                       fieldRoles:{stableId:'id',deck:'lvl',primaryPrompt:'w'},
                       getCards:()=>cards, decks:[{id:'D1'},{id:'D2'}] });
          const v=p.validate();
          // a legacy pack missing an id still only WARNS/errors as before (not a throw)
          let legacyNoIdThrew=false, noIdOk=null;
          try { noIdOk = mk({ getCards:()=>cards, fieldRoles:{}, decks:[] }).validate().ok; }
          catch(e){ legacyNoIdThrew=true; }
          return {
            constructs: typeof p==='object',
            id: p.getId(), version: p.getVersion(), title: p.getTitle(),
            deckIds: p.getDeckIds(), valOk: v.ok, valErrors: v.errors,
            schemaUndef: p.getSchemaVersion()===undefined,
            langProfileUndef: p.getLanguageProfile()===undefined,
            idRangeUndef: p.getIdRange()===undefined,
            packIdFallback: p.getPackId()==='legacy',
            optionalRolesEmpty: JSON.stringify(p.getOptionalRoles())==='[]',
            legacyNoIdThrew, noIdOk,
            noV1KeysInValidate: !('schemaVersion' in v) && !('idRange' in v)
          };
        }""")
        check("legacy constructs", lg["constructs"])
        check("legacy id/version/title unchanged", lg["id"] == "legacy" and lg["version"] == "0.1" and lg["title"] == "L")
        check("legacy decks unchanged", lg["deckIds"] == ["D1", "D2"])
        check("legacy validate ok", lg["valOk"] and lg["valErrors"] == [])
        check("legacy: no v1 accessors leak", lg["schemaUndef"] and lg["langProfileUndef"] and lg["idRangeUndef"])
        check("legacy: getPackId falls back to id", lg["packIdFallback"])
        check("legacy: getOptionalRoles == []", lg["optionalRolesEmpty"])
        check("legacy malformed NOT tightened into a throw", lg["legacyNoIdThrew"] is False and lg["noIdOk"] is False)
        check("legacy validate() shape unchanged (no v1 keys)", lg["noV1KeysInValidate"])

        # ================= V1 MODE — acceptance =================
        v1 = pg.evaluate("""()=>{""" + BASE + """
          const minimal = mk(base());
          const full = mk(Object.assign(base(), {
            shortTitle:'D', description:'d', publisher:'pub',
            source:{origin:'src.xlsx', license:'CC-BY', url:'https://x.test', acquiredAt:'2026-01-01'},
            sourceChecksum:'abc', contentChecksum:'def', generatedAt:'2026-01-01T00:00:00Z',
            minAppVersion:'1.0.0',
            languageProfile:{ target:'en-GB', translation:'vi', instruction:'vi', script:'Latn', direction:'ltr' },
            audio:{ locale:'en-GB', fallbackLocales:['en-US'], readFields:['primaryPrompt','exampleText'] },
            framework:{ name:'CEFR', version:'2020' },
            levels:[{id:'D1',order:1}], categories:['topic'],
            launch:{ visible:true, readiness:'launch' },
            search:{ fields:['primaryPrompt'], normalizer:'nfc-lower' },
            presentation:{ frontRoles:['primaryPrompt'], backRoles:['definition'] },
            optionalRoles:['pronunciation'], cardCount:2
          }));
          const v=minimal.validate();
          return {
            minimalOk: typeof minimal==='object',
            schemaVersion: minimal.getSchemaVersion(),
            packId: minimal.getPackId(),
            status: minimal.getStatus(),
            course: minimal.getCourse(),
            lang: minimal.getLanguageProfile(),
            idRange: minimal.getIdRange(),
            valOk: v.ok, valErrors: v.errors, valIdsInRange: v.idsInRange, valRoles: v.rolesResolve,
            valSchema: v.schemaVersion,
            fullOk: typeof full==='object',
            fullAudio: full.getAudio(), fullLaunch: full.getLaunch(),
            fullSource: full.getSource(), fullPresentation: full.getPresentation(),
            fullSearch: full.getSearch(), fullOptional: full.getOptionalRoles(),
            fullManifest: full.getManifest()
          };
        }""")
        check("v1 minimal pack accepted", v1["minimalOk"])
        check("v1 schemaVersion exposed", v1["schemaVersion"] == 1)
        check("v1 packId/status", v1["packId"] == "demo" and v1["status"] == "launch")
        check("v1 course", v1["course"] == {"courseId": "demo", "courseType": "general"})
        check("v1 languageProfile", v1["lang"] == {"target": "en-GB"})
        check("v1 idRange", v1["idRange"] == {"min": 1, "max": 1000})
        check("v1 validate ok + in range + roles resolve", v1["valOk"] and v1["valIdsInRange"] and v1["valRoles"] and v1["valErrors"] == [])
        check("v1 validate reports schemaVersion", v1["valSchema"] == 1)
        check("v1 complete manifest accepted", v1["fullOk"])
        check("v1 audio accessor", v1["fullAudio"]["locale"] == "en-GB" and v1["fullAudio"]["fallbackLocales"] == ["en-US"])
        check("v1 launch accessor", v1["fullLaunch"] == {"visible": True, "readiness": "launch"})
        check("v1 source accessor", v1["fullSource"]["origin"] == "src.xlsx" and v1["fullSource"]["license"] == "CC-BY")
        check("v1 presentation accessor", v1["fullPresentation"]["frontRoles"] == ["primaryPrompt"])
        check("v1 search accessor", v1["fullSearch"]["fields"] == ["primaryPrompt"])
        check("v1 optionalRoles accessor", v1["fullOptional"] == ["pronunciation"])
        check("v1 manifest scalars", v1["fullManifest"]["publisher"] == "pub" and v1["fullManifest"]["minAppVersion"] == "1.0.0")

        # ================= V1 MODE — fail-closed rejections =================
        rej = pg.evaluate("""()=>{""" + BASE + """
          return {
            schemaZero:      rejects(s=>s.schemaVersion=0),
            schemaTwo:       rejects(s=>s.schemaVersion=2),
            schemaString:    rejects(s=>s.schemaVersion='1'),
            noPackId:        rejects(s=>delete s.packId),
            badPackId:       rejects(s=>s.packId='Bad_Id'),
            packIdMismatch:  rejects(s=>{ s.id='other'; }),
            noCourseId:      rejects(s=>delete s.courseId),
            badCourseType:   rejects(s=>s.courseType='quiz'),
            noVersion:       rejects(s=>delete s.version),
            noTitle:         rejects(s=>delete s.title),
            badStatus:       rejects(s=>s.status='published'),
            noLangProfile:   rejects(s=>delete s.languageProfile),
            noTarget:        rejects(s=>s.languageProfile={}),
            badTarget:       rejects(s=>s.languageProfile={target:'zh_CN'}),
            badTargetLong:   rejects(s=>s.languageProfile={target:'notalocale'}),
            badScript:       rejects(s=>s.languageProfile={target:'en',script:'hans'}),
            badDirection:    rejects(s=>s.languageProfile={target:'en',direction:'sideways'}),
            badAudioType:    rejects(s=>s.audio=[]),
            badAudioLocale:  rejects(s=>s.audio={locale:'english'}),
            badAudioRole:    rejects(s=>s.audio={readFields:['nonsense']}),
            noIdRange:       rejects(s=>delete s.idRange),
            idMinZero:       rejects(s=>s.idRange={min:0,max:10}),
            idMinNegative:   rejects(s=>s.idRange={min:-5,max:10}),
            idMaxLtMin:      rejects(s=>s.idRange={min:100,max:10}),
            idNonInteger:    rejects(s=>s.idRange={min:1.5,max:10}),
            idUnsafe:        rejects(s=>s.idRange={min:1,max:Number.MAX_SAFE_INTEGER}),
            idOverInt4:      rejects(s=>s.idRange={min:1,max:2147483648}),
            noFieldRoles:    rejects(s=>delete s.fieldRoles),
            unknownRole:     rejects(s=>s.fieldRoles={stableId:'id',deck:'lvl',primaryPrompt:'w',bogusRole:'x'}),
            missingReqRole:  rejects(s=>s.fieldRoles={stableId:'id',deck:'lvl'}),
            badRoleValue:    rejects(s=>s.fieldRoles={stableId:'id',deck:'lvl',primaryPrompt:123}),
            badOptionalRole: rejects(s=>s.optionalRoles=['nope']),
            badLaunchVis:    rejects(s=>s.launch={visible:'yes'}),
            badReadiness:    rejects(s=>s.launch={readiness:'soon'}),
            badPresRole:     rejects(s=>s.presentation={frontRoles:['nope']}),
            badSearchRole:   rejects(s=>s.search={fields:['nope']}),
            badCategories:   rejects(s=>s.categories=[1,2]),
            badLevels:       rejects(s=>s.levels='D1'),
            badCardCount:    rejects(s=>s.cardCount='2'),
            // optional role declared => the required role may be absent
            optionalAllows:  (()=>{ const s=base(); s.fieldRoles={stableId:'id',deck:'lvl'}; s.optionalRoles=['primaryPrompt'];
                                    try{ mk(s); return true; }catch(e){ return false; } })()
          };
        }""")
        for k, v in rej.items():
            if k == "optionalAllows":
                check("v1 declared-optional required role allowed", v is True)
            else:
                check("v1 rejects: " + k, v is True)

        # ================= V1 content checks (ids/decks) via validate() =================
        cv = pg.evaluate("""()=>{""" + BASE + """
          const withCards=(cs, extra)=>{ const s=base(); s.getCards=()=>cs; Object.assign(s, extra||{}); return mk(s).validate(); };
          const below = withCards([{id:0,lvl:'D1',w:'a'}]);
          const above = withCards([{id:5000,lvl:'D1',w:'a'}]);
          const nonInt= withCards([{id:'7',lvl:'D1',w:'a'}]);
          const dup   = withCards([{id:5,lvl:'D1',w:'a'},{id:5,lvl:'D1',w:'b'}]);
          const undecl= withCards([{id:5,lvl:'D9',w:'a'}]);
          const good  = withCards([{id:5,lvl:'D1',w:'a'},{id:6,lvl:'D2',w:'b'}]);
          const roleMiss = withCards([{id:5,lvl:'D1'}]);          // 'w' field absent
          const roleOpt  = withCards([{id:5,lvl:'D1'}], {optionalRoles:['primaryPrompt']});
          return {
            belowBad: below.ok===false && below.idsInRange===false,
            aboveBad: above.ok===false && above.idsInRange===false,
            nonIntBad: nonInt.ok===false && nonInt.idsInRange===false,
            dupBad: dup.ok===false && dup.idsUnique===false,
            undeclBad: undecl.ok===false && undecl.deckRefsValid===false,
            goodOk: good.ok===true && good.idsInRange===true && good.rolesResolve===true,
            roleMissBad: roleMiss.ok===false && roleMiss.rolesResolve===false,
            roleOptOk: roleOpt.rolesResolve===true
          };
        }""")
        for k in ["belowBad", "aboveBad", "nonIntBad", "dupBad", "undeclBad", "goodOk", "roleMissBad", "roleOptOk"]:
            check("v1 content: " + k, cv[k])

        # ================= Immutability (no mutation, no card clone/reorder) =================
        im = pg.evaluate("""()=>{""" + BASE + """
          const src=[{id:5,lvl:'D1',w:'a'},{id:6,lvl:'D2',w:'b'}];
          const spec=base(); spec.getCards=()=>src;
          spec.audio={locale:'en-GB',fallbackLocales:['en-US'],readFields:['primaryPrompt']};
          spec.presentation={frontRoles:['primaryPrompt'],backRoles:['definition']};
          spec.optionalRoles=['pronunciation'];
          spec.source={origin:'o'};
          const snap=JSON.stringify(spec, (k,v)=>typeof v==='function'?'fn':v);
          const cardsSnap=JSON.stringify(src);
          const order=src.map(c=>c.id).join(',');
          const p=mk(spec);
          for(let i=0;i<10;i++){ p.getCards(); p.getDecks(); p.getFieldRoles(); p.getLanguageProfile();
            p.getAudio(); p.getIdRange(); p.getLaunch(); p.getSource(); p.getPresentation();
            p.getSearch(); p.getOptionalRoles(); p.getManifest(); p.validate(); }
          // returned copies must not be able to corrupt internals
          const a=p.getAudio(); a.locale='MUTATED'; a.fallbackLocales.push('x');
          const or=p.getOptionalRoles(); or.push('x');
          const ir=p.getIdRange(); ir.min=999;
          return {
            specUnchanged: JSON.stringify(spec,(k,v)=>typeof v==='function'?'fn':v)===snap,
            cardsUnchanged: JSON.stringify(src)===cardsSnap,
            orderUnchanged: p.getCards().map(c=>c.id).join(',')===order,
            liveArrayIdentity: p.getCards()===src,                // NOT cloned
            cardObjectIdentity: p.getCards()[0]===src[0],
            audioCopyIsolated: p.getAudio().locale==='en-GB' && p.getAudio().fallbackLocales.length===1,
            optionalCopyIsolated: p.getOptionalRoles().length===1,
            idRangeCopyIsolated: p.getIdRange().min===1
          };
        }""")
        for k in ["specUnchanged", "cardsUnchanged", "orderUnchanged", "liveArrayIdentity",
                  "cardObjectIdentity", "audioCopyIsolated", "optionalCopyIsolated", "idRangeCopyIsolated"]:
            check("immutability: " + k, im[k])

        # ================= HSK v1 adapter equivalence =================
        hk = pg.evaluate("""()=>{
          const p=HSKUtil.contentPack, v=p.validate();
          const cards=p.getCards(), ids=cards.map(c=>c.id);
          const counts={}; cards.forEach(c=>{counts[c.level]=(counts[c.level]||0)+1;});
          let byIdOk=true; for(let i=0;i<cards.length;i++){ if(HSKUtil.cards.getById(ids[i])!==cards[i]) {byIdOk=false;break;} }
          return {
            schemaVersion: p.getSchemaVersion(), packId: p.getPackId(), id: p.getId(),
            status: p.getStatus(), course: p.getCourse(),
            lang: p.getLanguageProfile(), audio: p.getAudio(),
            idRange: p.getIdRange(), launch: p.getLaunch(), source: p.getSource(),
            search: p.getSearch(), presentation: p.getPresentation(),
            version: p.getVersion(), title: p.getTitle(),
            languagesLegacy: p.getLanguages(),
            roles: p.getFieldRoles(), deckIds: p.getDeckIds(),
            total: cards.length, first: ids[0], last: ids[ids.length-1],
            contiguous: ids.every((v,i)=>v===i+1),
            counts: counts,
            liveSource: p.getCards()===window.HSK_CARDS,
            byIdOk: byIdOk,
            valOk: v.ok, valErrors: v.errors, valIdsInRange: v.idsInRange, valRoles: v.rolesResolve,
            testModes: p.getTestModes().length,
            hasCapStudy: p.hasCapability('study'), hasCapTest: p.hasCapability('test'),
            manifestNoInvented: (()=>{ const m=p.getManifest();
              return !('publisher' in m) && !('sourceChecksum' in m) && !('contentChecksum' in m) &&
                     !('generatedAt' in m) && !('minAppVersion' in m) && !('cardCount' in m); })(),
            sourceNoInventedLicense: (()=>{ const s=p.getSource(); return !('license' in s) && !('url' in s); })()
          };
        }""")
        check("hsk schemaVersion 1", hk["schemaVersion"] == 1)
        check("hsk packId/id both 'hsk'", hk["packId"] == "hsk" and hk["id"] == "hsk")
        check("hsk status launch", hk["status"] == "launch")
        check("hsk course", hk["course"] == {"courseId": "hsk", "courseType": "exam"})
        check("hsk languageProfile", hk["lang"] == {"target": "zh-CN", "translation": "vi", "instruction": "vi", "script": "Hans", "direction": "ltr"})
        check("hsk audio zh-CN + word/example only", hk["audio"] == {"locale": "zh-CN", "fallbackLocales": ["zh"], "readFields": ["primaryPrompt", "exampleText"]})
        check("hsk idRange 1..999999", hk["idRange"] == {"min": 1, "max": 999999})
        check("hsk launch visible", hk["launch"] == {"visible": True, "readiness": "launch"})
        check("hsk source origin factual", hk["source"] == {"origin": "source_data/HSK1-HSK6.xlsx"})
        check("hsk no invented provenance in manifest", hk["manifestNoInvented"])
        check("hsk no invented license/url", hk["sourceNoInventedLicense"])
        # --- unchanged legacy surface ---
        check("hsk version unchanged", hk["version"] == "1.0.0")
        check("hsk title unchanged", hk["title"] == "HSK Tiếng Trung")
        check("hsk LEGACY languages map unchanged", hk["languagesLegacy"] == {"prompt": "zh", "reading": "pinyin", "meaning": "vi", "audio": "zh-CN"})
        check("hsk field roles unchanged", hk["roles"] == {
            "primaryPrompt": "word", "pronunciation": "pinyin", "definition": "meaning",
            "exampleText": "example", "examplePronunciation": "examplePinyin",
            "exampleTranslation": "translation", "deck": "level", "stableId": "id"})
        check("hsk deck ids unchanged", hk["deckIds"] == ["HSK1", "HSK2", "HSK3", "HSK4", "HSK5", "HSK6"])
        check("hsk 5002 cards", hk["total"] == 5002)
        check("hsk ids 1..5002 contiguous", hk["contiguous"] and hk["first"] == 1 and hk["last"] == 5002)
        check("hsk per-deck counts exact", hk["counts"] == {"HSK1": 149, "HSK2": 150, "HSK3": 295, "HSK4": 600, "HSK5": 1295, "HSK6": 2513})
        check("hsk getCards is the LIVE window.HSK_CARDS", hk["liveSource"])
        check("hsk getById identity for every card", hk["byIdOk"])
        check("hsk 6 test modes", hk["testModes"] == 6)
        check("hsk capabilities unchanged", hk["hasCapStudy"] and hk["hasCapTest"])
        check("hsk v1 validation clean", hk["valOk"] and hk["valIdsInRange"] and hk["valRoles"] and hk["valErrors"] == [])

        # ================= Cost sanity (no scan added to hot paths) =================
        perf = pg.evaluate("""()=>{
          const p=HSKUtil.contentPack;
          const t0=performance.now(); for(let i=0;i<200;i++) p.getCards(); const tGet=performance.now()-t0;
          const t1=performance.now(); const v=p.validate(); const tVal=performance.now()-t1;
          return { tGet:Math.round(tGet*100)/100, tVal:Math.round(tVal*100)/100, cards:v.cards };
        }""")
        check("getCards() stays O(1) (200 calls < 20ms)", perf["tGet"] < 20)
        check("validate() single pass over 5002 cards is fast (<250ms)", perf["tVal"] < 250)

        check("no console/page errors", len(errs) == 0)
        result = {"suite": "content_pack_v1", "pass": len(fails) == 0 and len(errs) == 0,
                  "fails": fails, "errors": errs, "perf": perf}
        print(json.dumps(result, ensure_ascii=False))
        b.close()
        return 0 if result["pass"] else 1

if __name__ == "__main__":
    import sys
    sys.exit(main())
