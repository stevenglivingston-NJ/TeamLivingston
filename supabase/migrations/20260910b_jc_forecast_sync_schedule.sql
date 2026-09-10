-- Job costing, part 5: the forecast (SOLD-side) ETL becomes serverless.
--
-- `mcp-servers/jc-forecast-sync.py` only ever ran when a person ran it, which
-- meant a newly sold job had no forecast lines until someone remembered. The
-- same logic now lives in the `jc-forecast-sync` Edge Function, driven by
-- pg_cron. Nothing about it depends on a workstation being switched on, and --
-- unlike a scheduled agent session -- there is no model and no connector
-- classifier in the path, so it cannot stall the way the Routines documented in
-- CLAUDE.md did.
--
-- Split into two modes so each invocation stays well inside the function time
-- budget:
--   index -- page ServiceMinder invoices once a day, cache contact -> proposal
--   jobs  -- refresh a small batch of the stalest jobs, every few minutes
--
-- Applied 2026-09-10.

-- Which jobs are stalest. Nulls first, so a brand-new job is picked up next tick.
alter table public.jc_jobs
  add column if not exists forecast_synced_at timestamptz;

-- Cached ServiceMinder contact -> accepted-proposal map. Proposals are only
-- queryable while OPEN, so they are discovered invoice-first (an invoice keeps
-- its ProposalId forever); this table is that discovery, made durable.
create table if not exists public.jc_sm_proposal_index (
  brand          text not null,
  sm_contact_id  bigint not null,
  proposal_id    bigint not null,
  seen_at        timestamptz not null default now(),
  primary key (brand, sm_contact_id, proposal_id)
);

-- Run log, so a silent failure is visible instead of just producing stale data.
create table if not exists public.jc_sync_runs (
  id         uuid primary key default gen_random_uuid(),
  ran_at     timestamptz not null default now(),
  mode       text not null,
  ok         boolean not null default true,
  jobs_done  int  not null default 0,
  sm_lines   int  not null default 0,
  jt_lines   int  not null default 0,
  detail     jsonb
);
create index if not exists jc_sync_runs_ran_idx on public.jc_sync_runs(ran_at desc);

alter table public.jc_sm_proposal_index enable row level security;
alter table public.jc_sync_runs         enable row level security;

drop policy if exists jc_sm_idx_read on public.jc_sm_proposal_index;
create policy jc_sm_idx_read on public.jc_sm_proposal_index
  for select to authenticated using (public.has_jc_access());

drop policy if exists jc_sync_runs_read on public.jc_sync_runs;
create policy jc_sync_runs_read on public.jc_sync_runs
  for select to authenticated using (public.has_jc_access());

-- Freshness signal for the intranet + the watchdog: how long since a good run.
create or replace function public.jc_sync_health() returns jsonb
language sql stable security definer set search_path = public as $$
  select jsonb_build_object(
    'last_ok_jobs_run',  (select max(ran_at) from jc_sync_runs where mode='jobs'  and ok),
    'last_ok_index_run', (select max(ran_at) from jc_sync_runs where mode='index' and ok),
    'failures_24h',      (select count(*)   from jc_sync_runs where not ok and ran_at > now() - interval '24 hours'),
    'jobs_never_synced', (select count(*)   from jc_jobs where forecast_synced_at is null),
    'stalest_job_hours', (select round(extract(epoch from (now() - min(coalesce(forecast_synced_at, 'epoch'::timestamptz))))/3600)
                            from jc_jobs)
  );
$$;
revoke all on function public.jc_sync_health() from public, anon;
grant execute on function public.jc_sync_health() to authenticated, service_role;

-- ---------------------------------------------------------------------------
-- Schedules
-- ---------------------------------------------------------------------------
select cron.unschedule('jc-forecast-index')
 where exists (select 1 from cron.job where jobname = 'jc-forecast-index');
select cron.unschedule('jc-forecast-jobs')
 where exists (select 1 from cron.job where jobname = 'jc-forecast-jobs');

-- Rebuild the proposal index once a day, early, before the job batches run.
select cron.schedule('jc-forecast-index', '5 6 * * *', $cron$
  select net.http_post(
    url     := 'https://tguwpswcneywvscxzyef.supabase.co/functions/v1/jc-forecast-sync',
    headers := jsonb_build_object(
                 'Content-Type', 'application/json',
                 'x-cron-secret', (select value from public.dispatch_config where key = 'cron_secret')),
    body    := '{"mode":"index"}'::jsonb,
    timeout_milliseconds := 150000);
$cron$);

-- Refresh the stalest jobs every 10 minutes: 48 jobs cycle in well under an hour,
-- and a job sold this morning has forecast lines by lunchtime.
select cron.schedule('jc-forecast-jobs', '*/10 * * * *', $cron$
  select net.http_post(
    url     := 'https://tguwpswcneywvscxzyef.supabase.co/functions/v1/jc-forecast-sync',
    headers := jsonb_build_object(
                 'Content-Type', 'application/json',
                 'x-cron-secret', (select value from public.dispatch_config where key = 'cron_secret')),
    body    := '{"mode":"jobs","batch":10}'::jsonb,
    timeout_milliseconds := 150000);
$cron$);
