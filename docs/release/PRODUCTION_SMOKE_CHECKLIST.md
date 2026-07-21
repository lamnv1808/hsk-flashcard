# Production Smoke Checklist (web release)

Run after a Render deploy is **Live**, in a hard-refreshed or fresh/incognito browser context, on
both a mobile viewport and desktop, in light and dark mode. Use **test fixtures only** for any
logged-in checks — never real user data.

## Entry choice (configured deployments)
Production ships a populated `supabase-config.js`, so a logged-out visitor is asked once.
Run the whole checklist through the **no-account** path — never a real account.
- [ ] A fresh/incognito context shows the chooser with **all three** actions: Đăng nhập, Đăng ký,
      **Học không cần tài khoản**.
- [ ] Choosing **Học không cần tài khoản** closes the chooser, and the top bar then shows the
      **Đăng nhập** control that reopens the same chooser.
- [ ] After that choice: a plain reload **and** an offline reload stay usable with no chooser.

## Boot & home
- [ ] Home loads with **no console errors**.
- [ ] Daily Goal panel renders (near the top) with the correct `N/G` and progress bar.
- [ ] Streak stat renders.

## Study Mode
- [ ] Study at least **3 cards**.
- [ ] Flip and grade using **all four** ratings (Chưa nhớ / Khó / Nhớ được / Rất dễ).
- [ ] Every newly entered card starts **front-side** (no answer leak) — after grade, skip, previous/undo, swipe.
- [ ] With **front pinyin ON** and with **front pinyin OFF**: after flipping, the back shows the **Hanzi + pinyin** above the meaning (Hotfix 24.1).
- [ ] Tapping the back Hanzi and the back pinyin each read the **Chinese word once** (zh-CN); no pinyin/Vietnamese spoken; card stays flipped.
- [ ] Word audio ("Từ") and example audio ("Ví dụ") each play once and speak **Chinese only**.
- [ ] Skip, previous/undo, and swipe (left = next, right = previous) all work.

## Completion & continuity
- [ ] Complete a **level session** → completion breakdown correct → **Keep Going** starts another same-levels session.
- [ ] Complete a **Weak Words** session → "Quay lại Từ cần cải thiện" returns to the **refreshed** list.
- [ ] Complete a **Bookmarks** session → "Quay lại Từ đã lưu" returns to the **refreshed** list.

## Other modes & persistence
- [ ] Run a **Test Mode** quiz (does not affect SRS/daily count/streak).
- [ ] Reload → progress **persists**.
- [ ] **Local-only** mode works (no account) — study + progress persist locally. Storage must be
      the base keys (`hsk_flashcard_progress_v2` / `_settings_v2`), with **no** `hsk_session`,
      **no** `hsk_current_user`, **no** `hsk_sync_*` key and **no** Supabase request at all.
- [ ] Logged-in **account isolation** verified with test fixtures (account B never sees account A's data).
- [ ] **Offline**: load once online, go offline → app shell + a Study session still work.

## Cross-cutting
- [ ] Mobile and desktop layouts OK; **light and dark** mode readable; no horizontal overflow.
- [ ] Zero console/page errors throughout.
