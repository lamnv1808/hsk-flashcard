# Phase 24E-A — Pack Registry and Boot Foundation

## Objective
Build and prove the product-neutral foundation Phase 24E-B needs — registry validation,
pure boot planning, deterministic catalog generation and checksum-verified promotion —
**without loading any of it in production**.

**Zero production runtime effect.** No new file is referenced by `index.html`, called by any
production script, or added to the service-worker precache. `data.js`, `sw.js`, `app.js` and
every runtime module are byte-unchanged.

## Why Phase 24E is split

Phase 24E discovery identified twelve independent risk surfaces: registry validation,
deterministic catalog generation, payload promotion, parser-time boot, account-scoped
settings, active-pack lifecycle, analytics filtering, bookmarks/notes filtering, Test Mode
history, audio metadata, local and cloud reset, and service-worker packaging.

Landing all twelve at once would recreate exactly the integration risk that Phases 18–20 were
restructured to avoid. So:

- **24E-A** (this phase) builds the foundation and proves it in isolation.
- **24E-B** integrates it into production with one controlled service-worker bump.

## Accepted discovery decisions (binding)

1. **Reload-on-switch is the lifecycle boundary.** No in-page pack switching. Load-time
   singletons (`app.js:2,3,7` are `const`), the once-built `CardRepository` index, field roles
   frozen at engine construction, IIFE-private snapshots in `test.js`/`insights.js`, and twelve
   accumulating `addEventListener` sites make in-page teardown unsafe. The codebase already
   solves the identical problem for account switching with `location.reload()`.
2. **Eventual runtime shape:** eager small committed catalog · exactly one active pack payload
   per page load · synchronous classic-script loading · page reload after changing
   `activePackId`.
3. **No asynchronous runtime loading.** No `fetch()` for payloads, no dynamic `import()`, no ES
   modules, no runtime JSON fetching, no framework, no bundler, no async boot restructuring.
   Evidence: the service worker never calls `cache.put`, so anything fetched at runtime is
   unavailable offline; `registerServiceWorker` is a hard no-op on native; and every core
   singleton is constructed at script-parse time against `getCards()`.
4. **Reset means reset only the active pack.** Implementation belongs to 24E-B.
5. **Only real, validated, launch-ready packs may be visible.** HSK is the only real pack.
   Synthetic packs are test fixtures. IELTS, TOEIC, JLPT and TOPIK must not appear.
6. **Integer identity frozen.** HSK 1–999,999 · IELTS 1,000,000–1,999,999 ·
   TOEIC 2,000,000–2,999,999 · JLPT 3,000,000–3,999,999 · TOPIK 4,000,000–4,999,999.
7. **Runtime checksum semantics must be honest** (see *Checksum trust boundary*).

## Registry — `hsk_flashcard_app/core/content/pack-registry.js`

`NS.createPackRegistry(catalog)` either returns a validated registry or **throws**. There is no
silent fallback from a malformed catalog: a wrong-pack fallback is worse than a visible failure,
because card ids are the join key for every learner's SRS progress.

The job nothing else in the codebase does: **cross-pack integer id-range overlap rejection.**
ContentPack v1 validates a single pack's declared range but cannot see a second pack, and its
`validate()` has no production caller at all. Overlap rejection has been deferred to "the Phase
24E registry" since Phase 24C; this is it.

**Validated per pack:** `packId`/`courseId` (`IDENT_RE`, unique) · `version` · `title` ·
`shortTitle?` · `courseType` ∈ exam|general · `status` ∈ draft|beta|launch ·
`languageProfile.target` (BCP-47) and optional `translation`/`instruction`/`script`/`direction` ·
`audio.locale`/`fallbackLocales`/`readFields` · `capabilities`/`categories`/`levels`
(unique `deckId`, integer `order`) · `launch{visible,readiness}` · `idRange` (safe ints,
`min>0`, `max>=min`, `max<=2147483647`) · `allocated{min,max,count,gaps}` (inside `idRange`,
`count` within span, null min/max iff `count===0`) · `sourceChecksum`/`contentChecksum`
(`sha256:` + 64 lower-case hex) · `manifestPath`/`cardsPath` (relative, distinct, no URL,
absolute, drive, UNC, backslash, `..` or empty segment) · `minAppVersion?` (dotted numeric).

**Validated across packs:** duplicate `packId`; declared-range overlap; allocated-range overlap;
`defaultPackId` must name a launch-visible declared pack.

**Launch honesty is structural:** `launch.visible === true` is rejected unless *both* `status`
and `launch.readiness` are `"launch"`. A catalog cannot claim a pack is publicly visible while
admitting it is not ready.

**API:** `getSchemaVersion` `getAppVersion` `getPackIds` `hasPack` `getPack` `getAllPacks`
`getLaunchVisiblePackIds(appVersion)` `getLaunchVisiblePacks(appVersion)`
`getDefaultPackId(appVersion)` `getIdRange` `getAllocated` `getAssetPaths` `isCompatible`
`isLaunchVisible` `compareVersions`.

Every accessor returns a **deep** copy. A shallow array slice was not enough — `levels` is an
array of objects, so slicing it still handed callers live deck objects; a test caught that and
the copy is now recursive.

**Default selection** is deterministic and product-neutral: an explicit `defaultPackId` wins;
otherwise the launch-visible, version-compatible pack with the lowest declared `idRange.min`.
Ranges are disjoint, so that is a total order with no tie-break and no hard-coded pack name.

**Does not:** load scripts, touch storage, touch the DOM, access the network or Supabase, build
sessions, write progress, compute SRS, or contain a single HSK/Chinese literal.

## Boot plan — `hsk_flashcard_app/core/content/pack-boot.js`

`NS.planPackBoot({registry, requestedPackId, appVersion})` → a plan. **Pure.**

```jsonc
{ "planVersion":1, "ok":true, "packId":"beta", "reason":"requested",
  "requestedPackId":"beta", "fallbackFrom":null,
  "scripts":["packs/beta/beta-content-pack.js","packs/beta/beta-cards.js"],
  "idRange":{...}, "allocated":{...},
  "expected":{"packId","version","sourceChecksum","contentChecksum",
              "manifestPath","cardsPath"},
  "error":null }
```

Reasons: `requested` · `default-first-run` · `fallback-unknown-pack` ·
`fallback-malformed-request` · `fallback-not-launch-visible` ·
`fallback-incompatible-app-version`. Errors: `NO_REGISTRY` · `NO_LAUNCH_VISIBLE_PACK`.

**Two invariants asserted hardest**, because both corrupt data rather than merely breaking a
screen:
- **never returns an empty pack** — a boot with no cards is an explicit error, not a silently
  empty app;
- **never returns a mixed plan** — exactly one pack's two scripts, manifest before cards.

A requested id that cannot be a pack id (corrupt storage, wrong type, injected string) is
rejected by `IDENT_RE` **before** it is used as a lookup key, so it can never reach a path.
Purity is asserted directly: the planner is called with `document.write`, `fetch`,
`XMLHttpRequest` and `Storage.prototype.get/setItem` replaced by traps, and the DOM length is
compared before and after.

`NS.serializePackBootPlan(plan)` gives a deterministic, fixed-key-order serialization for
golden tests and logging.

## Deterministic catalog generation — `scripts/build_pack_catalog.py`

Reads **both** inputs per pack, because neither alone suffices:
- `registry-handoff.json` — identity, status, launch metadata, ranges, checksums, file inventory;
- `<packId>-content-pack.js` — the only place `title`, `languageProfile`, `audio`,
  `capabilities`, `levels`, `categories` and `minAppVersion` exist.

The manifest's JSON is extracted by **marker slice** (`.manifest = … ;`) and parsed. The
generated JavaScript is **never executed**. The naive "first `[` to last `]`" trick is
deliberately avoided — the wrapper contains `FLASHEDU_PACKS["id"]`, which is exactly the failure
mode the legacy HSK importer has.

Output: `window.FLASHEDU_CATALOG = {…};` — a classic, static, data-only script. The wrapper is a
tool-owned literal and the whole document goes through the Phase 24D `js_json` hardening
(`</` neutralised, U+2028/U+2029 escaped), so no catalogued value reaches a code position.

**Determinism, measured:** input-order independent and byte-identical across repeated runs.
Packs are ordered by declared range start (a total order, since ranges are disjoint) and all
JSON is `sort_keys=True`.

**Honesty rules, enforced not documented:** visibility is *derived* —
`declared visible AND launchEligible AND status=="launch" AND readiness=="launch"`. An author
can write `launch.visible: true` in a spreadsheet while the build found the pack
launch-ineligible; the catalog downgrades it to hidden and the generator reports why. Provenance,
licence and readiness are never synthesised. Build-only artifacts (CSI, QA reports, ledger, the
handoff itself) never reach the catalog.

Exit codes: `0` ok · `1` defect (nothing written) · `2` usage/environment · `3` `--check` drift.

## Promotion — `scripts/promote_content_pack.py`

The only sanctioned way to move Phase 24D output into a runtime app root. Manual copying is not
acceptable: it bypasses every checksum the pipeline computed, cannot detect a partial or stale
promotion, and silently breaks the release checker's clean-tree gate until someone remembers to
commit. A dedicated command makes those failures loud.

| Aspect | Contract |
|---|---|
| Promoted | `<packId>-content-pack.js`, `<packId>-cards.js` → `<app-root>/packs/<packId>/` |
| Build-only | CSI, `qa-report.*`, `registry-handoff.json`, ledger — never promoted |
| Verification | every byte re-hashed against `generatedFiles[]`; size checked; mismatch refuses |
| Containment | `packId` validated first; `realpath` on both sides; a symlinked `packs/` escaping the app root is refused |
| Atomicity | full staging → journal → two atomic renames (`os.replace(dir → existing dir)` raises on Windows) → cleanup; failure restores the previous generation |
| Lock | the canonical per-pack `PackLock` from Phase 24D |
| Stale removal | files not in the promoted set are removed **inside that pack's directory only** |
| Launch gate | refuses a launch-ineligible pack unless `--allow-draft` (test/staging roots only) |
| Wiring | prints the exact `sw.js` ASSETS additions, the cache bump, the pinned-test update and the `index.html` step — and **never performs any of them** |
| Never | edits `index.html`, edits `sw.js`, edits the pinned SW test, runs git, pushes, merges or deploys |

Catalog regeneration is driven by what is **promoted**, not by what happens to be built: a
catalog advertising a pack the runtime does not have is precisely the stale-state failure this
tooling exists to prevent. Each promoted file is re-verified on the way through, and a promoted
pack with no build handoff is fatal.

> **Deliberate non-decision:** promotion scratch (`.promote-staging-*`, `.promote-old-*`,
> `.promote-txn-*.json`) is **not** gitignored. A leftover marker means an interrupted
> promotion, and it *should* fail the release checker's clean-tree gate rather than hide.

## Checksum trust boundary

The catalog and the payloads ship from the **same origin and the same commit**. Checksums
therefore prove:

- partial promotion
- stale files
- catalog/payload disagreement
- packaging mistakes
- accidental corruption

They do **not** protect against a hostile actor who can modify both the catalog and the payload
in the same release — such an actor simply updates both. No cryptographic signing, WebCrypto
boot, or new trust infrastructure is added, and none should be implied. Phase 24E-B's runtime
comparison of catalog metadata against payload-declared metadata, paths, ids and ranges is a
consistency check, not tamper-proofing.

## Launch visibility rules

- Only `status: launch` + `launch.readiness: launch` + `launchEligible: true` may be visible.
- The registry rejects a catalog that claims otherwise; the generator downgrades rather than lies.
- HSK is the only real pack. No IELTS, TOEIC, JLPT or TOPIK entry exists anywhere.
- No fake, disabled or "coming soon" option is representable: a hidden pack is simply absent
  from `getLaunchVisiblePackIds()`.

## Synthetic fixture restrictions

`tests/fixtures/packs/synth-en/` is an English fixture with **no pronunciation column** (proving
`pronunciation` is optional for non-Chinese packs) in a synthetic id range **5,000,000–5,999,999**
— outside every reserved course block, so it can never be mistaken for real content. It is
test-only, never promoted into the real app, never in a production catalog, never in UI, and is
not named IELTS or TOEIC. `test_pack_foundation_isolation.py` scans every shipped `.js`/`.html`/
`.css`/`.webmanifest` for its identifiers and fails if any appears.

## HSK compatibility proof

`data.js` sha256 `D0B0A279228D86CAF7DBE14C757502311EC90E22F3D8A7C14A978C056BE42377`,
1,263,402 bytes, 5,002 cards, ids 1..5002 contiguous — all asserted by
`test_pack_foundation_isolation.py` and by the pre-existing 44 suites, which pass unchanged.
Card order, object identity, deck counts, field mappings, the HSK adapter, ContentPack v1,
Study Mode, Test Mode, audio, bookmarks/notes, Daily Goal/streak, completion/Keep Going,
targeted return, P0 answer-leak protection, SRS goldens, ProgressWriter, auth/sync and
offline/PWA are all untouched, because **nothing in this phase is loaded by the app**.

## Owner reset decision (recorded, not implemented)

**Reset progress will reset only the active pack.** Expected 24E-B behavior: local progress
deletion limited to the active pack's id range; cloud deletion limited to the same range;
bookmarks/notes scoped consistently; no Supabase schema, RPC or payload change; no other pack's
progress deleted.

> **Architecture correction, binding:** Phase 24E-B **is** allowed to modify `sync.js`, narrowly,
> for the active-range reset filter. Today `sync.js:164` issues
> `DELETE card_progress?card_id=gte.0` — every row for the user, across every pack. The Phase 24E
> discovery report's blanket "sync.js unchanged" statement is incompatible with active-pack reset
> and must not be carried forward. All other sync transport semantics remain frozen.

## Zero production integration status

| Surface | State |
|---|---|
| `index.html` | unchanged; neither foundation module referenced |
| `sw.js` | unchanged; `hsk-flashcards-v36`; exactly 36 assets; no foundation file precached |
| Production JS | no file calls `createPackRegistry` or `planPackBoot` |
| `hsk_flashcard_app/packs/` | still contains only `hsk/`; no `catalog.js` |
| `release_check.py` / pinned SW test | unchanged |
| `data.js` | byte-identical |

Enforced by `test_pack_foundation_isolation.py`. **If Phase 24E-B lands, that suite failing is
the intended signal that integration happened**, and it must be updated deliberately.

## Performance

| Measure | Result |
|---|---|
| Catalog size | 1 pack 1,046 B · 3 packs 2,822 B · 5 packs 4,598 B (~890 B/pack) |
| Catalog generation | ~74–77 ms for 1/3/5 packs (dominated by interpreter start-up) |
| Promotion | whole promotion suite, incl. ~8 promotions and 5 fixture builds, 1.6 s |
| Registry lookup | **O(1)** — a plain object keyed by `packId`; no card scan |
| Range validation | **O(n log n)** — one sort plus a single adjacent-pair scan |
| Boot-plan resolution | O(n) in pack count (n ≤ 5) |
| Runtime parse cost | **zero** — the modules are not loaded in production |
| Card clones | none; no 5,002-card array is copied anywhere |
| Network | none |

Catalog growth is linear and tiny: even 5 packs is under 5 KB, which comfortably justifies the
"eager catalog, lazy payload" split — the payloads are ~250 bytes/card (HSK is 1.26 MB).

## Security

- No `eval`, no `new Function`, no shell execution, no `shell=True`, no `subprocess` in the
  promotion tool, no network, no Supabase, no secrets, no production data.
- No spreadsheet-derived value reaches a JavaScript code position; the catalog wrapper is a
  tool-owned literal and all data goes through the Phase 24D `js_json` hardening (`</script`,
  U+2028, U+2029).
- All output paths are containment-checked; symlinks are resolved **before** the containment
  decision; catalog identifiers are validated **before** any path is constructed.
- The registry rejects URL, absolute, protocol-relative, drive, UNC, backslash and `..` paths, so
  a future parser-time insertion can only ever receive a plain relative path from a validated
  catalog.

## Tests

**49/49** — 44 pre-existing suites unchanged (no assertion removed or weakened) plus 5 new,
grouped by risk surface rather than by file:

| Suite | Checks | Covers |
|---|---|---|
| `test_pack_registry.py` | 74 | acceptance, identity, id ranges incl. exact/partial/adjacent overlap, allocated overlap and containment, paths (10 malformed forms), checksums, launch honesty, hidden filtering, `minAppVersion` gating, deterministic default, deep-copy isolation |
| `test_pack_boot_plan.py` | 37 | requested/first-run/unknown/malformed/hidden/incompatible, exactly-one-pack and fixed order, no-valid-pack error, missing registry, determinism, **purity traps** on DOM/storage/network, plan isolation |
| `test_pack_catalog_build.py` | — | determinism (order-independent + repeat-identical), catalog contract, build-only exclusion, launch honesty incl. forced downgrade, defaults, overlap rejection, 8 malformed-handoff cases, `--check` |
| `test_pack_promotion.py` | — | checksum verification, missing asset, containment + symlink escape, stale removal scoped to the pack, atomicity, refusal leaves target unchanged, catalog regeneration, orphan detection, launch gate + `--allow-draft`, no git/network/Supabase, real app untouched |
| `test_pack_foundation_isolation.py` | — | not in `index.html`, not in SW, no production caller, SW v36 + 36 assets, `data.js` hash/size, no synthetic leak, `packs/` still HSK-only, release tooling untouched |

Grouping rationale: registry and boot plan are separate because one is a validator and the other
a resolver with a purity contract; catalog and promotion are separate because one is pure
generation and the other is a filesystem transaction; isolation is separate because it is the
guard that must break loudly when 24E-B integrates.

## Known limitations

1. **Nothing is wired.** The foundation is proven but unused; the runtime still boots exactly as
   before. That is the point of the split, not an oversight.
2. **Parser-time insertion is unproven.** 24E-B must demonstrate it on static hosting,
   subdirectory hosting, desktop Chrome, mobile Chrome/Safari, offline PWA and Capacitor-local
   assets. If it is not reliable, **stop and report** — do not silently introduce async boot. The
   fallback candidate (eager classic-script loading of all launch packs) needs owner approval.
3. **Checksums are consistency evidence, not tamper protection** (see trust boundary).
4. **The catalog carries no `description`.** Deliberate: 24E-A ships only what a runtime needs.
5. **HSK has no catalog entry yet.** HSK's payload is `data.js` with a hand-authored adapter, not
   generated output; giving it a catalog entry (with per-pack `manifestPath`/`cardsPath`) is a
   24E-B decision and requires no HSK regeneration.
6. **Windows directory-entry `fsync` is unavailable** (inherited from Phase 24D); promotion
   durability relies on NTFS metadata journaling for the rename itself.
7. **`minAppVersion` comparison is dotted-numeric, not semver** — no pre-release or build
   metadata semantics.

## Rollback

Anchor: `main` = `58a9ddb799298cf020810e660ce3009e2c8220df`. Phase 24E-A is a single commit on
`phase-24e-a-pack-foundation`.

`git revert <sha>` removes `core/content/pack-registry.js`, `core/content/pack-boot.js`,
`scripts/build_pack_catalog.py`, `scripts/promote_content_pack.py`,
`scripts/contentpack/catalog.py`, `tests/fixtures/packs/synth-en/`, the five new suites and this
document, and restores `tests/run_regression.py` (deregistering the suites) and
`docs/architecture/PHASE_PLAN.md`.

Expected suite count after rollback: **44/44**. Regression: `python tests/run_regression.py`.
Release check: `python scripts/release_check.py` → 9/9, `hsk-flashcards-v36`, 36 precache assets —
**identical before and after, because Phase 24E-A never touched a gated surface**.

**No runtime redeploy and no cache purge are required**, and **no user-data migration exists** —
nothing production loads reads or writes anything this phase added.

## Phase 24E-B entry criteria

1. Phase 24E-A merged; regression green; `release_check.py` 9/9 on synchronized `main`.
2. Parser-time script insertion proven on all six environments above, **or** the eager fallback
   explicitly approved by the owner/architecture lead.
3. HSK catalog-entry shape agreed (`data.js` + hand-authored adapter as its `cardsPath`/
   `manifestPath`).
4. Pack-scoped settings migration plan accepted (non-destructive; legacy keys retained for
   rollback).
5. The narrow `sync.js` active-range reset filter authorized (recorded above).
6. Exactly one service-worker bump budgeted, v36 → v37, with the pinned test literal updated in
   lockstep.
7. A decision on whether `test_pack_foundation_isolation.py` is updated or split when
   integration lands.
