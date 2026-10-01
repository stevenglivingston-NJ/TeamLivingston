-- SIGNATURE BEFORE ANY ORDER — the orders.ktubtu.com workbook (/w) enforces it too (Steven 2026-09-30).
--
-- The pricing app's order page (/o/<token>) already refuses to place an order until the job's final
-- Selection Sheet is signed in JobTread ("Order Sheet — final selections (PDF)"). The workbook saves
-- lines straight to Supabase through ord_save_line, which had no such check, so the rule could be
-- side-stepped there. This adds it:
--
--   · jc_jobs.selections_signed (+ when / source / who / note). The pricing Worker sets it from
--     JobTread after every order-sheet sync (ord_mark_signed, shared secret). A job made by hand in
--     the workbook has no JobTread sheet to sign, so a person ticks "Signed on paper" instead
--     (ord_mark_signed_paper) — named, timed and logged in ord_history. JobTread jobs cannot be
--     ticked by hand: their signature comes from JobTread only.
--   · ord_save_line refuses to PLACE an order on an unsigned job: moving a line into ordered /
--     shipped / partial / received / backordered / damaged, or giving it a PO #, order date or
--     vendor confirmation. Lines already placed before the rule stay editable (grandfathered).
--
-- The Google Sheet Job Tracker's two-way sync is still not covered (known, documented).

alter table public.jc_jobs add column if not exists selections_signed        boolean not null default false;
alter table public.jc_jobs add column if not exists selections_signed_at     timestamptz;
alter table public.jc_jobs add column if not exists selections_signed_source text;   -- 'jobtread' | 'paper'
alter table public.jc_jobs add column if not exists selections_signed_by     text;
alter table public.jc_jobs add column if not exists selections_signed_note   text;

-- The Worker, after each order-sheet build: what JobTread says. A paper signature (hand-made job)
-- is never overwritten by a JobTread read.
create or replace function public.ord_mark_signed(p_secret text, p_jt_job text, p_signed boolean,
  p_signed_at timestamptz default null, p_doc text default null)
returns jsonb language plpgsql security definer set search_path = public as $$
declare j public.jc_jobs;
begin
  perform public.ord_check_secret(p_secret);
  select * into j from jc_jobs where jobtread_job_id = p_jt_job;
  if not found then return jsonb_build_object('found', false); end if;
  if coalesce(j.selections_signed_source, '') = 'paper' then return jsonb_build_object('found', true, 'kept', 'paper'); end if;
  if coalesce(j.selections_signed, false) is distinct from coalesce(p_signed, false) then
    update jc_jobs set selections_signed = coalesce(p_signed, false),
           selections_signed_at = case when p_signed then coalesce(p_signed_at, now()) else null end,
           selections_signed_source = case when p_signed then 'jobtread' else null end,
           selections_signed_by = case when p_signed then 'JobTread' else null end,
           selections_signed_note = case when p_signed then left(p_doc, 200) else null end
     where id = j.id;
    insert into ord_history (job_id, action, field, old_value, new_value, actor)
    values (j.id, 'job', 'selections_signed', coalesce(j.selections_signed, false)::text, coalesce(p_signed, false)::text,
            'JobTread sync' || coalesce(' — ' || left(p_doc, 120), ''));
  end if;
  return jsonb_build_object('found', true, 'signed', coalesce(p_signed, false));
end $$;
grant execute on function public.ord_mark_signed(text, text, boolean, timestamptz, text) to anon, authenticated;

-- A person, for a job made by hand in the workbook (no JobTread job): "the client signed the
-- Selection Sheet on paper". Named and logged; can be taken back the same way.
create or replace function public.ord_mark_signed_paper(p_job uuid, p_note text default null, p_undo boolean default false)
returns jsonb language plpgsql security definer set search_path = public as $$
declare j public.jc_jobs; act text;
begin
  perform public.ord_require();
  act := public.ord_actor();
  select * into j from jc_jobs where id = p_job and orders_tracked;
  if not found then raise exception 'job is not on the orders sheet'; end if;
  if j.jobtread_job_id is not null then
    raise exception 'This job is in JobTread — its Selection Sheet is signed there, not ticked here.';
  end if;
  if not p_undo and coalesce(trim(p_note), '') = '' then
    raise exception 'Say where the signed sheet is (e.g. "scanned to the job''s Drive folder, signed 9/30").';
  end if;
  update jc_jobs set selections_signed = not p_undo,
         selections_signed_at = case when p_undo then null else now() end,
         selections_signed_source = case when p_undo then null else 'paper' end,
         selections_signed_by = case when p_undo then null else act end,
         selections_signed_note = case when p_undo then null else left(p_note, 300) end
   where id = j.id;
  insert into ord_history (job_id, action, field, old_value, new_value, actor)
  values (j.id, 'job', 'selections_signed', coalesce(j.selections_signed, false)::text,
          case when p_undo then 'false' else 'true (on paper): ' || left(p_note, 200) end, act);
  return jsonb_build_object('signed', not p_undo, 'by', act);
end $$;
grant execute on function public.ord_mark_signed_paper(uuid, text, boolean) to authenticated;

-- ord_save_line, as in 20260930b, plus the signature check before the update.
create or replace function public.ord_save_line(p jsonb) returns jsonb
language plpgsql security definer set search_path = public as $$
declare l public.ord_lines; pf boolean; k text; act text; keys text[]; js public.jc_jobs;
  placed text[] := array['ordered','shipped','partial','received','backordered','damaged_return'];
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

  -- SIGNATURE BEFORE ANY ORDER (Steven 2026-09-30). Placing an order — a line moving INTO an ordered
  -- status, or getting a PO #, order date or signed vendor confirmation — needs the job's final
  -- Selection Sheet signed (JobTread, or on paper for a job made by hand here). A line already
  -- placed before the rule can still be updated (shipped, received…), as on the order page.
  select * into js from jc_jobs where id = l.job_id;
  if not coalesce(js.selections_signed, false) and not (coalesce(l.status, '') = any(placed)) and (
       ('status' = any(keys) and (p->>'status') = any(placed))
    or ('po_number' = any(keys) and coalesce(p->>'po_number', '') <> '' and (p->>'po_number') is distinct from l.po_number)
    or ('ordered_on' = any(keys) and coalesce(p->>'ordered_on', '') <> '' and nullif(p->>'ordered_on','')::date is distinct from l.ordered_on)
    or ('confirmation_on' = any(keys) and coalesce(p->>'confirmation_on', '') <> '' and nullif(p->>'confirmation_on','')::date is distinct from l.confirmation_on)) then
    raise exception '%', case when js.jobtread_job_id is null
      then 'The Selection Sheet isn''t marked signed for this job. Nothing is ordered until it is — tick "Signed (paper)" at the top of the job once the client has signed.'
      else 'The final Selection Sheet isn''t signed in JobTread yet. Nothing is ordered until it is — this job picks up the signature on its next sync, or straight away from Sync on the job.' end;
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
