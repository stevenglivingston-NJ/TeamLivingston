-- ===========================================================================
-- CompanyCam time tracking -> job costing labor (2026-09-18)
--
-- WHAT THIS CLOSES
-- The 2026-09-01 design (docs/JOB_COSTING_DESIGN.md §7) had to allocate crew
-- labor by INFERENCE, because "no per-job timesheets exist anywhere". Its
-- evidence hierarchy was: JobTread daily assignment > CompanyCam photo presence
-- > install schedule > even split (flagged). Every tier there is a guess about
-- who was where. CompanyCam time tracking replaces the guess with clocked hours
-- and becomes the new top tier: evidence = 'companycam hours'.
--
-- THE DECISION THIS ENCODES (Steven, 2026-09-18)
-- Hours are the ALLOCATION KEY, never a dollar source. CompanyCam says how the
-- week's real payroll dollars SPLIT across jobs; payroll says how many dollars
-- there are. This is deliberate and it is the whole point:
--
--   * CompanyCam has no pay-rate field anywhere in its API — it returns hours,
--     never dollars. Any rate table would be our invention, and would drift
--     from real pay the first time someone works overtime or gets a raise.
--   * The QBO/Gusto sweep ALREADY pushes the weekly lump into jc_actual_costs.
--     If hours x rate also wrote cost, every job would be charged for labor
--     TWICE. Splitting the real payment instead makes double-counting
--     structurally impossible rather than something a reviewer has to catch.
--   * jc_labor_allocations' existing contract is that a person's week must sum
--     to what they were actually paid. Pro-rata splitting satisfies that by
--     construction; hours x rate cannot.
--
-- So: jc_payroll_periods holds the dollars, jc_cc_time_entries holds the hours,
-- and jc_allocate_week() divides the former by the latter.
--
-- WHAT IS NOT WORKING YET (probed live 2026-09-18 — read before debugging)
--   1. ZERO hours are logged company-wide. The time-tracking plan IS active
--      (the summary endpoint answers cleanly), but nobody has clocked in. An
--      empty jc_cc_time_entries means "no adoption yet", not "broken sync".
--   2. The COMPANYCAM_TOKEN cannot read time entries over curl. /v2/projects,
--      /v2/users, /v2/company, /v2/webhooks, /v2/tags, /v2/groups all return
--      200; every time-entry path variant (/v2/timeentries, /v2/time_entries,
--      /v2/timecards, /v2/time-entries, and the summary/report forms) returns
--      302 -> /users/sign_in. A 302-to-sign_in on that token is a SCOPE
--      symptom, not a wrong path.
--   3. Likely why: CompanyCam's time tracking is busybusy-backed — webhook
--      263822 on this company posts photo.* to company-cam-api.busybusy.io.
--      The MCP connector's OAuth identity reads time entries fine; the static
--      API token does not.
--   Consequence: until the token gains time-entry scope, jc-labor-sync.py can
--   ingest from a JSON file (--from-json) but cannot poll on a schedule. Per
--   CLAUDE.md, a scheduled Routine must NOT reach CompanyCam through mcp__*
--   tools — it would stall in REQUIRES_ACTION forever rather than erroring.
-- ===========================================================================

-- ---------------------------------------------------------------------------
-- 1) Raw CompanyCam time entries. Mirrored verbatim, keyed by CompanyCam's own
--    id so re-running the sync is idempotent. `since` on the CompanyCam side
--    also surfaces soft-deleted entries, which is why deleted_at exists here:
--    an entry a crew member deletes must STOP counting toward the split, and
--    silently vanishing rows would make last week's allocation unreproducible.
-- ---------------------------------------------------------------------------
create table if not exists public.jc_cc_time_entries (
  cc_entry_id       text primary key,
  cc_user_id        text not null,
  person            text not null,            -- resolved from /v2/users at sync time
  cc_project_id     text,
  clock_in_at       timestamptz not null,
  clock_out_at      timestamptz,
  duration_seconds  numeric,
  hours             numeric,                  -- duration_seconds/3600, 3dp
  status            text check (status in ('completed','active')),
  work_date         date not null,            -- clock_in bucketed in America/New_York
  week_start        date not null,            -- Monday of work_date
  deleted_at        timestamptz,              -- soft-deleted in CompanyCam
  raw               jsonb,
  synced_at         timestamptz not null default now()
);
create index if not exists jc_cc_te_week_idx    on public.jc_cc_time_entries(person, week_start);
create index if not exists jc_cc_te_project_idx on public.jc_cc_time_entries(cc_project_id);
create index if not exists jc_cc_te_date_idx    on public.jc_cc_time_entries(work_date);

comment on table public.jc_cc_time_entries is
  'Raw CompanyCam clock-in/out mirror. Hours only — CompanyCam never returns dollars.';
comment on column public.jc_cc_time_entries.deleted_at is
  'Set when CompanyCam reports the entry soft-deleted. Excluded from allocation; kept so a past week stays reproducible.';

-- ---------------------------------------------------------------------------
-- 2) CompanyCam project -> job. THE join that decides whether labor lands on
--    the right job, and the one most likely to be wrong.
--
--    There is no hard key. CompanyCam projects carry a name and an address;
--    jc_jobs carries customer_name and address. Same-surname collisions are
--    routine in this data (the design doc already flags "two active jobs, same
--    surname" as a live failure mode). So a machine match is a PROPOSAL, and
--    confirmed_by is what makes it trustworthy.
--
--    bucket covers the non-job case: shop days, bench time, warranty go-backs.
--    Those hours must still be visible — money that vanishes into "overhead"
--    is exactly what the job-costing control exists to prevent — but they must
--    not inflate a job's labor.
-- ---------------------------------------------------------------------------
create table if not exists public.jc_cc_project_map (
  cc_project_id    text primary key,
  cc_project_name  text,
  cc_address       text,
  job_id           uuid references public.jc_jobs(id) on delete set null,
  bucket           text not null default 'job'
                   check (bucket in ('job','bench','shop','warranty','overhead','unmapped')),
  match_confidence numeric,                   -- 0..1, null when set by hand
  match_method     text,                      -- trigram_name | address | manual | single_candidate
  confirmed_by     text,
  confirmed_at     timestamptz,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now()
);
create index if not exists jc_cc_map_job_idx on public.jc_cc_project_map(job_id);

comment on table public.jc_cc_project_map is
  'CompanyCam project -> jc_jobs. Machine matches are proposals; confirmed_at is what makes one authoritative.';

-- ---------------------------------------------------------------------------
-- 3) Payroll periods — the DOLLARS being split. One row per person per week
--    per payment source, carrying what they were actually paid.
--
--    burden_pct exists for W2 (Steven's decision #3: allocate W2 payroll to
--    jobs from day one). Employer taxes and insurance are real job cost; gross
--    alone understates it. Default 0 so a 1099 row needs no thought.
--
--    allocated_at is the queue: null means this week's money has NOT been
--    split across jobs yet. That is the same posture as a held invoice — crew
--    pay cannot leave the building unallocated.
-- ---------------------------------------------------------------------------
create table if not exists public.jc_payroll_periods (
  id           uuid primary key default gen_random_uuid(),
  person       text not null,
  labor_kind   text not null default 'contract' check (labor_kind in ('contract','employee')),
  week_start   date not null,
  gross_amount numeric not null check (gross_amount >= 0),
  burden_pct   numeric not null default 0 check (burden_pct >= 0 and burden_pct < 1),
  source       text not null default 'manual' check (source in ('gusto','qbo_bill','payroll','manual')),
  source_ref   text,
  note         text,
  allocated_at timestamptz,
  created_by   text,
  created_at   timestamptz not null default now()
);
create unique index if not exists jc_payroll_uniq
  on public.jc_payroll_periods(person, week_start, coalesce(source_ref,''));
create index if not exists jc_payroll_queue_idx
  on public.jc_payroll_periods(week_start) where allocated_at is null;

comment on column public.jc_payroll_periods.burden_pct is
  'Employer burden on top of gross (W2 taxes/insurance). Allocated total = gross_amount * (1 + burden_pct).';
comment on column public.jc_payroll_periods.allocated_at is
  'Null = still on the allocation queue. Crew pay must not sit unsplit.';

-- ---------------------------------------------------------------------------
-- 4) Extend jc_labor_allocations so a row can say WHERE it came from and how
--    many hours backed it. The existing table already mirrors into
--    jc_actual_costs via jc_labor_alloc_mirror.
-- ---------------------------------------------------------------------------
alter table public.jc_labor_allocations
  add column if not exists hours              numeric,
  add column if not exists source             text not null default 'manual',
  add column if not exists payroll_period_id  uuid references public.jc_payroll_periods(id) on delete cascade,
  add column if not exists cc_project_id      text;

do $$ begin
  if not exists (select 1 from pg_constraint where conname = 'jc_labor_source_chk') then
    alter table public.jc_labor_allocations
      add constraint jc_labor_source_chk
      check (source in ('manual','companycam','jobtread_assignment','install_schedule','even_split','qbo_sweep'));
  end if;
end $$;

create index if not exists jc_labor_period_idx on public.jc_labor_allocations(payroll_period_id);

comment on column public.jc_labor_allocations.hours is
  'Clocked hours backing this allocation. Evidence, not a multiplier — dollars come from payroll.';

-- ---------------------------------------------------------------------------
-- 5) THE ALLOCATOR. Splits one person-week of real payroll across the jobs
--    they clocked into, pro rata by hours.
--
--    Two details that matter more than they look:
--
--    (a) IDEMPOTENCY. Re-running must not double-charge. jc_labor_allocations
--        mirrors into jc_actual_costs on INSERT only, so clearing allocations
--        alone would orphan the actuals. This deletes both, keyed on the
--        payroll period, before re-inserting.
--
--    (b) EXACT SUM. Naive rounding leaves a cent or two adrift, and the whole
--        premise is that a person's week ties to cash. Largest-remainder:
--        round every share down to cents, then hand the residual to the
--        largest share. sum(allocations) = gross * (1+burden), always.
-- ---------------------------------------------------------------------------
create or replace function public.jc_allocate_week(p_period_id uuid, p_actor text default 'system')
returns table (job_id uuid, bucket text, hours numeric, amount numeric)
language plpgsql security definer set search_path = public as $$
-- The RETURNS TABLE columns (job_id, bucket, hours, amount) share names with
-- jc_labor_allocations' own columns. Without this, `set amount = amount + ...`
-- is ambiguous and the function fails at runtime, not at create time.
#variable_conflict use_column
declare
  v_period      public.jc_payroll_periods%rowtype;
  v_total       numeric;
  v_total_hours numeric;
  v_allocated   numeric;
  v_top_alloc   uuid;
  v_residual    numeric;
begin
  select * into v_period from public.jc_payroll_periods where id = p_period_id;
  if not found then
    raise exception 'jc_allocate_week: no payroll period %', p_period_id;
  end if;

  v_total := round(v_period.gross_amount * (1 + v_period.burden_pct), 2);

  -- (a) clear any previous allocation of THIS period, actuals included.
  delete from public.jc_actual_costs
   where source = 'labor_alloc'
     and source_ref in (select id::text from public.jc_labor_allocations
                         where payroll_period_id = p_period_id);
  delete from public.jc_labor_allocations where payroll_period_id = p_period_id;

  -- Hours this person clocked that week. Only completed, non-deleted entries
  -- count: an open shift has no duration, and a deleted one was retracted by
  -- the crew member. No temp table on purpose -- a temp table with
  -- ON COMMIT DROP blows up the second call inside one transaction, which is
  -- exactly what allocating a batch of weeks from the intranet does.
  select coalesce(sum(t.hours), 0) into v_total_hours
    from public.jc_cc_time_entries t
   where t.person     = v_period.person
     and t.week_start = v_period.week_start
     and t.status     = 'completed'
     and t.deleted_at is null
     and coalesce(t.hours,0) > 0;

  -- No hours clocked: the money still cannot disappear. Park the whole week in
  -- the bench bucket (job_id null) so it stays visible and obviously
  -- unallocated, rather than being silently dropped or spread across jobs that
  -- have no evidence behind them.
  if v_total_hours <= 0 then
    insert into public.jc_labor_allocations
      (person, labor_kind, week_start, job_id, bucket, days, hours, amount,
       evidence, source, payroll_period_id, created_by)
    values (v_period.person, v_period.labor_kind, v_period.week_start, null, 'bench',
            null, 0, v_total,
            'no companycam hours clocked this week - unallocated',
            'companycam', p_period_id, p_actor);

    update public.jc_payroll_periods set allocated_at = now() where id = p_period_id;

    return query
      select l.job_id, l.bucket, l.hours, l.amount
        from public.jc_labor_allocations l
       where l.payroll_period_id = p_period_id;
    return;
  end if;

  -- Pro-rata split. trunc to cents so no share is ever rounded UP past its
  -- true weight; the shortfall is handed to the largest share below.
  insert into public.jc_labor_allocations
    (person, labor_kind, week_start, job_id, bucket, days, hours, amount,
     evidence, source, payroll_period_id, cc_project_id, created_by)
  select v_period.person,
         v_period.labor_kind,
         v_period.week_start,
         s.job_id,
         case when s.job_id is not null then 'job' else s.bucket end,
         round(s.hours / 8.0, 2),
         s.hours,
         trunc(v_total * (s.hours / v_total_hours) * 100) / 100,
         format('companycam hours: %s of %s h this week', s.hours, v_total_hours),
         'companycam',
         p_period_id,
         s.cc_project_id,
         p_actor
    from (
      select m.job_id                                as job_id,
             coalesce(m.bucket,'unmapped')           as bucket,
             sum(t.hours)                            as hours,
             min(t.cc_project_id)                    as cc_project_id
        from public.jc_cc_time_entries t
        left join public.jc_cc_project_map m on m.cc_project_id = t.cc_project_id
       where t.person     = v_period.person
         and t.week_start = v_period.week_start
         and t.status     = 'completed'
         and t.deleted_at is null
         and coalesce(t.hours,0) > 0
       group by 1, 2
    ) s;

  -- (b) hand the rounding residual to the largest share so the week ties to
  -- cash EXACTLY. Without this a person-week drifts a cent or two from what
  -- they were actually paid, and the one promise this table makes is that it
  -- does not.
  select coalesce(sum(l.amount), 0) into v_allocated
    from public.jc_labor_allocations l where l.payroll_period_id = p_period_id;

  v_residual := round(v_total - v_allocated, 2);
  if v_residual <> 0 then
    select l.id into v_top_alloc
      from public.jc_labor_allocations l
     where l.payroll_period_id = p_period_id
     order by l.amount desc, l.id
     limit 1;

    update public.jc_labor_allocations
       set amount = amount + v_residual
     where id = v_top_alloc;

    -- keep the mirrored actual in step with the adjusted allocation
    update public.jc_actual_costs a
       set amount = l.amount
      from public.jc_labor_allocations l
     where l.id = v_top_alloc
       and a.source = 'labor_alloc'
       and a.source_ref = l.id::text;
  end if;

  update public.jc_payroll_periods set allocated_at = now() where id = p_period_id;

  return query
    select l.job_id, l.bucket, l.hours, l.amount
      from public.jc_labor_allocations l
     where l.payroll_period_id = p_period_id
     order by l.amount desc;
end $$;

comment on function public.jc_allocate_week(uuid, text) is
  'Splits one person-week of actual payroll across jobs pro rata by CompanyCam hours. Idempotent; sums exactly to gross*(1+burden).';

-- ---------------------------------------------------------------------------
-- 6) Outbound sync logs. Both exist so a write can be UNDONE, not just traced.
--
--    jc_jobtread_cost_log matters most. Steven chose auto-write above a 0.85
--    match (2026-09-18), against the staged-write recommendation — the risk
--    being that a same-surname collision writes real money into the wrong job
--    budget with nobody watching. Auto-write is therefore only acceptable with
--    a reversal path: every line records the JobTread cost-item id it created
--    and the confidence it was written at, so a bad match can be reversed by
--    query instead of hunted through JobTread by hand.
-- ---------------------------------------------------------------------------
create table if not exists public.jc_jobtread_cost_log (
  id               uuid primary key default gen_random_uuid(),
  job_id           uuid references public.jc_jobs(id) on delete set null,
  jobtread_job_id  text not null,
  jt_cost_item_id  text,
  week_start       date,
  person           text,
  category         text,
  amount           numeric not null,
  hours            numeric,
  match_confidence numeric,
  auto_written     boolean not null default false,
  written_at       timestamptz not null default now(),
  written_by       text,
  reversed_at      timestamptz,
  reversed_by      text,
  reversal_reason  text,
  request          jsonb,
  response         jsonb
);
create index if not exists jc_jt_log_job_idx on public.jc_jobtread_cost_log(job_id, week_start);
create index if not exists jc_jt_log_live_idx on public.jc_jobtread_cost_log(jobtread_job_id) where reversed_at is null;

comment on table public.jc_jobtread_cost_log is
  'Every actual-cost line written into JobTread, with the confidence it was auto-written at and a reversal trail.';

-- jc_sm_note_log: ServiceMinder has NO cost API. Probed 2026-09-18 across 15
-- endpoint spellings (jobcost/cost/margin/purchaseorder/vendorinvoice/posting/
-- expense/joblines, singular and plural) — every one returns SM's empty-200
-- "no such endpoint" signature. Custom fields are 48 contact-level + 1
-- appointment-level; none at proposal or job level, none cost-related. So the
-- only write surface is a contact note. note_hash stops the same unchanged
-- summary being posted twice and turning the contact's note history into spam.
create table if not exists public.jc_sm_note_log (
  id             uuid primary key default gen_random_uuid(),
  job_id         uuid references public.jc_jobs(id) on delete cascade,
  brand          text not null,
  sm_contact_id  bigint not null,
  sm_proposal_id bigint,
  note_hash      text not null,
  note_body      text,
  posted_at      timestamptz not null default now(),
  posted_by      text,
  response       jsonb
);
create index if not exists jc_sm_note_job_idx on public.jc_sm_note_log(job_id, posted_at desc);
create unique index if not exists jc_sm_note_dedupe on public.jc_sm_note_log(job_id, note_hash);

comment on table public.jc_sm_note_log is
  'Cost summaries posted back to ServiceMinder as contact notes. SM exposes no cost API — a note is the only write surface.';

-- ---------------------------------------------------------------------------
-- 7) Views the intranet tab reads.
-- ---------------------------------------------------------------------------

-- Labor per job: clocked hours + allocated dollars, split by labor kind.
create or replace view public.jc_job_labor as
select j.id                                as job_id,
       j.brand,
       j.customer_name,
       j.status,
       j.contract_total,
       coalesce(sum(l.hours), 0)           as hours,
       coalesce(sum(l.amount), 0)          as labor_cost,
       coalesce(sum(l.amount) filter (where l.labor_kind = 'contract'), 0) as contract_labor,
       coalesce(sum(l.amount) filter (where l.labor_kind = 'employee'), 0) as employee_labor,
       count(distinct l.person)            as people,
       max(l.week_start)                   as last_week,
       case when coalesce(j.contract_total,0) > 0
            then round(coalesce(sum(l.amount),0) / j.contract_total * 100, 1)
       end                                 as labor_pct_of_contract
  from public.jc_jobs j
  left join public.jc_labor_allocations l on l.job_id = j.id
 group by j.id, j.brand, j.customer_name, j.status, j.contract_total;

comment on view public.jc_job_labor is
  'Per-job labor rollup. labor_pct_of_contract feeds the HFC Total Labor <15% check.';

-- The allocation queue: payroll that has not been split yet, with the hours
-- available to split it. no_hours = true means the split cannot be evidenced —
-- that week needs a human, not a retry.
create or replace view public.jc_labor_queue as
select p.id                                as payroll_period_id,
       p.person,
       p.labor_kind,
       p.week_start,
       p.gross_amount,
       p.burden_pct,
       round(p.gross_amount * (1 + p.burden_pct), 2) as allocatable,
       p.source,
       p.source_ref,
       coalesce(h.hours, 0)                as clocked_hours,
       coalesce(h.jobs, 0)                 as jobs_touched,
       coalesce(h.unmapped_hours, 0)       as unmapped_hours,
       (coalesce(h.hours,0) = 0)           as no_hours,
       (coalesce(h.unmapped_hours,0) > 0)  as has_unmapped_projects
  from public.jc_payroll_periods p
  left join lateral (
       select sum(t.hours)                                              as hours,
              count(distinct m.job_id) filter (where m.job_id is not null) as jobs,
              sum(t.hours) filter (where m.job_id is null
                                     and coalesce(m.bucket,'unmapped') = 'unmapped') as unmapped_hours
         from public.jc_cc_time_entries t
         left join public.jc_cc_project_map m on m.cc_project_id = t.cc_project_id
        where t.person = p.person
          and t.week_start = p.week_start
          and t.status = 'completed'
          and t.deleted_at is null
  ) h on true
 where p.allocated_at is null;

comment on view public.jc_labor_queue is
  'Payroll weeks awaiting allocation. has_unmapped_projects means hours exist but their CompanyCam project is not mapped to a job yet — map it before allocating or those hours land in a bucket.';

-- CompanyCam projects still needing a job, ranked by how much time is on them.
create or replace view public.jc_cc_unmapped_projects as
select t.cc_project_id,
       max(coalesce(m.cc_project_name, t.raw->'project'->>'name')) as cc_project_name,
       sum(t.hours)                as hours,
       count(*)                    as entries,
       count(distinct t.person)    as people,
       min(t.work_date)            as first_seen,
       max(t.work_date)            as last_seen,
       max(m.match_confidence)     as best_guess_confidence,
       max(m.job_id::text)         as proposed_job_id
  from public.jc_cc_time_entries t
  left join public.jc_cc_project_map m on m.cc_project_id = t.cc_project_id
 where t.deleted_at is null
   and (m.cc_project_id is null or (m.job_id is null and m.bucket in ('job','unmapped')) or m.confirmed_at is null)
 group by t.cc_project_id
 order by sum(t.hours) desc;

comment on view public.jc_cc_unmapped_projects is
  'CompanyCam projects whose hours are not yet landing on a confirmed job. Highest-hours first — that is where mis-costing hurts most.';

-- ---------------------------------------------------------------------------
-- 8) RLS — same capability as the rest of job costing (has_jc_access()).
--    Hiding the tab is not access control.
-- ---------------------------------------------------------------------------
alter table public.jc_cc_time_entries   enable row level security;
alter table public.jc_cc_project_map    enable row level security;
alter table public.jc_payroll_periods   enable row level security;
alter table public.jc_jobtread_cost_log enable row level security;
alter table public.jc_sm_note_log       enable row level security;

do $$
declare t text;
begin
  foreach t in array array['jc_cc_time_entries','jc_cc_project_map','jc_payroll_periods',
                           'jc_jobtread_cost_log','jc_sm_note_log'] loop
    execute format('drop policy if exists %I on public.%I', t||'_jc', t);
    execute format('create policy %I on public.%I for all to authenticated using (public.has_jc_access()) with check (public.has_jc_access())', t||'_jc', t);
  end loop;
end $$;

drop trigger if exists jc_cc_map_touch on public.jc_cc_project_map;
create trigger jc_cc_map_touch before update on public.jc_cc_project_map
  for each row execute function public.touch_updated_at();

-- Views run with the caller's rights so table RLS applies through PostgREST.
alter view public.jc_job_labor             set (security_invoker = on);
alter view public.jc_labor_queue           set (security_invoker = on);
alter view public.jc_cc_unmapped_projects  set (security_invoker = on);

-- ---------------------------------------------------------------------------
-- 9) ServiceMinder push becomes a QUEUE, not just a log.
--
--    Why it has to be: the intranet is a browser app talking to Supabase over
--    PostgREST with the anon key. ServiceMinder authenticates by putting its
--    ApiKey INSIDE the request body, so a browser-side post would ship a live
--    SM API key to every logged-in tab and to anyone who opens devtools. It is
--    also cross-origin. So the UI never calls ServiceMinder.
--
--    Instead: the person confirms WHICH ServiceMinder job/proposal they are
--    updating, previews the exact note, and the UI writes a `pending` row here.
--    jc-labor-sync.py --push-sm (server side, holding the key) drains it and
--    flips the row to posted/failed. The person still sees what went where.
-- ---------------------------------------------------------------------------
alter table public.jc_sm_note_log
  add column if not exists status        text not null default 'posted'
    check (status in ('pending','posted','failed')),
  add column if not exists requested_by  text,
  add column if not exists requested_at  timestamptz,
  add column if not exists error         text;

-- posted_at is only meaningful once it actually posted.
alter table public.jc_sm_note_log alter column posted_at drop not null;
alter table public.jc_sm_note_log alter column posted_at drop default;

-- The dedupe index must not block re-queueing a note that FAILED, and must not
-- let the same unchanged summary be queued twice while one is still pending.
drop index if exists public.jc_sm_note_dedupe;
create unique index if not exists jc_sm_note_dedupe
  on public.jc_sm_note_log(job_id, note_hash) where status <> 'failed';

create index if not exists jc_sm_note_pending_idx
  on public.jc_sm_note_log(requested_at) where status = 'pending';

comment on column public.jc_sm_note_log.status is
  'pending = queued by a person in the intranet; posted = written to the SM contact; failed = SM rejected it.';
