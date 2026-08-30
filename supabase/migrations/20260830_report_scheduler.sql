-- Report scheduler + cancellation watch (2026-08-30)
-- ---------------------------------------------------------------------------
-- Three pieces:
--   report_schedules   when a report goes out, how often, and to whom.
--                      Editable from the intranet (Reports tab, admin only).
--   report_snapshots   the latest rendered body for each report key. Agents and
--                      scripts write here; the dispatcher only reads.
--   enqueue_due_reports()  hourly pg_cron job. Finds due schedules, drops one
--                      notify_queue row per recipient, advances the schedule.
--
-- The split matters: generating a report and delivering it are separate
-- failures. If a generator stops running the dispatcher sends nothing new
-- rather than re-sending stale numbers, and the intranet shows the snapshot
-- age so a silent generator failure is visible instead of looking fresh.

create table if not exists public.report_schedules (
  key            text primary key,
  name           text not null,
  description    text default '',
  tab            text default 'reports',        -- intranet tab this report lives on
  frequency      text not null default 'weekly' -- daily | weekly | monthly | off
                 check (frequency in ('daily','weekly','monthly','off')),
  day_of_week    int  default 1                 -- 0=Sun … 6=Sat, weekly only
                 check (day_of_week between 0 and 6),
  day_of_month   int  default 1                 -- monthly only
                 check (day_of_month between 1 and 28),
  hour_local     int  not null default 7        -- send hour, America/New_York
                 check (hour_local between 0 and 23),
  recipients     text[] not null default '{}',
  enabled        boolean not null default true,
  last_sent_at   timestamptz,
  last_result    text,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);

create table if not exists public.report_snapshots (
  report_key   text primary key references public.report_schedules(key) on delete cascade,
  generated_at timestamptz not null default now(),
  subject      text not null,
  body         text not null,
  metrics      jsonb not null default '{}'::jsonb
);

alter table public.report_schedules enable row level security;
alter table public.report_snapshots enable row level security;

-- Schedules are owner-controlled; snapshots are readable by any signed-in user
-- so the intranet can show the numbers without exposing recipient lists.
drop policy if exists report_schedules_admin on public.report_schedules;
create policy report_schedules_admin on public.report_schedules
  for all to authenticated using (public.is_admin()) with check (public.is_admin());

drop policy if exists report_snapshots_read on public.report_snapshots;
create policy report_snapshots_read on public.report_snapshots
  for select to authenticated using (true);

create or replace function public.touch_report_schedule()
returns trigger language plpgsql as $$
begin new.updated_at = now(); return new; end $$;
drop trigger if exists trg_touch_report_schedule on public.report_schedules;
create trigger trg_touch_report_schedule before update on public.report_schedules
  for each row execute function public.touch_report_schedule();

-- Is this schedule due right now? Evaluated in America/New_York so the "Monday
-- 7am" a human configured stays Monday 7am across DST changes.
create or replace function public.report_is_due(s public.report_schedules, now_utc timestamptz)
returns boolean language plpgsql immutable as $$
declare
  -- `timestamptz at time zone 'America/New_York'` converts to naive local time.
  -- Chaining `at time zone 'UTC'` first double-converts and shifts the hour.
  loc timestamp := now_utc at time zone 'America/New_York';
  lastloc timestamp;
begin
  if not s.enabled or s.frequency = 'off' or coalesce(array_length(s.recipients,1),0) = 0 then
    return false;
  end if;
  if extract(hour from loc)::int < s.hour_local then return false; end if;

  if s.frequency = 'weekly' and extract(dow from loc)::int <> s.day_of_week then return false; end if;
  if s.frequency = 'monthly' and extract(day from loc)::int <> s.day_of_month then return false; end if;

  if s.last_sent_at is null then return true; end if;
  lastloc := s.last_sent_at at time zone 'America/New_York';
  -- one send per calendar day, and never twice in the same period
  return lastloc::date < loc::date;
end $$;

create or replace function public.enqueue_due_reports()
returns int language plpgsql security definer set search_path = public as $$
declare
  s public.report_schedules;
  snap public.report_snapshots;
  rcpt text;
  n int := 0;
  stamp text;
begin
  for s in select * from public.report_schedules loop
    if not public.report_is_due(s, now()) then continue; end if;

    select * into snap from public.report_snapshots where report_key = s.key;
    if snap.report_key is null then
      update public.report_schedules
         set last_result = 'skipped — no snapshot has ever been generated'
       where key = s.key;
      continue;
    end if;
    -- Never mail numbers the generator has not refreshed for this period.
    if snap.generated_at < now() - interval '8 days' then
      update public.report_schedules
         set last_result = 'skipped — snapshot is stale (' || snap.generated_at::date || ')'
       where key = s.key;
      continue;
    end if;

    stamp := s.key || ':' || (now() at time zone 'America/New_York')::date::text;
    foreach rcpt in array s.recipients loop
      if exists (select 1 from public.notify_queue where source = stamp || ':' || rcpt) then
        continue;
      end if;
      insert into public.notify_queue(kind, recipient_email, subject, body, source)
      values ('report', rcpt, snap.subject, snap.body, stamp || ':' || rcpt);
      n := n + 1;
    end loop;

    update public.report_schedules
       set last_sent_at = now(),
           last_result  = 'queued for ' || coalesce(array_length(s.recipients,1),0) || ' recipient(s)'
     where key = s.key;
  end loop;
  return n;
end $$;
revoke all on function public.enqueue_due_reports() from anon, authenticated;

-- Hourly. The per-schedule hour_local check inside decides what actually fires,
-- so a missed hour (maintenance, outage) still sends later the same day rather
-- than silently skipping the week.
select cron.unschedule('report-dispatch') where exists (select 1 from cron.job where jobname='report-dispatch');
select cron.schedule('report-dispatch', '20 * * * *', $cron$ select public.enqueue_due_reports(); $cron$);

-- Seed: the consultation cancellation watch Steven asked for.
insert into public.report_schedules (key, name, description, tab, frequency, day_of_week, hour_local, recipients)
values (
  'cancel_watch',
  'Consultation Cancellation Watch',
  'Weekly KTU in-home consultation cancellation rate against the 24% allowed ceiling, with every cancellation outside the allowed reasons named and its replacement-lead cost.',
  'reports', 'weekly', 1, 7,
  array['byabra@kitchentuneup.com','SLivingston@kitchentuneup.com','sonya@goaxyom.com']
)
on conflict (key) do update
  set name = excluded.name,
      description = excluded.description,
      recipients = excluded.recipients;
