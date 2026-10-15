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
The function compares registered name and date of birth to identify a possible candidate only when there is a unique match. This candidate match is not proof and cannot approve a request; parent names are not stored in the current profile schema. An administrator must independently verify ownership, obtain the target Auth user UUID from a trusted admin console, record a concise review rationale, and approve/reject. An approval creates a 24-hour one-time ticket shown only to an allowlisted administrator. Deliver it only through a separately verified channel. The claimant sets a password, signs in, then changes email through Supabase Auth and completes Supabase's email verification. Do not use the new email from the form as proof by itself.

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


## Security-fix branch update (review carefully)
- Admin actions now require a confirmed, allowlisted email and an Authenticator Assurance Level of `aal2` from Supabase Auth. This must be verified with a staging account that has enrolled MFA; merely configuring `RECOVERY_ADMIN_EMAILS` is not enough.
- Rate-attempt RPC now takes a transaction-scoped advisory lock for each hashed attempt key before counting/inserting, preventing parallel requests from sharing the same stale count.
- Ticket completion claims a ticket using `processing_at IS NULL`; explicit password-update failures release the claim for retry. A server crash during the Auth update can leave the ticket processing and require administrator support. The ticket is deliberately not reclaimed automatically because Auth update outcome may be uncertain and replay could reset the password again.
- Admin approval now inserts the hashed ticket before conditionally changing the request from Pending. If the compare-and-set status update loses a race, the unused ticket is deleted.
- Migration now schedules `purge_document_recovery_requests()` daily using Supabase Cron at 03:17 UTC if `pg_cron` is available. After applying in staging, verify the job in `cron.job`, inspect `cron.job_run_details` daily, and alert on failed or missing runs. The SQL migration has not been applied by this PR.
- Added `index.test.ts` integration tests and a GitHub Actions type-check/test workflow. Tests requiring a real disposable staging user are skipped unless `RECOVERY_TEST_ALLOW_STAGING=YES` plus explicit staging URL/key/user token are set. The test refuses the known production Supabase URL and production website domain.
- Email change remains a manual authenticated Supabase Auth flow after password recovery. This does **not yet guarantee recovery when the old email confirmation is required by the project's Auth settings**. Do not claim the no-old-email recovery requirement is complete until this exact flow is implemented and tested without weakening email verification.
- Recovery code is generated from authenticated Recovery Settings, not automatically displayed at registration. If product requirements require first-time code generation during registration, implement and test that separately before marking the full requirement complete.
- Parent names and date of birth are collected as supporting details, not treated as proof. Current schema does not contain independently verified parent-name fields; admin must use a separate trusted verification process.
- CI and integration results must be checked on the new PR commit; this local tool session did not run Deno or apply a migration.

## Follow-up security hardening (code changes; staging verification still required)
- Recovery Code redemption now calls `document_recovery_consume_code`, a service-role-only PostgreSQL function that locks the matching code row, marks it used, and inserts the short-lived ticket in one transaction. Concurrent verifiers should receive at most one ticket, and a crash cannot leave a ticket issued without consuming the code. Apply the updated migration to a disposable staging database before deploying the function.
- If Supabase Auth returns an error during a password update, the function now treats the outcome as potentially ambiguous and keeps the ticket's processing claim. It no longer automatically releases the ticket for replay. Support must independently verify the account and issue a fresh recovery ticket if needed; never assume an Auth error proves the password was unchanged.
- The above are source-level changes only. Deno checks, SQL migration execution, concurrency tests, Auth fault-injection tests and staging end-to-end tests have not yet been run.
- **Known unresolved requirement:** changing email when the claimant cannot access the old email has not been demonstrated under this project's actual Supabase Auth confirmation settings. Do not bypass email verification or set the new address as confirmed merely to avoid the old-email confirmation. This PR is not production-ready until a secure recovery-authorized email-change flow is implemented and tested.
