-- orders → JobTread write-back (Steven 2026-09-30: "Build the JobTread write-back").
--
-- Where ordering stands is typed on orders.ktubtu.com (the order page /o/<token> and the workbook
-- /w). This carries it back into JobTread so a PM looking at the job there sees the same thing:
--
--   · per line — the job BUDGET cost item's own fields: Status (✅Ordered / Received / …),
--     Schedule: Date Ordered, Schedule: Date Received and Purchased Cost $. The budget item, not
--     the Selection Sheet's item: items on an approved Customer Order are locked ("The
--     customFieldValues field … cannot be updated while this Customer Order is approved", probed
--     2026-09-30). A selection line (key sel:<doc item>) writes to that item's jobCostItem; an
--     estimate line (key line:<budget item>) writes to itself. The Worker resolves and stores it.
--   · per job — JobTread's "Job Status" option, moved FORWARD ONLY and only inside its ordering
--     stretch (Order To Be Placed → Sent to Supplier for Quotation → Order Partially Placed →
--     Order Placed → Some materials received). Anything a person set past that is never touched.
--     "Everything received" is a comment on the job, not a status move: scheduling is the PM's call.
--
-- Only changes are pushed: jt_pushed holds what JobTread was last given, and a line is due when
-- what it should say differs. A field someone later edits in JobTread stays as they left it until
-- the line changes again on orders.

alter table public.ord_lines add column if not exists jt_item_id text;          -- budget cost item written to
alter table public.ord_lines add column if not exists jt_pushed jsonb not null default '{}'::jsonb;
alter table public.ord_lines add column if not exists jt_pushed_at timestamptz;
alter table public.ord_lines add column if not exists jt_push_error text;

create table if not exists public.ord_jt_job_state (
  job_id uuid primary key references public.jc_jobs(id) on delete cascade,
  target text,                -- the ordering stage last evaluated (or 'ALL_RECEIVED')
  applied text,               -- what was written to Job Status, when it was (null = JobTread was ahead)
  note text,
  updated_at timestamptz not null default now()
);
alter table public.ord_jt_job_state enable row level security;   -- definer functions only

-- JobTread's item Status option for an orders status. Only the ordering words are written; a line
-- that was never pushed keeps whatever JobTread says ("Estimate: …", "Selections: …").
create or replace function public.ord_jt_item_status(p_status text, p_was_pushed boolean) returns text
language sql immutable as $$
  select case
    when p_status in ('ordered','shipped','partial','backordered') then '✅Ordered'
    when p_status = 'received' then 'Received'
    when not p_was_pushed then null
    when p_status in ('cancelled','not_ordered','sub_supplies') then 'N/A'
    else '➡️Order Ready To Be Placed' end;
$$;

-- What JobTread's item fields should say for one line. A key is present when it has a value, or
-- when it was pushed before (then null clears it in JobTread).
create or replace function public.ord_jt_desired(l public.ord_lines) returns jsonb
language sql stable as $$
  select jsonb_strip_nulls(jsonb_build_object(
           'status',   ord_jt_item_status(l.status, l.jt_pushed ? 'status'),
           'ordered',  l.ordered_on::text,
           'received', l.received_on::text,
           'cost',     l.actual_cost))
      || (select coalesce(jsonb_object_agg(k, null), '{}'::jsonb)
            from jsonb_object_keys(l.jt_pushed) k
           where k in ('ordered','received','cost')
             and case k when 'ordered' then l.ordered_on is null when 'received' then l.received_on is null
                        else l.actual_cost is null end);
$$;

-- Lines whose JobTread fields are behind. A failed line waits 6 hours before the schedule retries
-- it; asking for one job (p_jt_job) retries at once.
create or replace function public.ord_jt_pending(p_secret text, p_limit int default 40, p_jt_job text default null)
returns jsonb language plpgsql stable security definer set search_path = public as $$
declare res jsonb;
begin
  perform ord_check_secret(p_secret);
  select coalesce(jsonb_agg(x), '[]'::jsonb) into res from (
    select l.id, l.source_key, l.jt_item_id, l.jt_pushed as pushed, ord_jt_desired(l) as desired,
           j.jobtread_job_id as jt_job, coalesce(l.product, l.item) as name
      from ord_lines l join jc_jobs j on j.id = l.job_id
     where j.jobtread_job_id is not null
       and (p_jt_job is null or j.jobtread_job_id = p_jt_job)
       and l.source_key ~ '^(sel|line):' and l.removed_at is null
       and l.kind in ('product','material','selection')
       and jsonb_strip_nulls(ord_jt_desired(l)) is distinct from l.jt_pushed
       and (p_jt_job is not null or l.jt_push_error is null or l.jt_pushed_at < now() - interval '6 hours')
     order by l.updated_at desc
     limit greatest(1, least(p_limit, 200))) x;
  return res;
end $$;

-- The Worker wrote a line (p_error null) or failed to. p_item is the budget item it resolved.
create or replace function public.ord_jt_mark(p_secret text, p_id uuid, p_pushed jsonb, p_item text default null, p_error text default null)
returns void language plpgsql security definer set search_path = public as $$
begin
  perform ord_check_secret(p_secret);
  update ord_lines set
    jt_item_id    = coalesce(p_item, jt_item_id),
    jt_pushed     = case when p_error is null then jsonb_strip_nulls(coalesce(p_pushed, '{}'::jsonb)) else jt_pushed end,
    jt_pushed_at  = now(),
    jt_push_error = left(p_error, 300)
  where id = p_id;
end $$;

-- A job's ordering stage from its lines. Orderable = products and materials we buy (not labor,
-- not sub-supplied, not N/A or cancelled).
create or replace function public.ord_jt_job_target(p_job uuid) returns jsonb
language sql stable security definer set search_path = public as $$
  with s as (
    select count(*) as n,
           count(*) filter (where status in ('ordered','shipped','partial','backordered','received')) as placed,
           count(*) filter (where status = 'received') as recd,
           count(*) filter (where status in ('quote_requested','quote_received')) as quoting
      from ord_lines
     where job_id = p_job and removed_at is null and kind in ('product','material','selection')
       and status not in ('not_ordered','sub_supplies','cancelled'))
  select jsonb_build_object('n', s.n, 'placed', s.placed, 'received', s.recd, 'quoting', s.quoting,
    'target', case
      when s.n = 0 then null
      when s.recd = s.n then 'ALL_RECEIVED'
      when s.recd > 0 then 'Some materials received - Awaiting Some materials'
      when s.placed = s.n then 'Order Placed'
      when s.placed > 0 then 'Order Partially Placed'
      when s.quoting > 0 then 'Sent to Supplier for Quotation'
      when (select selections_signed from jc_jobs where id = p_job) then 'Order To Be Placed'
    end)
  from s;
$$;
revoke execute on function public.ord_jt_job_target(uuid) from anon, authenticated, public;

-- Jobs whose ordering stage changed since it was last evaluated (or p_jt_job, always).
create or replace function public.ord_jt_jobs_due(p_secret text, p_limit int default 20, p_jt_job text default null)
returns jsonb language plpgsql stable security definer set search_path = public as $$
declare res jsonb;
begin
  perform ord_check_secret(p_secret);
  select coalesce(jsonb_agg(x), '[]'::jsonb) into res from (
    select j.id as job_id, j.jobtread_job_id as jt_job, j.customer_name as customer, t.v as stage, st.target as last_target
      from jc_jobs j
      cross join lateral (select ord_jt_job_target(j.id) as v) t
      left join ord_jt_job_state st on st.job_id = j.id
     where j.jobtread_job_id is not null
       and exists (select 1 from ord_lines l where l.job_id = j.id)
       and (p_jt_job is null or j.jobtread_job_id = p_jt_job)
       and (p_jt_job is not null or (t.v->>'target') is distinct from st.target)
       and (t.v->>'target') is not null
     limit greatest(1, least(p_limit, 100))) x;
  return res;
end $$;

create or replace function public.ord_jt_job_mark(p_secret text, p_job uuid, p_target text, p_applied text, p_note text default null)
returns void language plpgsql security definer set search_path = public as $$
begin
  perform ord_check_secret(p_secret);
  insert into ord_jt_job_state (job_id, target, applied, note, updated_at)
  values (p_job, p_target, p_applied, left(p_note, 300), now())
  on conflict (job_id) do update set target = excluded.target,
    applied = coalesce(excluded.applied, ord_jt_job_state.applied), note = excluded.note, updated_at = now();
end $$;

grant execute on function public.ord_jt_pending(text, int, text), public.ord_jt_mark(text, uuid, jsonb, text, text),
  public.ord_jt_jobs_due(text, int, text), public.ord_jt_job_mark(text, uuid, text, text, text) to anon, authenticated;

-- The workbook reads whole rows: jt_pushed carries the purchased cost JobTread was given, so a
-- person without profit access gets it without the cost (same rule as every other cost field).
create or replace function public.ord_line_json(l public.ord_lines, p_profit boolean) returns jsonb
language sql stable as $$
  select case when p_profit then to_jsonb(l)
         else to_jsonb(l) - public.ord_cost_fields() - 'auto' - 'jt_pushed'
              || jsonb_build_object('auto', (l.auto - public.ord_cost_fields()), 'jt_pushed', l.jt_pushed - 'cost') end;
$$;
