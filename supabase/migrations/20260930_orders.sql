-- ============================================================================
-- Orders (orders.ktubtu.com) — 2026-09-30
--
-- BUILDS ON the job-costing spine; it does not start a second one:
--   · job        = jc_jobs (same row the intranet Job Costing tab and the pricing app's
--                  Monthly reporting already read). Four columns added, nothing renamed.
--   · actual $   = jc_actual_costs. An order line with an actual cost is mirrored into the
--                  ledger as source='order_line' by trigger, so jc_job_pnl / jc_job_summary /
--                  the 45% payment gate see it with no new reporting code.
--   · invoices   = payables (ktubtubilling front door + QBO sweep). An order line linked to a
--                  CONFIRMED payable stops contributing its own row: the invoice is the cost,
--                  never both.
--   · SM notes   = jc_sm_note_log (same queue jc-labor-sync.py drains). Status 'posting'
--                  added so two drainers can never post the same note twice.
--
-- NEW: ord_lines (the order sheet rows), ord_history (who changed what), and three
-- per-person permission flags set from pricing.ktubtu.com → Admin → Users.
--
-- Access model: tables are RLS-on with NO policies for `authenticated`; every read and write
-- goes through the SECURITY DEFINER functions below, which check the caller's flags. That is
-- what lets cost/GP columns be hidden from someone who may see orders but not profitability —
-- RLS alone cannot hide columns.
-- ============================================================================

-- ---------------------------------------------------------------- permissions
alter table public.profiles add column if not exists orders_access boolean not null default false;
alter table public.profiles add column if not exists profit_access boolean not null default false;

create or replace function public.has_orders_access() returns boolean
language sql stable security definer set search_path = public as $$
  select auth.role() = 'service_role' or exists (select 1 from public.profiles where id = auth.uid()
                 and (orders_access or role = 'admin' or profit_access or jc_access or finance_access));
$$;
-- Costs, actual amounts and GP. Job-costing and finance users already see all of this.
create or replace function public.has_profit_access() returns boolean
language sql stable security definer set search_path = public as $$
  select auth.role() = 'service_role' or exists (select 1 from public.profiles where id = auth.uid()
                 and (profit_access or jc_access or finance_access));
$$;

-- Admin sets a person's flags (pricing.ktubtu.com → Admin → Users). finance_access is
-- deliberately NOT settable here: it opens owner-only personal financials.
create or replace function public.admin_set_access(p_user uuid, p_flags jsonb) returns jsonb
language plpgsql security definer set search_path = public as $$
begin
  if not public.is_admin() then raise exception 'admin only'; end if;
  update public.profiles set
    orders_access = coalesce((p_flags->>'orders_access')::boolean, orders_access),
    profit_access = coalesce((p_flags->>'profit_access')::boolean, profit_access),
    jc_access     = coalesce((p_flags->>'jc_access')::boolean, jc_access),
    updated_at    = now()
  where id = p_user;
  return (select jsonb_build_object('id', id, 'orders_access', orders_access,
          'profit_access', profit_access, 'jc_access', jc_access) from public.profiles where id = p_user);
end $$;

-- ---------------------------------------------------------------- job columns
alter table public.jc_jobs add column if not exists orders_tracked   boolean not null default false;
alter table public.jc_jobs add column if not exists orders_source    text;       -- 'jobtread' | 'manual'
alter table public.jc_jobs add column if not exists orders_synced_at timestamptz;
alter table public.jc_jobs add column if not exists orders_status    text;       -- builder verdict: Ready to order / Needs info / …
create unique index if not exists jc_jobs_jobtread_uq on public.jc_jobs (jobtread_job_id) where jobtread_job_id is not null;

-- ---------------------------------------------------------------- order lines
create table if not exists public.ord_lines (
  id            uuid primary key default gen_random_uuid(),
  job_id        uuid not null references public.jc_jobs(id) on delete cascade,
  source        text not null default 'manual' check (source in ('auto','manual')),
  source_key    text,                              -- builder key (sel:<id> / line:<id>) for idempotent sync
  kind          text not null default 'product' check (kind in ('product','selection','material','service','labor')),
  auto          jsonb not null default '{}'::jsonb, -- the builder's latest values, kept even when overridden
  overridden    text[] not null default '{}',       -- fields a person set; the sync never touches these
  needs         text[] not null default '{}',       -- builder's "needs info" list
  category      text not null default 'direct_materials'
                  check (category in ('direct_materials','contract_labor','employee_labor','sales_commission','other')),
  section       text,  item text, product text, sku text, vendor text, link text, image_url text,
  qty           numeric, unit text,
  exp_unit_cost numeric, exp_cost numeric, exp_retail numeric, ceiling numeric,
  actual_cost   numeric, credit numeric,            -- credit = returns / credits back (net = actual − credit)
  status        text not null default 'to_order'
                  -- same vocabulary as the Job Tracker's Order status column (playbook §7)
                  check (status in ('to_order','ordered','shipped','partial','received','backordered',
                                    'damaged_return','cancelled','sub_supplies','not_ordered')),
  po_number     text, ordered_on date, expected_on date, received_on date, qty_received numeric,
  need_by       date, lead_days int,
  payable_id    uuid references public.payables(id) on delete set null,
  notes         text,
  removed_at    timestamptz, removed_by text, removed_reason text,
  sort          int,
  created_by    text, created_at timestamptz not null default now(),
  updated_by    text, updated_at timestamptz not null default now()
);
create unique index if not exists ord_lines_key_uq on public.ord_lines (job_id, source_key) where source_key is not null;
create index if not exists ord_lines_job_idx on public.ord_lines (job_id);
create index if not exists ord_lines_payable_idx on public.ord_lines (payable_id) where payable_id is not null;
alter table public.ord_lines enable row level security;

create table if not exists public.ord_history (
  id        bigserial primary key,
  job_id    uuid not null references public.jc_jobs(id) on delete cascade,
  line_id   uuid,
  action    text not null,        -- add | edit | override | revert | remove | restore | sync | job
  field     text, old_value text, new_value text,
  actor     text not null,
  at        timestamptz not null default now()
);
create index if not exists ord_history_job_idx on public.ord_history (job_id, at desc);
alter table public.ord_history enable row level security;

-- Who is acting: the RPCs set ord.actor; a direct SQL edit falls back to the JWT email.
create or replace function public.ord_actor() returns text language sql stable as $$
  select coalesce(nullif(current_setting('ord.actor', true), ''), auth.email(), 'system');
$$;

-- Field-level audit on every path (RPC, sync, hand SQL).
create or replace function public.ord_lines_audit() returns trigger
language plpgsql security definer set search_path = public as $$
declare o jsonb; n jsonb; k text; act text := public.ord_actor();
  skip text[] := array['updated_at','updated_by','created_at','created_by','auto','sort','overridden','needs'];
begin
  if tg_op = 'INSERT' then
    insert into ord_history (job_id, line_id, action, new_value, actor)
    values (new.job_id, new.id, 'add', coalesce(new.product, new.item), act);
    return new;
  elsif tg_op = 'DELETE' then
    -- the whole job is being deleted (cascade): its history goes with it, nothing to record
    if not exists (select 1 from jc_jobs where id = old.job_id) then return old; end if;
    insert into ord_history (job_id, line_id, action, old_value, actor)
    values (old.job_id, old.id, 'delete', coalesce(old.product, old.item), act);
    return old;
  end if;
  o := to_jsonb(old); n := to_jsonb(new);
  for k in select jsonb_object_keys(n) loop
    continue when k = any(skip);
    if (o->k) is distinct from (n->k) then
      insert into ord_history (job_id, line_id, action, field, old_value, new_value, actor)
      values (new.job_id, new.id,
              case when k = 'removed_at' and new.removed_at is not null then 'remove'
                   when k = 'removed_at' then 'restore'
                   when coalesce(current_setting('ord.mode', true),'') = 'sync' then 'sync'
                   when k = any(new.overridden) and not (k = any(old.overridden)) then 'override'
                   when k = any(old.overridden) and not (k = any(new.overridden)) then 'revert'
                   else 'edit' end,
              k, o->>k, n->>k, act);
    end if;
  end loop;
  new.updated_at := now(); new.updated_by := act;
  return new;
end $$;
drop trigger if exists ord_lines_audit_ins on public.ord_lines;
drop trigger if exists ord_lines_audit_upd on public.ord_lines;
drop trigger if exists ord_lines_audit_del on public.ord_lines;
create trigger ord_lines_audit_ins after insert on public.ord_lines for each row execute function public.ord_lines_audit();
create trigger ord_lines_audit_upd before update on public.ord_lines for each row execute function public.ord_lines_audit();
create trigger ord_lines_audit_del after delete on public.ord_lines for each row execute function public.ord_lines_audit();

-- ---------------------------------------------------------------- ledger bridge
-- One ledger. An order line's net actual becomes a jc_actual_costs row (source 'order_line'),
-- UNLESS the line is linked to a payable that the ledger already carries — then the invoice
-- is the cost and the order line's own row is removed.
create or replace function public.ord_sync_actual(p_line uuid) returns void
language plpgsql security definer set search_path = public as $$
declare l public.ord_lines; net numeric; invoiced boolean;
begin
  select * into l from public.ord_lines where id = p_line;
  if not found then
    delete from public.jc_actual_costs where source = 'order_line' and source_ref = p_line::text;
    return;
  end if;
  net := coalesce(l.actual_cost, 0) - coalesce(l.credit, 0);
  invoiced := l.payable_id is not null and exists (
    select 1 from public.jc_actual_costs where payable_id = l.payable_id and source in ('payable','payable_auto'));
  if l.removed_at is not null or l.status = 'cancelled' or net = 0 or invoiced then
    delete from public.jc_actual_costs where source = 'order_line' and source_ref = l.id::text;
    return;
  end if;
  update public.jc_actual_costs
     set job_id = l.job_id, category = l.category, vendor = l.vendor, amount = net,
         occurred_on = coalesce(l.ordered_on, l.received_on, l.created_at::date),
         description = left(trim(coalesce(l.product, l.item, '') || coalesce(' · PO ' || l.po_number, '')), 300)
   where source = 'order_line' and source_ref = l.id::text;
  if not found then
    insert into public.jc_actual_costs (job_id, category, description, vendor, amount, occurred_on,
                                        source, source_ref, created_by)
    values (l.job_id, l.category,
            left(trim(coalesce(l.product, l.item, '') || coalesce(' · PO ' || l.po_number, '')), 300),
            l.vendor, net, coalesce(l.ordered_on, l.received_on, l.created_at::date),
            'order_line', l.id::text, coalesce(l.updated_by, l.created_by, 'orders'));
  end if;
end $$;

create or replace function public.ord_lines_ledger() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  perform public.ord_sync_actual(case when tg_op = 'DELETE' then old.id else new.id end);
  return null;
end $$;
drop trigger if exists ord_lines_ledger on public.ord_lines;
create trigger ord_lines_ledger after insert or update or delete on public.ord_lines
  for each row execute function public.ord_lines_ledger();

-- When a payable is confirmed / un-confirmed, re-decide every order line linked to it.
create or replace function public.ord_payable_changed() returns trigger
language plpgsql security definer set search_path = public as $$
declare r record;
begin
  for r in select id from public.ord_lines where payable_id = new.id loop
    perform public.ord_sync_actual(r.id);
  end loop;
  return null;
end $$;
drop trigger if exists payables_ord_lines on public.payables;
-- name sorts after payables_sync_actuals, so the ledger row for the invoice already exists
create trigger payables_zz_ord_lines after insert or update on public.payables
  for each row execute function public.ord_payable_changed();

-- ---------------------------------------------------------------- SM note claim state
alter table public.jc_sm_note_log drop constraint if exists jc_sm_note_log_status_check;
alter table public.jc_sm_note_log add constraint jc_sm_note_log_status_check
  check (status in ('pending','posting','posted','failed'));
alter table public.jc_sm_note_log add column if not exists kind text not null default 'job_costing';

-- ---------------------------------------------------------------- helpers
create or replace function public.ord_require(p_profit boolean default false) returns void
language plpgsql stable security definer set search_path = public as $$
begin
  if not public.has_orders_access() then raise exception 'no orders access — ask an admin (pricing.ktubtu.com → Admin → Users)'; end if;
  if p_profit and not public.has_profit_access() then raise exception 'no profitability access — ask an admin'; end if;
end $$;

-- Fields grouped by who may edit them, and which the JobTread sync owns.
create or replace function public.ord_cost_fields() returns text[] language sql immutable as $$
  select array['exp_unit_cost','exp_cost','exp_retail','ceiling','actual_cost','credit','payable_id'];
$$;
create or replace function public.ord_auto_fields() returns text[] language sql immutable as $$
  select array['kind','section','item','product','sku','vendor','link','qty','unit',
               'exp_unit_cost','exp_cost','exp_retail','ceiling','category','image_url'];
$$;

-- A line as the caller may see it (cost fields stripped without profit access).
create or replace function public.ord_line_json(l public.ord_lines, p_profit boolean) returns jsonb
language sql stable as $$
  select case when p_profit then to_jsonb(l)
         else to_jsonb(l) - public.ord_cost_fields() - 'auto'
              || jsonb_build_object('auto', (l.auto - public.ord_cost_fields())) end;
$$;

-- ---------------------------------------------------------------- reads
-- The portfolio: every tracked job with its order counts and (profit access) GP.
create or replace function public.ord_jobs() returns jsonb
language plpgsql stable security definer set search_path = public as $$
declare pf boolean;
begin
  perform public.ord_require();
  pf := public.has_profit_access();
  return coalesce((
    select jsonb_agg(x order by x->>'last_activity' desc nulls last) from (
      select jsonb_build_object(
        'id', j.id, 'brand', j.brand, 'customer', j.customer_name, 'address', j.address,
        'status', j.status, 'service', j.service_type,
        'jobtread_job_id', j.jobtread_job_id, 'jobtread_number', j.jobtread_number,
        'sm_contact_id', j.sm_contact_id, 'sm_proposal_id', j.sm_proposal_id,
        'orders_source', j.orders_source, 'orders_status', j.orders_status, 'orders_synced_at', j.orders_synced_at,
        'lines', c.lines, 'to_order', c.to_order, 'ordered', c.ordered, 'late', c.late,
        'received', c.received, 'needs_info', c.needs_info, 'backordered', c.backordered,
        'last_activity', (select max(at) from ord_history h where h.job_id = j.id)
      ) || case when pf then jsonb_build_object(
        'revenue', coalesce(nullif(s.total_revenue, 0), nullif(j.contract_total, 0), c.exp_retail),
        'revenue_basis', case when coalesce(s.total_revenue, j.contract_total, 0) > 0 then 'contract' else 'estimate' end,
        'exp_cost', c.exp_cost, 'order_actual', c.actual,
        'actual_cost', coalesce(s.actual_cost, 0),
        'forecast_cost', coalesce(s.forecasted_cost, 0),
        'gm_expected', case when coalesce(nullif(s.total_revenue,0), nullif(j.contract_total,0), c.exp_retail, 0) > 0
             then round(100 * (1 - c.exp_cost / coalesce(nullif(s.total_revenue,0), nullif(j.contract_total,0), c.exp_retail)), 1) end,
        'gm_actual', case when coalesce(s.actual_cost,0) > 0 and coalesce(nullif(s.total_revenue,0), nullif(j.contract_total,0), c.exp_retail, 0) > 0
             then round(100 * (1 - s.actual_cost / coalesce(nullif(s.total_revenue,0), nullif(j.contract_total,0), c.exp_retail)), 1) end
      ) else '{}'::jsonb end as x
      from jc_jobs j
      left join jc_job_summary s on s.job_id = j.id
      left join lateral (
        select count(*) filter (where l.removed_at is null) lines,
               count(*) filter (where l.removed_at is null and l.status = 'to_order' and l.kind not in ('labor','service')) to_order,
               count(*) filter (where l.removed_at is null and l.status in ('ordered','shipped','partial')) ordered,
               count(*) filter (where l.removed_at is null and l.status in ('ordered','shipped','partial','backordered') and l.expected_on < current_date) late,
               count(*) filter (where l.removed_at is null and l.status = 'backordered') backordered,
               count(*) filter (where l.removed_at is null and l.status = 'received') received,
               count(*) filter (where l.removed_at is null and cardinality(l.needs) > 0 and not ('needs' = any(l.overridden))) needs_info,
               coalesce(sum(l.exp_cost) filter (where l.removed_at is null), 0) exp_cost,
               coalesce(sum(l.exp_retail) filter (where l.removed_at is null), 0) exp_retail,
               coalesce(sum(coalesce(l.actual_cost,0) - coalesce(l.credit,0)) filter (where l.removed_at is null), 0) actual
          from ord_lines l where l.job_id = j.id) c on true
      where j.orders_tracked) q), '[]'::jsonb);
end $$;

create or replace function public.ord_job(p_job uuid) returns jsonb
language plpgsql stable security definer set search_path = public as $$
declare pf boolean;
begin
  perform public.ord_require();
  pf := public.has_profit_access();
  return jsonb_build_object(
    'job', (select to_jsonb(j) - case when pf then array[]::text[] else array['contract_total','added_revenue_post_sale','commission_pct'] end
              from jc_jobs j where j.id = p_job),
    'summary', case when pf then (select to_jsonb(s) from jc_job_summary s where s.job_id = p_job) end,
    'lines', coalesce((select jsonb_agg(public.ord_line_json(l, pf) order by l.removed_at nulls first, l.sort nulls last, l.created_at)
                         from ord_lines l where l.job_id = p_job), '[]'::jsonb),
    -- invoices already mapped to this job (the ktubtubilling front door), to link to lines
    'invoices', case when pf then coalesce((select jsonb_agg(jsonb_build_object('id', p.id, 'vendor', p.vendor,
                  'invoice_number', p.invoice_number, 'amount', p.amount, 'invoice_date', p.invoice_date,
                  'mapping_status', p.mapping_status, 'status', p.status, 'po_hint', p.po_hint,
                  'linked_lines', (select count(*) from ord_lines l where l.payable_id = p.id)) order by p.invoice_date desc)
                  from payables p where p.job_id = p_job), '[]'::jsonb) end,
    'other_costs', case when pf then coalesce((select jsonb_agg(jsonb_build_object('source', a.source, 'vendor', a.vendor,
                  'amount', a.amount, 'occurred_on', a.occurred_on, 'category', a.category, 'description', a.description))
                  from jc_actual_costs a where a.job_id = p_job and a.source <> 'order_line'), '[]'::jsonb) end,
    'sm_notes', (select coalesce(jsonb_agg(jsonb_build_object('status', n.status, 'requested_at', n.requested_at,
                  'posted_at', n.posted_at, 'error', n.error, 'requested_by', n.requested_by) order by n.requested_at desc), '[]'::jsonb)
                 from (select * from jc_sm_note_log n where n.job_id = p_job and n.kind = 'orders' order by requested_at desc limit 10) n),
    'history', (select coalesce(jsonb_agg(to_jsonb(h) - case when pf then array[]::text[]
                   else array[]::text[] end order by h.at desc), '[]'::jsonb)
                from (select * from ord_history h where h.job_id = p_job
                        and (pf or h.field is null or not (h.field = any(public.ord_cost_fields())))
                      order by at desc limit 400) h),
    'can', jsonb_build_object('profit', pf)
  );
end $$;

-- Search the job spine (for "add a client"): jobs not yet tracked, by name / JT number.
create or replace function public.ord_find_jobs(p_q text) returns jsonb
language plpgsql stable security definer set search_path = public as $$
begin
  perform public.ord_require();
  return coalesce((select jsonb_agg(jsonb_build_object('id', id, 'brand', brand, 'customer', customer_name,
            'address', address, 'status', status, 'jobtread_job_id', jobtread_job_id,
            'jobtread_number', jobtread_number, 'sm_proposal_id', sm_proposal_id, 'tracked', orders_tracked))
    from (select * from jc_jobs where customer_name ilike '%' || p_q || '%' or jobtread_number ilike '%' || p_q || '%'
          order by orders_tracked desc, updated_at desc limit 25) j), '[]'::jsonb);
end $$;

-- ---------------------------------------------------------------- writes (people)
-- Add / link a job to the orders sheet. Links to an existing jc_jobs row (by id, then by
-- JobTread id) before it ever creates one, so the job spine is not duplicated.
create or replace function public.ord_add_job(p jsonb) returns jsonb
language plpgsql security definer set search_path = public as $$
declare jid uuid; act text;
begin
  perform public.ord_require();
  act := public.ord_actor(); perform set_config('ord.actor', act, true);
  jid := nullif(p->>'id','')::uuid;
  if jid is null and coalesce(p->>'jobtread_job_id','') <> '' then
    select id into jid from jc_jobs where jobtread_job_id = p->>'jobtread_job_id';
  end if;
  if jid is null and coalesce(p->>'link_to','') <> '' then
    jid := (p->>'link_to')::uuid;
    update jc_jobs set jobtread_job_id = coalesce(jobtread_job_id, nullif(p->>'jobtread_job_id','')),
                       jobtread_number = coalesce(jobtread_number, nullif(p->>'jobtread_number',''))
     where id = jid;
  end if;
  if jid is null then
    if coalesce(p->>'brand','') not in ('KTU','BTU') or coalesce(p->>'customer','') = '' then
      raise exception 'brand (KTU/BTU) and customer are required';
    end if;
    insert into jc_jobs (brand, customer_name, address, status, jobtread_job_id, jobtread_number,
                         contract_total, notes, orders_source)
    values (p->>'brand', p->>'customer', nullif(p->>'address',''), 'approved',
            nullif(p->>'jobtread_job_id',''), nullif(p->>'jobtread_number',''),
            case when public.has_profit_access() then nullif(p->>'contract_total','')::numeric end,
            'Added from orders.ktubtu.com by ' || act, coalesce(nullif(p->>'orders_source',''), 'manual'))
    returning id into jid;
  end if;
  update jc_jobs set orders_tracked = true,
         orders_source = coalesce(orders_source, nullif(p->>'orders_source',''), 'manual')
   where id = jid;
  insert into ord_history (job_id, action, new_value, actor) values (jid, 'job', 'added to orders', act);
  return jsonb_build_object('id', jid);
end $$;

-- Create or edit one line. p = { id?, job_id, ...fields }. Editing a field the JobTread sync
-- owns records it as an override, so the next sync leaves the person's number alone.
create or replace function public.ord_save_line(p jsonb) returns jsonb
language plpgsql security definer set search_path = public as $$
declare l public.ord_lines; pf boolean; k text; act text; keys text[];
  editable text[] := array['kind','category','section','item','product','sku','vendor','link','image_url','qty','unit',
    'status','po_number','ordered_on','expected_on','received_on','qty_received','need_by','lead_days','notes','sort',
    'ordered_by','paid_with','confirmation_on',
    'exp_unit_cost','exp_cost','exp_retail','ceiling','actual_cost','credit','payable_id'];
begin
  perform public.ord_require();
  pf := public.has_profit_access();
  act := public.ord_actor(); perform set_config('ord.actor', act, true);
  select array_agg(x) into keys from jsonb_object_keys(p) x where x = any(editable);
  keys := coalesce(keys, '{}');
  if not pf and keys && public.ord_cost_fields() then raise exception 'no profitability access — cost fields are read-only for you'; end if;

  if coalesce(p->>'id','') = '' then
    if not exists (select 1 from jc_jobs where id = (p->>'job_id')::uuid and orders_tracked) then
      raise exception 'job is not on the orders sheet';
    end if;
    insert into ord_lines (job_id, source, created_by, updated_by, item)
    values ((p->>'job_id')::uuid, 'manual', act, act, coalesce(p->>'item', p->>'product', 'New item'))
    returning * into l;
  else
    select * into l from ord_lines where id = (p->>'id')::uuid for update;
    if not found then raise exception 'line not found'; end if;
  end if;

  update ord_lines t set
    kind = case when 'kind' = any(keys) then p->>'kind' else t.kind end,
    category = case when 'category' = any(keys) then p->>'category' else t.category end,
    section = case when 'section' = any(keys) then p->>'section' else t.section end,
    item = case when 'item' = any(keys) then p->>'item' else t.item end,
    product = case when 'product' = any(keys) then p->>'product' else t.product end,
    sku = case when 'sku' = any(keys) then p->>'sku' else t.sku end,
    vendor = case when 'vendor' = any(keys) then p->>'vendor' else t.vendor end,
    link = case when 'link' = any(keys) then p->>'link' else t.link end,
    image_url = case when 'image_url' = any(keys) then p->>'image_url' else t.image_url end,
    qty = case when 'qty' = any(keys) then nullif(p->>'qty','')::numeric else t.qty end,
    unit = case when 'unit' = any(keys) then p->>'unit' else t.unit end,
    status = case when 'status' = any(keys) then p->>'status' else t.status end,
    po_number = case when 'po_number' = any(keys) then p->>'po_number' else t.po_number end,
    ordered_on = case when 'ordered_on' = any(keys) then nullif(p->>'ordered_on','')::date else t.ordered_on end,
    expected_on = case when 'expected_on' = any(keys) then nullif(p->>'expected_on','')::date else t.expected_on end,
    received_on = case when 'received_on' = any(keys) then nullif(p->>'received_on','')::date else t.received_on end,
    qty_received = case when 'qty_received' = any(keys) then nullif(p->>'qty_received','')::numeric else t.qty_received end,
    need_by = case when 'need_by' = any(keys) then nullif(p->>'need_by','')::date else t.need_by end,
    lead_days = case when 'lead_days' = any(keys) then nullif(p->>'lead_days','')::int else t.lead_days end,
    notes = case when 'notes' = any(keys) then p->>'notes' else t.notes end,
    ordered_by = case when 'ordered_by' = any(keys) then p->>'ordered_by' else t.ordered_by end,
    paid_with = case when 'paid_with' = any(keys) then p->>'paid_with' else t.paid_with end,
    confirmation_on = case when 'confirmation_on' = any(keys) then nullif(p->>'confirmation_on','')::date else t.confirmation_on end,
    sort = case when 'sort' = any(keys) then nullif(p->>'sort','')::int else t.sort end,
    exp_unit_cost = case when 'exp_unit_cost' = any(keys) then nullif(p->>'exp_unit_cost','')::numeric else t.exp_unit_cost end,
    exp_cost = case when 'exp_cost' = any(keys) then nullif(p->>'exp_cost','')::numeric else t.exp_cost end,
    exp_retail = case when 'exp_retail' = any(keys) then nullif(p->>'exp_retail','')::numeric else t.exp_retail end,
    ceiling = case when 'ceiling' = any(keys) then nullif(p->>'ceiling','')::numeric else t.ceiling end,
    actual_cost = case when 'actual_cost' = any(keys) then nullif(p->>'actual_cost','')::numeric else t.actual_cost end,
    credit = case when 'credit' = any(keys) then nullif(p->>'credit','')::numeric else t.credit end,
    payable_id = case when 'payable_id' = any(keys) then nullif(p->>'payable_id','')::uuid else t.payable_id end,
    -- a person editing a sync-owned field on an auto line = an override the sync must respect
    overridden = case when t.source = 'auto'
      then (select coalesce(array_agg(distinct f), '{}') from unnest(t.overridden || (
              select coalesce(array_agg(x), '{}') from unnest(keys) x where x = any(public.ord_auto_fields())
                and (to_jsonb(t)->>x) is distinct from (p->>x))) f)
      else t.overridden end
  where t.id = l.id
  returning * into l;
  return public.ord_line_json(l, pf);
end $$;

-- Put a field back to the JobTread value.
create or replace function public.ord_revert(p_line uuid, p_field text) returns jsonb
language plpgsql security definer set search_path = public as $$
declare l public.ord_lines; pf boolean;
begin
  perform public.ord_require();
  pf := public.has_profit_access();
  if p_field = any(public.ord_cost_fields()) and not pf then raise exception 'no profitability access'; end if;
  if not (p_field = any(public.ord_auto_fields())) then raise exception 'not a JobTread-synced field'; end if;
  perform set_config('ord.actor', public.ord_actor(), true);
  select * into l from ord_lines where id = p_line for update;
  l := jsonb_populate_record(l, jsonb_build_object(p_field, l.auto->p_field));
  l.overridden := array_remove(l.overridden, p_field);
  update ord_lines set (kind, section, item, product, sku, vendor, link, qty, unit, exp_unit_cost, exp_cost,
                        exp_retail, ceiling, category, image_url, overridden)
     = (l.kind, l.section, l.item, l.product, l.sku, l.vendor, l.link, l.qty, l.unit, l.exp_unit_cost, l.exp_cost,
        l.exp_retail, l.ceiling, l.category, l.image_url, l.overridden)
   where id = p_line returning * into l;
  return public.ord_line_json(l, pf);
end $$;

-- Strike through / restore. Never a hard delete from the UI — history must survive.
create or replace function public.ord_remove_line(p_line uuid, p_reason text, p_restore boolean default false) returns jsonb
language plpgsql security definer set search_path = public as $$
declare l public.ord_lines;
begin
  perform public.ord_require();
  perform set_config('ord.actor', public.ord_actor(), true);
  update ord_lines set removed_at = case when p_restore then null else now() end,
         removed_by = case when p_restore then null else public.ord_actor() end,
         removed_reason = case when p_restore then null else nullif(p_reason,'') end
   where id = p_line returning * into l;
  return public.ord_line_json(l, public.has_profit_access());
end $$;

-- Queue a ServiceMinder contact note with the job's purchases (vendor · date · amount).
-- The pricing Worker posts it (it holds the SM key; the browser never does).
create or replace function public.ord_queue_sm_note(p_job uuid) returns jsonb
language plpgsql security definer set search_path = public as $$
declare j jc_jobs; body text; h text; act text;
begin
  perform public.ord_require(true);
  act := public.ord_actor();
  select * into j from jc_jobs where id = p_job;
  if j.sm_contact_id is null then raise exception 'this job has no ServiceMinder contact linked'; end if;
  body := public.ord_sm_note_body(p_job);
  if body is null then raise exception 'no purchases with an amount yet'; end if;
  h := left(encode(sha256(convert_to(body, 'UTF8')), 'hex'), 32);
  if exists (select 1 from jc_sm_note_log where job_id = p_job and note_hash = h and status in ('pending','posting','posted')) then
    return jsonb_build_object('queued', false, 'reason', 'this exact purchase list is already in ServiceMinder or queued');
  end if;
  insert into jc_sm_note_log (job_id, brand, sm_contact_id, sm_proposal_id, note_hash, note_body, status,
                              requested_by, requested_at, kind)
  values (p_job, j.brand, j.sm_contact_id, j.sm_proposal_id, h, body, 'pending', act, now(), 'orders');
  return jsonb_build_object('queued', true);
end $$;

create or replace function public.ord_sm_note_body(p_job uuid) returns text
language sql stable security definer set search_path = public as $$
  select case when count(*) = 0 then null else
    'PURCHASES / JOB COSTING — Proposal #' || coalesce((select sm_proposal_id::text from jc_jobs where id = p_job), 'n/a') || E'\n'
    || 'Vendor | Date purchased | Actual amount' || E'\n'
    || string_agg(coalesce(nullif(l.vendor,''), '(vendor?)') || ' | ' || coalesce(to_char(l.ordered_on, 'MM/DD/YYYY'), '(date?)')
                  || ' | $' || to_char(coalesce(l.actual_cost,0) - coalesce(l.credit,0), 'FM999,999,990.00')
                  || coalesce('  (PO ' || l.po_number || ')', ''), E'\n' order by l.ordered_on nulls last, l.vendor)
    || E'\n' || 'Total: $' || to_char(sum(coalesce(l.actual_cost,0) - coalesce(l.credit,0)), 'FM999,999,990.00')
    || E'\n' || '— from orders.ktubtu.com. Enter these under the proposal''s Margins in ServiceMinder (SM has no API for it).'
  end
  from (select vendor, ordered_on, po_number, sum(actual_cost) actual_cost, sum(credit) credit
          from ord_lines where job_id = p_job and removed_at is null and status <> 'cancelled'
           and coalesce(actual_cost,0) - coalesce(credit,0) <> 0
         group by vendor, ordered_on, po_number) l;
$$;

-- ---------------------------------------------------------------- Worker (server) entry points
-- The pricing Worker holds only the anon key. It proves itself with the same shared secret it
-- already uses for queue-notify (stored here only as a SHA-256 hash).
create or replace function public.ord_check_secret(p_secret text) returns void
language plpgsql stable security definer set search_path = public as $$
declare want text;
begin
  select value into want from dispatch_config where key = 'queue_notify_secret_sha256';
  if want is null or encode(sha256(convert_to(coalesce(p_secret,''), 'UTF8')), 'hex') <> want then
    raise exception 'unauthorized';
  end if;
end $$;

-- Idempotent sync of one job from the order-sheet builder. p_job = { jobtread_job_id, brand,
-- customer, address, jobtread_number, contract_total?, status }; p_lines = builder rows.
-- Never overwrites a field a person overrode; strikes (never deletes) auto lines that
-- disappeared from JobTread; restores them if they come back.
create or replace function public.ord_sync_job(p_secret text, p_job jsonb, p_lines jsonb, p_actor text default 'JobTread sync')
returns jsonb language plpgsql security definer set search_path = public as $$
declare jid uuid; r jsonb; l public.ord_lines; f text; seen text[] := '{}'; ins int := 0; upd int := 0; rem int := 0;
  newv jsonb; cur jsonb; patch jsonb;
begin
  perform public.ord_check_secret(p_secret);
  perform set_config('ord.actor', coalesce(p_actor, 'JobTread sync'), true);
  perform set_config('ord.mode', 'sync', true);

  select id into jid from jc_jobs where jobtread_job_id = p_job->>'jobtread_job_id';
  if jid is null then
    -- link to an SM-seeded job for the same customer that has no JobTread id yet
    select id into jid from jc_jobs
     where brand = p_job->>'brand' and jobtread_job_id is null and status <> 'closed'
       and lower(customer_name) = lower(p_job->>'customer')
     order by updated_at desc limit 1;
    if jid is not null then
      update jc_jobs set jobtread_job_id = p_job->>'jobtread_job_id',
                         jobtread_number = coalesce(jobtread_number, p_job->>'jobtread_number') where id = jid;
    end if;
  end if;
  if jid is null then
    insert into jc_jobs (brand, customer_name, address, status, jobtread_job_id, jobtread_number, contract_total, notes, orders_source)
    values (coalesce(p_job->>'brand','KTU'), coalesce(p_job->>'customer','(unknown)'), p_job->>'address', 'approved',
            p_job->>'jobtread_job_id', p_job->>'jobtread_number', nullif(p_job->>'contract_total','')::numeric,
            'Created by the JobTread order-sheet sync', 'jobtread')
    returning id into jid;
  end if;
  update jc_jobs set orders_tracked = true, orders_source = coalesce(orders_source, 'jobtread'),
         orders_synced_at = now(), orders_status = p_job->>'status' where id = jid;

  for r in select * from jsonb_array_elements(coalesce(p_lines, '[]'::jsonb)) loop
    seen := seen || (r->>'source_key');
    newv := jsonb_strip_nulls(jsonb_build_object(
      'kind', r->>'kind', 'section', r->>'section', 'item', r->>'item', 'product', r->>'product', 'sku', r->>'sku',
      'vendor', r->>'vendor', 'link', r->>'link', 'qty', r->'qty', 'unit', r->>'unit',
      'exp_unit_cost', r->'exp_unit_cost', 'exp_cost', r->'exp_cost', 'exp_retail', r->'exp_retail',
      'ceiling', r->'ceiling', 'category', r->>'category', 'image_url', r->>'image_url'));
    select * into l from ord_lines where job_id = jid and source_key = r->>'source_key';
    if not found then
      insert into ord_lines (job_id, source, source_key, auto, needs, status, created_by, sort)
      values (jid, 'auto', r->>'source_key', newv,
              coalesce((select array_agg(x) from jsonb_array_elements_text(r->'needs') x), '{}'),
              coalesce(r->>'status', 'to_order'), coalesce(p_actor, 'JobTread sync'), nullif(r->>'sort','')::int)
      returning * into l;
      ins := ins + 1;
      patch := newv;
    else
      -- only fields the person did not override, and only when the value actually changed
      cur := to_jsonb(l);
      patch := '{}'::jsonb;
      for f in select jsonb_object_keys(newv) loop
        if not (f = any(l.overridden)) and (cur->f) is distinct from (newv->f)
           and (cur->>f) is distinct from (newv->>f) then
          patch := patch || jsonb_build_object(f, newv->f);
        end if;
      end loop;
      if patch <> '{}'::jsonb or l.removed_by = 'JobTread sync' or l.auto is distinct from newv then upd := upd + 1; end if;
    end if;
    l := jsonb_populate_record(l, patch);
    update ord_lines set
      kind = l.kind, section = l.section, item = l.item, product = l.product, sku = l.sku, vendor = l.vendor,
      link = l.link, qty = l.qty, unit = l.unit, exp_unit_cost = l.exp_unit_cost, exp_cost = l.exp_cost,
      exp_retail = l.exp_retail, ceiling = l.ceiling, category = l.category, image_url = l.image_url,
      auto = newv,
      needs = coalesce((select array_agg(x) from jsonb_array_elements_text(r->'needs') x), '{}'),
      -- builder status only seeds non-ordering rows; a person's status always wins
      status = case when l.status = 'to_order' and r->>'status' in ('not_ordered','sub_supplies') then r->>'status' else l.status end,
      removed_at = case when l.removed_by = 'JobTread sync' then null else l.removed_at end,
      removed_by = case when l.removed_by = 'JobTread sync' then null else l.removed_by end,
      removed_reason = case when l.removed_by = 'JobTread sync' then null else l.removed_reason end,
      sort = coalesce(nullif(r->>'sort','')::int, l.sort)
    where id = l.id;
    -- the order page / tracker / JobTread item fields for this line, when the Worker sent them
    if jsonb_typeof(r->'fields') = 'object' then
      perform set_config('ord.mode', '', true);
      perform set_config('ord.actor', coalesce(nullif(r->'fields'->>'by',''), p_actor, 'JobTread sync'), true);
      perform public.ord_apply_item(l.id, r->'fields');
      perform set_config('ord.actor', coalesce(p_actor, 'JobTread sync'), true);
      perform set_config('ord.mode', 'sync', true);
    end if;
  end loop;

  -- auto lines no longer on the estimate/selections: strike through, keep the history
  update ord_lines set removed_at = now(), removed_by = 'JobTread sync',
         removed_reason = 'No longer on the JobTread estimate / selections'
   where job_id = jid and source = 'auto' and removed_at is null and not (source_key = any(seen));
  get diagnostics rem = row_count;
  return jsonb_build_object('job_id', jid, 'inserted', ins, 'updated', upd, 'removed', rem);
end $$;

-- Jobs the Worker should re-sync: tracked JobTread jobs, least recently synced first.
create or replace function public.ord_sync_queue(p_secret text, p_limit int default 12) returns jsonb
language plpgsql security definer set search_path = public as $$
begin
  perform public.ord_check_secret(p_secret);
  return coalesce((select jsonb_agg(jobtread_job_id) from (
    select jobtread_job_id from jc_jobs
     where orders_tracked and jobtread_job_id is not null and coalesce(orders_source,'jobtread') = 'jobtread'
       and status not in ('complete','closed')
     order by orders_synced_at nulls first limit p_limit) q), '[]'::jsonb);
end $$;

-- SM note drain for the Worker: claim pending order notes atomically ('posting'), then mark.
create or replace function public.ord_sm_claim(p_secret text, p_limit int default 10) returns jsonb
language plpgsql security definer set search_path = public as $$
begin
  perform public.ord_check_secret(p_secret);
  return coalesce((with n as (
    update jc_sm_note_log set status = 'posting'
     where id in (select id from jc_sm_note_log where status = 'pending' and kind = 'orders'
                  order by requested_at limit p_limit for update skip locked)
    returning id, brand, sm_contact_id, sm_proposal_id, note_body)
    select jsonb_agg(to_jsonb(n)) from n), '[]'::jsonb);
end $$;
create or replace function public.ord_sm_mark(p_secret text, p_id uuid, p_ok boolean, p_response jsonb, p_error text)
returns void language plpgsql security definer set search_path = public as $$
begin
  perform public.ord_check_secret(p_secret);
  update jc_sm_note_log set status = case when p_ok then 'posted' else 'failed' end,
         posted_at = case when p_ok then now() end, posted_by = 'pricing-worker',
         response = p_response, error = p_error
   where id = p_id and status = 'posting';
end $$;

-- ---------------------------------------------------------------- invoice → line matching
-- For each order line with a vendor and an amount but no invoice, link the unique invoice on
-- the same job from the same vendor whose amount matches (±$1) or whose PO hint names the PO.
-- Suggest-only when ambiguous: nothing is linked on a guess.
create or replace function public.ord_match_invoices() returns int
language plpgsql security definer set search_path = public as $$
declare r record; n int := 0; cand uuid; cnt int;
begin
  perform set_config('ord.actor', 'invoice matcher', true);
  for r in select * from ord_lines l where l.payable_id is null and l.removed_at is null
             and coalesce(l.vendor,'') <> '' loop
    select (array_agg(p.id))[1], count(*) into cand, cnt from payables p
     where p.job_id = r.job_id
       and not exists (select 1 from ord_lines x where x.payable_id = p.id)
       and similarity(lower(p.vendor), lower(r.vendor)) >= 0.45
       and ((r.actual_cost is not null and abs(p.amount - r.actual_cost) <= 1)
            or (coalesce(r.po_number,'') <> '' and (p.po_hint ilike '%' || r.po_number || '%'
                                                   or p.invoice_number ilike '%' || r.po_number || '%')));
    if cnt = 1 then
      update ord_lines set payable_id = cand,
             actual_cost = case when 'actual_cost' = any(overridden) or actual_cost is not null then actual_cost
                                else (select amount from payables where id = cand) end
       where id = r.id;
      n := n + 1;
    end if;
  end loop;
  return n;
end $$;

-- run it with the existing hourly job-costing cron
create or replace function public.jc_nightly_orders_hook() returns void language sql as $$ select public.ord_match_invoices(); $$;

grant execute on function public.has_orders_access(), public.has_profit_access(), public.admin_set_access(uuid, jsonb),
  public.ord_jobs(), public.ord_job(uuid), public.ord_find_jobs(text), public.ord_add_job(jsonb),
  public.ord_save_line(jsonb), public.ord_revert(uuid, text), public.ord_remove_line(uuid, text, boolean),
  public.ord_queue_sm_note(uuid) to authenticated;
grant execute on function public.ord_sync_job(text, jsonb, jsonb, text), public.ord_sync_queue(text, int),
  public.ord_sm_claim(text, int), public.ord_sm_mark(text, uuid, boolean, jsonb, text) to anon, authenticated;
revoke execute on function public.ord_sync_actual(uuid), public.ord_match_invoices() from anon, authenticated, public;

-- Order-line ↔ invoice matching rides the existing hourly job-costing cron (jc-match-and-escalate).
drop function if exists public.jc_nightly_orders_hook();
create or replace function public.jc_nightly() returns jsonb
language plpgsql security definer set search_path = public as $$
declare v_match jsonb; v_esc jsonb; v_ord int;
begin
  v_match := public.jc_run_matcher();
  v_ord   := public.ord_match_invoices();
  v_esc   := public.jc_refresh_escalations();
  return jsonb_build_object('ran_at', now(), 'matcher', v_match, 'order_lines_matched', v_ord, 'escalations', v_esc);
end $$;

-- Initial permissions (2026-09-30): the whole team works orders; profitability for the owner
-- accounts, Sonya (job costing) and Mayra (orders). Change per person in pricing.ktubtu.com → Admin → Users.
update public.profiles set orders_access = true where role in ('admin','homeservices');
update public.profiles set profit_access = true
 where lower(email) in ('stevenglivingston@gmail.com','slivingston@kitchentuneup.com','sonya@goaxyom.com','mdasilva@kitchentuneup.com');
