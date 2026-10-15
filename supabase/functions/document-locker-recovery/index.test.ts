// Staging-only integration tests for document-locker-recovery Edge Function.
// Run with Deno and environment variables set for a disposable Supabase staging project.
// Never point RECOVERY_TEST_BASE_URL at production.
// Required: RECOVERY_TEST_BASE_URL, RECOVERY_TEST_ANON_KEY, RECOVERY_TEST_USER_ACCESS_TOKEN.
// Optional destructive test: RECOVERY_TEST_NEW_PASSWORD (changes only the dedicated test user's password).
import { assert, assertEquals, assertExists, assertNotEquals } from "jsr:@std/assert";

const base = Deno.env.get("RECOVERY_TEST_BASE_URL")?.replace(/\/$/, "");
const anon = Deno.env.get("RECOVERY_TEST_ANON_KEY");
const userToken = Deno.env.get("RECOVERY_TEST_USER_ACCESS_TOKEN");
const adminToken = Deno.env.get("RECOVERY_TEST_ADMIN_ACCESS_TOKEN");
const enabled = Boolean(Deno.env.get("RECOVERY_TEST_ALLOW_STAGING") === "YES" && base && anon && userToken && !/nnwbezwnwxybwwnhaetw\.supabase\.co|computerprachi\.online/i.test(base));
const newPassword = Deno.env.get("RECOVERY_TEST_NEW_PASSWORD");

async function invoke(action: string, payload: Record<string, unknown> = {}, token?: string) {
  const response = await fetch(base + "/functions/v1/document-locker-recovery", {
    method: "POST",
    headers: { "content-type": "application/json", apikey: anon!, ...(token ? { authorization: "Bearer " + token } : {}) },
    body: JSON.stringify({ action, ...payload }),
  });
  return { response, body: await response.json() };
}

Deno.test({ name: "unknown action is rejected", ignore: !enabled, fn: async () => {
  const { response } = await invoke("not-a-real-action");
  assertEquals(response.status, 400);
}});

Deno.test({ name: "admin endpoints reject unauthenticated callers", ignore: !enabled, fn: async () => {
  const { response } = await invoke("admin_list");
  assertEquals(response.status, 403);
}});

Deno.test({ name: "invalid recovery code returns generic non-enumerating response", ignore: !enabled, fn: async () => {
  const { response, body } = await invoke("verify_code", { code: "CPR-00000-00000-00000-00000-00000-00000-00000-00000" });
  assertEquals(response.status, 200);
  assertExists(body.message);
  assertEquals("user_id" in body, false);
  assertEquals("ticket" in body, false);
}});

Deno.test({ name: "generated code is single-use under concurrent verification", ignore: !enabled, fn: async () => {
  const issued = await invoke("issue_code", {}, userToken!);
  assertEquals(issued.response.status, 200);
  assertExists(issued.body.code);
  const code = issued.body.code as string;
  const pair = await Promise.all([invoke("verify_code", { code }), invoke("verify_code", { code })]);
  const tickets = pair.filter(x => typeof x.body.ticket === "string");
  assertEquals(tickets.length, 1, "exactly one concurrent verifier may receive a ticket");
  assertNotEquals(pair[0].body.ticket, pair[1].body.ticket);
  // Consume/cleanup through the dedicated staging test user only.
  if (newPassword && tickets[0]) {
    const completed = await invoke("complete_recovery", { ticket: tickets[0].body.ticket, password: newPassword });
    assertEquals(completed.response.status, 200);
    const replay = await invoke("complete_recovery", { ticket: tickets[0].body.ticket, password: newPassword });
    assertEquals(replay.response.status, 400);
  }
}});

Deno.test({ name: "malformed/expired/reused ticket cannot reset a password", ignore: !enabled, fn: async () => {
  const { response } = await invoke("complete_recovery", { ticket: "f".repeat(64), password: newPassword || "Staging-Only-Password-123!" });
  assertEquals(response.status, 400);
}});


Deno.test({ name: "ordinary authenticated user without admin AAL2 is denied admin access", ignore: !enabled, fn: async () => {
  const { response } = await invoke("admin_list", {}, userToken!);
  assertEquals(response.status, 403);
}});

Deno.test({ name: "rate limiter eventually returns 429 for repeated requests", ignore: !enabled, fn: async () => {
  let sawLimit = false;
  for (let i = 0; i < 12; i++) {
    const { response } = await invoke("unknown-rate-limit-test-action");
    if (response.status === 429) { sawLimit = true; break; }
  }
  assertEquals(sawLimit, true, "expected server-side per-IP rate limit to reject repeated requests");
}});


Deno.test({ name: "allowlisted staging administrator with an AAL2 session can access the review queue", ignore: !(enabled && adminToken), fn: async () => {
  const { response, body } = await invoke("admin_list", {}, adminToken!);
  assertEquals(response.status, 200, "the staging admin token must belong to an allowlisted, email-confirmed AAL2 administrator");
  assertExists(body.requests);
}});
