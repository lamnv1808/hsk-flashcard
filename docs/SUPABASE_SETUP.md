# HSK Flashcards — Accounts & Cloud Sync Setup

This app runs in **local-only mode** (exactly as before) until you fill in
`hsk_flashcard_app/supabase-config.js`. Follow this guide to turn on accounts
+ cloud sync. Target scale: a handful of users (family), simple and stable.

---

## 0. What you are building

- A Supabase **Postgres** database (per-user progress/settings) with **RLS**.
- Four Supabase **Edge Functions** (`register`, `login`, `change-pin`, `delete-account`).
- Auth model: **username + 4-digit PIN**. The PIN is never stored. The server
  derives a strong credential `HMAC_SHA256(PIN_PEPPER, "username:pin")` and uses
  Supabase Auth (bcrypt) to store only the hash of that credential.
- The browser only ever holds the **public anon key** (safe; protected by RLS).

---

## 1. Create the Supabase project

1. Go to <https://supabase.com> → **New project**. Pick a name + a strong DB password + region.
2. Wait for provisioning (~2 min).
3. **Settings → API**. Copy these:
   - **Project URL** → `https://<ref>.supabase.co`
   - **anon public** key (safe for the browser)
   - **service_role** key (SECRET — never commit, never put in the browser)

---

## 2. Create the database

Open **SQL Editor → New query**, paste the entire contents of
[`supabase/schema.sql`](../supabase/schema.sql), and **Run**. It is idempotent
(safe to re-run). This creates:

| Table | Purpose |
|---|---|
| `profiles` | `id → auth.users`, `username` (normalized, unique, case-insensitive), `display_username` (original case) |
| `card_progress` | one row per (user, card): due/interval/reps/correct/attempts/updated_at |
| `user_settings` | one JSON row per user (streak, audio, dark, decks, session size, **front-pinyin display**) |
| `login_attempts` | rate-limit counters (server-only, no client access) |

> The per-user **"Hiển thị Pinyin ở mặt trước"** preference is stored inside the
> `user_settings.data` JSON — no schema change is needed for it, and it syncs +
> stays isolated per account automatically. Re-running `schema.sql` on an existing
> project is safe; it adds `display_username` via `add column if not exists`.

RLS is enabled so each user can only read/write their own rows. Two RPCs
(`sync_push_progress`, `sync_push_settings`) implement **latest-updated_at-wins**
so a stale device can never overwrite newer data.

---

## 3. Install the CLI & link

```bash
npm install -g supabase          # or: brew install supabase/tap/supabase
supabase login
supabase link --project-ref <your-project-ref>
```

Set `project_id` in [`supabase/config.toml`](../supabase/config.toml) to your ref.

---

## 4. Set the Edge Function secret

Generate a pepper **once** and set it. Do **not** change it after users exist
(it would invalidate every PIN).

```bash
openssl rand -hex 32                       # copy the output
supabase secrets set PIN_PEPPER=<that-hex-value>
```

`SUPABASE_URL`, `SUPABASE_ANON_KEY`, and `SUPABASE_SERVICE_ROLE_KEY` are injected
automatically into Edge Functions — you do **not** set them.

---

## 5. Deploy the Edge Functions

`register` and `login` are public (no user JWT yet), so JWT verification must be
off. `config.toml` already sets this; deploy each function:

```bash
supabase functions deploy register        --no-verify-jwt
supabase functions deploy login           --no-verify-jwt
supabase functions deploy change-pin      --no-verify-jwt
supabase functions deploy delete-account  --no-verify-jwt
```

(The `--no-verify-jwt` flag matches `config.toml`; `change-pin` / `delete-account`
verify the caller's access token inside the function.)

Verify in **Dashboard → Edge Functions** that all four are deployed.

---

## 6. Turn it on in the frontend

Edit `hsk_flashcard_app/supabase-config.js`:

```js
window.SUPABASE_CONFIG = {
  url: "https://<ref>.supabase.co",
  anonKey: "<anon public key>"
};
```

Commit + deploy. On next load the app shows the **Login / Register** gate.
(Leaving the fields blank reverts to local-only mode instantly.)

---

## 6b. Local development

Use the existing **`run.bat`** (double-click it, or run it in a terminal):

```bat
run.bat        :: starts  python -m http.server 8000  in the repo root
```

Then open <http://localhost:8000/hsk_flashcard_app/>. Test in a real browser
(not just an in-editor preview). With `supabase-config.js` blank you are testing
local-only mode; fill it in to test the account gate against your project.

## 7. Render configuration

This stays a **Static Site**. No build command, no server, no env vars on Render
(the browser config lives in `supabase-config.js`, the secrets live in Supabase).

- **Publish directory:** repository root (served at `/hsk_flashcard_app/`), or set
  the root to `hsk_flashcard_app` if you prefer the app at `/`.
- Ensure the Supabase project URL is reachable over HTTPS (it is by default).
- No CORS config needed on Render; the Edge Functions return permissive CORS
  headers, and Supabase REST/Auth allow browser origins by default.

If you later add a strict Content-Security-Policy, allow `connect-src` to
`https://<ref>.supabase.co`.

---

## 8. Migration (existing local progress)

Nothing to run server-side. The **first time** a user logs in on a device that
has legacy progress, the app asks: **Import / Skip / View Summary**.

- Import merges local cards the cloud does not already have (never overwrites
  newer cloud data) and uploads them.
- Local data is **never deleted**, even after import.
- The prompt is shown once per account per device.

---

## 9. Rollback

Because everything is config-gated, rollback is safe and instant:

1. **Disable accounts (fastest):** blank out `url`/`anonKey` in
   `supabase-config.js` and redeploy. The app returns to local-only mode; all
   existing on-device progress keeps working. No data loss.
2. **Revert code:** `git revert <commit>` (or redeploy the previous build). The
   Supabase project can stay up, unused.
3. **Full teardown:** delete the four Edge Functions and, if desired, drop the
   tables (`drop table ... cascade`) or delete the Supabase project. Do this only
   after exporting any data you want to keep (each user can use **Export
   progress** from the profile menu).

Rolling back the frontend never deletes cloud data; rolling forward again just
re-reads it.

---

## 10. Quick manual test checklist

- Register `test1` / `1234` → auto-login, study a few cards.
- Open a second browser/incognito, register `test2` / `5678`, study different
  cards → confirm the two accounts show **different** progress.
- Log out → log back in as `test1` → progress restored from cloud.
- Change PIN, log out, log in with the new PIN.
- Go offline (DevTools → Network → Offline), study, come back online → the
  profile menu shows "Đã đồng bộ" and the new cards appear on the other device.
- Fail login 5× → 6th attempt returns a 15-minute lockout.
- Delete account → data gone from cloud; local cache cleared.
