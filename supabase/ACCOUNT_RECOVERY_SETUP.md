# Document Locker account recovery — deployment checklist

This branch is a **review-only proposal**. No migration or Edge Function has been applied/deployed to production.

## Components
- `document-locker-recovery-settings.html`: signed-in user generates/regenerates a Recovery Code.
- `document-locker-recovery.html`: public Recovery Code flow and admin-review request form.
- `document-locker-recovery-admin.html`: admin review UI; route is not a security boundary.
- `supabase/functions/document-locker-recovery/index.ts`: server-side hashing, single-use recovery tickets, request handling and allowlist-protected review.
- `supabase/migrations/202610140001_document_locker_account_recovery.sql`: private tables, RLS/revokes, rate-attempt helper and retention routine.
- `supabase/config.toml`: disables gateway JWT enforcement for the mixed public/authenticated function; protected actions validate the bearer token in the handler.

## Required setup before testing in a non-production Supabase project
1. Review the migration and apply it to a disposable development/staging project first. The production project currently has no recorded migrations through the management API; do not infer that it is safe to apply this migration directly.
2. Deploy the Edge Function to staging with the Supabase CLI or dashboard, including `supabase/config.toml`. The function expects Supabase's `SUPABASE_URL`, `SUPABASE_ANON_KEY`, and `SUPABASE_SERVICE_ROLE_KEY` server environment variables. Never put the service-role key in HTML or commit it.
3. Set server-side secret `RECOVERY_ADMIN_EMAILS` to a comma-separated allowlist of exact administrator email addresses. Use individual, protected administrator accounts with MFA. Do not put this allowlist in client code.
4. Configure a daily trusted scheduler to invoke `public.purge_document_recovery_requests()` using a server-side privileged context. The SQL function is defined, but this branch does not schedule it automatically.
5. Confirm Supabase Auth's existing email confirmation and password policies. Existing Email OTP recovery code is left in place. Mobile OTP remains unavailable.
6. Run the tests below in staging before considering a production rollout.

## Admin verification procedure
The current schema does not contain verified parent-name fields, so submitted names/DOB are **not** automatically linked to an account. An administrator must independently verify ownership, obtain the target Auth user UUID from a trusted admin console, record a concise review rationale, and approve/reject. An approval creates a 24-hour one-time ticket shown only to an allowlisted administrator. Deliver it only through a separately verified channel. The claimant sets a password, signs in, then changes email through Supabase Auth and completes Supabase's email verification. Do not use the new email from the form as proof by itself.

## Retention
Identity-bearing requests expire after 30 days and are removed by `purge_document_recovery_requests()`; attempts older than 24 hours and expired/used tickets are also purged. Audit entries intentionally omit submitted names, dates of birth, contact addresses and review notes. The cleanup routine must be scheduled and verified operationally.

## Test checklist (not yet run against staging)
- Generate and regenerate code; confirm old code fails and only hash is stored.
- Valid code succeeds once; invalid, expired and reused code fail generically.
- Repeated requests return HTTP 429 after the configured attempt threshold.
- No token/code returned to unauthenticated or non-allowlisted admin clients.
- Admin list/decision denied to ordinary users; public users cannot set status or approve.
- Approved ticket expires, is single-use, and can update password only once.
- New password login and subsequent email change/verification succeed.
- Existing Email OTP flow, dashboard navigation and private document operations remain unchanged.
- Confirm scheduler removes identity data after 30 days.
