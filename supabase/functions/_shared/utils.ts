// Shared helpers for the HSK auth Edge Functions.
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

export const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};

export function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...corsHeaders, "Content-Type": "application/json" },
  });
}

export const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
export const ANON_KEY = Deno.env.get("SUPABASE_ANON_KEY")!;
export const SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
export const PEPPER = Deno.env.get("PIN_PEPPER")!;

// Service-role client (bypasses RLS) — used only inside functions, never shipped.
export function adminClient() {
  return createClient(SUPABASE_URL, SERVICE_KEY, { auth: { autoRefreshToken: false, persistSession: false } });
}
// Anon client — used to exchange credentials for a real session.
export function anonClient() {
  return createClient(SUPABASE_URL, ANON_KEY, { auth: { autoRefreshToken: false, persistSession: false } });
}

const USERNAME_RE = /^[a-z0-9._-]{3,20}$/;
const PIN_RE = /^\d{4}$/;
export function normUser(u: unknown) { return String(u ?? "").trim().toLowerCase(); }
export function validUsername(u: string) { return USERNAME_RE.test(u); }
export function validPin(p: unknown) { return PIN_RE.test(String(p ?? "")); }
export function emailFor(username: string) { return `${username}@hsk.local`; }

// Strong credential derived from the PIN. Supabase only ever stores bcrypt(secret),
// so the 4-digit PIN itself is never stored and cannot be brute-forced via the DB.
export async function deriveSecret(username: string, pin: string): Promise<string> {
  const key = await crypto.subtle.importKey(
    "raw", new TextEncoder().encode(PEPPER),
    { name: "HMAC", hash: "SHA-256" }, false, ["sign"],
  );
  const sig = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(`${username}:${pin}`));
  return [...new Uint8Array(sig)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

// ---- rate limiting (per username) ----
const MAX_FAILS = 5;
const LOCK_MINUTES = 15;

export async function checkLock(admin: ReturnType<typeof adminClient>, username: string) {
  const { data } = await admin.from("login_attempts").select("*").eq("username", username).maybeSingle();
  if (data?.locked_until && new Date(data.locked_until).getTime() > Date.now()) return true;
  return false;
}
export async function registerFail(admin: ReturnType<typeof adminClient>, username: string) {
  const { data } = await admin.from("login_attempts").select("*").eq("username", username).maybeSingle();
  const fails = (data?.fails ?? 0) + 1;
  const locked_until = fails >= MAX_FAILS ? new Date(Date.now() + LOCK_MINUTES * 60000).toISOString() : null;
  await admin.from("login_attempts").upsert({ username, fails, locked_until });
}
export async function clearFails(admin: ReturnType<typeof adminClient>, username: string) {
  await admin.from("login_attempts").delete().eq("username", username);
}

// Exchange email+secret for a Supabase session via the anon password grant.
export async function passwordGrant(email: string, secret: string) {
  const res = await fetch(`${SUPABASE_URL}/auth/v1/token?grant_type=password`, {
    method: "POST",
    headers: { "apikey": ANON_KEY, "Content-Type": "application/json" },
    body: JSON.stringify({ email, password: secret }),
  });
  if (!res.ok) return null;
  return await res.json(); // {access_token, refresh_token, expires_in, expires_at, ...}
}
