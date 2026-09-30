-- pg_cron run-log retention (2026-09-30). APPLIED LIVE 2026-09-30.
--
-- cron.job_run_details had grown to 264K rows / 162 MB (every run since
-- 2026-07-06; the */10 and hourly jobs add ~3.5K rows a day), and queries
-- against it were timing out. That table is what morning_health_digest reads
-- for failed runs (last 24h), so it has to stay queryable.
--
-- One-time purge done by hand in weekly chunks (a single delete hit the
-- statement timeout). This job keeps 7 days from now on; one day's delete is
-- a few thousand rows. Autovacuum reuses the freed space.

select cron.unschedule('cron-log-cleanup') where exists (select 1 from cron.job where jobname = 'cron-log-cleanup');
select cron.schedule('cron-log-cleanup', '17 4 * * *',
  $$ delete from cron.job_run_details where end_time < now() - interval '7 days' $$);
