# DATA CONTRACTS (Phase 0)

Exact current schemas (real field names, defaults, and behavior) + a proposed
canonical model reachable **only through adapters**. The current production model
is the **compatibility contract**; nothing here renames a runtime field.

## 1. Vocabulary card — `window.HSK_CARDS[]` (`data.js`)

```jsonc
{
  "id": 1,                    // int, 1..5002, GLOBALLY UNIQUE + IMMUTABLE (progress join key)
  "level": "HSK1",            // string "HSK"+n; enumerated via distinct sort-by-number
  "word": "爱",               // Chinese (column B)   — the "front"
  "pinyin": "ài",             // vocab pinyin (col C)
  "meaning": "yêu",           // Vietnamese meaning (col D)
  "example": "我爱你。",       // Chinese example (col E)
  "examplePinyin": "Wǒ ài nǐ.", // example pinyin (col F)
  "translation": "Tôi yêu bạn." // Vietnamese translation (col G)
}
```
Defaults/behavior: all fields present for every card (importer trims, skips blank
rows). Order in the array = ascending `id`. **No optional fields today.**

## 2. Per-card progress / SRS state

**Local:** `localStorage["hsk_flashcard_progress_v2"(::uid)]` = `{ "<id>": state }`.
**Default when absent** (`getCardState`): `{due: today, interval:0, reps:0, correct:0, attempts:0}`.

```jsonc
"<cardId>": {
  "due": "2026-07-12",  // YYYY-MM-DD (UTC via toISOString slice); next review day
  "interval": 3,        // int days; last applied interval (0 for "again")
  "reps": 4,            // int; total gradings
  "correct": 3,         // int; count of good|easy only
  "attempts": 4         // int; total gradings (== reps in practice)
}
```
Derived (not stored): `failures = attempts - correct`; `lastGraded ≈ due - interval days`.
**Cloud:** table `card_progress(user_id, card_id, due, interval, reps, correct, attempts, updated_at, PK(user_id,card_id))` — same fields **plus server `updated_at`**. Local per-card timestamps live separately in `hsk_sync_meta::uid`.

## 3. Settings blob — `localStorage["hsk_flashcard_settings_v2"(::uid)]` and `user_settings.data` (jsonb)

Single JSON object; **every field optional with a safe default**. New metadata is
added here as new keys (see rows tagged *added*).

| Key | Type | Default | Meaning |
|---|---|---|---|
| `selectedLevels` | string[] | `["HSK1"]` | last study level selection |
| `sessionSize` | string | `"20"` | `"10".."100"` or `"all"` |
| `speechRate` | number | `1` | one of 0.5/0.75/1/1.25/1.5 (else →1) |
| `autoReadWord` | bool | `false` | auto-read word on new card |
| `autoReadExample` | bool | `false` | auto-read example on flip |
| `showFrontPinyin` | bool | `true` (undefined⇒true) | front pinyin preference |
| `dark` | bool | `false` | dark theme |
| `streak` | number | `0` | consecutive study days |
| `lastStudy` | string | — | last study date (YYYY-MM-DD) |
| `bookmarks` *(added)* | int[] | `[]` | bookmarked card IDs |
| `notes` *(added)* | `{ "<id>": string }` | `{}` | per-card plain-text notes (≤1000 chars) |
| `dailyCounts` *(added)* | `{ "YYYY-MM-DD": int }` | `{}` | words learned/local-day (rolling ~365) |
| `todayLearn` *(added)* | `{day, ids:int[]}` | — | dedup guard for "once/card/day" |

## 4. Auth / session

`hsk_session` = `{ access_token, refresh_token, expires_at (ms) }`.
`hsk_current_user` = `{ id (uuid), username (display case) }`.
`HSK_AUTH` (runtime) = `{ configured, userId, username, progressKey, settingsKey, needsAuth }`.
Server: `profiles(id uuid PK, username text lower-unique, display_username text, created_at, updated_at)`;
`login_attempts(username PK, fails, locked_until)` (service-role only). Auth user =
synthetic email `<username>@hsk.local`, password = `HMAC-SHA256(PIN_PEPPER, "<lower-username>:<pin>")`.

## 5. Sync bookkeeping (per user, local only)

`hsk_sync_dirty::uid` = `int[]` changed card IDs pending push.
`hsk_sync_meta::uid` = `{ "<id>": updatedAtISO }`.
`hsk_sync_lastpull::uid` = ISO string. `hsk_sync_settime::uid` = ISO (settings updatedAt).
`hsk_import_done::uid` = `"1"` once migration prompt shown.

## 6. Sync payloads

- Push progress: RPC `sync_push_progress({rows:[{card_id,due,interval,reps,correct,attempts,updated_at}]})` — upsert **only where `excluded.updated_at > existing`**.
- Delete progress: `DELETE /rest/v1/card_progress?card_id=in.(…)` / `?card_id=gte.0` (reset).
- Push settings: RPC `sync_push_settings(p_data=<full settings blob>, p_updated_at)` — newer-only.
- Pull: `GET /rest/v1/card_progress?select=…&updated_at=gt.<lastpull>`, `GET /rest/v1/user_settings?select=data,updated_at`.

## 7. Test Mode history (local, not synced)

`hsk_test_history[::uid]` = `[{date, levels[], types[], total, correct, percent}]`, max 20.

---

## 8. Proposed CANONICAL model (target — via adapters only, NOT runtime yet)

### 8.1 `Card` (canonical)
```ts
interface Card {
  id: string | number;        // stable; legacy = int id
  packId: string;             // e.g. "hsk" (NEW; adapter injects "hsk")
  deckId?: string;            // optional grouping
  level?: string;             // "HSK1" (generic label)
  levelOrder?: number;        // numeric sort key (adapter: parseInt of HSKn)
  prompt: { text: string; lang: string };          // front. HSK: {word, "zh"}
  reading?: { text: string; system: string };      // HSK: {pinyin, "pinyin"}
  meaning?: { text: string; lang: string };         // HSK: {meaning, "vi"}
  example?: { text: string; lang: string;
              reading?: {text; system}; translation?: {text; lang} };
  audio?: { lang: string };   // HSK: {"zh-CN"}
  tags?: string[];
  extra?: Record<string, unknown>;
}
```

### 8.2 `UserCardState` (canonical) — wraps existing SRS **1:1**
```ts
interface UserCardState {
  cardId: string | number;
  due: string;      // == legacy due
  interval: number; // == legacy interval
  reps: number;     // == legacy reps
  correct: number;  // == legacy correct
  attempts: number; // == legacy attempts
  updatedAt?: string; // == sync meta / server updated_at
}
```
The SRS scheduler operates on `UserCardState` and returns a new one; the adapter
serializes back to the exact legacy `{due,interval,reps,correct,attempts}` object.

## 9. Adapter mapping table (legacy ⇄ canonical) — the compatibility spine

| Canonical | Legacy source | Adapter rule |
|---|---|---|
| `Card.id` | `card.id` | identity |
| `Card.packId` | — | constant `"hsk"` (injected) |
| `Card.level`, `levelOrder` | `card.level` | passthrough; `levelOrder = parseInt(/\d+/)` |
| `Card.prompt` | `card.word` | `{text: word, lang:"zh"}` |
| `Card.reading` | `card.pinyin` | `{text: pinyin, system:"pinyin"}` |
| `Card.meaning` | `card.meaning` | `{text: meaning, lang:"vi"}` |
| `Card.example.*` | `example/examplePinyin/translation` | compose |
| `Card.audio.lang` | (hardcoded `"zh-CN"`) | pack config, default `"zh-CN"` |
| `UserCardState.*` | `progress[id].*` | identity for all 5 fields; `updatedAt` from sync meta |
| Settings.* | `settings.*` | identity; unknown keys preserved verbatim |

**Rule:** the legacy JSON on disk/cloud remains the source of truth. Adapters are
read/write shims. No canonical field may drop or rename a legacy field, and any
serialization round-trip (`legacy → canonical → legacy`) must be **byte-identical**
for untouched records (a characterization test enforces this in Phase 1).
