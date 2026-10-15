import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const login = await readFile(new URL("../document-locker-login.html", import.meta.url), "utf8");
const dashboard = await readFile(new URL("../document-locker-dashboard.html", import.meta.url), "utf8");
const recovery = await readFile(new URL("../document-locker-recovery.html", import.meta.url), "utf8");
const settings = await readFile(new URL("../document-locker-recovery-settings.html", import.meta.url), "utf8");
const edge = await readFile(new URL("../supabase/functions/document-locker-recovery/index.ts", import.meta.url), "utf8");
const migration = await readFile(new URL("../supabase/migrations/202610140001_document_locker_account_recovery.sql", import.meta.url), "utf8");

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
  assert.match(dashboard, /\.download\(doc\.storage_path\)/);
  assert.match(dashboard, /a\.download=doc\.document_name/);
  assert.match(dashboard, /function deletePrivateDocument/);
  assert.match(dashboard, /storage\.from\(['"]education-documents['"]\)/);
});

test("browser sources do not contain service-role credentials", () => {
  for (const [name, source] of [["login", login], ["dashboard", dashboard], ["recovery", recovery], ["settings", settings]]) {
    assert.doesNotMatch(source, /SUPABASE_SERVICE_ROLE_KEY|service_role/i, name);
  }
});


test("recovery code consumption is transactional and database-only", () => {
  assert.match(edge, /document_recovery_consume_code/);
  assert.match(migration, /document_recovery_consume_code[\s\S]*?for update[\s\S]*?set used_at = now\(\)[\s\S]*?insert into public\.document_recovery_tickets/i);
  assert.match(migration, /grant execute on function public\.document_recovery_consume_code\(text, text, timestamptz\) to service_role/i);
  assert.match(migration, /revoke all on function public\.document_recovery_consume_code\(text, text, timestamptz\) from public, anon, authenticated/i);
  assert.match(migration, /document_recovery_codes_code_hash_uidx/);
});

test("privileged admin endpoints require verified allowlisted AAL2 and fail closed on audit failure", () => {
  assert.match(edge, /user\.email_confirmed_at/);
  assert.match(edge, /adminEmails\.includes/);
  assert.match(edge, /data\.currentLevel !== "aal2"/);
  assert.match(edge, /admin_recovery_decision_attempt/);
  assert.match(edge, /Audit service unavailable\. No decision was applied/);
  assert.match(edge, /admin_recovery_reconciled/);
});

test("interrupted password operations have audited reconciliation and tickets are never reopened", () => {
  assert.match(edge, /admin_reconcile_list/);
  assert.match(edge, /admin_reconcile_ticket/);
  assert.match(edge, /document_recovery_reconciliation/);
  assert.match(edge, /Never clear processing_at or reopen this ticket/);
  assert.match(migration, /outcome_unknown/);
  assert.match(migration, /unique \(ticket_hash\)/);
});

test("cleanup schedule and privileged SQL access controls are declared", () => {
  assert.match(migration, /enable row level security/i);
  assert.match(migration, /revoke all on public\.document_recovery_audit from public, anon, authenticated/i);
  assert.match(migration, /purge_document_recovery_requests/);
  assert.match(migration, /document-recovery-daily-cleanup/);
  assert.match(migration, /document_recovery_cleanup_runs/);
  assert.match(migration, /status = 'failed', error_code = sqlstate/);
  assert.match(migration, /cron\.job_run_details/);
});

test("mobile OTP remains unavailable and email changes use Supabase verification flow", () => {
  assert.match(settings, /client\.auth\.updateUser\(\{email:/);
  assert.match(settings, /verification/i);
  assert.match(settings, /Mobile OTP is unavailable/i);
  assert.doesNotMatch(settings, /sendOtp|verifyOtp|phone:/i);
});


test("admin recovery decision is atomic: request lock, ticket, decision and outcome audit share one RPC transaction", () => {
  assert.match(migration, /function public\.document_recovery_admin_decide\([\s\S]*?for update[\s\S]*?insert into public\.document_recovery_tickets[\s\S]*?update public\.document_recovery_requests[\s\S]*?insert into public\.document_recovery_audit/i);
  assert.match(migration, /revoke all on function public\.document_recovery_admin_decide\(uuid,text,uuid,uuid,text,text,timestamptz\) from public, anon, authenticated/i);
  assert.match(migration, /grant execute on function public\.document_recovery_admin_decide\(uuid,text,uuid,uuid,text,text,timestamptz\) to service_role/i);
  assert.match(edge, /service\.rpc\("document_recovery_admin_decide"/);
  assert.doesNotMatch(edge, /from\("document_recovery_tickets"\)\.insert\(\{ ticket_hash:ticketHash, user_id:verifiedUserId/);
});

test("admin decision audit failure rolls back approval and ticket creation at database transaction boundary", () => {
  const rpc = migration.slice(migration.indexOf("create or replace function public.document_recovery_admin_decide"));
  assert.match(rpc, /insert into public\.document_recovery_audit/);
  assert.match(rpc, /return query select target\.id,effective_user,target\.new_email,p_decision/);
  assert.match(rpc, /for update/);
});

test("email-change flow does not manually mark a proposed email as confirmed", () => {
  assert.match(settings, /auth\.updateUser\(\{\s*email:/);
  assert.doesNotMatch(settings, /email_confirm:\s*true|email_confirmed_at\s*=/);
  assert.match(settings, /verification/i);
});
