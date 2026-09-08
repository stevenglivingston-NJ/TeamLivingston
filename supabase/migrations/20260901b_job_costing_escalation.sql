-- Job Costing, part 2 — margin escalation, override kinds, pricing variance.
-- Decisions recorded 2026-09-01 (Steven):
--   * Sonya works the queue and updates job costing (admin login, override rights).
--   * ANY job below 45% gross margin escalates before a payout is released.
--   * Overrides must be creatable for both gates, and always recorded.
--   * Over time, flag where we are under/over priced by item, and where to focus.

-- ---------------------------------------------------------------------------
-- 1) Projected gross margin for a job.
--    Revenue = forecasted sale + added revenue post sale.
--    Projected cost = the worse of (what we forecast) and (what we have actually
--    incurred so far) — so a job cannot look healthy merely because costs have
--    not landed yet. Returns null when there is no revenue to divide by.
-- ---------------------------------------------------------------------------
create or replace function public.jc_job_gm(p_job uuid)
returns numeric language sql stable as $$
  select case when rev > 0 then round(100.0 * (rev - projected_cost) / rev, 1) end
  from (
    select (coalesce(j.contract_total,0) + coalesce(j.added_revenue_post_sale,0)) rev,
           greatest(
             coalesce((select sum(coalesce(forecasted_cost,0)) from jc_forecast_lines where job_id=j.id),0),
             coalesce((select sum(amount) from jc_actual_costs where job_id=j.id),0)
           ) projected_cost
    from jc_jobs j where j.id = p_job
  ) s;
$$;

-- Cost-data coverage: how much of the projected cost is backed by real posted
-- actuals. A GM% is only as trustworthy as this number (validated Foreman rule).
create or replace function public.jc_job_cost_coverage(p_job uuid)
returns numeric language sql stable as $$
  select case when projected > 0 then round(100.0 * actual / projected, 0) else 0 end
  from (
    select coalesce((select sum(amount) from jc_actual_costs where job_id=p_job),0) actual,
           greatest(
             coalesce((select sum(coalesce(forecasted_cost,0)) from jc_forecast_lines where job_id=p_job),0),
             coalesce((select sum(amount) from jc_actual_costs where job_id=p_job),0)
           ) projected
  ) s;
$$;

-- ---------------------------------------------------------------------------
-- 2) Escalation columns + the 45% gate.
-- ---------------------------------------------------------------------------
alter table public.payables add column if not exists escalation_required boolean not null default false;
alter table public.payables add column if not exists escalation_reason text;
alter table public.payables add column if not exists escalation_approved_by text;
alter table public.payables add column if not exists escalation_approved_at timestamptz;

alter table public.jc_override_log add column if not exists kind text not null default 'unmapped_override';
alter table public.jc_override_log add column if not exists job_id uuid;
alter table public.jc_override_log add column if not exists gm_pct numeric;

-- THE GATE (v2): a payable may not reach scheduled/paid unless
--   (a) it is mapped (confirmed) or deliberately overridden or non-job overhead, AND
--   (b) if its job's projected GM is under 45%, a named person has approved the
--       payout with a reason. Both refusals name the blocker in the error.
create or replace function public.jc_payment_gate() returns trigger
language plpgsql as $$
declare v_gm numeric;
begin
  if new.status in ('scheduled','paid') and old.status is distinct from new.status then
    -- (a) mapping gate
    if not (new.mapping_status in ('confirmed','override')
            or coalesce(new.jc_category,'') = 'overhead_non_job') then
      raise exception
        'Payment blocked: payable % (% %) is % — map it to a job or record an override first',
        new.id, new.vendor, new.invoice_number, new.mapping_status;
    end if;
    -- (b) margin escalation gate — 45% floor
    if new.job_id is not null then
      v_gm := public.jc_job_gm(new.job_id);
      if v_gm is not null and v_gm < 45
         and coalesce(new.escalation_approved_by,'') = '' then
        -- built by concatenation: %-escaping inside RAISE printed "%41.0"
        raise exception '%', 'Payout escalation required: job projected gross margin is '
          || v_gm || '% (below the 45% floor). A named approver must release this payment.';
      end if;
    end if;
  end if;
  -- an override must carry a reason and a person
  if new.mapping_status = 'override'
     and (coalesce(new.held_reason,'') = '' or coalesce(new.mapped_by,'auto') = 'auto') then
    raise exception 'Override requires held_reason (why) and mapped_by (who)';
  end if;
  -- an escalation approval must carry a reason and a person
  if coalesce(new.escalation_approved_by,'') <> ''
     and coalesce(new.escalation_reason,'') = '' then
    raise exception 'Margin escalation approval requires a reason';
  end if;
  return new;
end $$;

-- Keep escalation_required current as costs land, so the queue can show it
-- BEFORE someone tries to pay.
create or replace function public.jc_refresh_escalations() returns jsonb
language plpgsql security definer set search_path = public as $$
declare n int;
begin
  update payables p set
    escalation_required = true,
    -- The reason states the BASIS, because an escalation raised on an estimate
    -- and one raised on measured cost are different decisions. Coverage 0% means
    -- no vendor invoices have landed yet and the GM rests on the forecast anchor.
    escalation_reason = coalesce(p.escalation_reason,
      'Job projected GM ' || public.jc_job_gm(p.job_id) || '% is below the 45% floor ('
      || case when public.jc_job_cost_coverage(p.job_id) >= 25
              then 'measured, ' else 'ESTIMATE-based, ' end
      || public.jc_job_cost_coverage(p.job_id) || '% cost coverage)')
  where p.status <> 'paid' and p.job_id is not null
    and coalesce(p.escalation_approved_by,'') = ''
    and public.jc_job_gm(p.job_id) < 45;
  get diagnostics n = row_count;
  update payables p set escalation_required = false, escalation_reason = null
  where p.status <> 'paid' and p.escalation_required
    and (p.job_id is null or public.jc_job_gm(p.job_id) >= 45);
  return jsonb_build_object('escalations_flagged', n);
end $$;
revoke all on function public.jc_refresh_escalations() from public, anon;
grant execute on function public.jc_refresh_escalations() to authenticated, service_role;

-- Log every escalation approval alongside every unmapped override.
create or replace function public.jc_log_override() returns trigger
language plpgsql as $$
begin
  if new.mapping_status = 'override' and old.mapping_status is distinct from 'override' then
    insert into jc_override_log(payable_id, vendor, invoice_number, amount, reason, approved_by, kind, job_id)
    values (new.id, new.vendor, new.invoice_number, new.amount,
            coalesce(new.held_reason,'(no reason recorded)'), coalesce(new.mapped_by,'unknown'),
            'unmapped_override', new.job_id);
  end if;
  if coalesce(new.escalation_approved_by,'') <> ''
     and coalesce(old.escalation_approved_by,'') = '' then
    insert into jc_override_log(payable_id, vendor, invoice_number, amount, reason, approved_by, kind, job_id, gm_pct)
    values (new.id, new.vendor, new.invoice_number, new.amount,
            coalesce(new.escalation_reason,'(no reason recorded)'), new.escalation_approved_by,
            'margin_escalation', new.job_id, public.jc_job_gm(new.job_id));
  end if;
  return new;
end $$;

-- ---------------------------------------------------------------------------
-- 3) Pricing variance — "where are we underpriced, overpriced, and where to focus".
--    Grows more truthful as mapped invoices accumulate. Two grains:
--      jc_line_variance — one sold line vs the invoices mapped to it
--      jc_item_variance — the same item across every job (the focus list)
-- ---------------------------------------------------------------------------
create or replace view public.jc_line_variance as
select f.id forecast_line_id, f.job_id, j.brand, j.customer_name, f.description,
       f.category, f.cost_code, f.qty, f.forecasted_cost, f.amount_charged,
       coalesce(sum(a.amount),0) actual_cost,
       coalesce(sum(a.amount),0) - coalesce(f.forecasted_cost,0) cost_variance,
       case when coalesce(f.amount_charged,0) > 0
            then round(100.0*(f.amount_charged - coalesce(sum(a.amount),0))/f.amount_charged,1)
       end line_margin_pct
from jc_forecast_lines f
join jc_jobs j on j.id = f.job_id
left join jc_actual_costs a on a.forecast_line_id = f.id
group by f.id, f.job_id, j.brand, j.customer_name, f.description, f.category,
         f.cost_code, f.qty, f.forecasted_cost, f.amount_charged;

-- Normalised item name so the same item lines up across jobs.
create or replace view public.jc_item_variance as
with norm as (
  select lower(regexp_replace(description, '[^a-zA-Z ]', '', 'g')) item,
         category, brand, job_id, forecasted_cost, amount_charged, actual_cost, line_margin_pct
  from jc_line_variance
)
select item, category, brand,
       count(distinct job_id) jobs,
       round(avg(amount_charged)::numeric,2) avg_charged,
       round(avg(nullif(forecasted_cost,0))::numeric,2) avg_forecast_cost,
       round(avg(nullif(actual_cost,0))::numeric,2) avg_actual_cost,
       round(avg(line_margin_pct)::numeric,1) avg_margin_pct,
       sum(actual_cost) - sum(coalesce(forecasted_cost,0)) total_cost_variance,
       case
         when avg(line_margin_pct) is null then 'no actuals yet'
         when avg(line_margin_pct) < 45 then 'underpriced — margin below floor'
         when avg(line_margin_pct) > 75 then 'overpriced — check competitiveness'
         else 'in range'
       end verdict
from norm
where item <> ''
group by item, category, brand
having count(distinct job_id) >= 2      -- an item is only a pattern across jobs
order by (sum(actual_cost) - sum(coalesce(forecasted_cost,0))) desc nulls last;

-- Job-level focus list: worst projected margin first, with coverage beside it.
create or replace view public.jc_focus as
select j.id job_id, j.brand, j.customer_name, j.service_type, j.status,
       (coalesce(j.contract_total,0)+coalesce(j.added_revenue_post_sale,0)) revenue,
       public.jc_job_gm(j.id) projected_gm_pct,
       public.jc_job_cost_coverage(j.id) cost_coverage_pct,
       (select count(*) from payables p where p.job_id=j.id and p.mapping_status in ('held','unmapped','auto_mapped')) held_invoices,
       (select count(*) from payables p where p.job_id=j.id and p.escalation_required and coalesce(p.escalation_approved_by,'')='') pending_escalations,
       (select coalesce(sum(amount),0) from jc_actual_costs a where a.job_id=j.id and a.is_unplanned) unplanned_cost
from jc_jobs j
where j.status not in ('closed')
order by public.jc_job_gm(j.id) nulls last;

alter view public.jc_line_variance set (security_invoker = on);
alter view public.jc_item_variance set (security_invoker = on);
alter view public.jc_focus         set (security_invoker = on);
