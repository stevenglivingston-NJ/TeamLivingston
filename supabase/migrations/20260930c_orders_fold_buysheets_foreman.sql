-- ============================================================================
-- Orders (2026-09-30, part c) — fold in the buy sheets and Foreman's ordering board.
--   · ord_check_secret also admits the service role, so a scheduled agent (Foreman, via sb.sh)
--     can feed orders without holding the Worker's secret.
--   · ord_sync_job takes a feed: 'jobtread' (the order-sheet builder, keys sel:/line:) or 'sm'
--     (ServiceMinder-proposal lines for sold jobs JobTread doesn't cover, keys sm:). Each feed
--     strikes only its own lines, and the SM feed anchors on (brand, sm_proposal_id).
--   · ceiling_basis: the buy sheet's reason for a line's ceiling (or "NEEDS COSTING").
-- ============================================================================
alter table public.ord_lines add column if not exists ceiling_basis text;

-- the basis travels with the ceiling: cost-gated, and owned by the sync unless a person overrides it
create or replace function public.ord_cost_fields() returns text[] language sql immutable as $$
  select array['exp_unit_cost','exp_cost','exp_retail','ceiling','ceiling_basis','actual_cost','credit','payable_id'];
$$;
create or replace function public.ord_auto_fields() returns text[] language sql immutable as $$
  select array['kind','section','item','product','sku','vendor','link','qty','unit',
               'exp_unit_cost','exp_cost','exp_retail','ceiling','ceiling_basis','category','image_url'];
$$;

create or replace function public.ord_check_secret(p_secret text) returns void
language plpgsql stable security definer set search_path = public as $$
declare want text;
begin
  if auth.role() = 'service_role' then return; end if;
  select value into want from dispatch_config where key = 'queue_notify_secret_sha256';
  if want is null or encode(sha256(convert_to(coalesce(p_secret,''), 'UTF8')), 'hex') <> want then
    raise exception 'unauthorized';
  end if;
end $$;

drop function if exists public.ord_sync_job(text, jsonb, jsonb, text);
create or replace function public.ord_sync_job(p_secret text, p_job jsonb, p_lines jsonb, p_actor text default 'JobTread sync', p_feed text default 'jobtread')
returns jsonb language plpgsql security definer set search_path = public as $$
declare jid uuid; r jsonb; l public.ord_lines; f text; seen text[] := '{}'; ins int := 0; upd int := 0; rem int := 0;
  newv jsonb; cur jsonb; patch jsonb;
begin
  perform public.ord_check_secret(p_secret);
  perform set_config('ord.actor', coalesce(p_actor, 'JobTread sync'), true);
  perform set_config('ord.mode', 'sync', true);
  if p_feed not in ('jobtread','sm') then raise exception 'unknown feed %', p_feed; end if;

  if coalesce(p_job->>'jobtread_job_id','') <> '' then
    select id into jid from jc_jobs where jobtread_job_id = p_job->>'jobtread_job_id';
  end if;
  -- the ServiceMinder feed (Foreman) anchors on the accepted proposal, like the rest of job costing
  if jid is null and coalesce(p_job->>'sm_proposal_id','') ~ '^\d+$' then
    select id into jid from jc_jobs where brand = p_job->>'brand' and sm_proposal_id = (p_job->>'sm_proposal_id')::bigint;
  end if;
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
    insert into jc_jobs (brand, customer_name, address, status, jobtread_job_id, jobtread_number, contract_total, notes, orders_source,
                         sm_proposal_id, sm_contact_id)
    values (coalesce(p_job->>'brand','KTU'), coalesce(p_job->>'customer','(unknown)'), p_job->>'address', 'approved',
            nullif(p_job->>'jobtread_job_id',''), nullif(p_job->>'jobtread_number',''), nullif(p_job->>'contract_total','')::numeric,
            case when p_feed = 'sm' then 'Created by the ServiceMinder order feed (Foreman)' else 'Created by the JobTread order-sheet sync' end,
            case when p_feed = 'sm' then 'serviceminder' else 'jobtread' end,
            case when coalesce(p_job->>'sm_proposal_id','') ~ '^\d+$' then (p_job->>'sm_proposal_id')::bigint end,
            case when coalesce(p_job->>'sm_contact_id','') ~ '^\d+$' then (p_job->>'sm_contact_id')::bigint end)
    returning id into jid;
  end if;
  update jc_jobs set orders_tracked = true,
         orders_source = coalesce(orders_source, case when p_feed = 'sm' then 'serviceminder' else 'jobtread' end),
         orders_synced_at = now(), orders_status = coalesce(p_job->>'status', orders_status) where id = jid;

  for r in select * from jsonb_array_elements(coalesce(p_lines, '[]'::jsonb)) loop
    seen := seen || (r->>'source_key');
    newv := jsonb_strip_nulls(jsonb_build_object(
      'kind', r->>'kind', 'section', r->>'section', 'item', r->>'item', 'product', r->>'product', 'sku', r->>'sku',
      'vendor', r->>'vendor', 'link', r->>'link', 'qty', r->'qty', 'unit', r->>'unit',
      'exp_unit_cost', r->'exp_unit_cost', 'exp_cost', r->'exp_cost', 'exp_retail', r->'exp_retail',
      'ceiling', r->'ceiling', 'ceiling_basis', r->>'ceiling_basis', 'category', r->>'category', 'image_url', r->>'image_url'));
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
      exp_retail = l.exp_retail, ceiling = l.ceiling, ceiling_basis = l.ceiling_basis, category = l.category, image_url = l.image_url,
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
   where job_id = jid and source = 'auto' and removed_at is null and not (source_key = any(seen))
     -- each feed only retires its own lines: JobTread keys sel:/line:, ServiceMinder keys sm:
     and split_part(source_key, ':', 1) = any(case when p_feed = 'sm' then array['sm'] else array['sel','line'] end);
  get diagnostics rem = row_count;
  return jsonb_build_object('job_id', jid, 'inserted', ins, 'updated', upd, 'removed', rem);
end $$;

grant execute on function public.ord_sync_job(text, jsonb, jsonb, text, text) to anon, authenticated;
