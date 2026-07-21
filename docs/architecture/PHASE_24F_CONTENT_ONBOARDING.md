# Phase 24F — Content Onboarding

Status: in progress on `phase-24f-content-onboarding`. Nothing pushed, merged or
deployed. No IELTS/TOEIC content exists yet and none is invented here.

## Landed so far

| Task | Commit | What |
|---|---|---|
| Legacy-aware promotion | `1d97a18` | `regenerate_catalog` accepts the handoff-less legacy HSK pack by re-verifying its existing `install.kind == "legacy-installed"` descriptor against deployed bytes |
| Course picker | this commit | Catalog-driven course selection + Home switcher; SW v40 → v41 |

## The course picker

`packBootShim.getLaunchVisiblePacks()` returns the launch-visible courses from
the **retained validated registry** — the same registry object the boot decision
used. The UI never reparses or reconstructs the catalog, so a course can only be
offered if the registry already cleared it. Hidden, draft and
version-incompatible packs are filtered out before the UI ever sees them, and
nothing in the UI hardcodes a course id.

### One course = completely inert

Production ships exactly one launch-visible course (HSK), so the picker renders
nothing at all: no dialog, no selector row, and **no settings, `activePackId`,
SETTIME, sync or storage write of any kind at boot**. The observed production
boot is `visible=["hsk"], gateHidden=true, rowHidden=true, settings=null`. The
existing layout is byte-for-byte the same markup plus two elements that stay
`hidden`.

This means every multi-course path below is currently reachable only under a
test-injected catalog. That is deliberate: the code ships ready, but no user can
reach it until a second validated pack exists.

### Two or more courses

| Stored `activePackId` | Boot reason | UI |
|---|---|---|
| valid launch-visible id | `requested` | boots it; Home shows the course selector |
| absent | `default-first-run` | **mandatory** dialog |
| malformed | `fallback-malformed-request` | **mandatory** dialog |
| unknown | `fallback-unknown-pack` | **mandatory** dialog |
| hidden | `fallback-not-launch-visible` | **mandatory** dialog |
| incompatible | `fallback-incompatible-app-version` | **mandatory** dialog |

A mandatory dialog cannot be dismissed (no close button, Escape ignored) and
**storage is never silently repaired** — the invalid value stays exactly as
stored until the user actively chooses.

### `persistSame`

`switchPack(packId, { persistSame: true })` is the one narrow extension. It
exists for a single real case: on first run with several courses, choosing the
one that already happens to be the effective default must still be recorded, or
the mandatory dialog would reappear forever.

- Calls **without** the option keep their exact previous behaviour.
- With the option, if the raw stored id already equals the effective id it stays
  a **zero-write no-op**.
- Otherwise it runs the existing readiness → snapshot → save → flush → reload
  path. `switchPack` therefore remains the first and only `activePackId` writer,
  and this is still not automatic repair: nothing writes unless a user chose.

UI code never touches `activePackId` or `localStorage` directly.

### Safety and accessibility

Controls disable while a switch is in flight and duplicate calls are refused;
failure shows an inline `role="alert"` error, leaves settings untouched and keeps
the dialog usable for another attempt; a mandatory dialog never closes on
failure. Switching is refused during an active Study or Test session, because a
switch reloads the page. Audio is stopped only by the existing switch
transaction. The dialog uses `role="dialog"`, `aria-modal="true"`, labelled and
described by its heading and hint, moves focus to the first option, traps Tab,
and marks the current course with `aria-current`. Styling reuses the existing
card/button system; there is no redesign.

## Verification

`tests/browser/test_pack_course_picker.py` drives the real parser-time boot and
the production switch API with coherent synthetic packs (never named
IELTS/TOEIC). Observed:

```
single-pack:   gateHidden=True rowHidden=True settings=None
multi/valid:   options=['hsk','compatpack'] current=compatpack
mandatory/*:   absent | malformed | unknown | hidden | incompatible
               -> dialog shown, storage unchanged, Escape ignored
choose-different: blob={'activePackId':'compatpack'} pack=compatpack count=6
default-choice:   blob={'activePackId':'hsk'} reason=requested
same-pack:        legacy=same-pack persistSame=same-pack (both zero-write)
failure:          gateOpen=True error=SYNC_NOT_READY settingsUnchanged=True
visual desktop 1440x900 / mobile 390x844: dialog within viewport, no clipping
```

Screenshots are written to a temp directory, never the repository.

## Service worker

Exactly one bump this task: `hsk-flashcards-v40` → `hsk-flashcards-v41`. The
picker adds no new file — it lives in already-precached `index.html`,
`styles.css`, `app.js` and `pack-boot-shim.js` — so the inventory stays at
**40 distinct assets**. The bump is still required because those precached
bytes changed and are served cache-first.

## Limitations

- The multi-course screenshots depict a **test-only catalog**. Production has one
  course, so no user can currently reach the picker.
- WebKit/Safari is not covered (only the chromium Playwright binary is
  installed); the suite reports the skip rather than passing silently.
- No physical-device testing.
