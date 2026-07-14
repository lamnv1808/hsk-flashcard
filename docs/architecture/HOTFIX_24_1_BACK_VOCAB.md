# Hotfix 24.1 — Back card face always shows the vocabulary word + pinyin

Focused product-behavior correction. The card back now always repeats the primary Chinese
vocabulary and its pinyin before the meaning, **independent of the front-pinyin setting**.

## Bug
`applyPinyinDisplay()` conflated two things: the front-pinyin setting also **hid the entire back
vocab block** when front pinyin was enabled (the default):
```
$("backWordBlock").style.display = showFP ? "none" : "";   // <- direct bug
```
So with "Hiển thị Pinyin ở mặt trước" ON, flipping showed the meaning with no back Hanzi/pinyin and
no clickable pronunciation target. (`#backWordBlock` also carried an inline `style="display:none"`.)

## Fix
The setting now controls **only** the front vocab pinyin; the back block is always visible.
```
function applyPinyinDisplay(){
  const showFP = settingsRepo.getFrontPinyinEnabled();
  $("pinyin").style.display = showFP ? "" : "none";   // front pinyin follows the setting
  $("backWordBlock").style.display = "";              // back vocab (word + pinyin) always visible
}
```
- **index.html:** removed the obsolete inline `style="display:none"` on `#backWordBlock`. No ID or
  DOM-hierarchy change; no second vocab block.
- **Back values** still come from the Phase 17 read model (`m.back.primary` / `m.back.pronunciation`)
  in `renderCard`; no read-model or front-payload change.
- **Audio:** the existing single `bindWordAudio($("backWordBlock"))` listener is reused unchanged —
  `stopPropagation` → `suppressClick` guard → `speakWord()` (zh-CN word only; never pinyin/Vietnamese).
  Hanzi and pinyin are both inside the one click target; no new listener, no nested button, no
  `tabindex`. `S` on the back still reads the example; the front word and the "Từ" button unchanged.

## CSS / mobile layout
The back now always repeats word + pinyin, so it is equally dense in both setting states. The mobile
one-screen density rules that were scoped to `.flashcard.no-front-pinyin` (top-align + internal-scroll
safety net + compressed meaning/example/divider) now apply to the back face in **both** states. The
`.no-front-pinyin` class became fully obsolete (no other references) and was **retired** — no dead
behavior left. Desktop spacing, dark mode, swipe/drag, flip animation, reduced motion, and safe areas
are unchanged. Desktop Study remains a normal scrollable page (pre-existing; the one-screen guarantee
is the ≤720px layout).

## Answer-leak (P0) — unchanged
The back block is display:block but sits on the CSS-culled back face (`backface-visibility:hidden` +
`rotateY(180deg)`), exactly like `#meaning`/`#example` — not visually exposed before flip. The
`renderCard` no-flip-anim reflow guard is untouched, so every card-changing transition (grade / skip /
swipe next / swipe prev·undo / restart / Keep Going / targeted session) starts the new card front-side
with no leak. `p0_test` remains green.

## Setting matrix (verified)
- **showFrontPinyin = true (default):** front = word + pinyin; back = **word + pinyin** + Nghĩa + meaning
  + example + example-pinyin + translation. Back block clickable → reads the word once.
- **showFrontPinyin = false:** front = word only; back = identical to above.

## Tests
`tests/regression/back_vocab_visibility.py` (registered → **34/34**): both setting states (front
word/pinyin visibility + back word/pinyin always visible + meaning/example correct); audio (back Hanzi
and back pinyin each read the word once in zh-CN, card stays flipped, not pinyin/Vietnamese; example
click and `S`-on-back read the example; "Từ" button reads the word; drag→click suppressed; single
listener); navigation (next/prev front-side, back word updates, no stale prior word); layout at
360×800/375×667/390×844/1366×768 in light + dark (no horizontal overflow, back word visible, mobile
rating buttons in-viewport). Full regression **34/34 PASS** (incl. p0 answer-leak, SRS goldens, audio,
Study flow; zero console/page errors).

## Service Worker
Cache **v34 → v35** (runtime assets changed). Asset list, install/activate/fetch, and cache strategy
unchanged (no new runtime asset added).

## Files
Changed: `app.js` (applyPinyinDisplay + comments), `index.html` (drop inline display:none), `styles.css`
(retarget the density rules, retire `.no-front-pinyin`), `sw.js` (v35), `tests/regression/back_vocab_visibility.py`
(new), `tests/run_regression.py`, this doc. Unchanged: `data.js`, importer, ContentPack, presentation
read-model shape, StudySessionEngine/StateMachine, Scheduler/SRS, ProgressWriter/Repository,
grade/skip/undo/navigation, answer-leak guard, `auth.js`, platform adapter, `sync.js`, Supabase,
storage/schema/payloads, Daily Goal, streak, completion/Keep Going, targeted continuity, bookmark/note,
Test Mode, speech voice selection, auto-read, audio buttons, card IDs/content.

## Rollback
Branch `hotfix/back-vocab-always-visible` off `58a597d`. Revert: restore the `showFP ? "none" : ""`
back-block display + `.no-front-pinyin` toggle in `applyPinyinDisplay`, re-add the inline
`display:none`, re-scope the density CSS to `.no-front-pinyin`, SW v35→v34, remove the suite +
registration + this doc. `git revert <sha>` restores prior behavior. No stored user data changes.
Regression after rollback: 33/33.
