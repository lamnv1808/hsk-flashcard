// POST /functions/v1/login  { username, pin }
// Verifies credentials with per-username rate limiting and NO user enumeration.
import {
  corsHeaders, json, adminClient, normUser, validUsername, validPin,
  emailFor, deriveSecret, passwordGrant, checkLock, registerFail, clearFails,
} from "../_shared/utils.ts";

// One generic message so we never reveal whether a username exists.
const GENERIC = "invalid credentials";

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: corsHeaders });
  if (req.method !== "POST") return json({ error: "method not allowed" }, 405);

  let body: any;
  try { body = await req.json(); } catch { return json({ error: "bad request" }, 400); }

  const username = normUser(body.username);
  const pin = String(body.pin ?? "");
  // Invalid format -> generic error (still no enumeration).
  if (!validUsername(username) || !validPin(pin)) return json({ error: GENERIC }, 401);

  const admin = adminClient();

  if (await checkLock(admin, username)) {
    return json({ error: "too many attempts, try again later" }, 429);
  }

  const secret = await deriveSecret(username, pin);
  const session = await passwordGrant(emailFor(username), secret);

  if (!session) {
    await registerFail(admin, username);
    return json({ error: GENERIC }, 401);
  }

  await clearFails(admin, username);

  // Resolve the display username from the profile (fallback to input).
  const uid = session.user?.id;
  let name = username;
  if (uid) {
    const { data: prof } = await admin.from("profiles").select("username").eq("id", uid).maybeSingle();
    if (prof?.username) name = prof.username;
  }

  return json({ user: { id: uid, username: name }, session });
});
