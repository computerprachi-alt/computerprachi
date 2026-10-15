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
4. The migration attempts to schedule `public.purge_document_recovery_requests()` daily through Supabase Cron at 03:17 UTC if `pg_cron` is available. After applying in staging, verify the job in `cron.job`, inspect `cron.job_run_details`, and configure alerting for failed/missing runs. A migration declaration is not evidence that the scheduler actually ran.
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


## Added security hardening and crash reconciliation
- Recovery-code redemption is performed by `document_recovery_consume_code`, which locks the matching row and atomically marks the code used while inserting its ticket. A unique index prevents duplicate stored code hashes. The RPC is revoked from browser roles and executable only by `service_role`.
- Recovery code issuance and verification withhold the code/ticket if their audit event cannot be written. Admin request-list access and decision attempts are audited before privileged data/mutations are returned/applied. If the final decision audit fails, the one-time ticket is revoked/withheld.
- For a ticket stuck in `processing_at` for over five minutes, AAL2 administrators can use `admin_reconcile_list` and `admin_reconcile_ticket`. Reconciliation requires a rationale and one of `password_changed_confirmed`, `password_not_changed_confirmed`, or `outcome_unknown`; it is append-only and **never unlocks or replays the old ticket**. If another attempt is needed, begin a fresh independently verified recovery.
- Static regression assertions cover the source-level security invariants. They are not substitutes for executing the migration, deployed Edge Function, Supabase Auth confirmation behavior, MFA, concurrency, or failure injection against a dedicated staging project.
- The normal authenticated `auth.updateUser({ email })` path must honor the project's actual email confirmation policy. This branch does not bypass old-email confirmation and does not yet prove the special case where the user has lost the old email. Do not deploy until a supported, independently verified new-email confirmation path for admin-assisted recovery has been implemented and exercised in staging.
- Recovery code is currently generated on demand from Recovery Settings after sign-in; it is not automatically shown during registration. Existing users can generate/regenerate it after login.
- Mobile OTP is intentionally unavailable. No simulated OTP is sent.


## GitHub Actions: secure staging workflow (manual setup required)
- `.github/workflows/document-locker-recovery.yml` is the unprivileged pull-request workflow. It has `contents: read`, runs type-check and source-level tests only, and does not reference Supabase secrets or run live integration tests.
- `.github/workflows/document-locker-recovery-staging.yml` is a separate `workflow_dispatch` workflow. It requires the operator to type `STAGING`, supply the exact reviewed 40-character commit SHA, and uses the protected GitHub Environment `document-locker-staging`. It checks out that exact commit with `persist-credentials: false`, verifies the commit is reachable from `feature/document-locker-account-recovery`, rejects known production URLs, and only then runs staging tests. It has read-only repository permissions.
- **This YAML does not create or prove Environment protection.** Before use, a repository administrator must create Settings → Environments → `document-locker-staging`, configure required reviewers (at least one trusted reviewer who is not the workflow initiator where GitHub's plan/settings support that restriction), restrict deployment branches to `feature/document-locker-account-recovery` or an explicitly approved reviewed branch, and add only disposable-staging values as Environment secrets/variables. Do not put these values in repository-level Actions secrets.
- Set Environment variable `RECOVERY_TEST_ALLOW_STAGING=YES` and `RECOVERY_TEST_BASE_URL` to the disposable staging Supabase URL. Set Environment secrets `RECOVERY_TEST_ANON_KEY`, `RECOVERY_TEST_USER_ACCESS_TOKEN`, and `RECOVERY_TEST_ADMIN_ACCESS_TOKEN` (the last must be a dedicated allowlisted administrator's current AAL2 session token); set `RECOVERY_TEST_NEW_PASSWORD` only if intentionally running the destructive password-change test against the synthetic staging user. Never add a production URL, service-role key, customer data, or production credentials. The service-role key is not needed by this client-side test job; it belongs only in the staging Edge Function's server-side configuration.
- A Supabase access token is a bearer credential. Its lifetime depends on the staging project's Auth JWT/session settings; this repository workflow cannot determine its expiry from the token without decoding/validating its claims against the project configuration. Prefer a dedicated synthetic test user, the shortest practical session lifetime, a fresh token provisioned immediately before the approved run, and immediate revocation/rotation afterward. Never echo the token or include it in test output. Do not use a production user token.
- **Review-before-secrets rule:** before approving the Environment gate, inspect the exact `reviewed_commit` diff, the workflow YAML, every test file and every script/action it can execute. A protected Environment prevents secrets from being released before approval, but it does not make malicious reviewed code safe.
- The staging workflow is manually triggered only; pull-request runs never receive staging secrets and never run live integration tests. Do not use `pull_request_target` to execute untrusted PR code.
- The Environment, required reviewers, branch restrictions, variables and secrets are manual GitHub Settings tasks. This change does not configure them via API and does not claim they are already enabled.
- Staging integration tests must not be reported as passed unless the manually approved workflow actually runs with the protected Environment and its test results show the tests executed (not ignored/skipped). This workflow does not apply migrations or deploy the Edge Function; those are separate, explicit staging-only setup steps.


## Atomic admin decision hardening (current branch update)
- Admin approve/reject now calls the service-role-only `document_recovery_admin_decide` PostgreSQL RPC. It locks the pending request row, validates the requested state, creates an approval ticket (approval only), updates the request and writes the decision/ticket audit rows in one database transaction. If any database/audit insert fails, the transaction rolls back. The separate decision-attempt audit is written before calling the RPC.
- The Edge Function still performs confirmed-email allowlist and current AAL2 checks before the RPC. The RPC is not callable by `anon` or `authenticated`; only `service_role` may execute it.
- Source-level regression assertions were added for the atomic transaction and the email UI not marking a proposed address as confirmed. These assertions do not prove PostgreSQL behavior until the migration is applied and tests run in disposable staging.

## Remaining release blockers — do not deploy or mark Ready
- Registration-time Recovery Code generation/display is **not implemented**. Current code issuance is authenticated, on-demand from Recovery Settings. Do not claim every new registrant receives a code automatically.
- Lost-old-email recovery is **not complete**. The recovery request stores a proposed new email and the approved ticket currently changes the password only. The user must then sign in and use Supabase's regular email-change flow; depending on the project's Secure Email Change settings, that may require confirmation at the old address. Do not bypass Supabase confirmation or mark the new address confirmed manually. A supported, verified new-email ownership flow for this exact case remains required.
- Real staging integration validation (concurrency, expiry, AAL2 admin, password-update ambiguity/failure, email confirmation and cleanup cron execution/alerts) remains pending until a dedicated disposable staging project and protected GitHub Environment are configured and an approved run actually executes. Skipped tests are not passes.

- Recovery Codes now expire 365 days after issuance; the atomic consume RPC rejects expired codes, and the active daily cleanup function deletes expired or already-consumed code rows. This is migration/source evidence only until staging confirms the schema and cleanup job execution.
