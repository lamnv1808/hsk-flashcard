// ============================================================
//  Supabase configuration — PUBLIC values only.
// ------------------------------------------------------------
//  Leave BOTH fields blank to keep the app in LOCAL-ONLY mode
//  (exactly the current behavior — no accounts, no sync).
//
//  Fill them in AFTER you create your Supabase project to turn
//  on the Login / Register gate and cloud sync automatically.
//
//  `anonKey` is the PUBLIC anon key — it is safe to ship to the
//  browser and is protected by Row Level Security.
//  NEVER put the service_role key or any secret here.
// ============================================================
window.SUPABASE_CONFIG = {
  url: "",      // e.g. "https://abcdefghijkl.supabase.co"
  anonKey: ""   // e.g. "eyJhbGciOiJIUzI1NiIsInR5cCI6..."
};
