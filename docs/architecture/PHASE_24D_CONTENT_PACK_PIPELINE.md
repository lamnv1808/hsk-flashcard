# Phase 24D — Deterministic Excel/CSV → ContentPack v1 Pipeline

## Objective
Give the product team a deterministic, fail-closed, build-time path from an authored
spreadsheet to a strict ContentPack v1 pack, with stable card identity, reproducible
checksums, provenance gating and QA reports.

**Build-time tooling only.** No runtime asset, no service-worker change, no registry,
no pack loading, no onboarding, no content. Promotion into the runtime is Phase 24E;
content-quality acceptance is Phase 24F.

## Strategic fit
FA-004 (AI Constitution v1.1) Principle 2 — *Start Narrow, Build Reusable*. Milestone 1
ships one app with HSK, IELTS and TOEIC as three real study options, which requires a
repeatable way to ingest authored content without touching the learning engine. Principle 4
— *AI Reduces Effort, Not Noise* — is why this is a deterministic ingestion pipeline for
human-authored content, never a generator.

## What was built

```
scripts/build_content_pack.py      CLI, exit codes, ASCII-safe console output
scripts/contentpack/
    __init__.py    build-tool + CSI + ledger version constants
    findings.py    three severity classes, coordinates, accumulation
    normalize.py   Unicode policy (display-affecting vs comparison-only)
    schema.py      manifest allowlist, role vocabulary, reserved ranges, limits
    sources.py     .xlsx frontend + CSV frontend -> one RawSource
    validate.py    fail-closed validation, duplicate taxonomy, normalization
    identity.py    committed ID ledger, monotonic allocation, retirement
    emit.py        CSI, checksums, generated JS, containment, atomic publish
    qa.py          QA report (JSON + Markdown), registry handoff
    pipeline.py    orchestration; pure generation, then publish
```

Stages: `source → parse → validate → normalize → resolve stable ids → ContentPack v1
artifacts → checksums → QA reports → registry handoff → atomic publish`.

`scripts/import_hsk_excel.py` is **untouched** and remains the production HSK import path
until an explicit HSK cutover decision in a later phase.

## Canonical source contract

**Primary frontend** — one `.xlsx` workbook with sheets `manifest`, `cards`, optional `levels`.
**Secondary frontend** — a directory with `manifest.csv`, `cards.csv`, optional `levels.csv`;
UTF-8, BOM tolerated, RFC 4180 via the stdlib `csv` module. No spreadsheet application, no
shell parsing.

Columns are bound **by header name**, never by position. Duplicate headers, unknown columns,
missing required columns, hidden sheets, hidden rows, merged cells, formula cells and non-text
cell values are all **fatal** — every one of them is a silent failure in the legacy importer.

### Manifest
Key/value rows against a **strict allowlist**; an unknown key is fatal. ContentPack v1 itself
performs no unknown-top-level-key rejection, so the pipeline is the only layer that can catch a
typo such as `licence:` or `packid:`.

Tool-computed and therefore **fatal if authored**: `sourceChecksum`, `contentChecksum`,
`generatedAt`, `cardCount`, `fieldRoles`, `levels`.

### Card roles
Role names are taken from the existing closed vocabulary in
`hsk_flashcard_app/core/content/content-pack.js:60-65` rather than invented.

- Required: `sourceKey`, `deck`, `primaryPrompt`, `definition`
- Optional (declared by column presence): `pronunciation`, `exampleText`,
  `examplePronunciation`, `exampleTranslation`, `tags`
- Source-only: `notes` — authoring metadata, counted in QA, **never** emitted into the payload
  and never declared as a `fieldRole` (strict v1 rejects unknown roles)

`pronunciation` is **not** required. IELTS and TOEIC vocabulary have no pinyin, and requiring it
would hardcode HSK semantics into the generic contract.

Two identity concepts are kept apart: **`sourceKey`** is author-owned, build-time only, ASCII,
and never reaches the runtime; **`stableId`** is the ContentPack role naming the runtime integer
id field (always emitted as `id`). That separation is what lets authors use readable string
identity while the runtime id stays the integer the Supabase schema requires
(`card_progress.card_id int`, `sync_push_progress` casts `::int`).

## Canonical Source Intermediate (CSI)

Both frontends project into one CSI, and **the CSI bytes — never the raw `.xlsx` bytes — are the
`sourceChecksum` basis.** An `.xlsx` is a ZIP carrying per-entry timestamps, so re-saving an
unchanged workbook changes its bytes; hashing those would make the checksum a property of the
editor rather than of the content.

CSI is UTF-8, no BOM, LF, NFC-normalized, `sort_keys=True`, `separators=(",",":")`, cards sorted
by `sourceKey`. It excludes generated ids, `generatedAt`, build-tool version, filesystem paths,
timestamps and every machine-specific value.

**Verified:** an `.xlsx` workbook and the CSV directory it was built from produce byte-identical
CSI, `sourceChecksum`, `contentChecksum` and all three data artifacts.

## Identity: the committed ID ledger

`source_data/<packId>/<packId>-id-ledger.json` (committed) is the **sole** authority on card
identity. The pipeline never parses its own generated output to recover ids.

This inverts the single highest-risk behavior in the repository. `scripts/import_hsk_excel.py:64-71`
treats an unparseable `data.js` as "no prior data" and silently reallocates every card id from 1
with exit code 0 — which would destroy the join key for every learner's local and cloud SRS
progress. Here, a ledger that is **missing (without `--init-ledger`), unreadable, malformed,
version-mismatched, pack-mismatched, range-mismatched, or internally inconsistent is FATAL.**
There is no empty-ledger fallback.

| Situation | Behavior |
|---|---|
| Initial allocation | ascending `sourceKey` order from `idRange.min`; requires `--init-ledger` |
| Rebuild, no change | identical ids, byte-identical output |
| Row reorder | no effect (identity is keyed on `sourceKey`, output sorted by `cardId`) |
| Learner-text edit | no id change — the entire point; only `contentChecksum` moves |
| Deck move | no id change |
| New card | smallest unused id above the high-water mark; gaps are never filled |
| Deleted row | ledger entry → `retired`; requires `--allow-removals`; id never reused |
| Retired key returns | keeps its **original** id, so delete/restore preserves SRS history |
| Duplicate `sourceKey` | fatal, both coordinates reported |
| Case-insensitive key collision | fatal (keys are case-sensitive; ambiguity is rejected) |
| Duplicate assigned `cardId` | fatal |
| Id outside range / range exhausted | fatal |

A post-assignment **drift assertion** proves the anchor actually held, keeping the one genuinely
good idea from the legacy importer (`import_hsk_excel.py:160-164`).

Reserved ranges are enforced against the frozen blocks when `courseId` is one of
`hsk / ielts / toeic / jlpt / topik`; an unregistered course is INFO, because cross-pack overlap
rejection is Phase 24E's job. The handoff carries `allocated.min/max/count/gaps` so 24E can do an
exact overlap check without reading card payloads.

## Validation severities

| Class | Effect |
|---|---|
| **FATAL** | abort, nonzero exit, nothing written |
| **LAUNCH-BLOCKING** | builds; QA sets `launchEligible: false` |
| **WARNING / INFO** | recorded; never blocks the technical build |

Findings accumulate with a stable machine-readable code, a message, `sourceKey` where applicable,
and a coordinate (`sheet!cell` for Excel, `file!line N col M` for CSV). The legacy importer has
only "fatal" and "invisible", reports no coordinates, and stops at the first problem.

### Duplicate taxonomy
Legitimate polysemy must never be fatal — a Chinese headword with several senses is correct content.

| Case | Severity |
|---|---|
| Duplicate / case-colliding `sourceKey`, duplicate `cardId` | FATAL |
| Byte-identical rows under different keys | FATAL |
| Same prompt + same definition in one deck | LAUNCH-BLOCKING |
| Same prompt, different definitions in one deck (polysemy) | WARNING |
| Near-duplicate prompt (case/spacing/trailing punctuation) | WARNING |
| Same prompt across different decks | INFO |
| Repeated example sentences | INFO |

## Unicode policy

**Display-affecting** (alters stored text, applied once at read): CRLF/CR → LF; strip U+200B and
U+FEFF; **NFC** (never NFKC); trim edge whitespace including U+00A0 and U+3000.

**Comparison-only** (never stored): NFC + whitespace collapse + casefold, plus a trailing-punctuation
strip for near-duplicate detection.

Preserved exactly: Chinese, Vietnamese diacritics, pinyin tone marks, IPA, kana, kanji, Hangul,
full-width punctuation. NFKC is never applied because it folds full-width CJK punctuation, ligatures
and IPA modifier letters that are meaningful content.

Fatal rather than cleaned: U+200C/U+200D (script-semantic joiners — a human decides), lone
surrogates and malformed Unicode (never U+FFFD), control characters, embedded newlines/tabs.

## Formulas and injection prefixes

Formula cells are **fatal**, detected in a separate `data_only=False` pass before values are read
with `data_only=True`. A cached formula value is an artifact of whoever last recalculated the
workbook; trusting it would make the build depend on an editor's history.

Injection prefixes (`= + - @` tab CR) in learner content are **INFO only and never modified** —
`-ing`, `+/-` and IPA strings are legitimate. The output side designs the problem away instead:
artifacts are JS/JSON data and Markdown, never CSV, so nothing is re-interpreted by a spreadsheet.
*Tradeoff, stated:* a user who exports the QA report to CSV themselves could reintroduce the risk.
That is preferred over corrupting learner-visible text, and it is documented rather than silent.

## Generated output

All artifacts land in **`build/content-packs/<packId>/`** — outside `hsk_flashcard_app/`. This is
what makes "no runtime change, no SW bump" structural rather than merely intended, and it keeps
zero dead bytes out of the future Capacitor bundle. Writing inside the app directory is fatal.

```
<packId>-content-pack.js   manifest (data only)
<packId>-cards.js          card payload (data only), sorted ascending by cardId
<packId>-source.csi.json   canonical source intermediate (checksum basis)
qa-report.json             machine-readable
qa-report.md               human-readable
registry-handoff.json      Phase 24E input
```

The JS wrapper is a **tool-owned literal**. No spreadsheet value reaches a code position — not an
identifier, not a property expression, not a namespace. Author data lands only inside JSON value
positions, and the JSON additionally neutralizes `</` (so `</script` cannot terminate the element),
U+2028 and U+2029. `packId` is re-validated against `IDENT_RE` at the emit boundary rather than
trusting the upstream check.

Serialization mirrors the proven conventions: `ensure_ascii=False`, `separators=(",",":")`,
explicit field order, LF, trailing newline, UTF-8 no BOM.

### Checksums
Three values answering three different questions, deliberately not conflated:

| Value | Basis | Answers |
|---|---|---|
| `sourceChecksum` | CSI bytes | did the authored source change? |
| `contentChecksum` | emitted card payload only | did the card content change? |
| generated-file `sha256` | actual output bytes | are the artifacts intact? |

`generatedAt` is **omitted by default**, so a plain rebuild is byte-identical. Supplied only via
`--generated-at`, and even then it appears **only** in QA/handoff metadata — never in a runtime
artifact and never in a content-identity checksum. Build-tool version is QA metadata only, so a
tool refactor never looks like a content change.

## Provenance

Never invented. Draft and beta packs build fine without provenance. A pack claiming launch
readiness (`status: launch`, `launch.readiness: launch`, or `launch.visible: true`) without
`publisher`, `source.origin`, `source.license` and `source.url` is **LAUNCH-BLOCKING** with the
missing fields named explicitly. Unknown provenance stays unknown and blocks certification.

**Recorded honestly:** HSK content provenance and licensing remain genuinely unknown. The frozen
Company Pack contains no licensing guidance, and Phase 24C deliberately omitted these fields
rather than inventing them. This is deferred to the Phase 27/29 legal and store-compliance track.
It is a pre-existing Milestone 1 risk that this pipeline makes visible; it is not a 24D defect.

## Atomicity and containment

Full validation → complete staging (`.staging-<packId>`, sibling of the pack directory) with
`flush` + `fsync` → per-file `os.replace` promotion → `try/finally` staging cleanup. A failure at
any earlier point leaves the previous output **byte-unchanged**, verified by test. Obsolete
generated files are inventoried and removed **only inside the target pack directory**, never
recursively and never outside the containment root. A directory holding files this pipeline did
not produce is fatal without `--force`. `--check` writes nothing at all, including staging.

Path containment reuses the rules already proven in `scripts/release_check.py:88-114`: reject
URLs, protocol-relative and UNC paths, drive-absolute and absolute paths, `..` on either
separator, then confirm with `realpath`/`commonpath` so symlinks cannot escape.

## CLI

```
python scripts/build_content_pack.py --pack <packId> [options]
```

`--source --output --ledger --check --verify-deterministic --qa-only --force
--allow-removals --init-ledger --generated-at`

| Exit | Meaning |
|---|---|
| 0 | success |
| 1 | fatal validation (nothing written) |
| 2 | usage / environment / dependency |
| 3 | `--check` drift |
| 4 | `--verify-deterministic` byte difference |

Distinguishing 1 from 2 matters: CI must tell "the content is wrong" from "the tool could not run".
Console output is ASCII-only so a Windows cp1252 console cannot crash a build; non-ASCII content
appears only inside the UTF-8 artifacts. No `shell=True`, no subprocess, no network, no credentials.

## HSK conformance (read-only)

`tests/data/test_pack_build_hsk_conformance.py` projects the committed `data.js` into a generic
source, seeds a temporary ledger from the legacy `(level, word)` anchor hashed into the ASCII
`sourceKey` charset, and proves the generic pipeline reproduces **all 5,002 ids, their order, the
six decks, the audited per-level counts (149/150/295/600/1295/2513) and all eight fields**.

Nothing production is written: `data.js`, `source_data/HSK1-HSK6.xlsx`, `scripts/import_hsk_excel.py`
and `packs/hsk/hsk-content-pack.js` are asserted byte-unchanged by the test itself.

The hashed anchor is a **bridge for this proof only**, not an accepted authoring identity policy —
a derived anchor breaks exactly when a typo is fixed or a card moves level, which is why real packs
carry an author-owned `sourceKey`.

### Real content defect found

The fail-closed Unicode policy found a genuine, previously unrecorded defect in the **shipped** HSK
data: card **id 1303 (HSK5, 成人)** contains five stray **U+200C** zero-width non-joiners across
`example`, `examplePinyin` and `translation`. They are editing artifacts and carry no semantics in
Chinese or Vietnamese, and they are currently in production.

Phase 24D **does not modify `data.js`** to fix it. The conformance test asserts that the pipeline
detects it fatally on the real dataset, then quantifies it as the single exception: 5,001 of 5,002
cards reproduce byte-for-byte on every field, and card 1303's three fields differ by exactly
"remove U+200C, then apply the documented edge-trim" (removing the trailing joiner exposes a
trailing space on `translation`). **Owner decision required — routed to Phase 24F content QA.**

## Tests

**42/42** (36 existing preserved unchanged, no assertion removed or weakened; 6 added).

| Suite | Covers |
|---|---|
| `test_pack_build_parse.py` | both frontends, header binding, BOM, quoted comma, embedded newline, Unicode scripts, missing sheet/file/column, duplicate header, unknown column/manifest key, tool-computed field, formula cell, hidden sheet/row, merged cell, non-text cell, malformed CSV, row cap, optional levels, undeclared deck, Excel/CSV equivalence |
| `test_pack_build_identity.py` | stable rebuild, row reorder, text edit, deck move, new card, removal gate, retirement, no recycling, restore, duplicate/case-colliding/non-ASCII keys, every ledger failure mode, range exhaustion, reserved-range enforcement |
| `test_pack_build_determinism.py` | repeated build byte equality, on-disk equality, `--verify-deterministic`, output-path independence, checksum format and inventory, workbook byte churn, `generatedAt` isolation, what each checksum responds to, ledger stability, LF/BOM hygiene, report determinism |
| `test_pack_build_safety.py` | `</script` + U+2028/U+2029 escaping, wrapper ownership, full Unicode policy, containment (9 rejected forms), app-directory block, foreign/stale output, failure atomicity, orphan temp files, `--check` no-write (tree snapshots), all five exit codes, ASCII-only output, source hygiene greps |
| `test_pack_build_qa.py` | report shape, completeness metrics, markdown form, full duplicate taxonomy incl. polysemy staying non-fatal, provenance launch gate both ways, handoff schema, severity counts, coordinates |
| `test_pack_build_hsk_conformance.py` | 5,002-card reproduction, ids/order/decks/counts/fields, rebuild stability at real scale, production byte-unchanged, the U+200C finding |

**Deliberate convention change:** a missing `openpyxl` **fails** these suites rather than being
reported as a pass with a `skipped` key (the existing convention at
`tests/data/test_importer_determinism.py:20-24`). Silently skipping would hide the entire Phase 24D
coverage surface without turning the run red.

**QA report scope decision:** the report describes pack **state**, not the invocation. Per-build
deltas (how many ids this run allocated, reused or retired) and build-event notices
(`LEDGER_INITIALIZED`, `QA_ONLY`, `STALE_OUTPUT_REMOVED`) are printed on the console but excluded
from the report and handoff, so both stay pure functions of `(source, ledger)` and `--check`
compares like with like.

## Performance

The 5,002-card HSK conformance build (project → parse → validate → normalize → allocate → emit →
report, twice) completes in **~0.7 s**. Row cap 20,000, file cap 64 MB, field soft cap 4,000 chars.
Formula detection costs a second workbook pass, which is acceptable for build-time tooling.

Flagged forward for **Phase 24E**: a 20,000-card pack is roughly 5 MB of classic JS. Eagerly loading
three such packs would hurt native cold start. The manifest and cards are deliberately **separate
files** to preserve an eager-catalog / lazy-payload option.

## Service worker

**No change. `hsk-flashcards-v36` unchanged. ASSETS remains exactly 36 entries.** Nothing was added
under `hsk_flashcard_app/` and no precached file was modified, so `scripts/release_check.py` and its
pinned literal at `tests/tooling/test_release_check.py:219` are untouched and still pass 9/9.

## Git policy (owner decision Q3)

Committed: the authoritative ID ledgers (`source_data/**/<packId>-id-ledger.json`) and QA acceptance
reports for real packs. Ignored: `build/content-packs/` and `*.tmp`. Generated runtime JS is
reproducible from source + ledger, so committing it would add diff noise without information. The
ledger **must** stay committed — if it were machine-local, card ids would stop being reproducible,
which is the failure class this phase exists to eliminate.

Phase 24D uses **synthetic fixtures only**. No real HSK, IELTS or TOEIC ledger, report or content
was created or committed.

## Rollback

Anchor: `main` = `52bb08a61ff3ba79b85b77d3265a08988f92ea5a` (Phase 24C merged). Phase 24D is a single
commit on `phase-24d-content-pack-pipeline`.

`git revert <sha>` removes `scripts/build_content_pack.py`, `scripts/contentpack/`, the six new
suites and `tests/fixtures/packs/`, and restores `tests/run_regression.py` (deregistering the suites),
`.gitignore`, `docs/architecture/PHASE_PLAN.md` and `docs/release/MILESTONE_1_PRODUCT_FREEZE.md`.
Delete `build/content-packs/` if present — it is referenced by no runtime asset, so removal has zero
runtime effect. Authored sources and any ledger are preserved; discarding a ledger would be the one
genuinely destructive act available here.

Expected suite count after rollback: **36/36**. Regression: `python tests/run_regression.py`.
Release check: `python scripts/release_check.py` → 9/9, `hsk-flashcards-v36`, 36 precache assets —
unchanged before and after, because Phase 24D never touched a gated surface. No user-data migration,
no Supabase rollback, no redeploy and no cache purge are required.

## Known limitations (honest)

1. **HSK provenance/licensing unknown** — blocks launch certification for the HSK pack whenever it is
   run through this gate. Phase 27/29 legal track.
2. **HSK card 1303 carries stray U+200C** in shipped production data. Not fixed here. Phase 24F.
3. **Multi-line card content is unsupported** — embedded newlines are fatal. If a future pack needs
   multi-paragraph fields, the policy needs an explicit, reviewed extension.
4. **No cross-pack overlap enforcement** — single-pack range validation only, by design; Phase 24E.
5. **Ledger write and artifact publish are two sequential atomic operations**, not one transaction.
   Ledger is written first on purpose: a failure after it converges on the next run, whereas the
   reverse order could hand out different ids.
6. **`IDENT_RE` cannot match a 2-character id** (inherited from ContentPack v1), so `packId: "jp"`
   would be rejected. Flagged for the architecture lead; not changed here, since the runtime contract
   is frozen.
7. **`notes` is source-only** and is not carried into any artifact beyond a QA coverage count.
