# Phase 24F — Content Intake Kit (IELTS + TOEIC)

This is the operator guide for getting **human-authored or properly licensed**
IELTS and TOEIC vocabulary into FlashEdu.

**FlashEdu does not write course content and does not generate it with AI.** The
app is the memory layer; the words, definitions and examples come from a source
you own or are licensed to use. Nothing in this kit contains educational
content, and no IELTS or TOEIC source dataset exists in this repository yet.

The templates live in `docs/content/templates/`. See that folder's `README.md`
for the short version; this document is the full walkthrough.

## 1. What you hand over

One folder per course, containing three files:

```
source_data/ielts/
  manifest.csv    identity + provenance      (key,value)
  levels.csv      the decks                  (deckId,order,title,description)
  cards.csv       the cards                  (one row per card)
```

**Or one Excel workbook** with three sheets named exactly `manifest`, `cards`
and `levels`. `manifest` and `cards` are required; `levels` is optional but
strongly recommended so decks get real titles.

A ready-made, pre-formatted workbook is provided per course:

```
docs/content/templates/ielts/ielts-intake.template.xlsx
docs/content/templates/toeic/toeic-intake.template.xlsx
```

Deliver **either** a filled workbook **or** the three renamed CSVs for a course
-- not both. The workbook is usually easier: it is one file, the tabs and
headers already exist, and every cell is pre-formatted as Text.

Everything must be **UTF-8**. Headers must match exactly — the pipeline binds
columns by name and a duplicate or unknown header is a fatal error, so a typo
like `licence` or `packid` fails loudly instead of silently doing nothing.

## 2. Copy the template, do not edit it in place

The build pipeline looks for `manifest.csv` / `levels.csv` / `cards.csv`. The
kit ships `*.template.csv`, so it can never be consumed by accident:

```
mkdir -p source_data/ielts
cp docs/content/templates/ielts/manifest.template.csv source_data/ielts/manifest.csv
cp docs/content/templates/ielts/levels.template.csv   source_data/ielts/levels.csv
cp docs/content/templates/ielts/cards.template.csv    source_data/ielts/cards.csv
```

(Use `toeic` for TOEIC. On Windows PowerShell use `Copy-Item` instead of `cp`.)

## 2b. Filling the Excel workbook

1. Copy it out of `docs/` and rename it, e.g.
   `source_data/ielts/ielts.xlsx`. Never fill the file in `docs/`.
2. Fill the `manifest` tab: `title`, then the provenance block when you know it.
   Leave the pre-filled identity rows alone.
3. Fill `levels`: one row per deck.
4. Fill `cards`: one row per card. Delete whole optional COLUMNS you do not use.
5. Save as `.xlsx` (not `.xls`, not `.xlsm`, not CSV).

### Excel will try to "help" - do not let it

Every cell in the template is pre-formatted as **Text** for a reason. If a cell
is switched back to General, Excel silently rewrites what you typed and the
strict reader then rejects the file or, worse, imports the wrong value:

| You type | Excel stores as General | Consequence |
|---|---|---|
| `1000000` | the number 1000000 | manifest value is no longer a string |
| `007` | `7` | a `sourceKey` silently changes identity |
| `03-14` | a date | a deck code becomes a date |
| `=SUM(...)` | a formula | **fatal** - formulas are rejected outright |

Rules:

- keep the cells formatted as **Text**; paste with *Paste Special -> Values* or
  *Match Destination Formatting*, never a plain paste of styled content
- **no formulas anywhere** - a cached formula result depends on whoever last
  recalculated the workbook, so the importer refuses them
- no merged cells, no hidden rows, no hidden columns, no hidden sheets
- do not rename, reorder or delete the three tabs
- do not add extra tabs, macros, comments, images or links to other workbooks
- do not add an `id` column

If Excel reformats something, set the range back to Text and re-enter the value.

## 3. Reserved id ranges — already set, never change

Card ids are one **global integer namespace** shared by every course, because
they are the join key for a learner's progress rows. Overlap would silently mix
two courses' progress. The blocks are frozen in
`scripts/contentpack/schema.py` (`RESERVED_RANGES`):

| Course | Range |
|---|---|
| HSK | 1 - 999,999 |
| **IELTS** | **1,000,000 - 1,999,999** |
| **TOEIC** | **2,000,000 - 2,999,999** |
| JLPT | 3,000,000 - 3,999,999 |
| TOPIK | 4,000,000 - 4,999,999 |

**The tool assigns the ids.** Never add an `id` column, never hand-number cards,
never borrow another course's range.

## 4. `manifest.csv`

Two columns, `key,value`. The template already carries every fixed fact.

Already correct — leave alone: `schemaVersion`, `packId`, `courseId`,
`courseType`, `idRange.min`, `idRange.max`, `status`, `launch.visible`,
`launch.readiness`.

You fill in: `title` (and `shortTitle`, `description` if you want them), the
language profile if the defaults are wrong, and the provenance block.

Never supply: `sourceChecksum`, `contentChecksum`, `generatedAt`, `cardCount`,
`fieldRoles`, `levels`. These are **tool-computed**, and an author-supplied
value is fatal — a hand-typed number that disagrees with reality is worse than
no number at all.

List-valued keys are comma-separated inside one quoted cell, for example
`audio.readFields,"primaryPrompt,exampleText"`.

## 5. `levels.csv`

| Column | Required | Meaning |
|---|---|---|
| `deckId` | yes | stable deck code, e.g. `BAND6`, `PART5` |
| `order` | yes | integer sort order |
| `title` | no | shown to learners |
| `description` | no | optional blurb |

Every `deck` value in `cards.csv` must match a `deckId` here.

## 6. `cards.csv`

| Column | Required | Notes |
|---|---|---|
| `sourceKey` | **yes** | your permanent per-card key |
| `deck` | **yes** | must match a `deckId` |
| `primaryPrompt` | **yes** | the word/phrase being learned |
| `definition` | **yes** | the meaning |
| `pronunciation` | no | omit if the course has none |
| `exampleText` | no | example sentence |
| `examplePronunciation` | no | |
| `exampleTranslation` | no | |
| `tags` | no | comma-separated |
| `notes` | no | authoring notes; never shipped to learners |

Delete optional columns you do not use. Do not invent columns.

### `sourceKey` is the one thing you must never break

`sourceKey` is **author-owned and permanent**. It is how a card keeps the same
card id across every future rebuild, which is how a learner keeps their progress
on that card. Rules:

- unique within the course
- stable forever — never renumber, never recycle a retired key
- allowed shape: letters, digits, and `. _ : -`, up to 64 characters

Changing a `sourceKey` is not an edit: it retires one card and creates a new one
with fresh progress. Edit the text fields instead.

## 7. Provenance — required before launch, never invented

Four fields gate launch certification (`schema.py PROVENANCE_REQUIRED`):

- `publisher`
- `source.origin`
- `source.license`
- `source.url`

**Leave a field empty if you do not know it.** Empty blocks certification, which
is a safe and visible stop. A guessed publisher or an assumed licence is a false
legal claim that would ship to users and to app-store reviewers. Unknown
provenance must stay unknown.

## 8. Why draft content can build but cannot launch

A pack with `status=draft`, `launch.visible=false` and
`launch.readiness=internal` builds and can be QA'd, so you can iterate long
before anything is certified. But it is **not launch-eligible**, so:

- promotion refuses it unless you pass `--allow-draft` (test/staging roots only)
- the catalog will not mark it launch-visible
- the course picker only ever renders launch-visible packs

That is the safety property: **an unfinished or unlicensed course cannot appear
to a learner**, and there is no "coming soon" placeholder. A course becomes real
only when a human flips it to launch after the content and provenance review.

## 9. Formatting rules the pipeline enforces

- UTF-8 encoding
- exact header spelling; duplicate or unknown headers are fatal
- **no formulas** in XLSX (a cached formula result depends on whoever last
  recalculated the workbook — supply literal values)
- no merged cells, no hidden rows
- max 20,000 rows per source, 64 MB per file, 4,000 characters per field
- no `id` column, and no tool-computed manifest keys

## 10. Command order for a real ingestion

Run from the repository root. Nothing here touches the running app.

```bash
# 1. QA only - parse, validate and report. Writes no pack.
python scripts/build_content_pack.py --pack ielts \
  --source source_data/ielts --output build/content-packs/ielts --qa-only

# 2. First real build for a NEW pack - creates the id ledger.
python scripts/build_content_pack.py --pack ielts \
  --source source_data/ielts --output build/content-packs/ielts --init-ledger

# 3. Later builds: omit --init-ledger so existing ids are reused.
python scripts/build_content_pack.py --pack ielts \
  --source source_data/ielts --output build/content-packs/ielts

# 4. Prove the build is reproducible byte-for-byte.
python scripts/build_content_pack.py --pack ielts \
  --source source_data/ielts --output build/content-packs/ielts \
  --verify-deterministic

# 5. Dry-run promotion into the app root (reports drift, writes nothing).
python scripts/promote_content_pack.py --pack ielts \
  --app-root hsk_flashcard_app --check

# 6. Promote. A draft pack requires --allow-draft and must NOT be used for a
#    real launch root.
python scripts/promote_content_pack.py --pack ielts --app-root hsk_flashcard_app
```

`--init-ledger` is for a brand-new pack only. Re-running it on an established
pack would re-assign ids and orphan every learner's progress.

## 11. Human checkpoints — not automatable

| Before | A human must confirm |
|---|---|
| first build | the source is authored or licensed for this use |
| QA sign-off | definitions and examples are pedagogically correct |
| provenance sign-off | publisher, origin, licence and URL are **true** |
| flipping to launch | the course is complete enough to be worth a learner's time |
| store submission | the licence permits commercial distribution |

The pipeline verifies structure, determinism and identity. It cannot verify that
a definition is correct or that a licence is real. Those are founder decisions.

## 12. Current status

- Templates: ready
- Real IELTS content: **not started** — no source dataset exists
- Real TOEIC content: **not started** — no source dataset exists
- Blocker: a human-authored or licensed source file plus truthful provenance

Until those arrive, HSK remains the only launch-visible course, and the course
picker correctly shows no chooser at all.
