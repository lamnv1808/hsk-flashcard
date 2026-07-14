"""Phase 23 — Targeted-review continuity.

A targeted Study session (Weak Words / Bookmarks) returns the learner to the REFRESHED source
view after completion; level sessions keep Phase 21 Keep Going; unknown/malformed/explicit sessions
keep the generic Home flow. Source context is transient (module-local, never persisted/synced),
holds no cards/ids/DOM/callbacks, and normalizes unknown input to {type:"explicit"}.

Read-only w.r.t. production: local-only (Supabase config stubbed empty), localStorage cleared.
"""
import os, json
from playwright.sync_api import sync_playwright

URL = os.environ.get('HSK_BASE_URL', 'http://localhost:8000') + '/hsk_flashcard_app/'
EMPTY = 'window.SUPABASE_CONFIG={url:"",anonKey:""};'
fails = []
def check(n, c):
    if not c: fails.append(n)

def new_page(ctx):
    pg = ctx.new_page(); errs = []
    pg.on('pageerror', lambda e: errs.append('PAGEERR:' + str(e)))
    pg.on('console', lambda m: errs.append('CON:' + m.text) if m.type == 'error' else None)
    pg.goto(URL); pg.wait_for_timeout(300); pg.evaluate('()=>localStorage.clear()'); pg.reload(); pg.wait_for_timeout(300)
    return pg, errs

def reset(pg):
    pg.evaluate('()=>localStorage.clear()'); pg.reload(); pg.wait_for_timeout(300)

def is_view(pg, vid):
    return pg.evaluate("(v)=>document.getElementById(v).classList.contains('active')", vid)
def grade_current(pg, g):
    pg.evaluate("()=>{ if(!sessionState.flipped) flipCard(); }"); pg.evaluate("(g)=>gradeCard(g)", g)
def drive_complete(pg, g='good', maxn=40):
    for _ in range(maxn):
        if is_view(pg, 'completeView'): return
        grade_current(pg, g)

def actions(pg):
    return pg.evaluate("""()=>({
        complete: document.getElementById('completeView').classList.contains('active'),
        retHidden: document.getElementById('returnSourceBtn').hidden,
        retText: document.getElementById('returnSourceBtn').textContent,
        contHidden: document.getElementById('continueStudyBtn').hidden,
        contText: document.getElementById('continueStudyBtn').textContent,
        homeClass: document.getElementById('homeBtn').className })""")

# Launch a 1-card explicit session with a literal `source` expression, grade to completion.
def finish_with_source(pg, source_expr):
    reset(pg)
    pg.evaluate("(src)=>{ progress={}; save(); const id=cards.filter(c=>c.level==='HSK1')[0].id;"
                " HSK_APP.startSession([id], eval('('+src+')')); }", source_expr)
    pg.wait_for_timeout(100)
    drive_complete(pg)
    return actions(pg)

def make_weak(pg, n=4):
    reset(pg)
    pg.evaluate("()=>{ progress={}; save(); document.getElementById('sessionSize').value='10'; startStudy(['HSK1']); }"); pg.wait_for_timeout(120)
    for _ in range(n): grade_current(pg, 'again')
    pg.evaluate("()=>exitStudy()"); pg.wait_for_timeout(60)

with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={'width': 1280, 'height': 900})
    ctx.route('**/supabase-config.js', lambda r: r.fulfill(status=200, content_type='application/javascript', body=EMPTY))
    pg, errs = new_page(ctx)

    # ================= Source normalization (observed via completion actions) =================
    a = finish_with_source(pg, "undefined")
    check('no source -> explicit (ret hidden, home primary)', a['retHidden'] and a['contHidden'] and a['homeClass'] == 'primary-btn')
    a = finish_with_source(pg, "{feature:'weak'}")
    check('weak source -> return visible', not a['retHidden'] and a['retText'] == 'Quay lại Từ cần cải thiện')
    check('weak source -> keep-going hidden, home secondary', a['contHidden'] and a['homeClass'] == 'secondary-btn')
    a = finish_with_source(pg, "{feature:'bookmarks'}")
    check('bookmarks source -> return visible', not a['retHidden'] and a['retText'] == 'Quay lại Từ đã lưu')
    for expr, label in [("{feature:'smart'}", 'unknown feature'), ("{feature:123}", 'non-string feature'),
                        ("'weak'", 'raw string'), ("['weak']", 'array'), ("{}", 'empty object'),
                        ("{foo:'bar'}", 'no feature'), ("null", 'null'),
                        ("{feature:'weak', extra:function(){return 1;}}", 'callback-carrying (feature still honored)')]:
        a = finish_with_source(pg, expr)
        if 'callback-carrying' in label:
            check('malformed(%s) -> targeted weak, callback ignored' % label, not a['retHidden'] and a['retText'] == 'Quay lại Từ cần cải thiện')
        else:
            check('malformed(%s) -> explicit fallback' % label, a['retHidden'] and a['homeClass'] == 'primary-btn')

    # ================= Level session unchanged (Phase 21 Keep Going) =================
    reset(pg)
    pg.evaluate("()=>{ progress={}; save(); document.getElementById('sessionSize').value='10'; startStudy(['HSK1']); }"); pg.wait_for_timeout(120)
    drive_complete(pg)
    a = actions(pg)
    check('level: Keep Going shown', not a['contHidden'] and 'Học tiếp' in a['contText'])
    check('level: return hidden', a['retHidden'])
    check('level: home secondary', a['homeClass'] == 'secondary-btn')

    # ================= Weak: return opens refreshed weakWordsView + re-queries =================
    make_weak(pg, 4)
    pg.evaluate("()=>HSKInsights.showWeak()"); pg.wait_for_timeout(80)
    check('weak view active pre-study', is_view(pg, 'weakWordsView'))
    weak_before = pg.evaluate("()=>document.querySelectorAll('#weakList .word-row').length")
    check('weak list has entries', weak_before > 0)
    pg.evaluate("()=>document.getElementById('weakStudyBtn').click()"); pg.wait_for_timeout(120)
    check('weak study entered study view', is_view(pg, 'studyView'))
    check('weak study front-side (no leak)', pg.evaluate("()=>sessionState.flipped")==False and pg.evaluate("()=>!document.getElementById('flashcard').classList.contains('flipped')"))
    drive_complete(pg, 'easy')
    a = actions(pg)
    check('weak completion: return primary', not a['retHidden'] and a['retText'] == 'Quay lại Từ cần cải thiện')
    check('weak completion: home available (secondary)', a['homeClass'] == 'secondary-btn')
    # spy the live query, then return
    pg.evaluate("()=>{ const q=window.HSKUtil.analytics; window.__wq=0; const o=q.getWeakWords; q.getWeakWords=function(){window.__wq++; return o.apply(this,arguments);}; }")
    pg.evaluate("()=>document.getElementById('returnSourceBtn').click()"); pg.wait_for_timeout(100)
    check('return weak -> weakWordsView active', is_view(pg, 'weakWordsView'))
    check('return weak -> re-queried live progress (getWeakWords called)', pg.evaluate("()=>window.__wq") >= 1)
    check('return weak -> NOT in study view (no answer-side DOM)', not is_view(pg, 'studyView'))

    # ================= Bookmarks: return reflects removals + empty state =================
    reset(pg)
    ids = pg.evaluate("()=>cards.filter(c=>c.level==='HSK1').slice(0,3).map(c=>c.id)")
    pg.evaluate("(ids)=>ids.forEach(id=>HSKMeta.toggleBookmark(id))", ids)
    pg.evaluate("()=>HSKInsights.showBookmarks()"); pg.wait_for_timeout(80)
    check('bookmarks view active pre-study', is_view(pg, 'bookmarksView'))
    check('bookmark list has 3', pg.evaluate("()=>document.querySelectorAll('#bmList .word-row').length") == 3)
    pg.evaluate("()=>document.getElementById('bmStudyBtn').click()"); pg.wait_for_timeout(120)
    check('bookmark study entered study view', is_view(pg, 'studyView'))
    # remove one bookmark DURING study
    pg.evaluate("(id)=>HSKMeta.removeBookmark(id)", ids[0])
    pg.evaluate("()=>{ const q=window.HSKUtil.userMetadata; window.__bq=0; const o=q.getBookmarkedCards; q.getBookmarkedCards=function(){window.__bq++; return o.apply(this,arguments);}; }")
    drive_complete(pg)
    a = actions(pg)
    check('bookmark completion: return primary', not a['retHidden'] and a['retText'] == 'Quay lại Từ đã lưu')
    pg.evaluate("()=>document.getElementById('returnSourceBtn').click()"); pg.wait_for_timeout(100)
    check('return bookmarks -> bookmarksView active', is_view(pg, 'bookmarksView'))
    check('return bookmarks -> re-queried metadata', pg.evaluate("()=>window.__bq") >= 1)
    check('return bookmarks -> removed bookmark absent (2 left)', pg.evaluate("()=>document.querySelectorAll('#bmList .word-row').length") == 2)
    # remove the rest -> empty state on return
    pg.evaluate("(ids)=>ids.slice(1).forEach(id=>HSKMeta.removeBookmark(id))", ids)
    pg.evaluate("()=>HSKInsights.showBookmarks()"); pg.wait_for_timeout(60)
    check('bookmarks empty -> empty state + study disabled',
          pg.evaluate("()=>document.getElementById('bmList').textContent.indexOf('chưa lưu')>=0") and
          pg.evaluate("()=>document.getElementById('bmStudyBtn').disabled")==True)

    # ================= Rapid double-click harmless =================
    make_weak(pg, 3)
    pg.evaluate("()=>HSKInsights.showWeak()"); pg.wait_for_timeout(60)
    pg.evaluate("()=>document.getElementById('weakStudyBtn').click()"); pg.wait_for_timeout(100)
    drive_complete(pg, 'good')
    err_before = len(errs)
    pg.evaluate("()=>{ const b=document.getElementById('returnSourceBtn'); b.click(); b.click(); }"); pg.wait_for_timeout(100)
    check('double return-click: weakWordsView active', is_view(pg, 'weakWordsView'))
    check('double return-click: no new console/page errors', len(errs) == err_before)
    check('double return-click: not in study view', not is_view(pg, 'studyView'))

    # ================= Targeted cleared by a new session =================
    a = finish_with_source(pg, "{feature:'weak'}")   # targeted
    check('targeted before switch', not a['retHidden'])
    pg.evaluate("()=>{ document.getElementById('sessionSize').value='10'; startStudy(['HSK1']); }"); pg.wait_for_timeout(100)  # NEW level session
    drive_complete(pg)
    a = actions(pg)
    check('new level session clears targeted (return hidden)', a['retHidden'])
    reset(pg)
    pg.evaluate("()=>{ progress={}; save(); const id=cards.filter(c=>c.level==='HSK1')[0].id; HSK_APP.startSession([id], {feature:'bookmarks'}); }"); pg.wait_for_timeout(100)
    drive_complete(pg)
    check('targeted bookmarks set', not actions(pg)['retHidden'])
    pg.evaluate("()=>{ const id=cards.filter(c=>c.level==='HSK1')[1].id; HSK_APP.startSession([id]); }"); pg.wait_for_timeout(100)  # NEW explicit, no source
    drive_complete(pg)
    check('new explicit session clears targeted (return hidden)', actions(pg)['retHidden'])

    # ================= Handler fallback to Home when source not targeted =================
    # (explicit completion: the button is hidden, but the click handler itself must fall back safely)
    pg.evaluate("()=>document.getElementById('returnSourceBtn').click()"); pg.wait_for_timeout(80)
    check('return handler with non-targeted source -> Home fallback', is_view(pg, 'homeView'))

    # ================= Navigation makes zero writes/dirty =================
    make_weak(pg, 3)
    pg.evaluate("()=>HSKInsights.showWeak()"); pg.wait_for_timeout(60)
    pg.evaluate("()=>document.getElementById('weakStudyBtn').click()"); pg.wait_for_timeout(100)
    drive_complete(pg, 'good')
    wc = pg.evaluate("""()=>{ let saves=0, prog=0;
        const os=window.saveSettings; window.saveSettings=function(){saves++; return os.apply(this,arguments);};
        const op=window.save; window.save=function(){prog++; return op.apply(this,arguments);};
        document.getElementById('returnSourceBtn').click();
        window.saveSettings=os; window.save=op;
        return { saves, prog }; }""")
    check('return navigation: zero settings saves', wc['saves'] == 0)
    check('return navigation: zero progress saves', wc['prog'] == 0)

    check('no console/page errors', len(errs) == 0)
    ctx.close(); b.close()

print(json.dumps({'pass': len(fails) == 0, 'fails': fails, 'errs': errs[:6]}, ensure_ascii=False))
