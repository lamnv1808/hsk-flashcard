#!/usr/bin/env python3
"""Phase 24E-A - PackRegistry validation (foundation, not wired to production).

The registry is the layer that finally performs the check ContentPack v1 has
deferred since Phase 24C: cross-pack integer id-range overlap rejection.
ContentPack validates one pack's declared range but cannot see a second pack,
and its validate() has no production caller at all. Overlapping ranges would let
two packs share progress rows keyed by the same integer -- silent data
corruption, not a visible bug -- so every overlap case here is fatal.

The module under test is loaded by injection, NOT from index.html: Phase 24E-A
adds no production call site.
"""

import json
import os
import sys

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "tests", "support"))

from datajs import emit  # noqa: E402

URL = os.environ.get("HSK_BASE_URL", "http://localhost:8000") + "/hsk_flashcard_app/"
EMPTY = 'window.SUPABASE_CONFIG={url:"",anonKey:""};'
REGISTRY_JS = os.path.join(ROOT, "hsk_flashcard_app", "core", "content", "pack-registry.js")

# A minimal VALID catalog builder, plus helpers, as JS source.
HARNESS = """
window.__mkPack = function (over) {
  const p = {
    packId: 'alpha', version: '1.0.0', title: 'Alpha',
    courseId: 'alpha', courseType: 'general', status: 'launch',
    languageProfile: { target: 'en' },
    launch: { visible: true, readiness: 'launch' },
    idRange: { min: 1, max: 999999 },
    allocated: { min: 1, max: 10, count: 10, gaps: 0 },
    sourceChecksum: 'sha256:' + 'a'.repeat(64),
    contentChecksum: 'sha256:' + 'b'.repeat(64),
    manifestPath: 'packs/alpha/alpha-content-pack.js',
    cardsPath: 'packs/alpha/alpha-cards.js'
  };
  Object.assign(p, over || {});
  return p;
};
window.__mkCatalog = function (packs, extra) {
  const c = { schemaVersion: 1, packs: packs || [window.__mkPack()] };
  Object.assign(c, extra || {});
  return c;
};
window.__rejects = function (catalog) {
  try { HSKUtil.createPackRegistry(catalog); return false; } catch (e) { return true; }
};
window.__second = function (over) {
  return window.__mkPack(Object.assign({
    packId: 'beta', courseId: 'beta', title: 'Beta',
    idRange: { min: 1000000, max: 1999999 },
    allocated: { min: 1000000, max: 1000005, count: 6, gaps: 0 },
    manifestPath: 'packs/beta/beta-content-pack.js',
    cardsPath: 'packs/beta/beta-cards.js'
  }, over || {}));
};
"""

PROBE = """
() => {
  const mk = window.__mkPack, cat = window.__mkCatalog, rej = window.__rejects;
  const sec = window.__second;
  const R = {};

  // --- acceptance -------------------------------------------------------
  const one = HSKUtil.createPackRegistry(cat());
  R.singlePackOk = one.getPackIds().join(',') === 'alpha';
  R.schemaVersion = one.getSchemaVersion() === 1;
  R.hasPack = one.hasPack('alpha') && !one.hasPack('nope');
  R.getPackShape = one.getPack('alpha').title === 'Alpha';
  R.unknownPackUndefined = one.getPack('nope') === undefined;

  const two = HSKUtil.createPackRegistry(cat([mk(), sec()]));
  R.multiPackOk = two.getPackIds().sort().join(',') === 'alpha,beta';
  R.idRangeExposed = two.getIdRange('beta').min === 1000000;
  R.allocatedExposed = two.getAllocated('beta').count === 6;
  R.assetPaths = two.getAssetPaths('beta').cardsPath === 'packs/beta/beta-cards.js';

  // --- identity ---------------------------------------------------------
  R.duplicateId = rej(cat([mk(), mk()]));
  R.malformedIdUpper = rej(cat([mk({ packId: 'Alpha' })]));
  R.malformedIdSpace = rej(cat([mk({ packId: 'al pha' })]));
  R.malformedIdDot = rej(cat([mk({ packId: 'al.pha' })]));
  R.malformedIdEmpty = rej(cat([mk({ packId: '' })]));
  R.malformedIdSlash = rej(cat([mk({ packId: 'a/b' })]));
  R.malformedCourseId = rej(cat([mk({ courseId: 'Alpha!' })]));
  R.badSchemaVersion = rej(cat([mk()], { schemaVersion: 2 }));
  R.missingSchemaVersion = rej({ packs: [mk()] });
  R.emptyPacks = rej(cat([]));
  R.notAnObject = rej('nope') && rej(null) && rej([mk()]);

  // --- id ranges --------------------------------------------------------
  R.declaredOverlapExact = rej(cat([mk(), sec({ idRange: { min: 1, max: 999999 } })]));
  R.declaredOverlapPartial = rej(cat([
    mk({ idRange: { min: 1, max: 100 }, allocated: { min: 1, max: 10, count: 10, gaps: 0 } }),
    sec({ idRange: { min: 50, max: 200 }, allocated: { min: 60, max: 65, count: 6, gaps: 0 } })
  ]));
  R.declaredAdjacentOk = (function () {
    try {
      HSKUtil.createPackRegistry(cat([
        mk({ idRange: { min: 1, max: 100 }, allocated: { min: 1, max: 10, count: 10, gaps: 0 } }),
        sec({ idRange: { min: 101, max: 200 }, allocated: { min: 101, max: 106, count: 6, gaps: 0 } })
      ]));
      return true;
    } catch (e) { return false; }
  })();
  R.allocatedOverlap = rej(cat([
    mk({ idRange: { min: 1, max: 100 }, allocated: { min: 40, max: 60, count: 21, gaps: 0 } }),
    sec({ idRange: { min: 101, max: 200 }, allocated: { min: 55, max: 70, count: 16, gaps: 0 } })
  ]));
  R.allocOutsideDeclared = rej(cat([mk({ allocated: { min: 1, max: 1000000, count: 5, gaps: 0 } })]));
  R.allocMinBelowDeclared = rej(cat([
    mk({ idRange: { min: 100, max: 200 }, allocated: { min: 50, max: 150, count: 5, gaps: 0 } })]));
  R.allocCountExceedsSpan = rej(cat([mk({ allocated: { min: 1, max: 5, count: 99, gaps: 0 } })]));
  R.allocZeroNeedsNull = rej(cat([mk({ allocated: { min: 1, max: 1, count: 0, gaps: 0 } })]));
  R.allocZeroWithNullOk = (function () {
    try {
      HSKUtil.createPackRegistry(cat([mk({ allocated: { min: null, max: null, count: 0, gaps: 0 } })]));
      return true;
    } catch (e) { return false; }
  })();
  R.rangeMinZero = rej(cat([mk({ idRange: { min: 0, max: 100 } })]));
  R.rangeMaxBelowMin = rej(cat([mk({ idRange: { min: 100, max: 10 } })]));
  R.rangeAboveInt4 = rej(cat([mk({ idRange: { min: 1, max: 2147483648 } })]));
  R.rangeNonInteger = rej(cat([mk({ idRange: { min: 1.5, max: 100 } })]));

  // --- paths ------------------------------------------------------------
  const badPaths = ['../escape.js', '/abs.js', '//evil.example/x.js',
                    'https://evil.example/x.js', 'C:\\\\win\\\\x.js',
                    '\\\\\\\\unc\\\\share\\\\x.js', 'packs\\\\a\\\\b.js',
                    'packs//a.js', 'a/../../b.js', ''];
  R.badPathsRejected = badPaths.every(function (p) {
    return rej(cat([mk({ cardsPath: p })]));
  });
  R.samePathRejected = rej(cat([mk({ cardsPath: 'packs/alpha/alpha-content-pack.js' })]));
  R.goodPathAccepted = !rej(cat([mk({ cardsPath: 'packs/alpha/nested/x.js' })]));

  // --- checksums --------------------------------------------------------
  R.badChecksumPrefix = rej(cat([mk({ contentChecksum: 'md5:' + 'a'.repeat(64) })]));
  R.badChecksumLength = rej(cat([mk({ contentChecksum: 'sha256:abc' })]));
  R.badChecksumUpper = rej(cat([mk({ contentChecksum: 'sha256:' + 'A'.repeat(64) })]));

  // --- launch honesty ---------------------------------------------------
  R.visibleButNotReady = rej(cat([mk({ launch: { visible: true, readiness: 'beta' } })]));
  R.visibleButDraftStatus = rej(cat([mk({ status: 'draft' })]));
  R.badReadiness = rej(cat([mk({ launch: { visible: true, readiness: 'soon' } })]));
  R.nonBooleanVisible = rej(cat([mk({ launch: { visible: 'yes', readiness: 'launch' } })]));

  const hidden = HSKUtil.createPackRegistry(cat([
    mk(), sec({ status: 'draft', launch: { visible: false, readiness: 'internal' } })]));
  R.hiddenFiltered = hidden.getLaunchVisiblePackIds().join(',') === 'alpha';
  R.hiddenStillListed = hidden.getPackIds().sort().join(',') === 'alpha,beta';
  R.hiddenNotVisible = hidden.isLaunchVisible('beta') === false;

  // --- minAppVersion ----------------------------------------------------
  const gated = HSKUtil.createPackRegistry(cat([
    mk(), sec({ minAppVersion: '2.0.0' })]));
  R.versionGatedOut = gated.getLaunchVisiblePackIds('1.5.0').join(',') === 'alpha';
  R.versionGatedIn = gated.getLaunchVisiblePackIds('2.0.0').sort().join(',') === 'alpha,beta';
  R.versionNewer = gated.getLaunchVisiblePackIds('2.1.3').sort().join(',') === 'alpha,beta';
  R.compatibleFalse = gated.isCompatible('beta', '1.0.0') === false;
  R.compatibleTrue = gated.isCompatible('beta', '3.0.0') === true;
  R.noVersionRequired = gated.isCompatible('alpha', undefined) === true;
  R.badMinVersion = rej(cat([mk({ minAppVersion: 'v2' })]));
  R.cmp = HSKUtil.createPackRegistry(cat()).compareVersions('1.10.0', '1.9.0') === 1;

  // --- default selection ------------------------------------------------
  const dflt = HSKUtil.createPackRegistry(cat([sec(), mk()]));
  R.defaultLowestRange = dflt.getDefaultPackId() === 'alpha';
  R.defaultDeterministic = dflt.getDefaultPackId() === dflt.getDefaultPackId();
  const explicit = HSKUtil.createPackRegistry(cat([mk(), sec()], { defaultPackId: 'beta' }));
  R.explicitDefault = explicit.getDefaultPackId() === 'beta';
  R.badDefault = rej(cat([mk()], { defaultPackId: 'nope' }));
  R.hiddenDefault = rej(cat([
    mk({ status: 'draft', launch: { visible: false, readiness: 'internal' } })],
    { defaultPackId: 'alpha' }));
  const allHidden = HSKUtil.createPackRegistry(cat([
    mk({ status: 'draft', launch: { visible: false, readiness: 'internal' } })]));
  R.noDefaultWhenAllHidden = allHidden.getDefaultPackId() === null;

  // --- levels -----------------------------------------------------------
  R.duplicateDeck = rej(cat([mk({ levels: [{ deckId: 'A', order: 1 }, { deckId: 'A', order: 2 }] })]));
  R.badLevelOrder = rej(cat([mk({ levels: [{ deckId: 'A', order: 'x' }] })]));
  R.goodLevels = !rej(cat([mk({ levels: [{ deckId: 'A', order: 1 }] })]));

  // --- language / audio -------------------------------------------------
  R.badTarget = rej(cat([mk({ languageProfile: { target: 'zh_CN' } })]));
  R.missingLanguageProfile = rej(cat([mk({ languageProfile: undefined })]));
  R.badScript = rej(cat([mk({ languageProfile: { target: 'en', script: 'latin' } })]));
  R.badDirection = rej(cat([mk({ languageProfile: { target: 'en', direction: 'up' } })]));
  R.badAudioLocale = rej(cat([mk({ audio: { locale: 'en_US' } })]));
  R.goodAudio = !rej(cat([mk({ audio: { locale: 'en-US', fallbackLocales: ['en'] } })]));

  // --- copy semantics ---------------------------------------------------
  const src = cat([mk({ levels: [{ deckId: 'A', order: 1 }] })]);
  const reg = HSKUtil.createPackRegistry(src);
  const got = reg.getPack('alpha');
  got.title = 'MUTATED';
  got.idRange.min = 999;
  got.levels[0].deckId = 'MUTATED';
  const again = reg.getPack('alpha');
  R.copyIsolatesTitle = again.title === 'Alpha';
  R.copyIsolatesNested = again.idRange.min === 1;
  R.copyIsolatesArrays = again.levels[0].deckId === 'A';
  R.packIdsCopy = (function () { const a = reg.getPackIds(); a.push('x');
                                 return reg.getPackIds().length === 1; })();
  src.packs[0].title = 'CATALOG MUTATED AFTER CONSTRUCTION';
  R.detachedFromSource = reg.getPack('alpha').title === 'Alpha';

  return R;
}
"""


def main():
    fails = []

    def check(name, cond):
        if not cond:
            fails.append(name)

    errs = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context()
        ctx.route("**/supabase-config.js", lambda r: r.fulfill(
            status=200, content_type="application/javascript", body=EMPTY))
        pg = ctx.new_page()
        pg.on("pageerror", lambda e: errs.append("pageerror: %s" % e))
        pg.on("console", lambda m: errs.append("console: %s" % m.text)
              if m.type == "error" else None)
        pg.goto(URL)
        pg.wait_for_timeout(300)

        # Injected, not loaded from index.html: Phase 24E-A adds no production
        # call site, so the module must be provably absent from the page until
        # a test puts it there.
        pre = pg.evaluate("() => typeof window.HSKUtil.createPackRegistry")
        check("registry is NOT loaded by production index.html", pre == "undefined")

        pg.add_script_tag(path=REGISTRY_JS)
        pg.add_script_tag(content=HARNESS)
        result = pg.evaluate(PROBE)
        browser.close()

    for name in sorted(result):
        check(name, result[name] is True)
    if errs:
        fails.append("page errors: %s" % errs[:3])

    return emit("pack_registry", fails, {"checks": len(result)})


if __name__ == "__main__":
    sys.exit(main())
