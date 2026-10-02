-- The hourly re-price (20261002c) marked 8 quotes on its first run; 3 were internal test quotes
-- ("ZZ Pricing App E2E", "Price Engine", Steven's own BTU quote). Test and internal quotes now stay
-- out of the re-price and lose any mark they already carry. The rule extends the canonical
-- is_test_record (CLAUDE.md, Test/UAT records) with the pricing app's own fixtures: names starting
-- "zz", "E2E", "Price Engine", and quotes addressed to the owner's or the team's own mailboxes.
-- Retired services ("Custom Kitchen", "Please Select") are skipped by the Worker, which knows the
-- current service list.

create or replace function public.pq_is_internal_quote(p_customer jsonb) returns boolean
language sql immutable as $$
  select public.is_test_record(p_customer->>'name', p_customer->>'email')
      or btrim(coalesce(p_customer->>'name', '')) ~* '^zz|\ye2e\y|^price engine$'
      or lower(btrim(coalesce(p_customer->>'email', ''))) ~ '^stevenglivingston@gmail\.com$|@(kitchentuneup|bathtuneup|goaxyom|ktubtu)\.com$';
$$;
grant execute on function public.pq_is_internal_quote(jsonb) to anon, authenticated, service_role;

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
     and not public.pq_is_internal_quote(customer)
     and coalesce(updated_at, created_at) > now() - make_interval(days => greatest(p_days, 1))), '[]'::jsonb);
end $$;

-- Marks already on internal quotes (updated_at untouched, as pq_set_drift does).
update pricing_quotes set totals = totals - 'drift'
 where totals ? 'drift' and public.pq_is_internal_quote(customer);
