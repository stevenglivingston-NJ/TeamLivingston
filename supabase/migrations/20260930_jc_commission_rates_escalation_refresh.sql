-- Commission rates + live escalation reasons (2026-09-30). APPLIED LIVE 2026-09-30.
--
-- 1) Commission: Steven, 2026-09-30 -- "use the 12% for KTU and the 8% for BTU".
--    Every job gets its brand rate (25 jobs had none; KTU jobs were at the 8%
--    default). Note the design doc says 8% default / 12% self-generated; no
--    per-job source for self-gen exists, so the brand rate applies to all.
--    The Foreman seed's own commission rows (8%) move to
--    jc_forecast_lines_superseded so the job rate is the one forecast.
-- 2) jc_refresh_escalations(): the reason was written once (coalesce) and kept
--    the GM from the day it was flagged. It now refreshes on every run for
--    unapproved rows. Approved rows are never rewritten or cleared -- their
--    reason carries the approver's note ("... — approved: <why>").

update public.jc_jobs set commission_pct = case brand when 'KTU' then 0.12 when 'BTU' then 0.08 end
 where brand in ('KTU','BTU');

with moved as (
  delete from public.jc_forecast_lines f
   where f.source = 'foreman_estimate' and f.category = 'sales_commission'
  returning f.*
)
insert into public.jc_forecast_lines_superseded select m.*, now() from moved m;

select public.jc_refresh_commission_lines();

create or replace function public.jc_refresh_escalations()
 returns jsonb language plpgsql security definer set search_path to 'public' as $function$
declare n int;
begin
  update payables p set
    escalation_required = true,
    -- The reason states the BASIS, because an escalation raised on an estimate
    -- and one raised on measured cost are different decisions. Coverage 0% means
    -- no vendor invoices have landed yet and the GM rests on the forecast.
    escalation_reason =
      'Job projected GM ' || public.jc_job_gm(p.job_id) || '% is below the 45% floor ('
      || case when public.jc_job_cost_coverage(p.job_id) >= 25
              then 'measured, ' else 'ESTIMATE-based, ' end
      || public.jc_job_cost_coverage(p.job_id) || '% cost coverage)'
  where p.status <> 'paid' and p.job_id is not null
    and coalesce(p.escalation_approved_by,'') = ''
    and public.jc_job_gm(p.job_id) < 45;
  get diagnostics n = row_count;
  update payables p set escalation_required = false, escalation_reason = null
  where p.status <> 'paid' and p.escalation_required
    and coalesce(p.escalation_approved_by,'') = ''
    and (p.job_id is null or public.jc_job_gm(p.job_id) >= 45);
  return jsonb_build_object('escalations_flagged', n);
end $function$;

select public.jc_refresh_escalations();
