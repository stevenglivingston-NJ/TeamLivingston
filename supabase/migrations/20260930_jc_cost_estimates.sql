-- Job costing: a cost for every sold line (2026-09-30).
-- TABLE + FUNCTION CREATED LIVE 2026-09-30; NOT YET RUN (no estimate lines, no
-- cron) -- waiting on Steven to confirm the rule values. Dry run: KTU median
-- GM 52% (9 of 50 under 45%), BTU median 39% (17 of 23 under 45%).
--
-- ServiceMinder KTU parts carry no UnitCost, so 1,300+ sold lines forecast no
-- cost and most jobs showed 92-100% gross margin. This adds a line cost table
-- and derives an ESTIMATE line (source='estimate') for every sold line that has
-- a price but no cost. Nothing in ServiceMinder or JobTread is changed.
--
--   jc_cost_rules      first matching rule per brand wins (lowest priority):
--                      unit_cost x qty, or cost_ratio x price. Each rule names
--                      its basis; confirmed=false until Steven confirms it.
--   fallback           KTU 0.289 of price = median cost/price of 82 KTU
--                      catalog items; BTU 0.50 = median of BTU's own costed
--                      ServiceMinder lines (n=10, thin).
--   unitemized revenue contract + post-sale revenue above the sum of the
--                      priced lines is estimated at the fallback ratio.
--   over-itemized      where priced lines exceed the contract, line estimates
--                      are scaled down to the contract.
--   skipped            jobs with a costed JobTread breakout (that IS the budget).
--   Foreman estimate   for estimated jobs its materials + labor rows move to
--                      jc_forecast_lines_superseded (kept, reversible); its
--                      commission row stays.
--
--   select public.jc_refresh_estimate_lines(true);   -- dry run, writes nothing

create table if not exists public.jc_cost_rules (
  brand      text    not null check (brand in ('KTU','BTU')),
  priority   integer not null,
  match_rx   text    not null,              -- case-insensitive, on the line description
  unit_cost  numeric,                       -- per ServiceMinder unit (qty)
  cost_ratio numeric,                       -- or: share of the line's price
  basis      text    not null,
  confirmed  boolean not null default false,
  primary key (brand, priority),
  check ((unit_cost is null) <> (cost_ratio is null))
);
alter table public.jc_cost_rules enable row level security;
drop policy if exists jc_cost_rules_read on public.jc_cost_rules;
create policy jc_cost_rules_read on public.jc_cost_rules for select to authenticated using (true);

create table if not exists public.jc_forecast_lines_superseded (like public.jc_forecast_lines including all);
alter table public.jc_forecast_lines_superseded add column if not exists superseded_at timestamptz default now();
alter table public.jc_forecast_lines_superseded enable row level security;
revoke all on public.jc_forecast_lines_superseded from anon, authenticated;

insert into public.jc_cost_rules (brand, priority, match_rx, unit_cost, cost_ratio, basis) values
  ('KTU', 10, '^EL ',                                               null, 0.56,  'Elias Woodwork invoices on 6 jobs: median 56% of the EL door/molding sell'),
  ('KTU', 20, 'installation of new doors',                           55,  null,  'per door: catalog re-door all-in $145 less ~$90 Elias door material'),
  ('KTU', 30, '(quartz|granite).*(countertop|backsplash)|quartz countertops', 45, null, 'per sq ft: catalog Countertop Enhanced (Quartz) $45; ASAP bills show $31-42'),
  ('KTU', 35, 'countertop cutout',                                   40,  null,  'catalog Countertop Cutout'),
  ('KTU', 40, 'ceramic tile backsplash',                             19.34, null, 'per sq ft: catalog backsplash tile Enhanced $6 + install labor $13.34'),
  ('KTU', 50, 'upgraded frameless cabinets',                         948, null,  'per cabinet: catalog New Cabinets Semi-Custom all-in'),
  ('KTU', 51, 'premier shaker',                                      569, null,  'per cabinet: catalog New Cabinets Construction all-in'),
  ('KTU', 52, '(base|wall) cabinet add-on|new (base|wall) cabinets', 569, null,  'per cabinet: catalog New Cabinets Construction all-in'),
  ('KTU', 60, 'new cabinet hardware',                                4,   null,  'per piece: catalog NC Hardware'),
  ('KTU', 70, 'undermount stainless',                                120, null,  'catalog Sink: Stainless Single Bowl'),
  ('KTU', 71, 'rollout tray',                                        100, null,  'per tray: catalog Standard Rollout Trays'),
  ('KTU', 72, 'trash can pullout',                                   164, null,  'catalog 18" Double Trash Can Pullout'),
  ('KTU', 73, 'lazy susan',                                          128, null,  'catalog Lazy Susan'),
  ('KTU', 80, '^shipping',                                           350, null,  'catalog Shipping & Handling: Refacing/Redooring'),
  ('KTU', 81, 'remove existing kitchen cabinets',                    675, null,  'catalog Demo: Cabinets Only - Average'),
  ('KTU', 82, 'led light kit|under ?cabinet light',                  510, null,  'catalog Undercabinet Lighting'),
  ('KTU', 83, 'paint kitchen walls',                                 347, null,  'catalog Paint Kitchen Walls and Ceiling'),
  ('KTU', 84, 'paint cabinet doors, drawer fronts',                  54.3, null, 'per door: catalog Cabinet Painting: Labor'),
  ('KTU', 85, 'plank flooring installation labor',                   3,   null,  'per sq ft: catalog LVP Install Labor'),
  ('KTU', 86, 'luxury vinyl plank',                                  null, 0.52, 'catalog LVP Essential cost/price (units differ from SM)'),
  ('KTU', 87, 'tile flooring installation labor',                    null, 0.39, 'catalog Tile Floor Install Labor cost/price'),
  ('KTU', 88, 'crown',                                               65,  null,  'per run: catalog Crown Molding'),
  ('KTU', 999, '.',                                                  null, 0.289, 'fallback: median cost/price of 82 KTU catalog items'),
  ('BTU', 999, '.',                                                  null, 0.50,  'fallback: median of BTU''s costed ServiceMinder lines (n=10)')
on conflict (brand, priority) do update set match_rx = excluded.match_rx, unit_cost = excluded.unit_cost,
  cost_ratio = excluded.cost_ratio, basis = excluded.basis
  where not public.jc_cost_rules.confirmed;

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
     where l.source = 'sm_proposal' and coalesce(l.amount_charged, 0) > 0
  ), line_est as (
    select p.job_id, p.category, p.qty,
           r.priority, r.basis,
           round(coalesce(r.unit_cost * p.qty, r.cost_ratio * p.amount_charged)
                 * least(1, p.rev / nullif(p.charged_total, 0)), 2) cost,
           p.description
      from priced p
      cross join lateral (select * from jc_cost_rules r
                           where r.brand = p.brand and p.description ~* r.match_rx
                           order by r.priority limit 1) r
     where coalesce(p.forecasted_cost, 0) = 0
  ), residual as (
    select jb.id job_id, jb.brand, jb.rev - coalesce(sum(l.amount_charged), 0) amt
      from jobs jb
      left join jc_forecast_lines l on l.job_id = jb.id and l.source = 'sm_proposal' and coalesce(l.amount_charged, 0) > 0
     group by jb.id, jb.brand, jb.rev
  )
  select job_id, category, qty, cost,
         left('Estimate (' || basis || '): ' || description, 400) description, priority
    from line_est
  union all
  select r.job_id, 'other', 1, round(r.amt * f.cost_ratio, 2),
         'Estimate (' || f.basis || '): revenue not itemized in the proposal lines ($' || round(r.amt) || ')', 999
    from residual r join jc_cost_rules f on f.brand = r.brand and f.priority = 999
   where r.amt > 50;

  if dry then
    select jsonb_build_object(
      'lines', count(*), 'cost', round(sum(cost)),
      'by_rule', (select jsonb_object_agg(priority, jsonb_build_array(n, c)) from
                   (select priority, count(*) n, round(sum(cost)) c from _est group by 1) x),
      'jobs', count(distinct job_id)) into res from _est;
    return res;
  end if;

  -- a Foreman category estimate is superseded where line estimates now exist
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
