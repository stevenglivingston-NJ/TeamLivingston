-- Appointments hub — one row per KTU/BTU ServiceMinder appointment, feeding the
-- intranet Appointments tab (upcoming / past / cancelled) and the Home snapshot.
-- Goldeneye owns population (upsert on appointment_id). next_action /
-- next_action_by are HUMAN-owned (sales-meeting notes) and are never overwritten
-- by the agent — they are excluded from the agent's ON CONFLICT DO UPDATE SET.
create table if not exists public.appointments (
  id uuid primary key default gen_random_uuid(),
  appointment_id bigint,
  brand text,
  contact_id bigint,
  customer_name text,
  customer_phone text,
  customer_email text,
  address text,
  service text,
  service_agent text,
  appt_at timestamptz,
  status text,                       -- scheduled | completed | cancelled | status_0
  bucket text,                       -- upcoming | past | cancelled
  cancel_segment text,               -- follow_up | dead | unknown
  notes text,                        -- appointment-level notes (find_appointment)
  proposal_id bigint,
  proposal_status text,              -- open | accepted | expired | none
  proposal_amount numeric,
  next_action text,                  -- HUMAN-owned, preserved on re-runs
  next_action_by text,               -- HUMAN-owned, preserved on re-runs
  source text default 'serviceminder',
  scan_date date,
  updated_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  unique (appointment_id)
);

alter table public.appointments enable row level security;

-- All authenticated users can read/write the hub (customer-ops data, not
-- sensitive finance). Anon stays blocked.
drop policy if exists appointments_authed on public.appointments;
create policy appointments_authed on public.appointments
  for all to authenticated using (true) with check (true);

-- Realtime so the tab and Home snapshot update live as Goldeneye seeds rows.
do $$
begin
  if not exists (
    select 1 from pg_publication_tables
    where pubname='supabase_realtime' and schemaname='public' and tablename='appointments'
  ) then
    alter publication supabase_realtime add table public.appointments;
  end if;
end $$;
