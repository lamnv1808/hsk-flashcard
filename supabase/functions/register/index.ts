// POST /functions/v1/register  { username, pin }
// Creates an account, returns { user, session }. Auto-login on success.
import {
  corsHeaders, json, adminClient, normUser, validUsername, validPin,
  emailFor, deriveSecret, passwordGrant,
} from "../_shared/utils.ts";

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: corsHeaders });
  if (req.method !== "POST") return json({ error: "method not allowed" }, 405);

  let body: any;
  try { body = await req.json(); } catch { return json({ error: "bad request" }, 400); }

  const username = normUser(body.username);
  const pin = String(body.pin ?? "");
  if (!validUsername(username)) return json({ error: "invalid username" }, 400);
  if (!validPin(pin)) return json({ error: "invalid pin" }, 400);

  const admin = adminClient();

  // Uniqueness (case-insensitive).
  const { data: existing } = await admin.from("profiles").select("id").ilike("username", username).maybeSingle();
  if (existing) return json({ error: "username taken" }, 409);

  const secret = await deriveSecret(username, pin);
  const email = emailFor(username);

  const { data: created, error: cErr } = await admin.auth.admin.createUser({
    email, password: secret, email_confirm: true, user_metadata: { username },
  });
  if (cErr || !created?.user) {
    // Most likely the synthetic email already exists -> treat as taken.
    return json({ error: "username taken" }, 409);
  }
  const uid = created.user.id;

  const { error: pErr } = await admin.from("profiles").insert({ id: uid, username });
  if (pErr) {
    await admin.auth.admin.deleteUser(uid); // rollback
    return json({ error: "username taken" }, 409);
  }

  const session = await passwordGrant(email, secret);
  if (!session) return json({ error: "created but sign-in failed; please log in" }, 500);

  return json({ user: { id: uid, username }, session });
});
