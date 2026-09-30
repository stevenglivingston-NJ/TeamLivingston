-- ============================================================================
-- Orders (2026-09-30, part b) — bridge to the orders.ktubtu.com order-sheet page on main.
-- That page (orders-ui.js, saveOrderItem) and the two-way Google Sheet tracker keep per-line
-- fields in their own vocabulary (status labels, po, ordered, eta, received, actual, notes,
-- orderedBy, paidWith, confirmation). These functions translate so Supabase ord_lines is the
-- one record behind both that page and the /w workbook — no second store of order status.
-- ============================================================================
alter table public.ord_lines drop constraint if exists ord_lines_status_check;
alter table public.ord_lines add constraint ord_lines_status_check
  check (status in ('to_order','quote_requested','quote_received','ordered','shipped','partial','received',
                    'backordered','damaged_return','cancelled','sub_supplies','not_ordered'));
alter table public.ord_lines add column if not exists ordered_by text;
alter table public.ord_lines add column if not exists paid_with text;
alter table public.ord_lines add column if not exists confirmation_on date;

create or replace function public.ord_status_code(p_label text) returns text language sql immutable as $$
  select case p_label when 'Not ordered' then 'to_order' when 'Quote requested' then 'quote_requested'
    when 'Quote received' then 'quote_received' when 'Ordered' then 'ordered' when 'Shipped' then 'shipped'
    when 'Received' then 'received' when 'Backordered' then 'backordered' when 'Damaged / return' then 'damaged_return'
    when 'Cancelled' then 'cancelled' when 'N/A' then 'not_ordered' end;
$$;
create or replace function public.ord_status_label(p_code text) returns text language sql immutable as $$
  select case p_code when 'to_order' then 'Not ordered' when 'quote_requested' then 'Quote requested'
    when 'quote_received' then 'Quote received' when 'ordered' then 'Ordered' when 'shipped' then 'Shipped'
    when 'partial' then 'Shipped' when 'received' then 'Received' when 'backordered' then 'Backordered'
    when 'damaged_return' then 'Damaged / return' when 'cancelled' then 'Cancelled'
    when 'sub_supplies' then 'N/A' when 'not_ordered' then 'N/A' end;
$$;
create or replace function public.ord_date_or_null(v text) returns date language sql immutable as $$
  select case when v ~ '^\d{4}-\d{2}-\d{2}$' then v::date end;
$$;
create or replace function public.ord_money_or_null(v text) returns numeric language sql immutable as $$
  select case when regexp_replace(coalesce(v,''), '[$,\s]', '', 'g') ~ '^-?\d+(\.\d+)?$'
              then regexp_replace(v, '[$,\s]', '', 'g')::numeric end;
$$;

-- Apply the page's item fields to one line (used by saves and by tracker imports).
create or replace function public.ord_apply_item(p_line uuid, f jsonb) returns void
language plpgsql security definer set search_path = public as $$
begin
  update ord_lines t set
    status        = case when f ? 'status' and ord_status_code(f->>'status') is not null
                         and ord_status_label(t.status) is distinct from f->>'status' then ord_status_code(f->>'status') else t.status end,
    po_number     = case when f ? 'po' then nullif(f->>'po','') else t.po_number end,
    ordered_on    = case when f ? 'ordered' then ord_date_or_null(f->>'ordered') else t.ordered_on end,
    expected_on   = case when f ? 'eta' then ord_date_or_null(f->>'eta') else t.expected_on end,
    received_on   = case when f ? 'received' then ord_date_or_null(f->>'received') else t.received_on end,
    actual_cost   = case when f ? 'actual' then ord_money_or_null(f->>'actual') else t.actual_cost end,
    notes         = case when f ? 'notes' then nullif(f->>'notes','') else t.notes end,
    ordered_by    = case when f ? 'orderedBy' then nullif(f->>'orderedBy','') else t.ordered_by end,
    paid_with     = case when f ? 'paidWith' then nullif(f->>'paidWith','') else t.paid_with end,
    confirmation_on = case when f ? 'confirmation' then ord_date_or_null(f->>'confirmation') else t.confirmation_on end
  where t.id = p_line;
end $$;
revoke execute on function public.ord_apply_item(uuid, jsonb) from anon, authenticated, public;

-- The order page saved one line. p_actor = the signed-in person's email when the page sent a
-- session, otherwise the name typed on the page. Profit-gated fields are refused for a signed-in
-- person without cost access (link-only saves keep the page's existing link-is-permission model).
create or replace function public.ord_save_item(p_secret text, p_jt_job text, p_key text, p_fields jsonb,
                                                p_actor text, p_user_email text default null)
returns jsonb language plpgsql security definer set search_path = public as $$
declare lid uuid; pr profiles;
begin
  perform public.ord_check_secret(p_secret);
  if p_user_email is not null then
    select * into pr from profiles where lower(email) = lower(p_user_email);
    if pr.id is null or not (pr.orders_access or pr.role = 'admin' or pr.profit_access or pr.jc_access or pr.finance_access) then
      raise exception 'no orders access — ask an admin (pricing.ktubtu.com → Admin → Users)';
    end if;
    if p_fields ? 'actual' and not (pr.profit_access or pr.jc_access or pr.finance_access) then
      raise exception 'no cost access — actual cost is read-only for you';
    end if;
  end if;
  select l.id into lid from ord_lines l join jc_jobs j on j.id = l.job_id
   where j.jobtread_job_id = p_jt_job and l.source_key = p_key;
  if lid is null then return jsonb_build_object('ok', false, 'reason', 'line not in Supabase yet (next sync adds it)'); end if;
  perform set_config('ord.actor', coalesce(nullif(p_user_email,''), nullif(p_actor,''), 'order sheet'), true);
  perform set_config('ord.mode', '', true);
  perform public.ord_apply_item(lid, p_fields);
  return jsonb_build_object('ok', true, 'line_id', lid);
end $$;

-- Every line's page fields for one JobTread job, in the page's vocabulary, with who/when.
create or replace function public.ord_item_states(p_secret text, p_jt_job text) returns jsonb
language plpgsql security definer set search_path = public as $$
begin
  perform public.ord_check_secret(p_secret);
  return coalesce((select jsonb_object_agg(l.source_key, jsonb_strip_nulls(jsonb_build_object(
      'status', ord_status_label(l.status), 'po', l.po_number, 'ordered', l.ordered_on::text,
      'eta', l.expected_on::text, 'received', l.received_on::text,
      'actual', case when l.actual_cost is not null then to_char(l.actual_cost, 'FM999999990.00') end,
      'notes', l.notes, 'orderedBy', l.ordered_by, 'paidWith', l.paid_with, 'confirmation', l.confirmation_on::text,
      'by', l.updated_by, 'at', l.updated_at, 'removed', l.removed_at is not null)))
    from ord_lines l join jc_jobs j on j.id = l.job_id
   where j.jobtread_job_id = p_jt_job and l.source_key is not null), '{}'::jsonb);
end $$;

-- A lookup for the workbook's #jt=<JobTread id> links.
create or replace function public.ord_job_id_for_jt(p_jt text) returns uuid
language plpgsql stable security definer set search_path = public as $$
begin
  perform public.ord_require();
  return (select id from jc_jobs where jobtread_job_id = p_jt);
end $$;

grant execute on function public.ord_save_item(text, text, text, jsonb, text, text), public.ord_item_states(text, text) to anon, authenticated;
grant execute on function public.ord_job_id_for_jt(text) to authenticated;

-- ord_sync_job also applies each line's page fields (see 20260930_orders.sql for the full body)
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

-- ord_save_line accepts the order page's extra fields
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

-- job delete cascades cleanly (audit skips lines whose job is going)
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
