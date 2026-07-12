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
  url: "https://evksxsrlhpkjvgsbvlhu.supabase.co",
  anonKey: "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImV2a3N4c3JsaHBranZnc2J2bGh1Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODM4MTU5ODQsImV4cCI6MjA5OTM5MTk4NH0.Vd3u-I0eKsv18qbUJSRastiMzb-j8USW1TB_YSExFYw"
};