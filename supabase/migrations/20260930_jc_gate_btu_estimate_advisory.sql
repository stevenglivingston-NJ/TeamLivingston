-- Payment gate: BTU margin escalations are advisory while the margin is only
-- the brand average (2026-09-30). APPLIED LIVE 2026-09-30.
--
-- BTU proposals are lump sums, so a BTU job's forecast cost is the BTU P&L
-- average (50.6% of revenue, 20260930_jc_cost_estimates.sql). Every BTU job with
-- an 8% commission rate therefore lands at the same ~41% and would be blocked
-- by the 45% floor -- a block that says nothing about the job, so it would be
-- approved by reflex. Steven left BTU to discretion: until real vendor costs
-- cover 25% of a BTU job's projected cost, the escalation is still raised and
-- labelled (jc_refresh_escalations is unchanged) but does not block payment.
-- KTU keeps the hard block. The mapping gate (a) is unchanged for both brands.

create or replace function public.jc_payment_gate()
 returns trigger language plpgsql as $function$
declare v_gm numeric; v_brand text;
begin
  if new.status in ('scheduled','paid') and old.status is distinct from new.status then
    -- (a) mapping gate
    if not (new.mapping_status in ('confirmed','override')
            or coalesce(new.jc_category,'') = 'overhead_non_job') then
      raise exception
        'Payment blocked: payable % (% %) is % — map it to a job or record an override first',
        new.id, new.vendor, new.invoice_number, new.mapping_status;
    end if;
    -- (b) margin escalation gate — 45% floor
    if new.job_id is not null then
      v_gm := public.jc_job_gm(new.job_id);
      select brand into v_brand from jc_jobs where id = new.job_id;
      if v_gm is not null and v_gm < 45
         and coalesce(new.escalation_approved_by,'') = ''
         and not (v_brand = 'BTU' and public.jc_job_cost_coverage(new.job_id) < 25) then
        -- built by concatenation: %-escaping inside RAISE printed "%41.0"
        raise exception '%', 'Payout escalation required: job projected gross margin is '
          || v_gm || '% (below the 45% floor). A named approver must release this payment.';
      end if;
    end if;
  end if;
  -- an override must carry a reason and a person
  if new.mapping_status = 'override'
     and (coalesce(new.held_reason,'') = '' or coalesce(new.mapped_by,'auto') = 'auto') then
    raise exception 'Override requires held_reason (why) and mapped_by (who)';
  end if;
  -- an escalation approval must carry a reason and a person
  if coalesce(new.escalation_approved_by,'') <> ''
     and coalesce(new.escalation_reason,'') = '' then
    raise exception 'Margin escalation approval requires a reason';
  end if;
  return new;
end $function$;
