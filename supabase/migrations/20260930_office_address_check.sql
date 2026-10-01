-- Office-address appointment check moved off Claude Routines (2026-09-30).
-- APPLIED LIVE 2026-09-30. Edge function: supabase/functions/office-address-check.
-- Replaces routine "KTU/BTU — office-address appointment check" (hourly 12-23 UTC).

-- What has already been alerted, so each (contact, appointment time) alerts once
-- and a rescheduled appointment alerts again. Service role only.
create table if not exists public.office_address_alerts (
  brand      text   not null,
  contact_id bigint not null,
  appt_at    text   not null,   -- ServiceMinder DateTime string, as returned
  alerted_at timestamptz not null default now(),
  primary key (brand, contact_id, appt_at)
);
alter table public.office_address_alerts enable row level security;
revoke all on public.office_address_alerts from anon, authenticated;

select cron.unschedule('office-address-check') where exists (select 1 from cron.job where jobname='office-address-check');
select cron.schedule('office-address-check', '7 12-23 * * *', $$
  select net.http_post(
    url     := 'https://tguwpswcneywvscxzyef.supabase.co/functions/v1/office-address-check',
    headers := jsonb_build_object('Content-Type','application/json',
               'x-cron-secret',(select value from public.dispatch_config where key='cron_secret')),
    body    := '{}'::jsonb, timeout_milliseconds := 120000);
$$);
