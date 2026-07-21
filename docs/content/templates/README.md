# Content Intake Templates

Copy a template folder, fill it in, and hand it to the build pipeline. These
files are **empty scaffolding**: they carry the correct headers and the frozen
identity facts, and deliberately contain **no vocabulary, definitions, examples,
translations, decks or questions**. FlashEdu does not author or generate course
content — a human supplies properly licensed material.

```
docs/content/templates/
  ielts/  ielts-intake.template.xlsx   <- easiest: one workbook, three tabs
          manifest.template.csv  levels.template.csv  cards.template.csv
  toeic/  toeic-intake.template.xlsx
          manifest.template.csv  levels.template.csv  cards.template.csv
```

**Pick ONE of two ways to deliver a course** - the pipeline accepts either:

- **Excel (recommended):** fill `<course>-intake.template.xlsx`. One file, three
  tabs (`manifest`, `cards`, `levels`), already formatted as Text.
- **CSV:** fill the three `.template.csv` files.

Do not send both for the same course.

## Why `.template.csv`

The build pipeline looks for `manifest.csv`, `levels.csv` and `cards.csv`. The
`.template.` infix means this directory can never be consumed by accident, and
an unfilled template can never be built or promoted. **Copy and rename** — do
not point the builder at `docs/`.

```
mkdir -p source_data/ielts
cp docs/content/templates/ielts/manifest.template.csv source_data/ielts/manifest.csv
cp docs/content/templates/ielts/levels.template.csv   source_data/ielts/levels.csv
cp docs/content/templates/ielts/cards.template.csv    source_data/ielts/cards.csv
```

## What is already correct — do not change

| Field | IELTS | TOEIC | Why |
|---|---|---|---|
| `packId` / `courseId` | `ielts` | `toeic` | frozen identity |
| `courseType` | `exam` | `exam` | both are exam courses |
| `idRange.min` | `1000000` | `2000000` | reserved block (`schema.py RESERVED_RANGES`) |
| `idRange.max` | `1999999` | `2999999` | reserved block |
| `status` | `draft` | `draft` | nothing launches until certified |
| `launch.visible` | `false` | `false` | never offered to learners while draft |
| `launch.readiness` | `internal` | `internal` | never offered to learners while draft |

Card ids are **assigned by the tool** inside the reserved range. Never write an
`id` column; never reuse another course's range.

## What you must supply

`manifest.csv` — `title`, and (before launch) truthful `publisher`,
`source.origin`, `source.license`, `source.url`. Leave a field **empty rather
than guessing**: an empty field blocks launch certification, an invented one is
a lie that ships.

`levels.csv` — one row per deck: `deckId`, `order`, optional `title`,
`description`.

`cards.csv` — one row per card. Required: `sourceKey`, `deck`, `primaryPrompt`,
`definition`. Optional: `pronunciation`, `exampleText`, `examplePronunciation`,
`exampleTranslation`, `tags`, `notes`. Delete optional columns you do not use;
do not add columns the schema does not define.

`deck` must match a `deckId` in `levels.csv`. `sourceKey` is **yours and
permanent** — it is how a card keeps its id across rebuilds. Never renumber or
recycle a `sourceKey`.

## Rules the pipeline enforces

UTF-8; exact header spelling; no duplicate or unknown columns; no formulas,
merged cells or hidden rows in XLSX; no author-supplied `sourceChecksum`,
`contentChecksum`, `generatedAt`, `cardCount`, `fieldRoles` or `levels` (all
tool-computed); max 20,000 rows and 4,000 characters per field.

See `docs/content/PHASE_24F_CONTENT_INTAKE.md` for the full walkthrough and the
exact build/QA command order.
