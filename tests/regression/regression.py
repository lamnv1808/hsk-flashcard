import os
import json
from playwright.sync_api import sync_playwright
URL=(os.environ.get('HSK_BASE_URL','http://localhost:8000')+'/hsk_flashcard_app/')
with sync_playwright() as p:
    b=p.chromium.launch()
    ctx=b.new_context(viewport={"width":1280,"height":800})
    pg=ctx.new_page()
    errors=[]
    pg.on("console", lambda m: errors.append(m.text) if m.type=="error" else None)
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto(URL); pg.wait_for_timeout(300)
    pg.evaluate("() => localStorage.clear()"); pg.reload(); pg.wait_for_timeout(300)

    out={}
    # Spy on speech
    pg.evaluate("""() => {
      window.__spoke=[];
      const R=window.SpeechSynthesisUtterance;
      window.SpeechSynthesisUtterance=function(t){window.__spoke.push(t);return new R(t);};
      speechSynthesis.speak=()=>{}; speechSynthesis.cancel=()=>{};
      progress={}; save();
      startStudy(['HSK1']); session=session.slice(0,4); current=0; sessionGrades=[]; snapshots={}; renderCard();
    }""")
    def key(k): pg.evaluate(f"() => document.dispatchEvent(new KeyboardEvent('keydown',{{key:{json.dumps(k)},bubbles:true,cancelable:true}}))")

    # Space flips
    fl0=pg.evaluate("() => flipped"); key(" "); out["spaceFlips"]=(pg.evaluate("()=>flipped")!=fl0)
    # S on back reads example (zh)
    pg.evaluate("() => { window.__spoke=[]; }"); key("s")
    out["sReadsExampleOnBack"]=pg.evaluate("() => window.__spoke.slice()")
    # grade with '3' (good) only when flipped -> advances, interval 3 (algorithm unchanged)
    ids=pg.evaluate("() => session.map(c=>c.id)")
    key("3")
    out["grade3_interval"]=pg.evaluate(f"() => (progress[{ids[0]}]||{{}}).interval")
    out["advancedTo"]=pg.evaluate("() => current")
    # N skips
    cur=pg.evaluate("() => current"); key("n"); out["nSkips"]=(pg.evaluate("()=>current")==cur+1)
    # readAll: word then example, no pinyin/vietnamese
    pg.evaluate("() => { current=0; renderCard(); window.__spoke=[]; readAll(); }")
    ra=pg.evaluate("() => window.__spoke.slice()")
    c0=pg.evaluate("() => ({w:session[0].word,e:session[0].example,py:session[0].pinyin,epy:session[0].examplePinyin,m:session[0].meaning,tr:session[0].translation})")
    out["readAll"]=ra
    out["readAll_noPinyinNoViet"]=all(t not in (c0["py"],c0["epy"],c0["m"],c0["tr"]) for t in ra)
    # Esc exits
    key("Escape"); out["escExits"]=pg.evaluate("() => document.getElementById('homeView').classList.contains('active')")
    # Dark mode toggle
    pg.evaluate("() => document.getElementById('themeBtn').click()")
    out["darkOn"]=pg.evaluate("() => document.body.classList.contains('dark')")
    out["darkPersisted"]=pg.evaluate("() => JSON.parse(localStorage.getItem('hsk_flashcard_settings_v2')||'{}').dark===true")
    # autoRead word on new card
    pg.evaluate("""() => { settings.autoReadWord=true; startStudy(['HSK1']); window.__spoke=[]; current=0; renderCard(); }""")
    out["autoReadWord"]=pg.evaluate("() => window.__spoke.slice()")
    out["consoleErrors"]=errors
    print(json.dumps(out, ensure_ascii=False))
    ctx.close(); b.close()
