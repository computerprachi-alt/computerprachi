-- Computer Prachi Document Locker account recovery
-- Apply only after review in a non-production Supabase environment.
create extension if not exists pgcrypto;

create table if not exists public.document_recovery_codes (
  user_id uuid primary key references auth.users(id) on delete cascade,
  code_hash text not null,
  created_at timestamptz not null default now(),
  used_at timestamptz,
  updated_at timestamptz not null default now(),
  expires_at timestamptz not null default (now() + interval '365 days')
);
alter table public.document_recovery_codes add column if not exists expires_at timestamptz not null default (now() + interval '365 days');
alter table public.document_recovery_codes enable row level security;
revoke all on public.document_recovery_codes from public, anon, authenticated;

create table if not exists public.document_recovery_attempts (
  id bigint generated always as identity primary key,
  attempt_key text not null,
  attempted_at timestamptz not null default now(),
  succeeded boolean not null default false
);
create index if not exists document_recovery_attempts_key_time_idx
  on public.document_recovery_attempts(attempt_key, attempted_at desc);
alter table public.document_recovery_attempts enable row level security;
revoke all on public.document_recovery_attempts from public, anon, authenticated;

create table if not exists public.document_recovery_requests (
  id uuid primary key default gen_random_uuid(),
  account_user_id uuid references auth.users(id) on delete set null,
  registered_full_name text not null,
  date_of_birth date,
  mother_name text,
  father_name text,
  new_email text not null,
  status text not null default 'pending' check (status in ('pending','approved','rejected')),
  reviewer_user_id uuid references auth.users(id) on delete set null,
  reviewed_at timestamptz,
  review_notes text,
  created_at timestamptz not null default now(),
  expires_at timestamptz not null default (now() + interval '30 days'),
  completed_at timestamptz
);
create index if not exists document_recovery_requests_status_created_idx
  on public.document_recovery_requests(status, created_at);
alter table public.document_recovery_requests enable row level security;
revoke all on public.document_recovery_requests from public, anon, authenticated;

create table if not exists public.document_recovery_tickets (
  ticket_hash text primary key,
  user_id uuid not null references auth.users(id) on delete cascade,
  recovery_request_id uuid references public.document_recovery_requests(id) on delete cascade,
  expires_at timestamptz not null,
  used_at timestamptz,
  processing_at timestamptz,
  created_at timestamptz not null default now()
);
alter table public.document_recovery_tickets enable row level security;
revoke all on public.document_recovery_tickets from public, anon, authenticated;

create table if not exists public.document_recovery_audit (
  id bigint generated always as identity primary key,
  event_type text not null,
  user_id uuid references auth.users(id) on delete set null,
  request_id uuid,
  actor_user_id uuid references auth.users(id) on delete set null,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);
alter table public.document_recovery_audit enable row level security;
revoke all on public.document_recovery_audit from public, anon, authenticated;

-- Private, server-only RPC helpers. Edge Functions use the service role; browser roles cannot call these.
create or replace function public.document_recovery_record_attempt(p_attempt_key text, p_success boolean default false)
returns table(allowed boolean, attempts integer)
language plpgsql security definer set search_path = ''
as $$
declare n integer;
begin
  if p_attempt_key is null or length(p_attempt_key) < 32 or length(p_attempt_key) > 128 then
    return query select false, 0; return;
  end if;
  -- Serialize each key so concurrent requests cannot all pass the same count.
  perform pg_advisory_xact_lock(hashtextextended(p_attempt_key, 0));
  delete from public.document_recovery_attempts where attempted_at < now() - interval '24 hours';
  select count(*)::integer into n from public.document_recovery_attempts
    where attempt_key = p_attempt_key and attempted_at > now() - interval '15 minutes';
  if n >= 8 then return query select false, n; return; end if;
  insert into public.document_recovery_attempts(attempt_key, succeeded) values (p_attempt_key, coalesce(p_success,false));
  return query select true, n + 1;
end $$;
revoke all on function public.document_recovery_record_attempt(text, boolean) from public, anon, authenticated;
grant execute on function public.document_recovery_record_attempt(text, boolean) to service_role;

comment on table public.document_recovery_requests is 'PII retention: purge rejected/expired requests and identity fields after 30 days; retain only non-identifying audit metadata as required.';

-- Daily trusted scheduler and monitoring. Review failures in cron.job_run_details.
create extension if not exists pg_cron with schema pg_catalog;
create or replace function public.purge_document_recovery_requests()
returns integer
language plpgsql security definer set search_path = ''
as $$
declare removed integer;
begin
  delete from public.document_recovery_requests
    where created_at < now() - interval '30 days'
       or expires_at < now() - interval '30 days';
  get diagnostics removed = row_count;
  delete from public.document_recovery_attempts where attempted_at < now() - interval '24 hours';
  delete from public.document_recovery_codes where expires_at < now() or used_at is not null;
  delete from public.document_recovery_tickets where expires_at < now() or used_at is not null;
  return removed;
end $$;
revoke all on function public.purge_document_recovery_requests() from public, anon, authenticated;
grant execute on function public.purge_document_recovery_requests() to service_role;

-- Schedule once after verifying pg_cron is enabled for the project.
do $$
begin
  if not exists (select 1 from cron.job where jobname = 'document-recovery-daily-cleanup') then
    perform cron.schedule('document-recovery-daily-cleanup', '17 3 * * *', 'select public.purge_document_recovery_requests();');
  end if;
end $$;


-- Atomically consume a Recovery Code and issue its ticket in one transaction.
-- This closes the crash/race window between inserting a ticket and marking the code used.
create or replace function public.document_recovery_consume_code(
  p_code_hash text,
  p_ticket_hash text,
  p_expires_at timestamptz
)
returns uuid
language plpgsql
security definer
set search_path = ''
as $$
declare
  target_user uuid;
begin
  if p_code_hash is null or length(p_code_hash) <> 64
     or p_ticket_hash is null or length(p_ticket_hash) <> 64
     or p_expires_at is null or p_expires_at <= now()
     or p_expires_at > now() + interval '15 minutes' then
    return null;
  end if;

  select user_id into target_user
    from public.document_recovery_codes
    where code_hash = p_code_hash and used_at is null and expires_at > now()
    for update;

  if target_user is null then
    return null;
  end if;

  update public.document_recovery_codes
    set used_at = now(), updated_at = now()
    where user_id = target_user and code_hash = p_code_hash and used_at is null;

  if not found then
    return null;
  end if;

  insert into public.document_recovery_tickets(ticket_hash, user_id, expires_at)
    values (p_ticket_hash, target_user, p_expires_at);

  return target_user;
end;
$$;
revoke all on function public.document_recovery_consume_code(text, text, timestamptz) from public, anon, authenticated;
grant execute on function public.document_recovery_consume_code(text, text, timestamptz) to service_role;


-- Append-only reconciliation evidence for interrupted/ambiguous password updates.
-- A reconciliation never reopens a ticket; recovery must restart with fresh verification.
create table if not exists public.document_recovery_reconciliation (
  id bigint generated always as identity primary key,
  ticket_hash text not null references public.document_recovery_tickets(ticket_hash) on delete cascade,
  actor_user_id uuid not null references auth.users(id),
  outcome text not null check (outcome in ('password_changed_confirmed','password_not_changed_confirmed','outcome_unknown')),
  rationale text not null check (length(trim(rationale)) >= 10),
  created_at timestamptz not null default now(),
  unique (ticket_hash)
);
alter table public.document_recovery_reconciliation enable row level security;
revoke all on public.document_recovery_reconciliation from public, anon, authenticated;

-- One stored code hash must map to at most one account, protecting atomic redemption assumptions.
create unique index if not exists document_recovery_codes_code_hash_uidx
  on public.document_recovery_codes(code_hash);


-- Record cleanup outcomes for operational monitoring. Cron job history remains the scheduler-level signal.
create table if not exists public.document_recovery_cleanup_runs (
  id bigint generated always as identity primary key,
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  deleted_requests integer not null default 0,
  status text not null check (status in ('running','succeeded','failed')),
  error_code text
);
alter table public.document_recovery_cleanup_runs enable row level security;
revoke all on public.document_recovery_cleanup_runs from public, anon, authenticated;

create or replace function public.purge_document_recovery_requests()
returns integer
language plpgsql
security definer
set search_path = ''
as $$
declare
  run_id bigint;
  removed integer := 0;
begin
  insert into public.document_recovery_cleanup_runs(status)
    values ('running') returning id into run_id;
  begin
    delete from public.document_recovery_requests
      where created_at < now() - interval '30 days'
         or expires_at < now() - interval '30 days';
    get diagnostics removed = row_count;
    delete from public.document_recovery_attempts where attempted_at < now() - interval '24 hours';
    delete from public.document_recovery_codes where expires_at < now() or used_at is not null;
    delete from public.document_recovery_tickets where expires_at < now() or used_at is not null;
    update public.document_recovery_cleanup_runs
      set finished_at = now(), deleted_requests = removed, status = 'succeeded'
      where id = run_id;
    return removed;
  exception when others then
    update public.document_recovery_cleanup_runs
      set finished_at = now(), status = 'failed', error_code = sqlstate
      where id = run_id;
    raise;
  end;
end;
$$;
revoke all on function public.purge_document_recovery_requests() from public, anon, authenticated;
grant execute on function public.purge_document_recovery_requests() to service_role;


-- Atomically decide an admin recovery request, create (or withhold) its ticket,
-- and write the durable decision audit event in the same transaction.
-- The Edge Function must authenticate the allowlisted AAL2 administrator before calling this RPC.
create or replace function public.document_recovery_admin_decide(
  p_request_id uuid,
  p_decision text,
  p_verified_user_id uuid,
  p_actor_user_id uuid,
  p_review_notes text,
  p_ticket_hash text,
  p_ticket_expires_at timestamptz
)
returns table(request_id uuid, account_user_id uuid, new_email text, decision text)
language plpgsql
security definer
set search_path = ''
as $$
declare
  target public.document_recovery_requests%rowtype;
  effective_user uuid;
begin
  if p_request_id is null
     or p_decision not in ('approved','rejected')
     or p_actor_user_id is null
     or p_review_notes is null
     or length(trim(p_review_notes)) < 10 then
    raise exception 'invalid recovery decision' using errcode = '22023';
  end if;

  if p_decision = 'approved' then
    if p_verified_user_id is null
       or p_ticket_hash is null or length(p_ticket_hash) <> 64
       or p_ticket_expires_at is null
       or p_ticket_expires_at <= now()
       or p_ticket_expires_at > now() + interval '24 hours' then
      raise exception 'invalid approval ticket' using errcode = '22023';
    end if;
  elsif p_verified_user_id is not null or p_ticket_hash is not null or p_ticket_expires_at is not null then
    raise exception 'rejection must not create a recovery ticket' using errcode = '22023';
  end if;

  select * into target
    from public.document_recovery_requests
    where id = p_request_id
    for update;

  if not found or target.status <> 'pending' or target.expires_at <= now() then
    raise exception 'request is not pending or has expired' using errcode = '40001';
  end if;

  effective_user := case when p_decision = 'approved' then p_verified_user_id else null end;

  if p_decision = 'approved' then
    insert into public.document_recovery_tickets(ticket_hash,user_id,recovery_request_id,expires_at)
      values (p_ticket_hash,effective_user,p_request_id,p_ticket_expires_at);
  end if;

  update public.document_recovery_requests
    set status = p_decision,
        account_user_id = effective_user,
        reviewer_user_id = p_actor_user_id,
        reviewed_at = now(),
        review_notes = p_review_notes
    where id = p_request_id and status = 'pending';

  if not found then
    raise exception 'request decision lost a race' using errcode = '40001';
  end if;

  insert into public.document_recovery_audit(event_type,user_id,request_id,actor_user_id,metadata)
    values ('admin_recovery_request_' || p_decision,effective_user,p_request_id,p_actor_user_id,
      jsonb_build_object('decision',p_decision));

  if p_decision = 'approved' then
    insert into public.document_recovery_audit(event_type,user_id,request_id,actor_user_id,metadata)
      values ('admin_recovery_ticket_created',effective_user,p_request_id,p_actor_user_id,
        jsonb_build_object('ticket_hash_prefix',left(p_ticket_hash,12)));
  end if;

  return query select target.id,effective_user,target.new_email,p_decision;
end;
$$;
revoke all on function public.document_recovery_admin_decide(uuid,text,uuid,uuid,text,text,timestamptz) from public, anon, authenticated;
grant execute on function public.document_recovery_admin_decide(uuid,text,uuid,uuid,text,text,timestamptz) to service_role;
