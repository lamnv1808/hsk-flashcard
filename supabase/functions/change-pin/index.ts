// POST /functions/v1/change-pin  { oldPin, newPin }   (Authorization: Bearer <access_token>)
// Verifies the old PIN, then updates the derived credential.
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
  const oldPin = String(body.oldPin ?? "");
  const newPin = String(body.newPin ?? "");
  if (!validPin(oldPin) || !validPin(newPin)) return json({ error: "invalid pin" }, 400);

  const admin = adminClient();

  // Identify the caller from their JWT.
  const { data: got, error } = await admin.auth.getUser(token);
  if (error || !got?.user) return json({ error: "unauthorized" }, 401);
  const uid = got.user.id;

  const { data: prof } = await admin.from("profiles").select("username").eq("id", uid).maybeSingle();
  if (!prof?.username) return json({ error: "profile not found" }, 404);
  const username = prof.username;

  // Verify the OLD pin by attempting a sign-in with its derived secret.
  const oldSecret = await deriveSecret(username, oldPin);
  const ok = await passwordGrant(emailFor(username), oldSecret);
  if (!ok) return json({ error: "invalid credentials" }, 401);

  const newSecret = await deriveSecret(username, newPin);
  const { error: uErr } = await admin.auth.admin.updateUserById(uid, { password: newSecret });
  if (uErr) return json({ error: "update failed" }, 500);

  return json({ ok: true });
});
