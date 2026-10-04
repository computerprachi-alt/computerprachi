-- Computer Prachi: additive Supabase migration for tutor registrations
-- Review the duplicate check before running. This migration does not drop or rewrite existing data.
begin;

alter table public.tutor_registrations
  add column if not exists mobile text,
  add column if not exists whatsapp text,
  add column if not exists email text,
  add column if not exists gender text,
  add column if not exists qualification text,
  add column if not exists subjects text,
  add column if not exists classes text,
  add column if not exists board text,
  add column if not exists experience text,
  add column if not exists mode text,
  add column if not exists state text,
  add column if not exists city text,
  add column if not exists area text,
  add column if not exists tuition_fee text,
  add column if not exists available_time text,
  add column if not exists about text,
  add column if not exists payment_status text not null default 'pending',
  add column if not exists review_status text not null default 'pending';

-- Refuse to silently choose between existing duplicate IDs.
do $$
begin
  if exists (
    select 1
    from public.tutor_registrations
    where registration_id is not null
    group by registration_id
    having count(*) > 1
  ) then
    raise exception 'Duplicate registration_id values already exist; resolve them before applying the unique index.';
  end if;
end
$$;

create unique index if not exists tutor_registrations_registration_id_uidx
  on public.tutor_registrations (registration_id)
  where registration_id is not null;

alter table public.tutor_registrations enable row level security;

-- Remove broad anonymous/authenticated table privileges, then grant INSERT only
-- for the submitted registration fields. Payment/review statuses are server defaults
-- and cannot be supplied/changed by anonymous clients.
revoke all on table public.tutor_registrations from anon, authenticated;
grant insert (
  registration_id, name, mobile, whatsapp, email, gender, qualification,
  subjects, classes, board, experience, mode, state, city, area,
  tuition_fee, available_time, about
) on table public.tutor_registrations to anon;

drop policy if exists "Public can submit tutor registrations" on public.tutor_registrations;
create policy "Public can submit tutor registrations"
  on public.tutor_registrations
  for insert
  to anon
  with check (
    nullif(btrim(name), '') is not null
    and nullif(btrim(registration_id), '') is not null
    and payment_status = 'pending'
    and review_status = 'pending'
  );

-- Explicitly prevent public reads or mutations.
drop policy if exists "Public can read tutor registrations" on public.tutor_registrations;
drop policy if exists "Public can update tutor registrations" on public.tutor_registrations;
drop policy if exists "Public can delete tutor registrations" on public.tutor_registrations;
revoke select, update, delete on table public.tutor_registrations from anon, authenticated;

commit;
