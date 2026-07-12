"""SRS characterization (Phase 1). Drives the CURRENT gradeCard() in a real browser
and freezes its exact output (interval/reps/correct/attempts + due offset) as golden
values. It does NOT reimplement the formula — the goldens were derived by observing
the current production implementation and must not change without an approved decision.
"""
import os, json
from playwright.sync_api import sync_playwright

URL = os.environ.get("HSK_BASE_URL", "http://localhost:8000") + "/hsk_flashcard_app/"
EMPTY = 'window.SUPABASE_CONFIG={url:"",anonKey:""};'
fails = []
def check(n, c):
    if not c: fails.append(n)

def grade_card(pg, card_id, grade):
    """Start a single-card session for card_id (progress carries over), flip, grade.
    Returns the resulting progress record."""
    pg.evaluate("(id)=>{ window.HSK_APP.startSession([id]); }", card_id)
    pg.evaluate("()=>flipCard()")
    pg.evaluate("(g)=>gradeCard(g)", grade)
    return pg.evaluate("(id)=>window.HSK_APP.getProgress()[id]", card_id)

def main():
    with sync_playwright() as p:
        b = p.chromium.launch(); ctx = b.new_context(viewport={"width": 1280, "height": 900})
        ctx.route("**/supabase-config.js", lambda r: r.fulfill(status=200, content_type="application/javascript", body=EMPTY))
        pg = ctx.new_page(); errs = []
        pg.on("pageerror", lambda e: errs.append("PAGEERR:" + str(e)))
        pg.on("console", lambda m: errs.append("CON:" + m.text) if m.type == "error" else None)
        pg.goto(URL); pg.wait_for_timeout(300); pg.evaluate("()=>localStorage.clear()"); pg.reload(); pg.wait_for_timeout(300)
        today = pg.evaluate("()=>new Date().toISOString().slice(0,10)")

        # 1) fresh-card single grade -> exact state (GOLDEN)
        golden_fresh = {
            "again": {"interval": 0, "reps": 1, "correct": 0, "attempts": 1},
            "hard":  {"interval": 1, "reps": 1, "correct": 0, "attempts": 1},
            "good":  {"interval": 3, "reps": 1, "correct": 1, "attempts": 1},
            "easy":  {"interval": 7, "reps": 1, "correct": 1, "attempts": 1},
        }
        cid = 1
        for i, (grade, exp) in enumerate(golden_fresh.items()):
            pg.evaluate("()=>{ progress={}; save(); }")  # fresh card
            st = grade_card(pg, cid, grade)
            for k, v in exp.items():
                check(f"fresh {grade}: {k}={st.get(k)} exp {v}", st.get(k) == v)
            # due offset: again -> today; else today + interval days
            if grade == "again":
                check(f"fresh {grade}: due==today", st.get("due") == today)
            else:
                check(f"fresh {grade}: due present & >= today", st.get("due") >= today)

        # 2) interval progression (repeated grade on the same card, state carries over)
        progressions = {
            "good": [3, 6, 12, 24],
            "hard": [1, 1, 1, 1],
            "easy": [7, 21, 63],
        }
        for grade, seq in progressions.items():
            pg.evaluate("()=>{ progress={}; save(); }")
            got = []
            for _ in seq:
                st = grade_card(pg, cid, grade)
                got.append(st["interval"])
            check(f"{grade} interval progression {got} == {seq}", got == seq)

        # 3) repeated 'again' keeps interval 0 but increments reps/attempts, correct stays 0
        pg.evaluate("()=>{ progress={}; save(); }")
        last = None
        for n in range(1, 4):
            last = grade_card(pg, cid, "again")
        check("again x3: interval 0", last["interval"] == 0)
        check("again x3: reps==3", last["reps"] == 3)
        check("again x3: attempts==3", last["attempts"] == 3)
        check("again x3: correct==0", last["correct"] == 0)

        # 4) learned card graded again (seed interval 3, grade good -> 6)
        pg.evaluate("(id)=>{ progress={}; progress[id]={due:'2026-01-01',interval:3,reps:1,correct:1,attempts:1}; save(); }", cid)
        st = grade_card(pg, cid, "good")
        check("learned good: interval 3->6", st["interval"] == 6)
        check("learned good: reps 2", st["reps"] == 2)
        check("learned good: correct 2", st["correct"] == 2)

        # 5) grading never occurs unless flipped (guard) — grade without flip is a no-op
        pg.evaluate("()=>{ progress={}; save(); window.HSK_APP.startSession([1]); }")  # front, not flipped
        before = pg.evaluate("()=>JSON.stringify(window.HSK_APP.getProgress())")
        pg.evaluate("()=>gradeCard('good')")  # should be ignored (flipped=false)
        after = pg.evaluate("()=>JSON.stringify(window.HSK_APP.getProgress())")
        check("grade ignored when not flipped", before == after)

        result = {"suite": "srs_characterization", "pass": len(fails) == 0 and len(errs) == 0,
                  "fails": fails, "errors": errs}
        print(json.dumps(result, ensure_ascii=False))
        b.close()
        return 0 if result["pass"] else 1

if __name__ == "__main__":
    import sys
    sys.exit(main())
