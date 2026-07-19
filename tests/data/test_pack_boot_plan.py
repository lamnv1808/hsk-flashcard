#!/usr/bin/env python3
"""Phase 24E-A - planPackBoot purity and determinism (foundation only).

The boot planner decides which single pack a page load should use. Two of its
guarantees are data-safety guarantees rather than UX ones, and are asserted
hardest here:

  * it never returns an empty pack -- a boot with no cards must surface as an
    explicit error, not as a silently empty app;
  * it never returns a mixed plan -- exactly one pack's two scripts, in a fixed
    order, so no page can ever hold two packs' cards at once.

Purity is asserted directly: the planner is called with localStorage, fetch,
document.write and XMLHttpRequest replaced by traps that record any use.
"""

import os
import sys

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "tests", "support"))

from datajs import emit  # noqa: E402

URL = os.environ.get("HSK_BASE_URL", "http://localhost:8000") + "/hsk_flashcard_app/"
EMPTY = 'window.SUPABASE_CONFIG={url:"",anonKey:""};'
CORE = os.path.join(ROOT, "hsk_flashcard_app", "core", "content")
REGISTRY_JS = os.path.join(CORE, "pack-registry.js")
BOOT_JS = os.path.join(CORE, "pack-boot.js")

HARNESS = """
window.__pack = function (over) {
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
window.__beta = function (over) {
  return window.__pack(Object.assign({
    packId: 'beta', courseId: 'beta', title: 'Beta',
    idRange: { min: 1000000, max: 1999999 },
    allocated: { min: 1000000, max: 1000005, count: 6, gaps: 0 },
    manifestPath: 'packs/beta/beta-content-pack.js',
    cardsPath: 'packs/beta/beta-cards.js'
  }, over || {}));
};
window.__reg = function (packs, extra) {
  const c = { schemaVersion: 1, packs: packs };
  Object.assign(c, extra || {});
  return HSKUtil.createPackRegistry(c);
};
"""

PROBE = """
() => {
  const P = HSKUtil.planPackBoot, S = HSKUtil.serializePackBootPlan;
  const REASON = HSKUtil.packBootReasons, ERR = HSKUtil.packBootErrors;
  const pack = window.__pack, beta = window.__beta, reg = window.__reg;
  const R = {};

  const two = reg([pack(), beta()]);

  // --- happy paths ------------------------------------------------------
  const requested = P({ registry: two, requestedPackId: 'beta' });
  R.requestedWins = requested.ok && requested.packId === 'beta';
  R.requestedReason = requested.reason === REASON.REQUESTED;
  R.requestedNoFallback = requested.fallbackFrom === null;

  const first = P({ registry: two, requestedPackId: null });
  R.firstRunDefault = first.ok && first.packId === 'alpha';
  R.firstRunReason = first.reason === REASON.FIRST_RUN;
  R.undefinedIsFirstRun = P({ registry: two }).reason === REASON.FIRST_RUN;
  R.emptyStringIsFirstRun =
    P({ registry: two, requestedPackId: '' }).reason === REASON.FIRST_RUN;

  // --- exactly one pack, fixed order -----------------------------------
  R.exactlyTwoScripts = requested.scripts.length === 2;
  R.manifestBeforeCards =
    requested.scripts[0] === 'packs/beta/beta-content-pack.js' &&
    requested.scripts[1] === 'packs/beta/beta-cards.js';
  R.noMixedPack = requested.scripts.every(s => s.indexOf('/beta/') >= 0);
  R.idRangeMatchesPack = requested.idRange.min === 1000000;
  R.expectedChecksums =
    requested.expected.contentChecksum.indexOf('sha256:') === 0 &&
    requested.expected.packId === 'beta';
  R.neverEmptyScripts = [requested, first].every(p => p.scripts.length === 2);

  // --- fallbacks --------------------------------------------------------
  const unknown = P({ registry: two, requestedPackId: 'gamma' });
  R.unknownFallsBack = unknown.ok && unknown.packId === 'alpha';
  R.unknownReason = unknown.reason === REASON.UNKNOWN;
  R.unknownRecordsRequest = unknown.requestedPackId === 'gamma' &&
                            unknown.fallbackFrom === 'gamma';

  const malformed = ['../evil', 'ALPHA', 'a b', 'a/b', '../../x', 'a.b'];
  R.malformedFallsBack = malformed.every(function (bad) {
    const p = P({ registry: two, requestedPackId: bad });
    return p.ok && p.packId === 'alpha' && p.reason === REASON.MALFORMED;
  });
  R.nonStringFallsBack = [42, {}, [], true].every(function (bad) {
    const p = P({ registry: two, requestedPackId: bad });
    return p.ok && p.reason === REASON.MALFORMED;
  });
  // A malformed request must never reach the script list.
  R.malformedNeverInPath = (function () {
    const p = P({ registry: two, requestedPackId: '../../etc/passwd' });
    return p.scripts.every(s => s.indexOf('..') < 0 && s.indexOf('passwd') < 0);
  })();

  const withHidden = reg([pack(), beta({
    status: 'draft', launch: { visible: false, readiness: 'internal' } })]);
  const hidden = P({ registry: withHidden, requestedPackId: 'beta' });
  R.hiddenFallsBack = hidden.ok && hidden.packId === 'alpha';
  R.hiddenReason = hidden.reason === REASON.HIDDEN;

  const gated = reg([pack(), beta({ minAppVersion: '9.0.0' })]);
  const incompatible = P({ registry: gated, requestedPackId: 'beta',
                           appVersion: '1.0.0' });
  R.incompatibleFallsBack = incompatible.ok && incompatible.packId === 'alpha';
  R.incompatibleReason = incompatible.reason === REASON.INCOMPATIBLE;
  R.compatibleAgainWhenNewer =
    P({ registry: gated, requestedPackId: 'beta', appVersion: '9.1.0' }).packId === 'beta';

  // --- no valid pack ----------------------------------------------------
  const allHidden = reg([pack({
    status: 'draft', launch: { visible: false, readiness: 'internal' } })]);
  const none = P({ registry: allHidden, requestedPackId: null });
  R.noPackIsError = none.ok === false;
  R.noPackErrorCode = none.error.code === ERR.NO_LAUNCH_VISIBLE_PACK;
  R.noPackEmptyScripts = none.scripts.length === 0;
  R.noPackNullId = none.packId === null;
  const noneRequested = P({ registry: allHidden, requestedPackId: 'alpha' });
  R.noPackEvenWhenRequested = noneRequested.ok === false;

  const noReg = P({ requestedPackId: 'alpha' });
  R.missingRegistryIsError = noReg.ok === false &&
                             noReg.error.code === ERR.NO_REGISTRY;
  R.missingRegistryDoesNotThrow = true;   // reaching here proves it

  // --- determinism ------------------------------------------------------
  R.deterministicSerialization =
    S(P({ registry: two, requestedPackId: 'beta' })) ===
    S(P({ registry: two, requestedPackId: 'beta' }));
  R.serializationStable = S(requested).indexOf('"packId":"beta"') > 0;
  R.differentInputsDiffer = S(requested) !== S(first);

  // --- purity: no DOM, storage, network or document.write ---------------
  const touched = [];
  const realWrite = document.write;
  const realFetch = window.fetch;
  const realXHR = window.XMLHttpRequest;
  const realGet = Storage.prototype.getItem;
  const realSet = Storage.prototype.setItem;
  document.write = function () { touched.push('document.write'); };
  window.fetch = function () { touched.push('fetch'); return realFetch.apply(this, arguments); };
  window.XMLHttpRequest = function () { touched.push('XMLHttpRequest'); };
  Storage.prototype.getItem = function () { touched.push('localStorage.getItem'); return null; };
  Storage.prototype.setItem = function () { touched.push('localStorage.setItem'); };
  const before = document.documentElement.outerHTML.length;
  try {
    P({ registry: two, requestedPackId: 'beta' });
    P({ registry: two, requestedPackId: null });
    P({ registry: two, requestedPackId: '../evil' });
    P({ registry: allHidden, requestedPackId: 'alpha' });
  } finally {
    document.write = realWrite;
    window.fetch = realFetch;
    window.XMLHttpRequest = realXHR;
    Storage.prototype.getItem = realGet;
    Storage.prototype.setItem = realSet;
  }
  R.noSideEffects = touched.length === 0;
  R.domUnchanged = document.documentElement.outerHTML.length === before;

  // --- the plan is a copy, not a view -----------------------------------
  const plan = P({ registry: two, requestedPackId: 'beta' });
  plan.idRange.min = -1;
  plan.scripts.push('packs/evil/evil.js');
  const fresh = P({ registry: two, requestedPackId: 'beta' });
  R.planIsolated = fresh.idRange.min === 1000000 && fresh.scripts.length === 2;

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

        pre = pg.evaluate("() => typeof window.HSKUtil.planPackBoot")
        check("boot planner IS loaded by production index.html",
              pre == "function")

        pg.add_script_tag(path=REGISTRY_JS)
        pg.add_script_tag(path=BOOT_JS)
        pg.add_script_tag(content=HARNESS)
        result = pg.evaluate(PROBE)
        browser.close()

    for name in sorted(result):
        check(name, result[name] is True)
    if errs:
        fails.append("page errors: %s" % errs[:3])

    return emit("pack_boot_plan", fails, {"checks": len(result)})


if __name__ == "__main__":
    sys.exit(main())
