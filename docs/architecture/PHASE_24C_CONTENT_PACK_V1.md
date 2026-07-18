# Phase 24C — Content Pack v1, Integer ID Invariant, HSK v1 Compatibility Adapter

## Objective
Turn the existing generic ContentPack seam into a **versioned v1 contract** that future HSK, IELTS,
TOEIC, JLPT and TOPIK packs can declare against, establish the **integer card-ID invariant**, and
re-declare the existing HSK adapter as a valid v1 pack — with **zero user-visible change**.

**Contracts and tests only.** No registry, no importer, no onboarding, no new content, no pack
switching, no `app.js` consumer migration, no UI/CSS/storage change.

## Strategic fit
FA-004 (AI Constitution v1.1) Principle 2 — *Start Narrow, Build Reusable*: build the content model
so it can support HSK, IELTS, TOEIC, JLPT, TOPIK. Phase 1 ships **one app, three launch options**
(HSK, IELTS, TOEIC) with HSK as the deepest experience. Phase 24C is the reusable content contract
underneath that, and nothing else.

## Existing generic boundary (unchanged)
`core/content/content-pack.js` was already product-neutral (no HSK/Chinese literals) and every
consumer already reads decks/roles/test-modes through it, with `CardRepository` initialized from
`contentPack.getCards()`. Phase 24C therefore only **adds** to that seam.

## Legacy mode
A spec **without** `schemaVersion` behaves exactly as before: same constructor, same defaults, same
accessors, same `validate()` shape (no v1 keys added), same error/warning semantics. Legacy support
exists solely to prevent regressions for existing callers and tests; malformed legacy specs are **not**
silently tightened. The new v1 accessors return `undefined` (and `getOptionalRoles()` returns `[]`).

## Strict v1 mode
A spec **with** `schemaVersion` enters strict mode. The manifest is structurally validated **at
construction** and a malformed manifest **throws** — it is never downgraded into legacy defaults, and
`schemaVersion` must be exactly `1` (any other value, including `"1"`, fails closed). Validation is
O(1) with respect to card count (it never reads cards) and never mutates caller data. Error messages
name the failing manifest field and contain no secrets.

### Manifest shape
**Required:** `schemaVersion` (=1), `packId`, `version`, `status`, `title`, `courseId`, `courseType`,
`languageProfile.target`, `fieldRoles`, `idRange.min`, `idRange.max`.

**Optional:** `shortTitle`, `description`, `publisher`, `source{origin,license,url,acquiredAt}`,
`sourceChecksum`, `contentChecksum`, `generatedAt`, `minAppVersion`,
`languageProfile{translation,instruction,script,direction}`,
`audio{locale,fallbackLocales,readFields}`, `framework{name,version}`, `levels`, `categories`,
`launch{visible,readiness}`, `search{fields,normalizer}`, `presentation{frontRoles,backRoles}`,
`optionalRoles`, `capabilities`, `cardCount`.

> **Naming note (deliberate):** v1 language metadata lives in the additive **`languageProfile`**
> object, *not* inside the legacy `languages` map. `tests/browser/test_content_pack.py` asserts
> `getLanguages()` **exactly** equals `{prompt,reading,meaning,audio}`; extending `languages` would
> have broken that existing assertion. Semantics are identical; `getLanguages()` is untouched.

### Validation rules
*Identity* — `packId`/`courseId` are normalized lower-case identifiers (`^[a-z0-9]([a-z0-9-]{0,30}[a-z0-9])?$`);
`version`/`title` non-empty; `status ∈ {draft,beta,launch}`; `courseType ∈ {exam,general}`; when both
`packId` and legacy `id` are present they must match.
*Languages* — conservative BCP-47 structural check (`lang[-Script][-REGION]`), **not** a full locale
registry; `script` is ISO-15924 (`Xxxx`); `direction ∈ {ltr,rtl}`.
*ID range* — `min`/`max` safe integers, `min > 0`, `max >= min`, `max <= 2147483647` (int4 ceiling).
*Fields* — every declared role must be a known role and map to a non-empty field name; the required
roles `stableId`, `deck`, `primaryPrompt` must be declared unless listed in `optionalRoles`; unknown
roles in `fieldRoles`/`optionalRoles`/`audio.readFields`/`presentation.*`/`search.fields` fail closed.
*Metadata* — arrays/objects are type-checked; malformed audio/presentation/search/launch metadata fails.

`validate()` (which does read cards, one pass) additionally reports, for v1 packs: every card id is a
**safe integer inside the declared `idRange`**, ids are unique, deck references are declared, and
declared non-optional roles resolve to real card fields. It **never allocates ids, sorts, reorders or
mutates cards**. Cross-pack range-overlap rejection is **deferred to the Phase 24E registry**.

## Integer ID invariant (architecture)
Card identity is **one global integer namespace**. This is mandatory, not stylistic:
`supabase/schema.sql` declares `card_progress.card_id **int** not null` with primary key
`(user_id, card_id)`, and `sync_push_progress` casts `(r->>'card_id')::int`; local progress, bookmarks,
notes and the sync dirty/meta maps are all keyed by that same bare integer. Schema and payload changes
are out of scope, so composite or string keys are not available.

**Reserved, non-overlapping blocks of one million ids:**

| Pack | Reserved range |
|---|---|
| **HSK (legacy)** | **1 – 999,999** (existing ids 1…5002 unchanged) |
| IELTS | 1,000,000 – 1,999,999 |
| TOEIC | 2,000,000 – 2,999,999 |
| JLPT | 3,000,000 – 3,999,999 |
| TOPIK | 4,000,000 – 4,999,999 |

Rules: no id reuse across packs; **no renumbering after publication**; future packs allocate only
inside their registered range; `max` must stay within the database integer limit; an authoring
`sourceId`/`stableId` may exist as build-time metadata but **does not replace** the runtime integer
card id. Registry-enforced overlap rejection lands in Phase 24E. **No card ids were allocated in this
phase.**

## HSK v1 adapter
`packs/hsk/hsk-content-pack.js` now declares (factual values only, added **alongside** the untouched
legacy fields): `schemaVersion:1`, `packId:"hsk"`, `status:"launch"`, `courseId:"hsk"`,
`courseType:"exam"`, `languageProfile:{target:"zh-CN", translation:"vi", instruction:"vi",
script:"Hans", direction:"ltr"}`, `audio:{locale:"zh-CN", fallbackLocales:["zh"],
readFields:["primaryPrompt","exampleText"]}`, `idRange:{min:1,max:999999}`,
`launch:{visible:true, readiness:"launch"}`, `search.fields` and `presentation.front/backRoles`
mirroring today's runtime, and `source:{origin:"source_data/HSK1-HSK6.xlsx"}`.

**Honesty rules applied:** `publisher`, `source.license`, `source.url`, `source.acquiredAt`,
`sourceChecksum`, `contentChecksum`, `generatedAt`, `minAppVersion` are **omitted** — they are not
documented in the repository and were **not invented**; the Phase 24D pipeline will supply them.
`levels` and `cardCount` are omitted because decks and counts are **derived** from the cards
(`deckProvider`), so static declarations could drift. Structural ContentPack validity is **not** a
launch-quality claim; content quality gates are Phase 24F.

## HSK compatibility (verified)
`data.js` is **byte-unchanged** (sha256 identical to `main`). All 5,002 cards, ids 1…5002, order, field
values, deck ids/order and per-deck counts (149/150/295/600/1295/2513) are unchanged. `getCards()`
still returns the **live `window.HSK_CARDS` array** (same reference, never cloned) and `getById()`
returns the same object identity for every card. `getLanguages()`, `getFieldRoles()`, `getTestModes()`
(6 modes), capabilities, `getId()`/`getVersion()`/`getTitle()` are unchanged. Front-pinyin behavior,
Hotfix 24.1 back Hanzi+pinyin visibility, word/example audio, Study/Test/Weak Words/Bookmarks/Notes/
Insights/Daily Goal/streak/completion/Keep Going/targeted return, and local-only/auth/sync behavior are
all unchanged. **No user-data migration, no storage-key change, no Supabase schema or payload change.**

## Immutability
Construction and validation never mutate the manifest, cards array, card objects, deck definitions,
level arrays, field-role maps, or audio/presentation/source metadata. Accessors return small defensive
copies (mutating a returned copy cannot corrupt internals). **The 5,002 cards are never deep-cloned or
reordered.**

## Performance
Construction stays O(1) w.r.t. card count (v1 manifest validation never reads cards); card lookup
remains O(1) via the existing `byId` map; no scan was added to render/flip/grade; no new asset fetch,
no storage or network access, no extra `app.js` initialization. Measured in-browser: 200 × `getCards()`
≈ **0 ms**; a full `validate()` pass over 5,002 cards ≈ **0.4 ms**. No benchmark dependency introduced.

## Security
Data only — no dynamic code execution, no `eval`, no `innerHTML` for manifest data, no network access
in ContentPack, no source-URL fetch, no path handling added to the runtime, no secrets, no production
Supabase, no real user data. Validation error messages name manifest fields only.

## Deferred
**Phase 24D** — deterministic Excel/CSV → pack pipeline, checksums, provenance, QA reports.
**Phase 24E** — static Pack Registry, cross-pack **id-range overlap rejection**, pack loading,
pack-scoped runtime state. **Phase 24F** — three-option onboarding UX and IELTS/TOEIC launch content
with launch-quality gates.

## Service worker
`content-pack.js` and `hsk-content-pack.js` are precached runtime assets and both changed, so the cache
was bumped **exactly once: v35 → v36**. Caching strategy unchanged; **no asset added or removed** — the
inventory remains **36 distinct canonical precache assets**, and `scripts/release_check.py` (unchanged)
still parses the ASSETS array and verifies all 36.

## Tests
New `tests/browser/test_content_pack_v1.py` (registered → **36/36**): legacy back-compat (unchanged
behavior/defaults/validate shape, malformed legacy not tightened); v1 acceptance (minimal + complete
manifests, all accessors); **~40 fail-closed rejection cases** (schema version 0/2/"1", identity,
status/courseType, language profile/script/direction, audio, id range incl. `min<=0`, `max<min`,
non-integer, unsafe, above int4, field roles/unknown roles/missing required, launch/presentation/
search/categories/levels/cardCount); v1 content checks (card below/above range, non-integer id,
duplicate id, undeclared deck, role resolution, declared-optional role allowed); immutability (spec,
cards, order, live array identity, card object identity, copy isolation); and full HSK equivalence
(5,002 / ids / decks / counts / roles / test modes / live source / getById identity / no invented
provenance). Existing suites — including `content_pack`, `card_repository`, `test_mode_query`,
`card_stability`, `adapter_roundtrip`, p0 answer-leak, SRS goldens, Study/Test/features, auth/sync/
offline, Hotfix 24.1 back-vocab — all remain green with **no assertion removed or weakened**.

**Allowlist exception (owner-authorized):** `tests/tooling/test_release_check.py:219` pinned the real
service worker to `v35`; the mandated bump made that literal stale. The owner authorized changing
**only that version literal** to `v36`. The assertion keeps its purpose (pinning and verifying the
exact current production cache version); `scripts/release_check.py` was not modified and no assertion
was weakened.

## Rollback
Anchor: `main` = `b437163` (Phase 24B merged). Phase 24C is a single commit on
`phase-24c-content-pack-v1`. `git revert <sha>` restores: `core/content/content-pack.js`,
`packs/hsk/hsk-content-pack.js`, `sw.js` (**v36 → v35**), `tests/run_regression.py` (deregisters the
suite), `tests/tooling/test_release_check.py` (v36 → v35 literal), and removes
`tests/browser/test_content_pack_v1.py` + this document. Expected suite count after rollback: **35/35**.
Regression command: `python tests/run_regression.py`. **No user-data migration exists** and `data.js`
is byte-unchanged, so rollback requires no data work.

## Phase 24D entry criteria
Phase 24C merged to `main` and deployed-or-verified; regression green on `main`;
`python scripts/release_check.py` PASS on synchronized `main`; the v1 contract accepted as frozen for
pack authoring; owner-confirmed source-file conventions (Excel workbook vs three CSVs) and at least one
sample fixture per format. Phase 24D introduces **no runtime change** — it is a build-time pipeline that
emits v1-conformant packs plus checksums, provenance and QA reports.
