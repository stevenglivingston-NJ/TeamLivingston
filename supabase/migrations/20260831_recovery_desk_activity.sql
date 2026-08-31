-- Recovery Desk activity log (2026-08-31)
-- ---------------------------------------------------------------------------
-- Who has opened the Recovery Desk, when, roughly how long they stayed, and
-- what they saved. The desk has no per-user login (one shared passcode), so
-- "who" is the first name each person types into the desk once per browser
-- (already stored client-side as localStorage 'ktu-desk-name' and reused as
-- `updated_by` on every save) — this table just also captures it on page
-- views and session length, not only on saves.
--
-- Three event kinds, all written by the Worker after the passcode gate:
--   'view'     — the desk finished loading in a signed-in browser
--   'duration' — sent via navigator.sendBeacon on pagehide; ms on page
--   'save'     — an existing row was edited (mirrors what already updates
--                recovery_desk.updated_by, logged here too for the feed)

create table if not exists public.recovery_desk_activity (
  id          bigint generated always as identity primary key,
  desk        text not null default 'ktu',
  who         text not null default '',
  event       text not null check (event in ('view','duration','save')),
  row_id      text,                    -- set on 'save' events only
  duration_ms integer,                 -- set on 'duration' events only
  at          timestamptz not null default now()
);

create index if not exists recovery_desk_activity_at_idx
  on public.recovery_desk_activity (desk, at desc);

alter table public.recovery_desk_activity enable row level security;

-- The Worker writes with the anon key (same posture as recovery_desk itself)
-- but this table is never read back through that page, so anon may insert
-- only, never select.
drop policy if exists recovery_desk_activity_insert on public.recovery_desk_activity;
create policy recovery_desk_activity_insert on public.recovery_desk_activity
  for insert to anon, authenticated with check (true);

-- Reads are admin-only, via the intranet's authenticated Supabase session —
-- this is usage/monitoring data about the team, not customer data, but it
-- still doesn't belong in front of every logged-in role.
drop policy if exists recovery_desk_activity_select on public.recovery_desk_activity;
create policy recovery_desk_activity_select on public.recovery_desk_activity
  for select to authenticated using (is_admin());
