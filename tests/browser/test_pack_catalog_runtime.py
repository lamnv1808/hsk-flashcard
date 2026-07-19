#!/usr/bin/env python3
"""Phase 24E-B: the committed catalog is accepted by the real 24E-A registry.

The generator (tests/data/test_pack_catalog_legacy.py) proves the catalog is
deterministic and describes the real runtime files. This suite proves the other
half: that pack-registry.js -- which fails CLOSED on any defect -- actually
accepts it, and that planPackBoot resolves it the way Phase 24E-B requires.

Deliberately does NOT wire anything into index.html. The scripts are loaded
into a blank page, so HSK's production boot path is untouched by this suite.
"""

import json
import os
import sys

from playwright.sync_api import sync_playwright

BASE = os.environ.get("HSK_BASE_URL", "http://localhost:8000") + "/hsk_flashcard_app/"

fails = []


def check(name, cond):
    if not cond:
        fails.append(name)


def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        # Blank same-origin document: no app scripts, no HSK runtime.
        page.goto(BASE + "packs/catalog.js")
        page.goto(BASE)
        page.add_script_tag(url="core/content/pack-registry.js")
        page.add_script_tag(url="core/content/pack-boot.js")
        page.add_script_tag(url="packs/catalog.js")

        check("catalog global is present",
              page.evaluate("() => typeof window.FLASHEDU_CATALOG === 'object'"))

        # --- the registry accepts the committed catalog --------------------
        built = page.evaluate("""() => {
            try {
                var r = window.HSKUtil.createPackRegistry(window.FLASHEDU_CATALOG);
                return { ok: true, ids: r.getPackIds(),
                         visible: r.getLaunchVisiblePackIds(),
                         def: r.getDefaultPackId(),
                         range: r.getIdRange('hsk'),
                         assets: r.getAssetPaths('hsk') };
            } catch (e) { return { ok: false, error: String(e.message || e) }; }
        }""")
        check("registry accepts the committed catalog: " + str(built.get("error")),
              built.get("ok") is True)
        if built.get("ok"):
            check("exactly one pack", built["ids"] == ["hsk"])
            check("hsk is launch-visible", built["visible"] == ["hsk"])
            check("hsk is the deterministic default", built["def"] == "hsk")
            check("declared ownership range is 1..999999",
                  built["range"] == {"min": 1, "max": 999999})
            check("cardsPath is the legacy data.js",
                  built["assets"]["cardsPath"] == "data.js")
            check("manifestPath is the legacy adapter",
                  built["assets"]["manifestPath"] ==
                  "packs/hsk/hsk-content-pack.js")

        # --- boot planning resolves as Phase 24E-B requires -----------------
        plans = page.evaluate("""() => {
            var r = window.HSKUtil.createPackRegistry(window.FLASHEDU_CATALOG);
            function p(req) {
                return window.HSKUtil.planPackBoot({ registry: r, requestedPackId: req });
            }
            return {
                first:     p(null),
                requested: p('hsk'),
                unknown:   p('ielts'),
                malformed: p('../evil'),
                empty:     p('')
            };
        }""")
        check("first run defaults to hsk",
              plans["first"]["ok"] and plans["first"]["packId"] == "hsk" and
              plans["first"]["reason"] == "default-first-run")
        check("stored hsk is honored",
              plans["requested"]["reason"] == "requested" and
              plans["requested"]["packId"] == "hsk")
        check("unknown pack falls back to hsk, never empty",
              plans["unknown"]["ok"] and plans["unknown"]["packId"] == "hsk" and
              plans["unknown"]["reason"] == "fallback-unknown-pack")
        check("malformed pack id falls back to hsk, never empty",
              plans["malformed"]["ok"] and plans["malformed"]["packId"] == "hsk" and
              plans["malformed"]["reason"] == "fallback-malformed-request")
        check("empty stored id is treated as first run",
              plans["empty"]["ok"] and plans["empty"]["packId"] == "hsk")
        check("every plan names exactly one pack's assets",
              all(len(v["scripts"]) == 2 for v in plans.values() if v["ok"]))

        # --- a mixed / overlapping catalog must fail closed -----------------
        overlap = page.evaluate("""() => {
            var c = JSON.parse(JSON.stringify(window.FLASHEDU_CATALOG));
            var clone = JSON.parse(JSON.stringify(c.packs[0]));
            clone.packId = 'synth-en';
            clone.courseId = 'synth-en';
            clone.cardsPath = 'packs/synth-en/synth-en-cards.js';
            clone.manifestPath = 'packs/synth-en/synth-en-content-pack.js';
            c.packs.push(clone);           // same idRange -> must be rejected
            try { window.HSKUtil.createPackRegistry(c); return null; }
            catch (e) { return String(e.message || e); }
        }""")
        check("overlapping id ranges are rejected",
              overlap is not None and "overlap" in overlap)

        browser.close()

    print(json.dumps({"suite": "pack_catalog_runtime",
                      "pass": not fails, "failures": fails}))
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
