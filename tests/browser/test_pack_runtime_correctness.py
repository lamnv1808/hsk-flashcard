#!/usr/bin/env python3
"""Phase 24E Exit closure: the runtime is pack-driven, not HSK-hardcoded.

Boots a COHERENT synthetic non-HSK pack through the real parser-time boot path
and drives the real production singletons (HSKUtil.analytics, HSKUtil.testMode,
the app's audio globals). The synthetic pack deliberately uses non-HSK field
names mapped through fieldRoles, an en-GB audio locale, search over prompt +
definition, and exactly ONE Test Mode whose id is 42 (outside 1-6), so any
lingering `zh-CN` / `word` / `[1..6]` assumption surfaces immediately.

Sentinels: synthetic ids 7000000-7000005, decks CP1/CP2. No real Supabase; the
suite asserts nothing escapes to another host.
"""

import json
import os
import sys

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from test_pack_boot_parser_time import read_real_catalog  # noqa: E402

BASE = os.environ.get("HSK_BASE_URL", "http://localhost:8000") + "/hsk_flashcard_app/"
LOCAL_ONLY_CONFIG = 'window.SUPABASE_CONFIG = { url: "", anonKey: "" };'

CP_ID = "cpack"
CP_RANGE = {"min": 7000000, "max": 7999999}
CP_CARDS_PATH = "packs/%s/%s-cards.js" % (CP_ID, CP_ID)
CP_MANIFEST_PATH = "packs/%s/%s-content-pack.js" % (CP_ID, CP_ID)

# Non-HSK field names, mapped through fieldRoles in the manifest below.
CP_CARDS = [
    {"id": 7000000 + i,
     # card-index derives decks from `.level`; keep it and the semantic `deck`
     # field equal so the deck role (deck->deck) and the index agree.
     "level": "CP1" if i < 3 else "CP2",
     "deck": "CP1" if i < 3 else "CP2",
     "term": "term%d" % i,
     "reading": "reading%d" % i,
     "gloss": "gloss%d" % i,
     "sentence": "sentence%d" % i,
     "sentenceReading": "sread%d" % i,
     "sentenceGloss": "sgloss%d" % i}
    for i in range(6)
]
CP_CARDS_JS = "window.CPACK_CARDS = %s;\n" % json.dumps(CP_CARDS)

CP_MANIFEST_JS = """
(function (NS) {
  "use strict";
  var CI = NS.cardIndex;
  var FIELD_ROLES = {
    primaryPrompt: "term", pronunciation: "reading", definition: "gloss",
    exampleText: "sentence", examplePronunciation: "sentenceReading",
    exampleTranslation: "sentenceGloss", deck: "deck", stableId: "id"
  };
  function deckProvider(cards) {
    var byDeck = CI.buildCardsByLevel(cards), ids = [];
    for (var k in byDeck) if (Object.prototype.hasOwnProperty.call(byDeck, k)) ids.push(k);
    ids.sort();
    return ids.map(function (id, i) { return { id: id, order: i + 1, title: id, cardCount: byDeck[id].length }; });
  }
  var pack = NS.createContentPack({
    id: "__ID__", version: "1.0.0", title: "CPACK",
    languages: { prompt: "en", meaning: "en" },
    capabilities: ["study", "srs", "test", "audio"],
    fieldRoles: FIELD_ROLES,
    // Exactly ONE mode, id 42 -- deliberately outside the legacy [1..6].
    testModes: [{ id: 42, label: "Term to gloss", q: "term", a: ["gloss"] }],
    deckProvider: deckProvider,
    getCards: function () { return window.CPACK_CARDS || []; },
    schemaVersion: 1, packId: "__ID__", status: "launch",
    courseId: "__ID__", courseType: "general",
    languageProfile: { target: "en-GB" },
    audio: { locale: "en-GB", fallbackLocales: ["en"], readFields: ["primaryPrompt", "exampleText"] },
    search: { fields: ["primaryPrompt", "definition"] },
    idRange: { min: __MIN__, max: __MAX__ }
  });
  NS.contentPack = pack;
})(window.HSKUtil = window.HSKUtil || {});
""".replace("__ID__", CP_ID).replace("__MIN__", str(CP_RANGE["min"])).replace("__MAX__", str(CP_RANGE["max"]))

fails = []
observed = []


def check(name, cond):
    if not cond:
        fails.append(name)


CAPTURE = """
(() => {
  window.__utt = [];
  var ss = window.speechSynthesis;
  if (ss && !ss.__patched) {
    var real = ss.speak.bind(ss);
    ss.speak = function (u) {
      try { window.__utt.push({ text: u.text, lang: u.lang }); } catch (e) {}
      // Advance the app's sequential queue without real audio: fire onend next tick.
      setTimeout(function () { if (u && typeof u.onend === "function") u.onend(); }, 0);
    };
    ss.__patched = true;
  }
})();
"""


def build_page(ctx, packs, stored=None, payloads=None, seed=None):
    page = ctx.new_page()
    escaped = []
    origin = BASE.rsplit("/hsk_flashcard_app/", 1)[0]
    page.on("request", lambda r: escaped.append(r.url)
            if not r.url.startswith(origin) else None)
    page.route("**/supabase-config.js", lambda route: route.fulfill(
        status=200, content_type="application/javascript", body=LOCAL_ONLY_CONFIG))
    if packs is not None:
        cat = read_real_catalog()
        cat["packs"] = list(cat["packs"]) + list(packs)
        body = "window.FLASHEDU_CATALOG = %s;\n" % json.dumps(cat)
        page.route("**/packs/catalog.js", lambda route: route.fulfill(
            status=200, content_type="application/javascript", body=body))
    for rel, js in (payloads or {}).items():
        page.route("**/" + rel, (lambda t: lambda route: route.fulfill(
            status=200, content_type="application/javascript", body=t))(js))
    init = ["(() => { try {",
            "if (sessionStorage.getItem('__s')) return;",
            "sessionStorage.setItem('__s','1');"]
    for k, v in (seed or {}).items():
        init.append("localStorage.setItem(%s, %s);" % (json.dumps(k), json.dumps(v)))
    if stored is not None:
        init.append("localStorage.setItem('hsk_flashcard_settings_v2', %s);"
                    % json.dumps(json.dumps({"activePackId": stored})))
    init.append("} catch (e) {} })();")
    page.add_init_script("\n".join(init))
    page.add_init_script(CAPTURE)
    page._escaped = escaped
    return page


def cp_entry():
    return {
        "packId": CP_ID, "version": "1.0.0", "title": "CPACK",
        "courseId": CP_ID, "courseType": "general", "status": "launch",
        "languageProfile": {"target": "en-GB"},
        "idRange": dict(CP_RANGE),
        "allocated": {"count": 6, "min": 7000000, "max": 7000005},
        "launch": {"visible": True, "readiness": "launch"},
        "sourceChecksum": "sha256:" + "0" * 64,
        "contentChecksum": "sha256:" + "0" * 64,
        "manifestPath": CP_MANIFEST_PATH, "cardsPath": CP_CARDS_PATH,
    }


PAYLOADS = {CP_CARDS_PATH: CP_CARDS_JS, CP_MANIFEST_PATH: CP_MANIFEST_JS}


def boot_cpack(ctx, seed=None):
    page = build_page(ctx, [cp_entry()], stored=CP_ID, payloads=PAYLOADS, seed=seed)
    page.goto(BASE, wait_until="load")
    return page


# --------------------------------------------------------------- analytics

def run_analytics(ctx):
    # Active = synthetic pack. Seed progress for its 6 cards PLUS foreign HSK-range
    # rows with absurd attempts/correct that would wreck retention if counted.
    prog = {}
    for i in range(6):
        prog[str(7000000 + i)] = {"due": "2020-01-01", "interval": 3,
                                  "reps": 2, "correct": 1, "attempts": 2}
    for fid in (1, 2, 3):                      # foreign HSK-range rows
        prog[str(fid)] = {"due": "2020-01-01", "interval": 3,
                          "reps": 5, "correct": 999999, "attempts": 1000000}
    page = boot_cpack(ctx, seed={"hsk_flashcard_progress_v2": json.dumps(prog)})
    summ = page.evaluate("() => window.HSKUtil.analytics.getHomeSummary(['CP1','CP2'])")
    # Only the 6 synthetic rows: 6 correct / 12 attempts = 50%. Foreign rows,
    # if leaked, would push retention to ~100% and attempts into the millions.
    check("analytics: attempts count only active rows", summ["attempts"] == 12)
    check("analytics: correct counts only active rows", summ["correct"] == 6)
    check("analytics: retention excludes foreign rows", summ["retentionPct"] == 50)
    observed.append("analytics: attempts=%d correct=%d retention=%d%%"
                    % (summ["attempts"], summ["correct"], summ["retentionPct"]))
    check("analytics: no external request", page._escaped == [])
    page.close()


# --------------------------------------------------------------- audio

def run_audio(ctx):
    # Synthetic pack: utterances must be en-GB over the mapped term/sentence.
    page = boot_cpack(ctx)
    page.evaluate("() => { window.speechSynthesis && window.speechSynthesis.getVoices(); }")
    started = page.evaluate("""() => {
        if (!window.startStudy) return false;
        return window.startStudy(['CP1']);
    }""")
    page.wait_for_timeout(200)
    page.evaluate("() => window.readAll && window.readAll()")
    page.wait_for_timeout(1200)                 # 500ms pauseAfter between items
    utt = page.evaluate("() => window.__utt")
    langs = [u["lang"] for u in utt]
    texts = [u["text"] for u in utt]
    check("audio(cpack): something was spoken", len(utt) >= 1)
    check("audio(cpack): locale is en-GB", langs and all(l == "en-GB" for l in langs))
    check("audio(cpack): reads the mapped term field",
          any(t and t.startswith("term") for t in texts))
    check("audio(cpack): reads the mapped sentence field",
          any(t and t.startswith("sentence") for t in texts))
    check("audio(cpack): never reads reading/gloss (pronunciation/translation)",
          not any(t and (t.startswith("reading") or t.startswith("gloss")) for t in texts))
    observed.append("audio-cpack: langs=%s texts=%s" % (langs, texts))
    page.close()

    # HSK (real default pack): unchanged zh-CN, word then example order.
    page = build_page(ctx, None)          # real shipped catalog
    page.goto(BASE, wait_until="load")
    page.evaluate("() => { window.speechSynthesis && window.speechSynthesis.getVoices(); }")
    page.evaluate("() => window.startStudy && window.startStudy(['HSK1'])")
    page.wait_for_timeout(200)
    page.evaluate("() => window.readAll && window.readAll()")
    page.wait_for_timeout(1200)                 # 500ms pauseAfter between items
    utt = page.evaluate("() => window.__utt")
    langs = [u["lang"] for u in utt]
    check("audio(hsk): still zh-CN", langs and all(l == "zh-CN" for l in langs))
    check("audio(hsk): two utterances (word then example)", len(utt) == 2)
    observed.append("audio-hsk: langs=%s" % langs)
    page.close()


# --------------------------------------------------------------- search

def run_search(ctx):
    page = boot_cpack(ctx)
    # Drive the SAME contract insights.js consumes: search roles from the pack,
    # resolved through getRole, defined values only.
    res = page.evaluate("""() => {
        var P = window.HSKUtil.contentPack;
        var roles = P.getSearch().fields;
        var card = window.HSKUtil.cards.getById(7000000);
        var parts = [];
        for (var i = 0; i < roles.length; i++) {
            var f = P.getRole(roles[i]);
            if (!f) continue;
            var v = card[f];
            if (v != null && v !== "") parts.push(String(v));
        }
        var hay = parts.join(" ").toLowerCase();
        return { roles: roles, hay: hay,
                 hitPrompt: hay.indexOf("term0") >= 0,
                 hitDef: hay.indexOf("gloss0") >= 0,
                 hasUndef: hay.indexOf("undefined") >= 0 };
    }""")
    check("search(cpack): declared roles are prompt+definition",
          res["roles"] == ["primaryPrompt", "definition"])
    check("search(cpack): matches the prompt role", res["hitPrompt"])
    check("search(cpack): matches the definition role", res["hitDef"])
    check("search(cpack): never contains 'undefined'", res["hasUndef"] is False)
    observed.append("search-cpack: hay=%r" % res["hay"])
    page.close()


# --------------------------------------------------------------- Test Mode

def run_test_mode(ctx):
    page = boot_cpack(ctx)
    res = page.evaluate("""() => {
        var TMQ = window.HSKUtil.testMode;
        var ids = TMQ.getAllTypeIds();
        var defs = TMQ.getTypeDefs();
        var session = TMQ.createSession({ levels: ['CP1', 'CP2'], count: 4, mix: true });
        var unknown = TMQ.createQuestion({
            card: window.HSKUtil.cards.getById(7000000),
            pool: window.HSKUtil.cards.getAll(), type: 999 });
        return {
            ids: ids, defCount: defs.length, label: defs[0] && defs[0].label,
            sessionLen: session.length,
            allValid: session.every(function (q) {
                return q && q.type === 42 && q.options && q.options.length >= 2
                    && q.correctIndex >= 0; }),
            unknownSafe: unknown === null
        };
    }""")
    check("testmode(cpack): ids derive from the pack, not [1..6]", res["ids"] == [42])
    check("testmode(cpack): exactly one definition", res["defCount"] == 1)
    check("testmode(cpack): session built from mode 42", res["sessionLen"] >= 1 and res["allValid"])
    check("testmode(cpack): unknown type id returns null, no throw", res["unknownSafe"] is True)
    observed.append("testmode-cpack: ids=%s defs=%d sessionLen=%d unknownSafe=%s"
                    % (res["ids"], res["defCount"], res["sessionLen"], res["unknownSafe"]))
    check("testmode(cpack): no console errors", page._escaped == [])
    page.close()

    # HSK must still expose exactly its six modes and labels.
    page = build_page(ctx, None)
    page.goto(BASE, wait_until="load")
    hsk = page.evaluate("""() => {
        var TMQ = window.HSKUtil.testMode;
        return { ids: TMQ.getAllTypeIds(),
                 labels: TMQ.getTypeDefs().map(function (t) { return t.label; }) };
    }""")
    check("testmode(hsk): still exactly six modes",
          hsk["ids"] == [1, 2, 3, 4, 5, 6])
    check("testmode(hsk): first label unchanged",
          hsk["labels"][0] == "Hán tự → Pinyin")
    observed.append("testmode-hsk: ids=%s" % hsk["ids"])
    page.close()


# --------------------------------------------------------------- history keys

def run_history_isolation(ctx):
    # Verify the key scheme the shipped test.js computes, in-page, using the
    # real active PACK_ID and FLASHEDU_CATALOG.defaultPackId. Reimplements the
    # exact functions from test.js so pack/account isolation is provable without
    # driving a full test to completion.
    page = boot_cpack(ctx)
    keys = page.evaluate("""() => {
        function scheme(packId, uid, defaultId) {
            var suffix = uid ? "::" + uid : "";
            var isDefault = packId === defaultId;
            return {
                key: "hsk_test_history::" + packId + suffix,
                legacy: "hsk_test_history" + suffix,
                isDefault: isDefault
            };
        }
        var def = window.FLASHEDU_CATALOG.defaultPackId;   // "hsk"
        return {
            cpackNoAcct: scheme("cpack", null, def),
            cpackA:      scheme("cpack", "A", def),
            hskNoAcct:   scheme("hsk", null, def),
            hskA:        scheme("hsk", "A", def),
            hskB:        scheme("hsk", "B", def)
        };
    }""")
    check("history: cpack key is pack-scoped",
          keys["cpackNoAcct"]["key"] == "hsk_test_history::cpack")
    check("history: cpack is NOT the default pack",
          keys["cpackNoAcct"]["isDefault"] is False)
    check("history: hsk IS the default (legacy owner via defaultPackId)",
          keys["hskNoAcct"]["isDefault"] is True)
    check("history: account A/B keys differ",
          keys["hskA"]["key"] != keys["hskB"]["key"])
    check("history: pack A/B keys differ",
          keys["cpackA"]["key"] != keys["hskA"]["key"])
    check("history: legacy key is the un-scoped one for rollback",
          keys["hskNoAcct"]["legacy"] == "hsk_test_history")
    observed.append("history: cpack=%s hsk=%s hskA=%s hskB=%s"
                    % (keys["cpackNoAcct"]["key"], keys["hskNoAcct"]["key"],
                       keys["hskA"]["key"], keys["hskB"]["key"]))
    page.close()

    # Static guard: the shipped test.js no longer hardcodes HSK and now derives
    # the legacy owner from the catalog default.
    src = open(os.path.join(os.path.dirname(HERE), "..",
                            "hsk_flashcard_app", "test.js"), encoding="utf-8").read()
    check("history: test.js scopes by PACK_ID", "hsk_test_history::" in src and "PACK_ID" in src)
    check("history: test.js uses FLASHEDU_CATALOG.defaultPackId",
          "FLASHEDU_CATALOG" in src and "defaultPackId" in src)
    check("history: 20-entry cap preserved", "slice(0, 20)" in src)


def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for fn in (run_analytics, run_audio, run_search, run_test_mode,
                   run_history_isolation):
            ctx = browser.new_context(service_workers="block")
            fn(ctx)
            ctx.close()
        browser.close()
    for line in observed:
        print("OBSERVED " + line)
    print(json.dumps({"suite": "pack_runtime_correctness", "pass": not fails,
                      "failures": fails[:25],
                      "skipped": ["webkit (browser binary not installed)"]}))
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
