// POST /functions/v1/delete-account  { pin }   (Authorization: Bearer <access_token>)
// Verifies the PIN, then permanently deletes the auth user (cascades all data).
import {
  corsHeaders, json, adminClient, validPin, emailFor, deriveSecret, passwordGrant,
} from "../_shared/utils.ts";

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: corsHeaders });
  if (req.method !== "POST") return json({ error: "method not allowed" }, 405);

  const authz = req.headers.get("Authorization") || "";
  const token = authz.replace(/^Bearer\s+/i, "");
  if (!token) return json({ error: "unauthorized" }, 401);

  let body: any;
  try { body = await req.json(); } catch { return json({ error: "bad request" }, 400); }
  const pin = String(body.pin ?? "");
  if (!validPin(pin)) return json({ error: "invalid pin" }, 400);

  const admin = adminClient();

  const { data: got, error } = await admin.auth.getUser(token);
  if (error || !got?.user) return json({ error: "unauthorized" }, 401);
  const uid = got.user.id;

  const { data: prof } = await admin.from("profiles").select("username").eq("id", uid).maybeSingle();
  if (!prof?.username) return json({ error: "profile not found" }, 404);

  // Confirm identity with the PIN before destroying data.
  const secret = await deriveSecret(prof.username, pin);
  const ok = await passwordGrant(emailFor(prof.username), secret);
  if (!ok) return json({ error: "invalid credentials" }, 401);

  // ON DELETE CASCADE removes profiles / card_progress / user_settings.
  const { error: dErr } = await admin.auth.admin.deleteUser(uid);
  if (dErr) return json({ error: "delete failed" }, 500);
  await admin.from("login_attempts").delete().eq("username", prof.username);

  return json({ ok: true });
});
