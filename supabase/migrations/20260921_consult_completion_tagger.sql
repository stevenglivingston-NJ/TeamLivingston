-- Consult completion tagger: schema + cron schedule.
--
-- 12h after a consultation appointment ends, if it wasn't cancelled/no-show,
-- stamp appointment details onto the matching HighLevel contact and re-apply
-- the `appointment-completed` tag, in the correct brand sub-account.
--
-- Follows the same pattern as 20260910b_jc_forecast_sync_schedule.sql:
-- pg_cron + net.http_post, gated by the shared dispatch_config.cron_secret.
--
-- Applied 2026-09-21.

-- ---------------------------------------------------------------------------
-- 1. Secrets (app_secrets: key text PK, value text, updated_at)
-- ---------------------------------------------------------------------------
-- Naming follows the existing brand-suffixed style (GHL_PIT_KTU, SM_KEY_KTU).
-- HL_TOKEN_* are left as empty placeholders -- Steven must fill in real
-- HighLevel Private Integration tokens (scopes: calendars/events.readonly,
-- contacts.write). HL_LOCATION_* are the real, already-confirmed sub-account
-- location ids (same ones mcp-servers/ghl.sh hardcodes).
insert into public.app_secrets (key, value, updated_at) values
  ('HL_TOKEN_KTU', '', now()),
  ('HL_TOKEN_BTU', '', now()),
  ('HL_LOCATION_KTU', 'nHLCxHPidnhV1NFzRtZZ', now()),
  ('HL_LOCATION_BTU', '0uWA8M5BzHrrcJftuaDe', now())
on conflict (key) do nothing;

-- Optional: Takia's notify email for the exhausted-retry alert. Left blank;
-- Steven should fill it in. When blank, that notify_queue row is skipped
-- (Steven's row still goes out via default_recipient).
insert into public.app_secrets (key, value, updated_at) values
  ('NOTIFY_RECIPIENT_TAKIA', '', now())
on conflict (key) do nothing;

comment on table public.app_secrets is
  'Shared secrets/config for edge functions. HL_TOKEN_KTU/HL_TOKEN_BTU and '
  'NOTIFY_RECIPIENT_TAKIA are placeholders as of 2026-09-21 -- fill in before '
  'consult-completion-tagger can do real work.';

-- ---------------------------------------------------------------------------
-- 2. Config table: consult_calendars
-- ---------------------------------------------------------------------------
create table if not exists public.consult_calendars (
  id          uuid primary key default gen_random_uuid(),
  brand       text not null check (brand in ('KTU','BTU')),
  calendar_id text not null,
  label       text not null,
  active      boolean not null default true,
  created_at  timestamptz not null default now(),
  unique (brand, calendar_id)
);

insert into public.consult_calendars (brand, calendar_id, label, active) values
  ('KTU', 'IezEuyUywqr1OL7tjHEk', 'Consultation Calendar',     true),
  ('KTU', 'PvREY1pwo0f9zciKpcLh', 'Consultation - Virtual',    true),
  ('BTU', 'k6bokOz0oIicKYu93zhW', 'Consultation Calendar',     true),
  ('BTU', 'XAOonStahm7ggE22XyOe', 'Consultation - Showroom',   true)
on conflict (brand, calendar_id) do nothing;

alter table public.consult_calendars enable row level security;
drop policy if exists consult_calendars_read on public.consult_calendars;
create policy consult_calendars_read on public.consult_calendars
  for select to authenticated using (true);

-- ---------------------------------------------------------------------------
-- 3. Log table: consult_completion_log (idempotency key = hl_event_id)
-- ---------------------------------------------------------------------------
create table if not exists public.consult_completion_log (
  id             uuid primary key default gen_random_uuid(),
  hl_event_id    text not null unique,
  brand          text not null,
  hl_contact_id  text,
  hl_user_id     text,
  start_time     timestamptz,
  end_time       timestamptz,
  hl_status      text,
  sm_status      text,
  action         text not null check (action in (
                   'tagged','skipped_cancelled','skipped_noshow',
                   'skipped_sm_cancelled','skipped_no_contact','error'
                 )),
  detail         text,
  attempt_count  int not null default 1,
  processed_at   timestamptz not null default now()
);
create index if not exists consult_completion_log_processed_idx
  on public.consult_completion_log (processed_at desc);
create index if not exists consult_completion_log_action_idx
  on public.consult_completion_log (action);

alter table public.consult_completion_log enable row level security;
drop policy if exists consult_completion_log_read on public.consult_completion_log;
create policy consult_completion_log_read on public.consult_completion_log
  for select to authenticated using (true);

-- ---------------------------------------------------------------------------
-- 4. Health/summary function for the intranet panel (mirrors jc_sync_health()).
-- ---------------------------------------------------------------------------
create or replace function public.consult_completion_health() returns jsonb
language sql stable security definer set search_path = public as $$
  select jsonb_build_object(
    'last_run_at', (select max(processed_at) from consult_completion_log),
    'counts_7d', (
      select coalesce(jsonb_object_agg(action, cnt), '{}'::jsonb)
      from (
        select action, count(*) cnt
        from consult_completion_log
        where processed_at > now() - interval '7 days'
        group by action
      ) s
    ),
    'errors_7d', (
      select coalesce(jsonb_agg(jsonb_build_object(
               'hl_event_id', hl_event_id, 'brand', brand,
               'detail', detail, 'attempt_count', attempt_count,
               'processed_at', processed_at
             ) order by processed_at desc), '[]'::jsonb)
      from consult_completion_log
      where action = 'error' and processed_at > now() - interval '7 days'
    ),
    'skipped_sm_cancelled_7d', (
      select coalesce(jsonb_agg(jsonb_build_object(
               'hl_event_id', hl_event_id, 'brand', brand,
               'hl_contact_id', hl_contact_id, 'detail', detail,
               'processed_at', processed_at
             ) order by processed_at desc), '[]'::jsonb)
      from consult_completion_log
      where action = 'skipped_sm_cancelled' and processed_at > now() - interval '7 days'
    )
  );
$$;
revoke all on function public.consult_completion_health() from public, anon;
grant execute on function public.consult_completion_health() to authenticated, service_role;

-- ---------------------------------------------------------------------------
-- 5. Cron schedule -- every 15 minutes, same auth pattern as jc-forecast-sync.
-- ---------------------------------------------------------------------------
select cron.unschedule('consult-completion-tagger')
 where exists (select 1 from cron.job where jobname = 'consult-completion-tagger');

select cron.schedule('consult-completion-tagger', '*/15 * * * *', $cron$
  select net.http_post(
    url     := 'https://tguwpswcneywvscxzyef.supabase.co/functions/v1/consult-completion-tagger',
    headers := jsonb_build_object(
                 'Content-Type', 'application/json',
                 'x-cron-secret', (select value from public.dispatch_config where key = 'cron_secret')),
    body    := '{}'::jsonb,
    timeout_milliseconds := 150000);
$cron$);
