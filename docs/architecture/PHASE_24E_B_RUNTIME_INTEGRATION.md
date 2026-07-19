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

## Explicit pack switch

`HSKUtil.packBootShim.switchPack(targetPackId)` is the first and only writer of
`activePackId`. Boot stays read-only; persistence happens only in response to an
explicit user choice.

Validation reuses `planPackBoot` against the retained registry, so the
identifier rule and the visibility/version gates are never re-implemented. The
planner is built to FALL BACK, so its fallbacks must never be read as success: a
switch is valid only when the planner returns the exact requested pack for the
`requested` reason. Anything else fails with a stable code and mutates nothing.

Order is load-bearing:

```
validate -> await sync readiness -> stop audio -> mutate -> save
         -> bounded flush (3 s) -> location.reload()
```

Readiness comes before any mutation because `pullSettings()` replaces the blob
wholesale and only accepts a server copy newer than SETTIME; writing first would
suppress the pull and let the next push overwrite the account's bookmarks and
notes. Readiness failure is fail-closed: no audio stop, no write, no flush, no
reload. `switchPack` never calls `start()`, `pullAll()` or `pullSettings()`.

`sync.js` gained two narrow additive changes: `start()` is idempotent through one
shared promise (so the `online` listener registers exactly once) and exposes
`whenReady()`, which settles after the initial pull attempt and `reloadState()`
handling but before the legacy-import prompt; and `pushSettings()`/`flush()`
report whether the settings push was confirmed. All existing catch, retry, UI
and offline behavior is unchanged.

| Result | Meaning |
|---|---|
| `{ok:true, changed:true, packId, previousPackId, pushed, reloading:true}` | switched; `pushed` is settings-confirmation only |
| `{ok:true, changed:false, reason:"same-pack"}` | no-op; a malformed stored value is deliberately not repaired |
| `MALFORMED_PACK_ID` / `UNKNOWN_PACK` / `PACK_HIDDEN` / `PACK_INCOMPATIBLE` / `NO_CATALOG` / `PLAN_FAILED` | rejected; zero side effects |
| `SYNC_NOT_READY` | readiness missing/threw/rejected/timed out; zero side effects |
| `WRITE_FAILED` | save threw; in-memory and persisted state restored; no flush/reload |
| `SWITCH_IN_PROGRESS` | a different target is already switching |

A bug found by these tests and fixed: in local-only mode the async body had no
`await` before `location.reload()`, so it ran synchronously and cleared the
reentrancy guard before `switchPack()` returned, letting concurrent calls all
execute. It now yields once before doing any work.

## Current Gate closure: failure paths

**The two pulls are guarded independently.** `start()` used to wrap
`pullProgress(false)` and `pullSettings()` in one `try`, so a rejected progress
request skipped the settings request entirely while readiness still settled --
and a pack switch could then overwrite cloud bookmarks/notes this device had
never seen. Progress is still attempted first, settings is attempted regardless
of its outcome, `reloadState()` runs once if either successful pull changed
state, and the offline/error UI string is driven by whether either attempt
failed. Readiness still settles only after both attempts and before the
legacy-import prompt. Observed with `card_progress` aborted:
`order=['GET user_settings', 'POST push_settings']`, server bookmarks `[91,92]`
preserved, and the later switch changed only `activePackId`.

**A failed settings snapshot read is fail-closed.** `switchPack` reads the exact
previous raw blob before anything else. A successful read returning `null` means
"absent"; a THROW is different and returns `WRITE_FAILED` immediately. Swallowing
it and continuing with `prevRaw = null` would mean a later save failure
"restores" by deleting a blob that was never read -- destroying the user's
settings. The snapshot now precedes `stopSpeech()`, which previously ran first,
so a failed read no longer stops audio. Observed:
`code=WRITE_FAILED saves=0 stops=0 boots=1`.

**Save failure restores both copies.** If `saveSettings()` throws after the
modified blob has already been persisted, the live property is restored exactly
(including prior absence) and the previous raw blob is best-effort rewritten; no
flush, no reload. Observed: `live=hsk rawRestored=True boots=1`.

**The guard is latched through navigation.** An operation-local `reloadIssued`
flag is set only after `location.reload()` returns, and `finally` clears
`switching` only when it is false. The success promise resolves before navigation
actually happens, so clearing the guard there would open a window in which a
second call could save, flush and reload again on a document already on its way
out. If `reload()` throws, the flag stays false and the guard clears normally.
Observed in that exact window: `diff=SWITCH_IN_PROGRESS saves=1 stops=1 boots=2`.

**Offline, timeout and retry.** A logged-in offline switch persists locally and
reloads (`active=compatpack boots=2`). A hanging settings push times out at 3 s,
reports `pushed=false` and reloads anyway, retaining the choice and SETTIME. A
later page in the same browser context -- deliberately not reseeded -- inherits
the persisted blob and the existing `flush()` path pushes it:
`inherited=compatpack pushedActive=compatpack`.

## Active-pack reset

Reset used to delete every row the user owned in EVERY course
(`card_id=gte.0`) and to clear the whole dirty/meta map. It was also not
durable: if the cloud delete failed, the local rows were already gone but the
server rows survived, and because meta had been wiped the next `pullProgress`
saw `!localTime` for each of them and restored the deleted progress.

`ProgressWriter.reset(range)` now takes the active pack's declared ownership
range (HSK `1-999999`, not the observed allocation `1-5002`). It validates
finite integers with `min <= max` BEFORE any side effect; a missing or malformed
range fails closed with zero replace, save, `onReset` or request, because a
"reset everything" fallback would destroy other courses. It keeps every row
outside the range, calls `replaceProgress`/`save`/`onReset(range)` exactly once
each, and returns `{cleared, removed, range}`. `app.js` passes
`contentPack.getIdRange()`, forwards the range through its `onReset` hook, and
the confirmation now says "this course".

The cloud delete is bounded (`card_id=gte.<min>&card_id=lte.<max>`; user scope
still comes from RLS + bearer, no `user_id` predicate) and durable: the
validated range is written to an account-namespaced
`hsk_sync_pending_reset::<uid>` record synchronously before the first await, and
cleared only when the server confirms. A pending reset is retried through the
existing `flush()`/online lifecycle, and **`pullProgress` completes it before
accepting any server row** -- aborting the pull if it cannot -- because
accepting rows while a delete is still owed is exactly how deleted progress
comes back. Persisted ranges are re-validated before a URL is built, so corrupt
state can never widen a delete. Only active-range dirty ids and meta timestamps
are dropped; foreign entries survive byte-for-byte.

Observed: `DELETE ?card_id=gte.1&card_id=lte.999999`; on failure the marker is
retained and the next boot issues `DELETE` **before** any progress `GET`, with
no progress `GET` at all while unresolved; on success the marker clears, server
active rows are gone, foreign rows and the other account are untouched.

## Service worker

This phase required **two** bumps, not one. `v36 -> v37` added the boot assets
(36 -> **40 distinct assets**). `v37 -> v38` was then mandatory because the
switch API changed the runtime bytes of `sync.js` and
`core/content/pack-boot-shim.js`, which are themselves precached and served
cache-first: keeping v37 would have stranded installed users on stale copies of
exactly the files that were modified. The v38 bump changes no asset, so the
inventory stays at **40 distinct assets**. This supersedes the earlier
single-bump assumption recorded during increment 3, adding `packs/catalog.js`,
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
