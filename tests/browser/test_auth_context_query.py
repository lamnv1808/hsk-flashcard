"""Unit + characterization tests for the Phase 15 read-only AuthContextQuery
(window.HSKUtil.createAuthContextQuery + HSKUtil.authContext). Runs in the real
loaded browser.

Verifies configuration/auth/local-only semantics, storage-key derivation, canSync,
provider lifecycle (account swap, no stale), that no secret is exposed, and the strict
no-side-effects contract. Includes an inline-vs-query characterization of the exact
bootstrap key-selection logic across all three HSK_AUTH variants.
"""
import os, json
from playwright.sync_api import sync_playwright

URL = os.environ.get("HSK_BASE_URL", "http://localhost:8000") + "/hsk_flashcard_app/"
EMPTY = 'window.SUPABASE_CONFIG={url:"",anonKey:""};'
fails = []
def check(n, c):
    if not c: fails.append(n)

# faithful copy of the ORIGINAL inline derivations (app.js bootstrap + sync.js gate).
HELPERS = r"""
window.__PROG='hsk_flashcard_progress_v2';
window.__SET='hsk_flashcard_settings_v2';
window.__mkQ=function(authHolder, moduleHolder){
  return HSKUtil.createAuthContextQuery({
    authProvider:function(){ return authHolder.a; },
    authModuleProvider:function(){ return moduleHolder ? moduleHolder.m : undefined; }
  });
};
// original inline: stateKey = AUTH.progressKey || base ; settingsKey = AUTH.settingsKey || base
window.__oldKeys=function(a){
  var AUTH=a||{};
  return { prog: AUTH.progressKey || __PROG, set: AUTH.settingsKey || __SET };
};
// three canonical HSK_AUTH variants
window.__localOnly={ configured:false };
window.__gated={ configured:true, needsAuth:true };
window.__loggedIn={ configured:true, userId:'u-abc', username:'Minh',
  progressKey:'hsk_flashcard_progress_v2::u-abc', settingsKey:'hsk_flashcard_settings_v2::u-abc' };
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

        check("factory present", pg.evaluate("()=>typeof window.HSKUtil.createAuthContextQuery==='function'"))
        check("shared instance present", pg.evaluate("()=>typeof window.HSKUtil.authContext==='object'"))

        # ---- CONFIGURATION semantics ----
        cfg = pg.evaluate("""()=>{
          const q=v=>__mkQ({a:v}).getContext();
          const local=q(__localOnly), gated=q(__gated), logged=q(__loggedIn);
          // malformed / empty
          const empty=__mkQ({a:{}}).getContext();
          const nul=__mkQ({a:null}).getContext();
          // missing url or key -> auth.js would set configured:false; we model via {configured:false}
          return {
            localConfigured: local.configured===false, localLocalOnly: local.localOnly===true,
            localNoAuthReq: local.requiresAuth===false, localNotAuthed: local.authenticated===false,
            gatedConfigured: gated.configured===true, gatedNotLocal: gated.localOnly===false,
            gatedRequiresAuth: gated.requiresAuth===true, gatedNotAuthed: gated.authenticated===false,
            loggedConfigured: logged.configured===true, loggedAuthed: logged.authenticated===true,
            loggedNotLocal: logged.localOnly===false, loggedNoAuthReq: logged.requiresAuth===false,
            emptyLocalOnly: empty.localOnly===true && empty.configured===false,
            nullLocalOnly: nul.localOnly===true && nul.authenticated===false
          };
        }""")
        for k in ["localConfigured", "localLocalOnly", "localNoAuthReq", "localNotAuthed",
                  "gatedConfigured", "gatedNotLocal", "gatedRequiresAuth", "gatedNotAuthed",
                  "loggedConfigured", "loggedAuthed", "loggedNotLocal", "loggedNoAuthReq",
                  "emptyLocalOnly", "nullLocalOnly"]:
            check("config:" + k, cfg[k])

        # ---- AUTH STATE / user id / username / provider swap ----
        au = pg.evaluate("""()=>{
          const holder={a:__loggedIn};
          const q=__mkQ(holder);
          const before={ id:q.getUserId(), user:q.getUsername(), disp:q.getDisplayUsername() };
          holder.a=__gated;                         // swap to gated
          const gated={ id:q.getUserId(), authed:q.isAuthenticated() };
          holder.a=__loggedIn;                       // back
          const back={ id:q.getUserId() };
          return {
            userId: before.id==='u-abc', username: before.user==='Minh', display: before.disp==='Minh',
            swapObserved: gated.id===null && gated.authed===false,
            backNoStale: back.id==='u-abc'
          };
        }""")
        for k in ["userId", "username", "display", "swapObserved", "backNoStale"]:
            check("auth:" + k, au[k])

        # ---- STORAGE KEYS (+ characterization vs inline || logic) ----
        sk = pg.evaluate("""()=>{
          const A={ configured:true, userId:'u-A', username:'A', progressKey:'hsk_flashcard_progress_v2::u-A', settingsKey:'hsk_flashcard_settings_v2::u-A' };
          const B={ configured:true, userId:'u-B', username:'B', progressKey:'hsk_flashcard_progress_v2::u-B', settingsKey:'hsk_flashcard_settings_v2::u-B' };
          const K=v=>{ const q=__mkQ({a:v}); return { prog:q.getProgressKey(), set:q.getSettingsKey() }; };
          const eq=v=>{ const q=K(v); const o=__oldKeys(v); return q.prog===o.prog && q.set===o.set; };
          const kLocal=K(__localOnly), kA=K(A), kB=K(B);
          return {
            charLocal: eq(__localOnly), charGated: eq(__gated), charLogged: eq(__loggedIn), charA: eq(A), charB: eq(B),
            localBase: kLocal.prog==='hsk_flashcard_progress_v2' && kLocal.set==='hsk_flashcard_settings_v2',
            aNs: kA.prog==='hsk_flashcard_progress_v2::u-A' && kA.set==='hsk_flashcard_settings_v2::u-A',
            bNs: kB.prog==='hsk_flashcard_progress_v2::u-B',
            noCollision: kA.prog!==kB.prog,
            stable: __mkQ({a:A}).getProgressKey()===__mkQ({a:A}).getProgressKey()
          };
        }""")
        for k in ["charLocal", "charGated", "charLogged", "charA", "charB", "localBase", "aNs", "bNs", "noCollision", "stable"]:
            check("keys:" + k, sk[k])

        # ---- canSync (matches sync.js gate: configured && userId && HSKAuth present) ----
        cs = pg.evaluate("""()=>{
          const mod={m:{}};    // auth module present
          const noMod={m:undefined};
          const logged={a:__loggedIn}, local={a:__localOnly}, gated={a:__gated};
          return {
            loggedWithModule: __mkQ(logged, mod).canSync()===true,
            loggedNoModule: __mkQ(logged, noMod).canSync()===false,
            localNever: __mkQ(local, mod).canSync()===false,
            gatedNever: __mkQ(gated, mod).canSync()===false,   // configured but no userId
            ctxSyncAvailable: __mkQ(logged, mod).getContext().syncAvailable===true
          };
        }""")
        for k in ["loggedWithModule", "loggedNoModule", "localNever", "gatedNever", "ctxSyncAvailable"]:
            check("canSync:" + k, cs[k])

        # ---- SECURITY: no PIN / token / secret / session ever exposed ----
        sec = pg.evaluate("""()=>{
          // even if the auth object were polluted with sensitive fields, the context must not surface them
          const dirty={ configured:true, userId:'u-x', username:'X',
            progressKey:'hsk_flashcard_progress_v2::u-x', settingsKey:'hsk_flashcard_settings_v2::u-x',
            access_token:'SECRET_ACCESS', refresh_token:'SECRET_REFRESH', pin:'1234', password:'p', anonKey:'AK', service_role:'SR' };
          const ctx=__mkQ({a:dirty}).getContext();
          const s=JSON.stringify(ctx).toLowerCase();
          const allowed=['configured','requiresauth','authenticated','localonly','userid','username','displayusername','progresskey','settingskey','syncavailable'];
          const keysOnly=Object.keys(ctx).every(k=>allowed.indexOf(k.toLowerCase())>=0);
          return {
            keysOnly,
            noAccess: s.indexOf('secret_access')<0, noRefresh: s.indexOf('secret_refresh')<0,
            noPin: s.indexOf('1234')<0, noAnon: s.indexOf('"ak"')<0 && s.indexOf('anonkey')<0,
            noServiceRole: s.indexOf('service_role')<0 && s.indexOf('"sr"')<0,
            fieldCount: Object.keys(ctx).length===10
          };
        }""")
        for k in ["keysOnly", "noAccess", "noRefresh", "noPin", "noAnon", "noServiceRole", "fieldCount"]:
            check("security:" + k, sec[k])

        # ---- NO SIDE EFFECTS ----
        se = pg.evaluate("""()=>{
          const before={}; for(let i=0;i<localStorage.length;i++){const k=localStorage.key(i); before[k]=localStorage.getItem(k);}
          const beforeLen=localStorage.length;
          const src={ configured:true, userId:'u-z', username:'Z', progressKey:'p', settingsKey:'s' };
          const snap=JSON.stringify(src);
          const q=__mkQ({a:src});
          for(let i=0;i<40;i++){ q.getContext(); q.isConfigured(); q.isLocalOnly(); q.isAuthenticated(); q.requiresAuth();
            q.getUserId(); q.getUsername(); q.getDisplayUsername(); q.getProgressKey(); q.getSettingsKey(); q.canSync(); }
          const after={}; for(let i=0;i<localStorage.length;i++){const k=localStorage.key(i); after[k]=localStorage.getItem(k);}
          let unchanged=localStorage.length===beforeLen;
          for(const k in before){ if(before[k]!==after[k]) unchanged=false; }
          for(const k in after){ if(!(k in before)) unchanged=false; }
          return { storageUnchanged:unchanged, sourceUnmutated:JSON.stringify(src)===snap };
        }""")
        for k in ["storageUnchanged", "sourceUnmutated"]:
            check("sideEffect:" + k, se[k])

        # ---- SHARED INSTANCE mirrors the live HSK_AUTH (local-only under the empty-config mock) ----
        shared = pg.evaluate("""()=>{
          const q=HSKUtil.authContext;
          const live=window.HSK_AUTH||{};
          // under the empty SUPABASE_CONFIG mock, auth.js sets {configured:false} => local-only base keys
          return { mirrorsConfigured: q.isConfigured()===(!!live.configured),
                   mirrorsProgKey: q.getProgressKey()===(live.progressKey||'hsk_flashcard_progress_v2'),
                   localOnlyBase: q.getProgressKey()==='hsk_flashcard_progress_v2' };
        }""")
        for k in ["mirrorsConfigured", "mirrorsProgKey", "localOnlyBase"]:
            check("shared:" + k, shared[k])

        result = {"suite": "auth_context_query", "pass": len(fails) == 0 and len(errs) == 0, "fails": fails, "errors": errs}
        print(json.dumps(result, ensure_ascii=False))
        b.close()
        return 0 if result["pass"] else 1

if __name__ == "__main__":
    import sys
    sys.exit(main())
