-- ord_sm_claim: the data-modifying CTE must be the top-level statement (it was nested inside
-- coalesce(select …), which Postgres rejects: "WITH clause containing a data-modifying statement
-- must be at the top level"). Found on the first scheduled run, 2026-09-30 20:45 UTC.
create or replace function public.ord_sm_claim(p_secret text, p_limit int default 10) returns jsonb
language plpgsql security definer set search_path = public as $$
declare res jsonb;
begin
  perform public.ord_check_secret(p_secret);
  with n as (
    update jc_sm_note_log set status = 'posting'
     where id in (select id from jc_sm_note_log where status = 'pending' and kind = 'orders'
                  order by requested_at limit p_limit for update skip locked)
    returning id, brand, sm_contact_id, sm_proposal_id, note_body)
  select jsonb_agg(to_jsonb(n)) into res from n;
  return coalesce(res, '[]'::jsonb);
end $$;
