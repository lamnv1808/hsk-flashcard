#!/usr/bin/env python3
"""Phase 24E-A - proof that the foundation has ZERO production runtime effect.

Phase 24E was split precisely so the registry, boot planner, catalog generator
and promotion tool could be built and proven without touching the running app.
That claim is only worth anything if it is enforced, so this suite is the
enforcement: the new modules must not be referenced by index.html, must not be
precached, must not change the service worker, and no synthetic fixture content
may appear anywhere in the shipped application.

If Phase 24E-B ever lands, THIS is the suite that must be deliberately updated
alongside it -- it failing is the intended signal that integration happened.
"""

import hashlib
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "tests", "support"))

from datajs import emit  # noqa: E402

APP = os.path.join(ROOT, "hsk_flashcard_app")

FOUNDATION_JS = ("core/content/pack-registry.js", "core/content/pack-boot.js")

DATA_JS_SHA256 = "d0b0a279228d86caf7dbe14c757502311ec90e22f3d8a7c14a978c056be42377"
EXPECTED_CACHE = "hsk-flashcards-v36"
EXPECTED_ASSET_COUNT = 36

# Fixture identifiers that must never reach the shipped app.
# Phase 24E-B: FLASHEDU_CATALOG was removed from this list. In Phase 24E-A the
# catalog global was proof that the unwired foundation had leaked into
# production; from 24E-B it IS the production runtime catalog. The synthetic
# fixture guards below are unchanged -- no test/synthetic pack content ships.
SYNTHETIC_MARKERS = ("synth-en", "SynthEN", "Synthetic English")

# Launch options that must not appear until real, validated content exists
# (Phase 24F). A "coming soon" option is a product lie, so it fails here.
UNSHIPPED_COURSE_MARKERS = ("ielts", "toeic", "jlpt", "topik")


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def sha256_file(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def main():
    fails = []

    def check(name, cond):
        if not cond:
            fails.append(name)

    index_html = read(os.path.join(APP, "index.html"))
    sw = read(os.path.join(APP, "sw.js"))

    # --- the foundation modules exist but are not wired in ----------------
    for rel in FOUNDATION_JS:
        path = os.path.join(APP, rel.replace("/", os.sep))
        check("foundation module exists: %s" % rel, os.path.isfile(path))
        check("%s is NOT referenced by index.html" % rel, rel not in index_html)
        check("%s is NOT in the service-worker precache" % rel, rel not in sw)

    # A bare filename check too, in case a future edit uses a different prefix.
    for rel in FOUNDATION_JS:
        base = os.path.basename(rel)
        check("%s does not appear in index.html by name" % base,
              base not in index_html)
        check("%s does not appear in sw.js by name" % base, base not in sw)

    # --- no production code imports them ----------------------------------
    referenced_by = []
    for base, _dirs, files in os.walk(APP):
        for name in files:
            if not name.endswith(".js") or name in ("pack-registry.js", "pack-boot.js"):
                continue
            text = read(os.path.join(base, name))
            if "createPackRegistry" in text or "planPackBoot" in text:
                referenced_by.append(name)
    check("no production script calls the foundation API", referenced_by == [])

    # --- service worker is untouched ---------------------------------------
    version = re.search(r"const\s+CACHE\s*=\s*'([^']+)'", sw)
    check("service-worker cache constant is present", version is not None)
    check("service worker is still %s" % EXPECTED_CACHE,
          version and version.group(1) == EXPECTED_CACHE)

    assets = re.search(r"\bASSETS\s*=\s*(\[.*?\])", sw, re.S)
    check("ASSETS array is parseable", assets is not None)
    if assets:
        import ast
        items = ast.literal_eval(assets.group(1))
        check("precache inventory is still exactly %d assets" % EXPECTED_ASSET_COUNT,
              len(items) == EXPECTED_ASSET_COUNT)
        check("no foundation module is precached",
              not any("pack-registry" in i or "pack-boot" in i for i in items))
        check("no catalog is precached", not any("catalog" in i for i in items))

    # --- HSK runtime invariants --------------------------------------------
    data_js = os.path.join(APP, "data.js")
    check("data.js is byte-identical", sha256_file(data_js) == DATA_JS_SHA256)
    check("data.js size is unchanged", os.path.getsize(data_js) == 1263402)

    # --- no synthetic fixture content in the shipped app --------------------
    leaks = []
    for base, _dirs, files in os.walk(APP):
        for name in files:
            if not name.endswith((".js", ".html", ".css", ".webmanifest")):
                continue
            path = os.path.join(base, name)
            try:
                text = read(path)
            except (OSError, UnicodeDecodeError):
                continue
            for marker in SYNTHETIC_MARKERS:
                if marker in text:
                    leaks.append("%s in %s" % (marker, name))
    check("no synthetic fixture identifier appears in the shipped app",
          leaks == [])
    if leaks:
        fails.append("leaks: %s" % leaks[:5])

    # --- packs/ holds exactly the catalog and the HSK adapter ---------------
    # Phase 24E-B adds the production catalog. Anything BEYOND catalog.js and
    # hsk/ is still a failure: a stray synthetic pack, or an IELTS/TOEIC/JLPT/
    # TOPIK directory shipped before Phase 24F has real validated content.
    packs_dir = os.path.join(APP, "packs")
    entries = sorted(os.listdir(packs_dir)) if os.path.isdir(packs_dir) else []
    check("packs/ contains exactly catalog.js and the HSK adapter directory",
          entries == ["catalog.js", "hsk"])

    # --- the production catalog is present and HSK-only (Phase 24E-B) -------
    catalog_path = os.path.join(packs_dir, "catalog.js")
    check("packs/catalog.js exists", os.path.isfile(catalog_path))
    if os.path.isfile(catalog_path):
        catalog_src = read(catalog_path)
        check("catalog.js declares window.FLASHEDU_CATALOG",
              "window.FLASHEDU_CATALOG" in catalog_src)

        # Parse the assignment as data; never execute it.
        body = catalog_src[catalog_src.index("{", catalog_src.index(
            "window.FLASHEDU_CATALOG")):].rstrip()
        catalog = json.loads(body[:body.rindex("}") + 1])

        visible = [p for p in catalog.get("packs", [])
                   if p.get("launch", {}).get("visible") is True]
        check("catalog declares exactly one launch-visible pack",
              len(visible) == 1)
        check("the only launch-visible pack is hsk",
              [p["packId"] for p in visible] == ["hsk"])
        check("catalog references the legacy cards payload data.js",
              any(p.get("cardsPath") == "data.js" for p in visible))
        check("catalog references the legacy HSK adapter",
              any(p.get("manifestPath") == "packs/hsk/hsk-content-pack.js"
                  for p in visible))

        lowered = catalog_src.lower()
        check("catalog contains no synthetic fixture identifier",
              not any(m.lower() in lowered for m in SYNTHETIC_MARKERS))
        # No fake/"coming soon" launch options before Phase 24F.
        check("catalog offers no unshipped IELTS/TOEIC/JLPT/TOPIK option",
              not any(m in lowered for m in UNSHIPPED_COURSE_MARKERS))

    # --- release tooling is untouched ---------------------------------------
    checker = os.path.join(ROOT, "scripts", "release_check.py")
    checker_src = read(checker)
    check("release_check.py has no pack/catalog knowledge",
          "catalog" not in checker_src and "pack-registry" not in checker_src)
    pinned = read(os.path.join(ROOT, "tests", "tooling", "test_release_check.py"))
    check("the pinned service-worker literal is still v36",
          EXPECTED_CACHE in pinned)

    # --- the build tools cannot write into the app --------------------------
    emit_src = read(os.path.join(ROOT, "scripts", "contentpack", "emit.py"))
    check("the 24D pipeline still refuses to write inside the app",
          "must not write inside hsk_flashcard_app" in emit_src)

    return emit("pack_foundation_isolation", fails,
                {"swCache": EXPECTED_CACHE, "assets": EXPECTED_ASSET_COUNT})


if __name__ == "__main__":
    sys.exit(main())
