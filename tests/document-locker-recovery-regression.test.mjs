import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const login = await readFile(new URL("../../document-locker-login.html", import.meta.url), "utf8");
const dashboard = await readFile(new URL("../../document-locker-dashboard.html", import.meta.url), "utf8");
const recovery = await readFile(new URL("../../document-locker-recovery.html", import.meta.url), "utf8");
const settings = await readFile(new URL("../../document-locker-recovery-settings.html", import.meta.url), "utf8");

test("existing Email OTP password recovery remains present", () => {
  assert.match(login, /resetPasswordForEmail/);
  assert.match(login, /verifyOtp/);
  assert.match(login, /updateUser\(\{\s*password/);
});

test("login and dashboard recovery navigation exists", () => {
  assert.match(login, /document-locker-recovery\.html/);
  assert.match(dashboard, /document-locker-recovery-settings\.html/);
  assert.match(recovery, /Recovery Code/i);
  assert.match(settings, /Generate \/ Regenerate Recovery Code/);
});

test("private document access keeps owner checks and private bucket usage", () => {
  assert.match(dashboard, /function openPrivateDocument/);
  assert.match(dashboard, /\.eq\('user_id',currentUser\.id\)/);
  assert.match(dashboard, /createSignedUrl/);
  assert.match(dashboard, /download\s*:/);
  assert.match(dashboard, /function deletePrivateDocument/);
  assert.match(dashboard, /storage\.from\(['"]education-documents['"]\)/);
});

test("browser sources do not contain service-role credentials", () => {
  for (const [name, source] of [["login", login], ["dashboard", dashboard], ["recovery", recovery], ["settings", settings]]) {
    assert.doesNotMatch(source, /SUPABASE_SERVICE_ROLE_KEY|service_role/i, name);
  }
});
