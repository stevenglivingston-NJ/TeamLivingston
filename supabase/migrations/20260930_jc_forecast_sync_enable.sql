-- Job-costing forecast sync: switch the pg_cron path on (2026-09-30).
-- APPLIED LIVE 2026-09-30. 20260910b wrote the edge function and its schedule,
-- but neither was ever deployed/applied, so a Claude routine kept running the
-- Python nightly. The function could not have run anyway: its vendor keys were
-- only in the cloud environment. JOBTREAD_GRANT_KEY was copied into
-- app_secrets (RLS on, zero policies = service role only) and the function now
-- reads app_secrets as well as dispatch_config. First run matched the Python
-- output line-for-line (5 jobs, 99 sm_proposal lines).
select cron.unschedule('jc-forecast-index') where exists (select 1 from cron.job where jobname = 'jc-forecast-index');
select cron.unschedule('jc-forecast-jobs')  where exists (select 1 from cron.job where jobname = 'jc-forecast-jobs');
select cron.schedule('jc-forecast-index', '5 6 * * *', $cron$
  select net.http_post(
    url     := 'https://tguwpswcneywvscxzyef.supabase.co/functions/v1/jc-forecast-sync',
    headers := jsonb_build_object('Content-Type','application/json',
                 'x-cron-secret', (select value from public.dispatch_config where key = 'cron_secret')),
    body    := '{"mode":"index"}'::jsonb, timeout_milliseconds := 150000);
$cron$);
select cron.schedule('jc-forecast-jobs', '*/10 * * * *', $cron$
  select net.http_post(
    url     := 'https://tguwpswcneywvscxzyef.supabase.co/functions/v1/jc-forecast-sync',
    headers := jsonb_build_object('Content-Type','application/json',
                 'x-cron-secret', (select value from public.dispatch_config where key = 'cron_secret')),
    body    := '{"mode":"jobs","batch":10}'::jsonb, timeout_milliseconds := 150000);
$cron$);
