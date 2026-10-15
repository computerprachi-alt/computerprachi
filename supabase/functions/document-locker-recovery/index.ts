import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const url = Deno.env.get("SUPABASE_URL")!;
const anonKey = Deno.env.get("SUPABASE_ANON_KEY")!;
const serviceKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
const adminEmails = (Deno.env.get("RECOVERY_ADMIN_EMAILS") || "").split(",").map(v => v.trim().toLowerCase()).filter(Boolean);
const service = createClient(url, serviceKey, { auth: { persistSession: false, autoRefreshToken: false } });
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json", "cache-control": "no-store", "access-control-allow-origin": "https://computerprachi.online", "access-control-allow-headers": "authorization, apikey, content-type", "access-control-allow-methods": "POST, OPTIONS" } });
const sha = async (s: string) => Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s)))).map(b => b.toString(16).padStart(2,"0")).join("");
const randomToken = (n = 32) => { const b = crypto.getRandomValues(new Uint8Array(n)); return Array.from(b).map(x => x.toString(16).padStart(2,"0")).join(""); };
const clean = (s: unknown, max = 180) => typeof s === "string" ? s.trim().replace(/[\u0000-\u001f\u007f]/g, "").slice(0,max) : "";
async function authContext(req: Request) {
  const h = req.headers.get("authorization") || "";
  if (!h.startsWith("Bearer ")) return null;
  const client = createClient(url, anonKey, { auth: { persistSession: false, autoRefreshToken: false }, global: { headers: { Authorization: h } } });
  const { data, error } = await client.auth.getUser();
  if (error || !data.user) return null;
  return { user: data.user, client };
}
async function userFromRequest(req: Request) {
  return (await authContext(req))?.user ?? null;
}
async function requireAdminMfa(req: Request) {
  const context = await authContext(req);
  const user = context?.user;
  if (!user?.email || !user.email_confirmed_at || !adminEmails.includes(user.email.toLowerCase())) return null;
  // Require a current AAL2 session; allowlist membership alone is not MFA.
  const { data, error } = await context!.client.auth.mfa.getAuthenticatorAssuranceLevel();
  if (error || data.currentLevel !== "aal2") return null;
  return user;
}
async function rate(key: string) {
  const { data, error } = await service.rpc("document_recovery_record_attempt", { p_attempt_key: await sha(key), p_success: false });
  return !error && !!data?.[0]?.allowed;
}
async function audit(event_type: string, user_id: string | null = null, request_id: string | null = null, actor_user_id: string | null = null, metadata = {}) {
  const { error } = await service.from("document_recovery_audit").insert({ event_type, user_id, request_id, actor_user_id, metadata });
  if (error) console.error("recovery audit write failed", { event_type, code: error.code });
}
function validEmail(v: string) { return v.length <= 254 && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v); }

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return json({});
  if (req.method !== "POST") return json({ error: "Method not allowed" }, 405);
  let body: Record<string, unknown>;
  try { body = await req.json(); } catch { return json({ error: "Invalid request" }, 400); }
  const action = clean(body.action, 40);
  const ip = clean(req.headers.get("cf-connecting-ip") || req.headers.get("x-forwarded-for") || "unknown", 100).split(",")[0];
  if (!(await rate("ip:" + ip))) return json({ error: "Too many attempts. Try again later." }, 429);

  if (action === "issue_code") {
    const user = await userFromRequest(req);
    if (!user) return json({ error: "Authentication required" }, 401);
    const code = "CPR-" + randomToken(20).toUpperCase().match(/.{1,5}/g)!.join("-");
    const code_hash = await sha(code);
    const { error } = await service.from("document_recovery_codes").upsert({ user_id: user.id, code_hash, used_at: null, created_at: new Date().toISOString(), updated_at: new Date().toISOString() });
    if (error) return json({ error: "Could not create a recovery code. Try again later." }, 500);
    await audit("recovery_code_issued", user.id, null, user.id);
    return json({ code, message: "Save this code securely. It is shown only once; regenerating invalidates the previous code." });
  }

  if (action === "verify_code") {
    const code = clean(body.code, 120).toUpperCase();
    if (!/^CPR-(?:[A-F0-9]{5}-){7}[A-F0-9]{5}$/.test(code) || !(await rate("code:" + await sha(code)))) {
      return json({ message: "If the recovery details are valid, next steps will be provided." }, 200);
    }
    const hash = await sha(code);
    const ticket = randomToken(32), ticket_hash = await sha(ticket);
    // The database RPC locks and consumes the code and inserts the ticket in one transaction.
    // If the request races or the server crashes, no second ticket can be issued from this code.
    const { data: consumedUserId, error: consumeError } = await service.rpc("document_recovery_consume_code", {
      p_code_hash: hash,
      p_ticket_hash: ticket_hash,
      p_expires_at: new Date(Date.now()+10*60*1000).toISOString()
    });
    const userId = typeof consumedUserId === "string" ? consumedUserId : null;
    if (consumeError || !userId) {
      if (consumeError) console.error("atomic recovery-code consumption failed", { code: consumeError.code });
      return json({ message: "If the recovery details are valid, next steps will be provided." }, 200);
    }
    await audit("recovery_code_verified", userId);
    return json({ ticket, message: "Code verified. Set a new password now. You can update and verify your email after signing in." });
  }

  if (action === "submit_request") {
    const fullName = clean(body.registeredFullName, 120), dob = clean(body.dateOfBirth, 10);
    const mother = clean(body.motherName, 120), father = clean(body.fatherName, 120), newEmail = clean(body.newEmail, 254).toLowerCase();
    if (fullName.length < 2 || !/^\d{4}-\d{2}-\d{2}$/.test(dob) || !validEmail(newEmail)) return json({ message: "If the request can be accepted, instructions will be provided through the new contact method." });
    // Match registered name and DOB to create an internal candidate only. This is not proof of ownership
    // and cannot approve the request. The administrator must independently verify ownership and explicitly
    // supply the target Auth user UUID when approving. Parent names are not stored in the current profile schema.
    const { data: candidates } = await service.from("document_profiles").select("id").ilike("full_name", fullName).eq("date_of_birth", dob).limit(2);
    const matchedUser: string | null = candidates?.length === 1 ? candidates[0].id : null;
    const { error } = await service.from("document_recovery_requests").insert({
      account_user_id: matchedUser, registered_full_name: fullName, date_of_birth: dob,
      mother_name: mother || null, father_name: father || null, new_email: newEmail
    });
    if (error) return json({ message: "If the request can be accepted, instructions will be provided through the new contact method." });
    await audit("admin_recovery_request_submitted", matchedUser);
    return json({ message: "Your request has been received for manual review. For your safety, we cannot confirm account matches here. Do not submit identity documents unless an administrator asks through an official channel." });
  }

  if (action === "complete_recovery") {
    const ticket = clean(body.ticket, 128), password = typeof body.password === "string" ? body.password : "";
    if (ticket.length < 40 || password.length < 12 || password.length > 128) return json({ error: "Use a password of at least 12 characters and a valid recovery session." }, 400);
    const hash = await sha(ticket);
    const { data: t } = await service.from("document_recovery_tickets").select("ticket_hash,user_id,recovery_request_id,expires_at,used_at").eq("ticket_hash",hash).maybeSingle();
    if (!t || t.used_at || new Date(t.expires_at).getTime() < Date.now()) return json({ error: "Recovery session expired or invalid. Start again." }, 400);
    const now = new Date().toISOString();
    const { data: claimed } = await service.from("document_recovery_tickets").update({ processing_at: now }).eq("ticket_hash",hash).is("used_at",null).is("processing_at",null).gt("expires_at",now).select("user_id,recovery_request_id");
    if (!claimed?.length) return json({ error: "Recovery session expired, invalid, or already in use. If a server interruption occurred, contact support rather than retrying this ticket." }, 400);
    const { error } = await service.auth.admin.updateUserById(t.user_id, { password });
    if (error) {
      // Auth/network errors can be ambiguous: the Auth service may have applied the password
      // update before the response was lost. Never release the ticket for replay on an
      // ambiguous result. Keep processing_at set and require administrator reconciliation
      // and a newly verified recovery ticket if necessary.
      await audit("recovery_password_update_outcome_uncertain",t.user_id,t.recovery_request_id,null,{ auth_error_code: error.status || "unknown" });
      return json({ error: "The password update result could not be confirmed. For your security this ticket is locked against replay; contact support for a fresh verified recovery." }, 503);
    }
    const { error: finalizeError } = await service.from("document_recovery_tickets").update({ used_at: new Date().toISOString(), processing_at: null }).eq("ticket_hash",hash).is("used_at",null).not("processing_at","is",null);
    if (finalizeError) {
      console.error("ticket finalize failed after password update", { code: finalizeError.code });
      return json({ error: "Password update succeeded but recovery finalization needs administrator attention. Do not retry this ticket." }, 500);
    }
    if (t.recovery_request_id) {
      await service.from("document_recovery_requests").update({ completed_at: new Date().toISOString() }).eq("id",t.recovery_request_id).eq("status","approved");
    }
    await audit("recovery_password_updated",t.user_id,t.recovery_request_id);
    return json({ message: "Password updated. Sign in with your account email, then change your email in account settings and complete Supabase's email verification before using the new address." });
  }

  if (action === "admin_list" || action === "admin_decide") {
    const user = await requireAdminMfa(req);
    if (!user) return json({ error: "Not authorized. A verified allowlisted administrator with an AAL2 session is required." }, 403);
    if (action === "admin_list") {
      const { data, error } = await service.from("document_recovery_requests").select("id,registered_full_name,date_of_birth,mother_name,father_name,new_email,status,created_at,expires_at").eq("status","pending").order("created_at",{ascending:true}).limit(100);
      if (error) return json({ error: "Unable to load requests" }, 500);
      return json({ requests: data || [] });
    }
    const id = clean(body.requestId, 50), decision = clean(body.decision, 20), notes = clean(body.reviewNotes, 500), verifiedUserId = clean(body.verifiedUserId, 50);
    if (!/^[0-9a-f-]{36}$/i.test(id) || !["approved","rejected"].includes(decision) || notes.length < 10) return json({ error: "A valid request, decision and review notes are required." },400);
    const { data: request } = await service.from("document_recovery_requests").select("id,account_user_id,status,expires_at").eq("id",id).maybeSingle();
    if (!request || request.status !== "pending" || new Date(request.expires_at).getTime() < Date.now() || (decision === "approved" && !/^[0-9a-f-]{36}$/i.test(verifiedUserId))) return json({ error: "Request cannot be reviewed or lacks an administrator-verified account match." },400);
    if (decision === "approved") {
      const { data: authTarget, error: targetError } = await service.auth.admin.getUserById(verifiedUserId);
      if (targetError || !authTarget?.user) return json({ error: "The verified account could not be found." },400);
    }
    let approvedTicket: string | null = null;
    let ticketHash: string | null = null;
    if (decision === "approved") {
      approvedTicket = randomToken(32);
      ticketHash = await sha(approvedTicket);
      const { error: ticketError } = await service.from("document_recovery_tickets").insert({ ticket_hash:ticketHash, user_id:verifiedUserId, recovery_request_id:id, expires_at:new Date(Date.now()+24*60*60*1000).toISOString() });
      if (ticketError) return json({ error: "Request could not be approved. Contact the system administrator." },500);
    }
    const { data: changed } = await service.from("document_recovery_requests").update({ status:decision, account_user_id:decision === "approved" ? verifiedUserId : null, reviewer_user_id:user.id, reviewed_at:new Date().toISOString(), review_notes:notes }).eq("id",id).eq("status","pending").select("id,account_user_id,new_email").maybeSingle();
    if (!changed) {
      if (ticketHash) await service.from("document_recovery_tickets").delete().eq("ticket_hash",ticketHash).is("used_at",null);
      return json({ error: "Request was already reviewed." },409);
    }
    if (decision === "approved") {
      await audit("admin_recovery_ticket_created",changed.account_user_id,id,user.id);
      // The raw ticket is returned only once to an allowlisted AAL2 administrator.
    }
    await audit("admin_recovery_request_"+decision,changed.account_user_id,id,user.id);
    return json(decision === "approved" ? { message: "Approved. Deliver the one-time ticket only through an independently verified channel. It expires in 24 hours.", ticket: approvedTicket } : { message: "Request rejected. The claimant receives no recovery ticket." });
  }
  return json({ error: "Unknown action" }, 400);
});
