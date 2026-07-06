-- Notification delivery + agent-freshness automation (applied 2026-07-06).
-- Two pg_cron jobs make delivery + staleness detection independent of the
-- scheduled agent (CCR Routine) sessions, whose MCP connectors flap at startup.
--
-- Activate delivery by filling dispatch_config: set `ghl_pit` (HighLevel email)
-- and/or `slack_webhook_url`. Until then the edge function is dormant (claims
-- nothing) and Ax's hourly sweep remains the primary dispatcher.

create extension if not exists pg_cron;
create extension if not exists pg_net;

-- Service-role-only config for the dispatch-notify edge function.
create table if not exists public.dispatch_config (
  key text primary key,
  value text not null,
  updated_at timestamptz not null default now()
);
alter table public.dispatch_config enable row level security;

insert into public.dispatch_config (key, value) values
  ('cron_secret', encode(gen_random_bytes(24),'hex')),  -- sent by cron as x-cron-secret
  ('ghl_pit', ''),                                       -- HighLevel PIT (email delivery)
  ('ghl_location_id', 'nHLCxHPidnhV1NFzRtZZ'),           -- KTU location
  ('email_from', 'Axyom <noreply@ktuleads.com>'),
  ('default_recipient', 'stevenglivingston@gmail.com'),
  ('slack_webhook_url', '')                              -- optional Slack incoming webhook
on conflict (key) do nothing;

-- Agent freshness watchdog: flag stale daily-agent sections, write them to
-- system_health, and queue one alert per stale section per day.
create or replace function public.check_agent_freshness()
returns void language plpgsql security definer set search_path = public as $$
declare
  tracked text[] := array['moola_briefing','goldeneye_callouts','foreman_briefing',
                          'paid_brief','pipeline_briefing','organic_report','tekky_status'];
  rec record;
begin
  delete from public.intranet_records where section = 'system_health';
  for rec in
    select s as section,
           (select max((r.fields->>'scan_date')::date)
              from public.intranet_records r where r.section = s) as latest
    from unnest(tracked) s
  loop
    if rec.latest is null or rec.latest < current_date - 1 then
      insert into public.intranet_records(section, brand, sort_order, fields)
      values ('system_health', 'Both', 1, jsonb_build_object(
        'agent', rec.section,
        'severity', case when rec.latest is null then 'urgent' else 'warn' end,
        'title', rec.section || ' is stale',
        'latest_scan_date', coalesce(rec.latest::text, 'never'),
        'checked_at', now()));
      if not exists (
        select 1 from public.notify_queue
        where source = 'freshness:' || rec.section || ':' || current_date::text
      ) then
        insert into public.notify_queue(kind, subject, body, source)
        values ('system',
          '[Axyom] Agent stale: ' || rec.section,
          'The ' || rec.section || ' section has not updated (latest: ' ||
            coalesce(rec.latest::text, 'never') || '). Its scheduled run may be failing.',
          'freshness:' || rec.section || ':' || current_date::text);
      end if;
    end if;
  end loop;
end $$;
revoke all on function public.check_agent_freshness() from anon, authenticated;

-- Per-minute dispatcher (auth via dispatch_config.cron_secret).
select cron.schedule('dispatch-notify', '* * * * *', $cron$
  select net.http_post(
    url := 'https://tguwpswcneywvscxzyef.supabase.co/functions/v1/dispatch-notify',
    headers := jsonb_build_object(
      'Content-Type', 'application/json',
      'x-cron-secret', (select value from public.dispatch_config where key = 'cron_secret')),
    body := '{}'::jsonb,
    timeout_milliseconds := 8000);
$cron$);

-- Hourly freshness watchdog.
select cron.schedule('agent-freshness-watchdog', '10 * * * *', $cron$
  select public.check_agent_freshness();
$cron$);
