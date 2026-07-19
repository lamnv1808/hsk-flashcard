# Phase 24E-B — Runtime Registry Integration

Status: in progress. Increments 1 through 4B are complete and committed on
`phase-24e-b-runtime-integration`. Nothing has been pushed, merged or deployed.

Phase 24E-A built the registry, boot planner, catalog generator and promotion
tool and proved they had **zero** production effect. Phase 24E-B wires that
foundation into the running app, one reviewable increment at a time, without
changing what an HSK learner sees.

## Completed increments

| Increment | Commit | What landed |
|---|---|---|
| 24E-B.1 | `f7fb569` | Legacy-installed HSK runtime catalog (`packs/catalog.js`) + generator/drift and registry-acceptance suites |
| 24E-B.2 | `62e0243` | `.gitattributes` pinning LF for byte-sensitive files |
| 24E-B.2b | `68df556` | Catalog checksums made line-ending independent |
| 24E-B.3 | `95d023a` | Parser-time boot wiring; service worker v36 → v37 |
| 24E-B.3A | `a4f100c` | Raw `activePackId` passthrough; `appVersion` forwarding |
| 24E-B.3A.1 | `ce3f447` | Coherent synthetic pack fixture (test honesty) |
| 24E-B.4B | this commit | No-write active-pack contract locked by tests + this document |

## The catalog: HSK is a legacy-installed pack

The 24D pipeline can only describe packs it generated itself — it composes
runtime paths from a hardcoded `packs/<id>/<id>-*.js` template and requires a
`registry-handoff.json` naming those basenames. HSK predates that pipeline: its
payload is the hand-installed `data.js` and its adapter is
`packs/hsk/hsk-content-pack.js`, and no handoff exists.

So HSK is catalogued as **legacy-installed**, with explicit runtime paths. The
generator (`tests/data/test_pack_catalog_legacy.py`) is generic — nothing
branches on the string `"hsk"`; a pack is legacy-installed when it supplies
explicit paths instead of inheriting the template.

Checksum honesty: `contentChecksum` is the sha256 of the cards payload actually
served. `sourceChecksum` is required by `pack-registry.js`, and legacy HSK has
no canonical source image, so it is the raw workbook hash, labelled
`install.sourceChecksumBasis = "raw-workbook-bytes"`. A test asserts it is never
described as a CSI. No publisher, license, URL or legal status is invented.

Ownership scope is the **declared** `idRange` 1–999999, not the observed
allocation 1–5002.

## Parser-time boot

`core/content/pack-boot-shim.js` is the only script-tag inserter in the app. It
resolves the plan once, synchronously, then exposes `writeCards()` and
`writeManifest()`, called from `index.html` at exactly the two parse positions
the static `data.js` and `packs/hsk/hsk-content-pack.js` tags used to occupy.

### Why two insertion points, and why `plan.scripts` is ignored

`plan.scripts` is `[manifestPath, cardsPath]`. That is **not** the physical load
order. The real graph is:

```
data.js (window.HSK_CARDS)
  -> core/util/{levels,card-index}.js
  -> core/content/content-pack.js
  -> packs/hsk/hsk-content-pack.js   (reads HSK_CARDS, calls createContentPack)
  -> core/cards/card-repository.js   (eager singleton over the pack's cards)
```

The manifest depends on the cards payload **and** on three core modules sitting
between them, so the two payloads cannot be adjacent in either order. The shim
uses `plan.expected.cardsPath` / `plan.expected.manifestPath` instead.
`core/content/pack-boot.js` is deliberately **unchanged**: the ordering is a
property of this app's script graph, not of the product-neutral planner.

`document.write` is used because it is the only mechanism that inserts a
parser-blocking classic script at the current parse position with no async step.
`appendChild` would load asynchronously and let `card-repository.js` build its
eager singleton over an empty dataset. Both writes refuse to run once
`readyState` leaves `"loading"`, and each refuses a second invocation.

`supabase-config.js` is hoisted above the shim (it is a trivial, dependency-free
assignment) so the account-namespaced settings key can be resolved before
`auth.js` exists.

## Requested value vs effective pack

Two distinct things, deliberately never conflated:

- **Requested** — the raw stored `activePackId`, passed to `planPackBoot`
  untouched. The shim performs no validation, because duplicating the pack-id
  rule would create a second source of truth that can drift from the planner's.
- **Effective** — the pack actually selected, i.e.
  `window.HSKUtil.packBootShim.getActivePackId()`. **This is the runtime source
  of truth for the active pack.** No equivalent accessor exists on
  `settings-repository.js`, by design.

Resolution matrix, proven end-to-end in `tests/browser/test_pack_boot_parser_time.py`:

| Stored value | Reason |
|---|---|
| absent / `null` / `""` | `default-first-run` |
| object / array / number / boolean | `fallback-malformed-request` |
| malformed string | `fallback-malformed-request` |
| unknown valid id | `fallback-unknown-pack` |
| hidden pack | `fallback-not-launch-visible` |
| `minAppVersion` above catalog `appVersion` | `fallback-incompatible-app-version` |
| known launch-visible pack | `requested` |

Every case boots exactly one complete pack. Never empty, never mixed. A catalog
that fails validation renders a visible error rather than an empty app, because
an empty page with a clean console looks like data loss to a user.

`appVersion` is forwarded from `registry.getAppVersion()`. Without it,
`isCompatible()` fails closed on a non-string version and every pack declaring a
`minAppVersion` would be silently hidden.

## No automatic settings migration write

**Boot never writes settings.** It adds, removes, repairs and rewrites nothing;
the settings bytes and the sync timestamp are untouched, and
`HSKSync.onSettingsChanged()` is never called.

This is a data-safety property, not tidiness.

### The whole-blob cloud race

Bookmarks, notes, `dailyGoal` and `streak` all live inside the settings blob,
and settings are pushed **whole** (`SYNC_CONTRACT.md`). The write path is:

```
app.js:208  saveSettings() -> localStorage[settingsKey] = settings
                           -> HSKSync.onSettingsChanged()
sync.js:160 onSettingsChanged() -> SETTIME = now; schedulePush() (1200 ms)
sync.js:129 pullSettings() accepts the server blob only when
              !localT || srv.updated_at > localT
sync.js:130   wr(settingsKey, srv.data || {})     <- WHOLESALE REPLACEMENT
```

A write during boot sets `SETTIME = now`, so local looks newer than the server,
**the pull is skipped**, and the next debounced push overwrites the cloud with
this device's blob. On a fresh device with empty local settings that silently
destroys the account's bookmarks and notes — triggered by nothing but opening
the app.

Writing `activePackId: "hsk"` would also encode zero information: HSK is already
the deterministic catalog default, so the derived value is identical.

`tests/browser/test_pack_settings_no_write.py` locks this. Its cloud-race case
seeds a stale local blob plus a newer server blob and asserts the observed
ordering `GET user_settings -> settings write -> SETTIME write -> push`, that
the server blob wins intact, and that the push carries the accepted blob rather
than the stale one.

### Malformed and unknown values are retained

They are never repaired. Repair implies a boot-time write (the race above) and
destroys the signal that storage is corrupt. The fallback is deterministic and
its reason is recorded.

## Account namespace rules

The shim mirrors `auth.js` exactly: the settings key is namespaced **only** when
`SUPABASE_CONFIG` is configured *and* a cached `hsk_current_user` record with an
`id` exists; otherwise the original local-only key is used.

```
local-only : hsk_flashcard_settings_v2
account    : hsk_flashcard_settings_v2::<userId>
```

The shim runs before `auth.js`, so it cannot consult `HSK_AUTH` and duplicates
this rule deliberately. Tests cover local-only, account A, account B and the
untouched legacy global key; no account's blob is migrated or repaired.

## Lifecycle: reload is the boundary

Changing packs requires `location.reload()`. `app.js reloadState()` re-reads
settings after a cloud pull but never re-runs the shim, so an in-session change
cannot re-seat the load-time singletons (`HSKUtil.cards`, `analytics`,
`userMetadata`, `testMode`).

If a cloud pull delivers an `activePackId` different from the pack already
loaded, it is **ignored for the current session**. Auto-reloading would
interrupt study and risk a reload loop between two devices. The parse-time shim
picks it up on the next natural load.

If cloud settings arrive *without* `activePackId`, the key simply disappears
with the wholesale replacement; the next boot resolves the catalog default. No
error, no empty boot.

## The only future writer

Persistence belongs exclusively to the explicit user switch API in **24E-B.5**:
validate the target pack, save `activePackId` once, stop audio, `location.reload()`.
No in-page hot switching, and no teardown logic for load-time singletons.

## Deferred

- Nested per-pack settings (`packs.<id>.selectedLevels`, front-pronunciation).
  With one pack these would duplicate the legacy keys with no reader, creating
  two sources of truth before anything needs them.
- Active-pack reset scoping (24E-B.6).
- Analytics / bookmarks / notes / Weak Words scoping (24E-B.7).
- Audio / search / Test Mode pack-driving (24E-B.8).
- Onboarding UI and real IELTS/TOEIC content (24F).

## Service worker

Exactly one bump this phase: `hsk-flashcards-v36` -> `hsk-flashcards-v37`,
36 -> **40 distinct assets**, adding `packs/catalog.js`,
`core/content/pack-registry.js`, `core/content/pack-boot.js` and
`core/content/pack-boot-shim.js`.

`data.js` and `packs/hsk/hsk-content-pack.js` remain precached even though they
are no longer static `<script src>` tags — otherwise offline boot loses its
payload. install/activate/fetch strategy is unchanged, and no build-only
artifact is precached.

## Limitations

- **WebKit/Safari is not covered.** Only the chromium Playwright binary is
  installed and installing another is a dependency download, which this phase
  forbids. The boot suite skips WebKit and *reports* the skip, so a green run
  never implies WebKit coverage. Parser-time `document.write` on real Safari/iOS
  is **unverified**.
- Mobile viewport/UA, root-vs-subdirectory hosting and a simulated Capacitor
  origin are not covered.
- No physical-device testing. Offline boot is verified on chromium only.
- 165 tracked files still have CRLF working copies; `.gitattributes` corrects
  them on next checkout. They were deliberately not renormalized.

## Test evidence

| Suite | Proves |
|---|---|
| `tests/data/test_pack_catalog_legacy.py` | Deterministic generation, drift, path containment, line-ending independence |
| `tests/browser/test_pack_catalog_runtime.py` | The fail-closed registry accepts the shipped catalog; overlap rejected |
| `tests/browser/test_pack_boot_parser_time.py` | Boot order, single insertion, full fallback matrix, coherent synthetic pack, offline boot |
| `tests/browser/test_pack_settings_no_write.py` | No settings write, account isolation, cloud-race survival |
| `tests/data/test_pack_foundation_isolation.py` | Wiring is complete (referenced **and** precached); one API consumer; no synthetic or unshipped-course leak |

Phase 24E-A guards that asserted the foundation was *not* wired were inverted,
not deleted — their failing was the intended signal that integration happened.

## Rollback

Each increment is a separate commit and reverts cleanly:

```bash
git revert <commit>                 # single increment
git checkout main && git branch -D phase-24e-b-runtime-integration
```

Reverting the branch restores current HSK behavior exactly. The legacy
`selectedLevels` and `showFrontPinyin` keys are still the only settings the app
reads, so an older build ignores `activePackId` as an unknown key and behaves
identically.
