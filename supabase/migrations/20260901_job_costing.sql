-- Job Costing & Payment Control — KTU/BTU
-- Schema authority: KTU JCA ProfitabilityTracker (Forecasted vs Actual side by side;
-- categories Direct Materials / Contract Labor / Employee Labor / Sales Commission;
-- GO-BACKS / REWORKS / UNPLANNED isolated; Revenue = Forecasted Sale + Added Revenue POST SALE).
-- The control: a vendor invoice (payables row) cannot be released for payment until it is
-- mapped to a job + category (+ sold line where resolvable). Unmapped = HELD on the
-- exceptions queue. Paying an unmapped invoice is a recorded override, never the default.
-- Applied 2026-09-01.

-- ---------------------------------------------------------------------------
-- 1) jc_jobs — one row per sold job (the spine both sides join to).
--    Anchor id: ServiceMinder proposal (Invoice.ProposalId is populated on 100%
--    of sampled invoices; change orders hang off it). JobTread id carried for
--    budget/schedule joins; both live in foreman_board today.
-- ---------------------------------------------------------------------------
create table if not exists public.jc_jobs (
  id uuid primary key default gen_random_uuid(),
  brand text not null check (brand in ('KTU','BTU')),
  customer_name text not null,
  address text,
  service_type text,                      -- Refacing / New Cabinets / Full Bathroom Remodel / ...
  status text not null default 'approved' -- estimate|approved|in_progress|complete|closed
    check (status in ('estimate','approved','in_progress','complete','closed')),
  sm_proposal_id bigint,                  -- accepted ServiceMinder proposal (job anchor)
  sm_contact_id bigint,
  jobtread_job_id text,                   -- e.g. 22PFa8be5LH7
  jobtread_number text,
  contract_total numeric,                 -- Forecasted Sale (accepted proposal, pre change orders)
  added_revenue_post_sale numeric default 0,  -- signed change orders after the sale
  contract_signed date,
  install_start date,
  completed_on date,
  sales_agent text,
  commission_pct numeric,                 -- job-level commission rate (8% default; 12% self-gen)
  notes text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create unique index if not exists jc_jobs_sm_proposal_uq
  on public.jc_jobs(brand, sm_proposal_id) where sm_proposal_id is not null;
create index if not exists jc_jobs_customer_idx on public.jc_jobs(brand, lower(customer_name));

-- ---------------------------------------------------------------------------
-- 2) jc_forecast_lines — the SOLD side (Forecasted). From the accepted SM
--    proposal lines + change orders, and/or the JobTread budget. One row per
--    sold line; vendor invoices map back to these.
-- ---------------------------------------------------------------------------
create table if not exists public.jc_forecast_lines (
  id uuid primary key default gen_random_uuid(),
  job_id uuid not null references public.jc_jobs(id) on delete cascade,
  description text not null,
  category text not null check (category in
    ('direct_materials','contract_labor','employee_labor','sales_commission','other')),
  qty numeric default 1,
  unit_cost numeric,                      -- forecast unit cost (SM UnitCost / JT unitCost / catalog)
  forecasted_cost numeric,                -- qty * unit_cost (stored: sources disagree on rounding)
  amount_charged numeric,                 -- what the customer was charged for this line (sell)
  cost_code text,                         -- JobTread cost code (K03 ...) when known
  vendor_hint text,                       -- expected vendor (Elias, MSI, crew...) for auto-matching
  is_change_order boolean not null default false,
  source text not null default 'manual',  -- sm_proposal|sm_change_order|jobtread|catalog|manual
  source_line_id text,                    -- SM ProposalLine.Id / JT cost item id
  created_at timestamptz not null default now()
);
create index if not exists jc_forecast_job_idx on public.jc_forecast_lines(job_id, category);

-- ---------------------------------------------------------------------------
-- 3) payables — extend with the mapping/control columns.
--    mapping_status is the control state:
--      unmapped        -> just arrived; nobody/nothing has mapped it
--      auto_mapped     -> matcher assigned job+category at/above confidence; needs human confirm
--      held            -> could not be mapped (or auto-map rejected); ON the exceptions queue
--      confirmed       -> human confirmed job+category (+line when resolvable); releasable
--      override        -> deliberately approved WITHOUT a mapping; recorded, reasoned, releasable
-- ---------------------------------------------------------------------------
alter table public.payables add column if not exists job_id uuid references public.jc_jobs(id) on delete set null;
alter table public.payables add column if not exists jc_category text
  check (jc_category is null or jc_category in
    ('direct_materials','contract_labor','employee_labor','sales_commission','other','overhead_non_job'));
alter table public.payables add column if not exists forecast_line_id uuid references public.jc_forecast_lines(id) on delete set null;
alter table public.payables add column if not exists mapping_status text not null default 'unmapped'
  check (mapping_status in ('unmapped','auto_mapped','held','confirmed','override'));
alter table public.payables add column if not exists mapping_confidence numeric;
alter table public.payables add column if not exists held_reason text;    -- why it's on the exceptions queue
alter table public.payables add column if not exists mapped_by text;      -- 'auto' | person
alter table public.payables add column if not exists mapped_at timestamptz;
alter table public.payables add column if not exists is_unplanned boolean not null default false;
alter table public.payables add column if not exists unplanned_kind text
  check (unplanned_kind is null or unplanned_kind in ('go_back','rework','unplanned'));
alter table public.payables add column if not exists qbo_bill_id text;    -- QBO Bill.Id when synced
alter table public.payables add column if not exists po_hint text;        -- raw PO/customer text parsed off the invoice

-- THE GATE: a payable cannot leave 'unpaid' (i.e. be scheduled in Melio or marked
-- paid) unless it is 'confirmed', 'override', or explicitly non-job overhead.
create or replace function public.jc_payment_gate() returns trigger
language plpgsql as $$
begin
  if new.status in ('scheduled','paid') and old.status is distinct from new.status then
    if not (new.mapping_status in ('confirmed','override')
            or new.jc_category = 'overhead_non_job') then
      raise exception
        'Payment blocked: payable % (% %) is % — map it to a job or record an override first',
        new.id, new.vendor, new.invoice_number, new.mapping_status;
    end if;
  end if;
  -- an override must carry a reason and a person
  if new.mapping_status = 'override'
     and (coalesce(new.held_reason,'') = '' or coalesce(new.mapped_by,'auto') = 'auto') then
    raise exception 'Override requires held_reason (why) and mapped_by (who)';
  end if;
  return new;
end $$;
drop trigger if exists payables_payment_gate on public.payables;
create trigger payables_payment_gate before update on public.payables
  for each row execute function public.jc_payment_gate();

-- Override audit log — every deliberate unmapped approval, permanent record.
create table if not exists public.jc_override_log (
  id uuid primary key default gen_random_uuid(),
  payable_id uuid not null references public.payables(id) on delete cascade,
  vendor text, invoice_number text, amount numeric,
  reason text not null,
  approved_by text not null,
  created_at timestamptz not null default now()
);
create or replace function public.jc_log_override() returns trigger
language plpgsql as $$
begin
  if new.mapping_status = 'override' and old.mapping_status is distinct from 'override' then
    insert into public.jc_override_log(payable_id, vendor, invoice_number, amount, reason, approved_by)
    values (new.id, new.vendor, new.invoice_number, new.amount,
            coalesce(new.held_reason,'(no reason recorded)'), coalesce(new.mapped_by,'unknown'));
  end if;
  return new;
end $$;
drop trigger if exists payables_override_log on public.payables;
create trigger payables_override_log after update on public.payables
  for each row execute function public.jc_log_override();

-- ---------------------------------------------------------------------------
-- 4) jc_actual_costs — the ACTUAL side. One row per cost hitting a job:
--    mapped vendor invoices (payable_id), labor allocations, commission accruals.
--    A payable that spans jobs splits into several rows; sum(amount) over a
--    payable must equal the payable amount (checked by the reconciliation view).
-- ---------------------------------------------------------------------------
create table if not exists public.jc_actual_costs (
  id uuid primary key default gen_random_uuid(),
  job_id uuid not null references public.jc_jobs(id) on delete cascade,
  category text not null check (category in
    ('direct_materials','contract_labor','employee_labor','sales_commission','other')),
  description text,
  vendor text,
  amount numeric not null,
  occurred_on date,
  payable_id uuid references public.payables(id) on delete set null,
  forecast_line_id uuid references public.jc_forecast_lines(id) on delete set null,
  is_unplanned boolean not null default false,
  unplanned_kind text check (unplanned_kind is null or unplanned_kind in ('go_back','rework','unplanned')),
  source text not null default 'payable', -- payable|qbo_bill|labor_alloc|commission|manual
  source_ref text,                        -- QBO bill id / payroll ref / commissions row
  created_by text,
  created_at timestamptz not null default now()
);
create index if not exists jc_actuals_job_idx on public.jc_actual_costs(job_id, category);
create index if not exists jc_actuals_payable_idx on public.jc_actual_costs(payable_id);

-- ---------------------------------------------------------------------------
-- 5) jc_labor_allocations — fixed 1099 crew (Miguel Bara, Oscar Yupa Herrera,
--    Jerson Godoy) + W2 install labor, allocated to jobs by week. Every week's
--    allocations for a person must sum to what they were actually paid that
--    week (enforced by review, surfaced by the recon view). Bench time goes to
--    job_id NULL with bucket='bench' so jobs are not polluted but the money is
--    never invisible.
-- ---------------------------------------------------------------------------
create table if not exists public.jc_labor_allocations (
  id uuid primary key default gen_random_uuid(),
  person text not null,
  labor_kind text not null default 'contract' check (labor_kind in ('contract','employee')),
  week_start date not null,
  job_id uuid references public.jc_jobs(id) on delete set null,
  bucket text default 'job' check (bucket in ('job','bench','shop','warranty')),
  days numeric,                            -- days on site that week (evidence-based)
  amount numeric not null,
  evidence text,                           -- 'crew invoice','companycam photos','install schedule','even split (flagged)'
  payable_id uuid references public.payables(id) on delete set null,
  source_ref text,                         -- QBO bill / payroll run reference
  created_by text,
  created_at timestamptz not null default now()
);
create index if not exists jc_labor_week_idx on public.jc_labor_allocations(person, week_start);

-- Mirror labor allocations into jc_actual_costs automatically (job rows only).
create or replace function public.jc_labor_to_actuals() returns trigger
language plpgsql as $$
begin
  if new.job_id is not null then
    insert into public.jc_actual_costs(job_id, category, description, vendor, amount,
                                       occurred_on, payable_id, source, source_ref, created_by)
    values (new.job_id,
            case when new.labor_kind='contract' then 'contract_labor' else 'employee_labor' end,
            'Labor: '||new.person||' wk '||new.week_start||coalesce(' ('||new.days||'d)',''),
            new.person, new.amount, new.week_start, new.payable_id,
            'labor_alloc', new.id::text, new.created_by);
  end if;
  return new;
end $$;
drop trigger if exists jc_labor_alloc_mirror on public.jc_labor_allocations;
create trigger jc_labor_alloc_mirror after insert on public.jc_labor_allocations
  for each row execute function public.jc_labor_to_actuals();

-- ---------------------------------------------------------------------------
-- 6) Exceptions queue + per-job P&L views.
-- ---------------------------------------------------------------------------
create or replace view public.jc_exceptions as
select p.id, p.brand, p.vendor, p.invoice_number, p.amount, p.invoice_date, p.due_date,
       p.status, p.mapping_status, p.mapping_confidence, p.held_reason, p.po_hint,
       p.job_id, j.customer_name as mapped_job, p.jc_category, p.created_at
from public.payables p
left join public.jc_jobs j on j.id = p.job_id
where p.status not in ('paid')
  and (p.mapping_status in ('unmapped','held','auto_mapped'))
  and coalesce(p.jc_category,'') <> 'overhead_non_job'
order by p.due_date nulls last, p.amount desc;

-- Per-job JCA rollup: Forecast vs Actual by category, GM, benchmarks, go-backs.
-- HFC benchmarks (from the ProfitabilityTracker workbook — DO NOT substitute):
--   Gross Profit 50-55% | Total Labor <15% | Direct Materials <30% | Commission <8%
create or replace view public.jc_job_pnl as
with f as (
  select job_id, category,
         sum(coalesce(forecasted_cost, qty*unit_cost, 0)) fc,
         sum(coalesce(amount_charged,0)) charged
  from public.jc_forecast_lines group by 1,2
), a as (
  select job_id, category,
         sum(amount) filter (where not is_unplanned) ac,
         sum(amount) filter (where is_unplanned) unplanned
  from public.jc_actual_costs group by 1,2
), cat as (
  select coalesce(f.job_id,a.job_id) job_id, coalesce(f.category,a.category) category,
         coalesce(f.fc,0) forecasted_cost, coalesce(a.ac,0) actual_cost,
         coalesce(f.charged,0) amount_charged, coalesce(a.unplanned,0) unplanned_cost
  from f full outer join a on a.job_id=f.job_id and a.category=f.category
)
select j.id job_id, j.brand, j.customer_name, j.service_type, j.status,
       j.contract_total, coalesce(j.added_revenue_post_sale,0) added_revenue_post_sale,
       (coalesce(j.contract_total,0)+coalesce(j.added_revenue_post_sale,0)) total_revenue,
       c.category, c.forecasted_cost, c.actual_cost, c.unplanned_cost, c.amount_charged,
       case when coalesce(j.contract_total,0)+coalesce(j.added_revenue_post_sale,0) > 0
            then round(100.0*c.actual_cost/(j.contract_total+coalesce(j.added_revenue_post_sale,0)),1)
       end actual_pct_of_revenue,
       c.actual_cost - c.forecasted_cost cost_variance
from public.jc_jobs j
join cat c on c.job_id = j.id;

-- Job-level summary with HFC benchmark verdicts.
create or replace view public.jc_job_summary as
with p as (
  select job_id,
         sum(forecasted_cost) f_total, sum(actual_cost) a_total, sum(unplanned_cost) unplanned_total,
         sum(forecasted_cost) filter (where category='direct_materials') f_dm,
         sum(actual_cost)     filter (where category='direct_materials') a_dm,
         sum(forecasted_cost) filter (where category in ('contract_labor','employee_labor')) f_labor,
         sum(actual_cost)     filter (where category in ('contract_labor','employee_labor')) a_labor,
         sum(forecasted_cost) filter (where category='sales_commission') f_comm,
         sum(actual_cost)     filter (where category='sales_commission') a_comm
  from public.jc_job_pnl group by job_id
)
select j.id job_id, j.brand, j.customer_name, j.service_type, j.status,
       j.contract_total, coalesce(j.added_revenue_post_sale,0) added_revenue_post_sale,
       (coalesce(j.contract_total,0)+coalesce(j.added_revenue_post_sale,0)) total_revenue,
       p.f_total forecasted_cost, p.a_total actual_cost, coalesce(p.unplanned_total,0) unplanned_cost,
       p.a_dm actual_direct_materials, p.a_labor actual_total_labor, p.a_comm actual_commission,
       case when coalesce(j.contract_total,0)+coalesce(j.added_revenue_post_sale,0) > 0 then
         round(100.0*(1 - coalesce(p.a_total,0)/(j.contract_total+coalesce(j.added_revenue_post_sale,0))),1)
       end gross_margin_pct,
       -- HFC benchmark verdicts (null until any actuals exist)
       case when p.a_total is null then null
            when 100.0*(1-p.a_total/nullif(j.contract_total+coalesce(j.added_revenue_post_sale,0),0)) >= 50 then 'pass'
            else 'below' end gp_vs_benchmark,          -- 50-55%
       case when p.a_labor is null then null
            when 100.0*p.a_labor/nullif(j.contract_total+coalesce(j.added_revenue_post_sale,0),0) < 15 then 'pass'
            else 'over' end labor_vs_benchmark,        -- <15%
       case when p.a_dm is null then null
            when 100.0*p.a_dm/nullif(j.contract_total+coalesce(j.added_revenue_post_sale,0),0) < 30 then 'pass'
            else 'over' end dm_vs_benchmark,           -- <30%
       case when p.a_comm is null then null
            when 100.0*p.a_comm/nullif(j.contract_total+coalesce(j.added_revenue_post_sale,0),0) <= 8 then 'pass'
            else 'over' end commission_vs_benchmark    -- <8%
from public.jc_jobs j
left join p on p.job_id = j.id;

-- Reconciliation guard: split rows must sum to their payable.
create or replace view public.jc_split_mismatch as
select p.id payable_id, p.vendor, p.invoice_number, p.amount payable_amount,
       coalesce(sum(a.amount),0) allocated
from public.payables p
join public.jc_actual_costs a on a.payable_id = p.id
group by p.id, p.vendor, p.invoice_number, p.amount
having abs(p.amount - coalesce(sum(a.amount),0)) > 0.01;

-- ---------------------------------------------------------------------------
-- 7) RLS — same posture as jobs/payables (authenticated app users).
-- ---------------------------------------------------------------------------
alter table public.jc_jobs              enable row level security;
alter table public.jc_forecast_lines    enable row level security;
alter table public.jc_actual_costs      enable row level security;
alter table public.jc_labor_allocations enable row level security;
alter table public.jc_override_log      enable row level security;
do $$ begin
  if not exists (select 1 from pg_policies where tablename='jc_jobs' and policyname='jc_jobs_authed') then
    create policy jc_jobs_authed on public.jc_jobs for all to authenticated using (true) with check (true);
  end if;
  if not exists (select 1 from pg_policies where tablename='jc_forecast_lines' and policyname='jc_forecast_authed') then
    create policy jc_forecast_authed on public.jc_forecast_lines for all to authenticated using (true) with check (true);
  end if;
  if not exists (select 1 from pg_policies where tablename='jc_actual_costs' and policyname='jc_actuals_authed') then
    create policy jc_actuals_authed on public.jc_actual_costs for all to authenticated using (true) with check (true);
  end if;
  if not exists (select 1 from pg_policies where tablename='jc_labor_allocations' and policyname='jc_labor_authed') then
    create policy jc_labor_authed on public.jc_labor_allocations for all to authenticated using (true) with check (true);
  end if;
  if not exists (select 1 from pg_policies where tablename='jc_override_log' and policyname='jc_override_read') then
    create policy jc_override_read on public.jc_override_log for select to authenticated using (true);
  end if;
end $$;

-- updated_at touch
drop trigger if exists jc_jobs_touch on public.jc_jobs;
create trigger jc_jobs_touch before update on public.jc_jobs
  for each row execute function public.touch_updated_at();

-- Realtime for the exceptions queue + mapper UI
do $$ begin
  begin alter publication supabase_realtime add table public.jc_jobs; exception when duplicate_object then null; end;
  begin alter publication supabase_realtime add table public.jc_actual_costs; exception when duplicate_object then null; end;
end $$;
