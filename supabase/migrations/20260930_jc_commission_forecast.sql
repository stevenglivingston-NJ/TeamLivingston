-- Job costing: every job's forecast carries its sales commission (2026-09-30).
-- APPLIED LIVE 2026-09-30.
--
-- Only the 19 jobs seeded with a Foreman estimate had a commission cost line.
-- The other jobs forecast NO commission at all, although the job's own
-- commission_pct says one is owed, so their gross margin was overstated by that
-- rate (8% on every job that has one set).
--
-- jc_refresh_commission_lines() writes one source='commission_rate' line per
-- job: (contract_total + added_revenue_post_sale) * commission_pct. It skips a
-- job that already forecasts commission from another source (the Foreman
-- estimate, or a JobTread commission item), and a job whose commission_pct is
-- not set -- that is left for Steven to fill in, not assumed.
-- Recomputed every 10 minutes, just after the forecast sync, so contract or
-- rate changes flow through.

create or replace function public.jc_refresh_commission_lines() returns integer
language plpgsql security definer set search_path = public as $$
declare n integer;
begin
  delete from jc_forecast_lines where source = 'commission_rate';
  insert into jc_forecast_lines (job_id, description, category, qty, unit_cost, forecasted_cost, source)
  select j.id,
         'Sales commission @ ' || round(j.commission_pct * 100, 1) || '% of contract (jc_jobs.commission_pct)',
         'sales_commission', 1, c.amt, c.amt, 'commission_rate'
    from jc_jobs j
   cross join lateral (select round((coalesce(j.contract_total, 0) + coalesce(j.added_revenue_post_sale, 0))
                                    * j.commission_pct, 2) amt) c
   where j.commission_pct > 0 and c.amt > 0
     and not exists (select 1 from jc_forecast_lines f
                      where f.job_id = j.id and f.category = 'sales_commission'
                        and f.source <> 'commission_rate' and coalesce(f.forecasted_cost, 0) > 0);
  get diagnostics n = row_count;
  return n;
end $$;
revoke execute on function public.jc_refresh_commission_lines() from public, anon, authenticated;

select public.jc_refresh_commission_lines();

select cron.unschedule('jc-commission-lines') where exists (select 1 from cron.job where jobname = 'jc-commission-lines');
select cron.schedule('jc-commission-lines', '3-59/10 * * * *', $$ select public.jc_refresh_commission_lines(); $$);
