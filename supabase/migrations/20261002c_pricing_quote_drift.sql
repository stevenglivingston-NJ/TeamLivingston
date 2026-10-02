-- Saved quotes follow the price book (2026-10-02, after Roger May's painting proposal kept the old
-- bulkhead rate). The pricing Worker re-prices every saved quote from the last p_days on each
-- hourly price-book check and stamps totals.drift on the ones whose price moved; the app's quote
-- list shows it. The Worker holds only the anon key and proves itself with the shared secret it
-- already uses for the order sheets (ord_check_secret).

-- The saved quotes of one brand worth checking: priced, with a service, touched recently.
create or replace function public.pq_open_quotes(p_secret text, p_brand text, p_days int default 120)
returns jsonb language plpgsql stable security definer set search_path = public as $$
begin
  perform public.ord_check_secret(p_secret);
  return coalesce((select jsonb_agg(jsonb_build_object(
      'id', id, 'service', service, 'params', params, 'totals', totals,
      'sm_proposal_id', sm_proposal_id, 'customer', customer->>'name', 'status', status))
    from pricing_quotes
   where brand = p_brand and service is not null and params is not null
     and (totals->>'price') is not null
     and coalesce(updated_at, created_at) > now() - make_interval(days => greatest(p_days, 1))), '[]'::jsonb);
end $$;

-- Set (or, with null, clear) totals.drift. Only while the quote still carries the price the Worker
-- re-priced from: a save in between already re-priced it, and must win. Leaves updated_at alone so
-- the mark does not read as someone editing the quote.
create or replace function public.pq_set_drift(p_secret text, p_id uuid, p_drift jsonb, p_expect_price numeric)
returns boolean language plpgsql security definer set search_path = public as $$
declare n int;
begin
  perform public.ord_check_secret(p_secret);
  update pricing_quotes
     set totals = case when p_drift is null then coalesce(totals, '{}'::jsonb) - 'drift'
                       else coalesce(totals, '{}'::jsonb) || jsonb_build_object('drift', p_drift) end
   where id = p_id and round((totals->>'price')::numeric, 2) = round(p_expect_price, 2);
  get diagnostics n = row_count;
  return n > 0;
end $$;

revoke execute on function public.pq_open_quotes(text, text, int), public.pq_set_drift(text, uuid, jsonb, numeric) from public;
grant execute on function public.pq_open_quotes(text, text, int), public.pq_set_drift(text, uuid, jsonb, numeric) to anon, authenticated;
