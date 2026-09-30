-- Job costing: a cost for every sold line, from actual invoices + the P&L (2026-09-30).
-- APPLIED LIVE 2026-09-30.
--
-- ServiceMinder KTU parts carry no UnitCost, so 1,300+ sold lines forecast no
-- cost and most jobs showed 92-100% gross margin. This derives ESTIMATE lines
-- (source='estimate') from what the business actually paid. Nothing in
-- ServiceMinder or JobTread is changed.
--
-- Basis (Steven, 2026-09-30: "use past data ... use actual invoices"):
--   KTU doors/moldings   Elias Woodwork bills on the 10 jobs with a complete door
--                        bill: median 52.5% of the "EL ..." line sell (38-76%).
--   KTU countertops      MSI slab + ASAP fabrication bills: $70/sq ft
--                        (Ed Gold $70.1, Weinberger $75.8; slab median $34 on 3
--                        jobs, fabrication $31-42 on 2). The catalog's $45 was low.
--   KTU everything else  one ratio, calibrated so estimated KTU job cost equals
--                        the validated 2026 YTD P&L: COGS 48.3% of revenue
--                        (materials 30.5% + install labour 17.8%).
--   KTU unitemized       contract + post-sale revenue above the priced lines: 48.3%.
--   BTU                  98% of BTU revenue has no line price (lump-sum
--                        proposals), so line rules cannot work. A job's cost is
--                        topped up to the BTU P&L's 50.6% of revenue (materials
--                        22.0%, labour 28.6%); real ServiceMinder line costs count
--                        toward it. It is the brand average, not a job measurement
--                        -- see the payment gate change below.
--   Over-itemized        where priced lines exceed the contract, line estimates
--                        are scaled down to the contract.
--   Skipped              jobs with a costed JobTread breakout (that IS the budget).
--   Foreman estimate     on estimated jobs its materials + labour rows move to
--                        jc_forecast_lines_superseded (kept, reversible); its
--                        commission row stays.
--
--   select public.jc_refresh_estimate_lines(true);   -- dry run, writes nothing

create table if not exists public.jc_cost_rules (
  brand      text    not null check (brand in ('KTU','BTU')),
  priority   integer not null,
  kind       text    not null default 'line' check (kind in ('line','residual','job_floor')),
  match_rx   text    not null,              -- case-insensitive, on the line description
  unit_cost  numeric,                       -- per ServiceMinder unit (qty)
  cost_ratio numeric,                       -- or: share of the line's price / of revenue
  basis      text    not null,
  confirmed  boolean not null default false,
  primary key (brand, priority),
  check ((unit_cost is null) <> (cost_ratio is null))
);
alter table public.jc_cost_rules add column if not exists kind text not null default 'line';
alter table public.jc_cost_rules enable row level security;
drop policy if exists jc_cost_rules_read on public.jc_cost_rules;
create policy jc_cost_rules_read on public.jc_cost_rules for select to authenticated using (true);

create table if not exists public.jc_forecast_lines_superseded (like public.jc_forecast_lines including all);
alter table public.jc_forecast_lines_superseded add column if not exists superseded_at timestamptz default now();
alter table public.jc_forecast_lines_superseded enable row level security;
revoke all on public.jc_forecast_lines_superseded from anon, authenticated;

-- The first draft carried catalog costs; invoices disproved the countertop one
-- and the rest are replaced by the P&L calibration.
delete from public.jc_cost_rules where true;   -- pg_safeupdate needs a WHERE
insert into public.jc_cost_rules (brand, priority, kind, match_rx, unit_cost, cost_ratio, basis, confirmed) values
  ('KTU', 10,  'line',      '^EL ', null, 0.525,
   'Elias Woodwork bills, 10 jobs with a complete door bill: median 52.5% of EL sell', true),
  ('KTU', 30,  'line',      '(quartz|granite).*(countertop|backsplash)|quartz countertops', 70, null,
   'MSI slab + ASAP fabrication bills: $70/sq ft (Ed Gold $70.1, Weinberger $75.8)', true),
  ('KTU', 999, 'line',      '.', null, 0.438,
   'calibrated: KTU estimated job cost = 48.3% of revenue (2026 YTD P&L COGS)', true),
  ('KTU', 1000,'residual',  '.', null, 0.483,
   'KTU 2026 YTD P&L: COGS 48.3% of revenue', true),
  ('BTU', 1000,'job_floor', '.', null, 0.506,
   'BTU 2026 YTD P&L: COGS 50.6% of revenue (materials 22.0%, labour 28.6%)', true);

create or replace function public.jc_refresh_estimate_lines(dry boolean default false)
returns jsonb language plpgsql security definer set search_path = public as $$
declare res jsonb;
begin
  create temp table _est on commit drop as
  with jobs as (
    select j.id, j.brand, coalesce(j.contract_total, 0) + coalesce(j.added_revenue_post_sale, 0) rev
      from jc_jobs j
     where not exists (select 1 from jc_forecast_lines f where f.job_id = j.id
                         and f.source = 'jobtread' and coalesce(f.forecasted_cost, 0) > 0)
  ), priced as (
    select l.*, jb.brand, jb.rev,
           sum(l.amount_charged) over (partition by l.job_id) charged_total
      from jc_forecast_lines l join jobs jb on jb.id = l.job_id
     where jb.brand = 'KTU' and l.source = 'sm_proposal' and coalesce(l.amount_charged, 0) > 0
  ), line_est as (                     -- KTU: one estimate per priced, uncosted line
    select p.job_id, p.category, p.qty, r.priority, r.basis,
           round(coalesce(r.unit_cost * p.qty, r.cost_ratio * p.amount_charged)
                 * least(1, p.rev / nullif(p.charged_total, 0)), 2) cost,
           p.description
      from priced p
      cross join lateral (select * from jc_cost_rules r
                           where r.brand = p.brand and r.kind = 'line' and p.description ~* r.match_rx
                           order by r.priority limit 1) r
     where coalesce(p.forecasted_cost, 0) = 0
  ), ktu_resid as (                    -- KTU: revenue the priced lines do not account for
    select jb.id job_id, jb.rev - coalesce(sum(l.amount_charged), 0) amt
      from jobs jb
      left join jc_forecast_lines l on l.job_id = jb.id and l.source = 'sm_proposal' and coalesce(l.amount_charged, 0) > 0
     where jb.brand = 'KTU'
     group by jb.id, jb.rev
  ), btu_floor as (                    -- BTU: top the job's real costs up to the brand P&L ratio
    select jb.id job_id, r.cost_ratio, r.basis,
           jb.rev * r.cost_ratio - coalesce((select sum(coalesce(f.forecasted_cost, 0)) from jc_forecast_lines f
                                   where f.job_id = jb.id and f.category <> 'sales_commission'
                                     and f.source not in ('estimate', 'foreman_estimate', 'commission_rate')), 0) gap
      from jobs jb join jc_cost_rules r on r.brand = 'BTU' and r.kind = 'job_floor'
     where jb.brand = 'BTU'
  )
  select job_id, category, qty, cost,
         left('Estimate (' || basis || '): ' || description, 400) description
    from line_est
  union all
  select k.job_id, 'other', 1, round(k.amt * r.cost_ratio, 2),
         'Estimate (' || r.basis || '): revenue not itemized in the proposal lines ($' || round(k.amt) || ')'
    from ktu_resid k join jc_cost_rules r on r.brand = 'KTU' and r.kind = 'residual'
   where k.amt > 50
  union all
  select b.job_id, s.cat, 1, round(b.gap * s.share, 2),
         'Estimate (' || b.basis || '): ' || s.what || ' to the BTU average, above this job''s recorded costs'
    from btu_floor b
   cross join (values ('direct_materials', 22.0 / 50.6, 'materials'),
                      ('contract_labor',   28.6 / 50.6, 'labour')) s(cat, share, what)
   where b.gap > 50;

  if dry then
    select jsonb_build_object('lines', count(*), 'cost', round(sum(cost)), 'jobs', count(distinct job_id))
      into res from _est;
    return res;
  end if;

  -- a Foreman category estimate is superseded where estimates now exist
  with moved as (
    delete from jc_forecast_lines f
     where f.source = 'foreman_estimate' and f.category <> 'sales_commission'
       and exists (select 1 from _est e where e.job_id = f.job_id)
    returning f.*
  )
  insert into jc_forecast_lines_superseded select m.*, now() from moved m;

  delete from jc_forecast_lines where source = 'estimate';
  insert into jc_forecast_lines (job_id, description, category, qty, unit_cost, forecasted_cost, source)
  select job_id, description, category, qty, round(cost / nullif(qty, 0), 4), cost, 'estimate' from _est where cost > 0;

  select jsonb_build_object('lines', count(*), 'cost', round(sum(cost)), 'jobs', count(distinct job_id)) into res from _est;
  return res;
end $$;
revoke execute on function public.jc_refresh_estimate_lines(boolean) from public, anon, authenticated;

select public.jc_refresh_estimate_lines();
-- after the forecast sync (:00) and the commission lines (:03)
select cron.unschedule('jc-estimate-lines') where exists (select 1 from cron.job where jobname = 'jc-estimate-lines');
select cron.schedule('jc-estimate-lines', '5-59/10 * * * *', $$ select public.jc_refresh_estimate_lines(); $$);
