#!/usr/bin/env python3
"""Phase 24F: the IELTS/TOEIC content intake templates stay honest and inert.

The templates are scaffolding a human fills in. Two things can go wrong and both
are silent, so both are asserted here:

  1. DRIFT -- the templates stop matching scripts/contentpack/schema.py, so an
     operator fills in a shape the pipeline will reject. Headers and reserved id
     ranges are therefore derived FROM the schema module, never re-typed.
  2. FABRICATION -- a placeholder that looks like real content or real
     provenance gets committed. An invented publisher or licence is a false
     legal claim; an invented word is course content FlashEdu did not author.
     So the templates must contain zero data rows and zero provenance values.

They must also be impossible to build or promote by accident: `.template.csv`
is not a filename the pipeline ever reads, and every template declares
draft/internal/not-visible.
"""

import csv
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, os.path.join(ROOT, "tests", "support"))

from contentpack import schema                    # noqa: E402
from datajs import emit                           # noqa: E402

TEMPLATES = os.path.join(ROOT, "docs", "content", "templates")
GUIDE = os.path.join(ROOT, "docs", "content", "PHASE_24F_CONTENT_INTAKE.md")
APP = os.path.join(ROOT, "hsk_flashcard_app")

COURSES = ("ielts", "toeic")

# Anything that would make a template look like a shipped, launchable course.
FORBIDDEN_STATUS = {"status": "draft",
                    "launch.visible": "false",
                    "launch.readiness": "internal"}


def read_rows(path):
    with io.open(path, encoding="utf-8", newline="") as fh:
        return list(csv.reader(fh))


def manifest_map(path):
    rows = read_rows(path)
    return {r[0]: (r[1] if len(r) > 1 else "") for r in rows[1:] if r}


def main():
    fails = []

    def check(name, cond):
        if not cond:
            fails.append(name)

    # ---- the kit exists where the docs say it does ------------------------
    check("intake guide exists", os.path.isfile(GUIDE))
    check("templates README exists",
          os.path.isfile(os.path.join(TEMPLATES, "README.md")))

    for course in COURSES:
        d = os.path.join(TEMPLATES, course)
        man_p = os.path.join(d, "manifest.template.csv")
        lvl_p = os.path.join(d, "levels.template.csv")
        crd_p = os.path.join(d, "cards.template.csv")
        for label, p in (("manifest", man_p), ("levels", lvl_p), ("cards", crd_p)):
            check("%s: %s template exists" % (course, label), os.path.isfile(p))
        if not all(os.path.isfile(p) for p in (man_p, lvl_p, crd_p)):
            continue

        # ---- headers are derived from the schema, not re-typed ------------
        cards = read_rows(crd_p)
        check("%s: cards header matches schema.ALL_CARD_COLUMNS" % course,
              tuple(cards[0]) == schema.ALL_CARD_COLUMNS)
        for role in schema.REQUIRED_CARD_ROLES + (schema.SOURCE_KEY_COLUMN,):
            check("%s: cards header carries required '%s'" % (course, role),
                  role in cards[0])

        levels = read_rows(lvl_p)
        check("%s: levels header matches schema.ALL_LEVEL_COLUMNS" % course,
              tuple(levels[0]) == schema.ALL_LEVEL_COLUMNS)

        # ---- no authored content whatsoever -------------------------------
        check("%s: cards template has ZERO data rows" % course,
              len([r for r in cards[1:] if any(c.strip() for c in r)]) == 0)
        check("%s: levels template has ZERO data rows" % course,
              len([r for r in levels[1:] if any(c.strip() for c in r)]) == 0)

        # ---- manifest: keys are all schema-allowed ------------------------
        man = manifest_map(man_p)
        unknown = [k for k in man if k not in schema.MANIFEST_ALLOWED]
        check("%s: manifest declares no unknown key (%s)" % (course, unknown),
              unknown == [])
        missing = [k for k in schema.MANIFEST_REQUIRED if k not in man]
        check("%s: manifest carries every required key (%s)" % (course, missing),
              missing == [])
        computed = [k for k in man if k in schema.MANIFEST_TOOL_COMPUTED]
        check("%s: manifest supplies no tool-computed key (%s)" % (course, computed),
              computed == [])

        # ---- frozen identity ---------------------------------------------
        check("%s: packId is the course id" % course, man.get("packId") == course)
        check("%s: courseId is the course id" % course, man.get("courseId") == course)
        check("%s: courseType is exam" % course, man.get("courseType") == "exam")

        lo, hi = schema.RESERVED_RANGES[course]
        check("%s: idRange.min is the reserved %d" % (course, lo),
              man.get("idRange.min") == str(lo))
        check("%s: idRange.max is the reserved %d" % (course, hi),
              man.get("idRange.max") == str(hi))

        # ---- cannot claim launch ------------------------------------------
        for key, want in FORBIDDEN_STATUS.items():
            check("%s: %s is %s" % (course, key, want), man.get(key) == want)

        # ---- provenance is EMPTY, never invented --------------------------
        for key in schema.PROVENANCE_REQUIRED:
            check("%s: provenance '%s' is present but empty" % (course, key),
                  key in man and man[key].strip() == "")

    # ---- the kit cannot be consumed by the pipeline -----------------------
    consumable = []
    for base, _dirs, files in os.walk(TEMPLATES):
        for name in files:
            if name in ("manifest.csv", "cards.csv", "levels.csv"):
                consumable.append(os.path.join(base, name))
    check("no template is named like a real source file", consumable == [])

    # ---- the kit lives outside the runtime and outside source_data --------
    real = os.path.realpath(TEMPLATES)
    check("templates are not inside hsk_flashcard_app",
          not real.startswith(os.path.realpath(APP) + os.sep))
    check("templates are not inside source_data",
          not real.startswith(os.path.realpath(os.path.join(ROOT, "source_data")) + os.sep))

    # ---- no template leaked into the runtime or the catalog ---------------
    catalog_path = os.path.join(APP, "packs", "catalog.js")
    if os.path.isfile(catalog_path):
        with io.open(catalog_path, encoding="utf-8") as fh:
            catalog_text = fh.read()
        for course in COURSES:
            check("catalog still offers no %s pack" % course,
                  ('"packId":"%s"' % course) not in catalog_text)
    packs_dir = os.path.join(APP, "packs")
    entries = sorted(os.listdir(packs_dir)) if os.path.isdir(packs_dir) else []
    check("no course was promoted into the runtime",
          entries == ["catalog.js", "hsk"])

    # ---- still no real source dataset ------------------------------------
    src = os.path.join(ROOT, "source_data")
    listing = sorted(os.listdir(src)) if os.path.isdir(src) else []
    check("source_data still holds only the HSK workbook",
          listing == ["HSK1-HSK6.xlsx"])

    return emit("content_intake_templates", fails)


if __name__ == "__main__":
    sys.exit(main())
