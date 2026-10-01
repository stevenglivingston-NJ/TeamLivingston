-- Payment gate: margin escalations are advisory while the margin is an estimate
-- (2026-09-30). APPLIED LIVE 2026-09-30. BTU first; KTU added the same day at
-- Steven's call ("make it advisory for KTU too"): with 12% commission the KTU
-- P&L average is ~40%, so a hard 45% block held nearly every KTU payout.
--
-- BTU proposals are lump sums, so a BTU job's forecast cost is the BTU P&L
-- average (50.6% of revenue, 20260930_jc_cost_estimates.sql). Every BTU job with
-- an 8% commission rate therefore lands at the same ~41% and would be blocked
-- by the 45% floor -- a block that says nothing about the job, so it would be
-- approved by reflex. Steven left BTU to discretion: until real vendor costs
-- cover 25% of a BTU job's projected cost, the escalation is still raised and
-- labelled (jc_refresh_escalations is unchanged) but does not block payment.
-- Both brands: the hard block returns for a job once real vendor costs cover
-- 25% of its projected cost. The mapping gate (a) is unchanged.

create or replace function public.jc_payment_gate()
 returns trigger language plpgsql as $function$
declare v_gm numeric;
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
      if v_gm is not null and v_gm < 45
         and coalesce(new.escalation_approved_by,'') = ''
         and public.jc_job_cost_coverage(new.job_id) >= 25 then
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

-- The intranet hides "Scheduled in Melio" / "Mark paid" whenever
-- escalation_required is set, so an advisory escalation must NOT set it.
-- escalation_required now means "this payment is held"; an advisory keeps its
-- reason (prefixed "Advisory:") for the queue to show. Approved rows are never
-- rewritten or cleared (their reason carries the approver's note).
create or replace function public.jc_refresh_escalations()
 returns jsonb language plpgsql security definer set search_path to 'public' as $function$
declare n_block int; n_adv int;
begin
  update payables p set
    escalation_required = true,
    escalation_reason = 'Job projected GM ' || public.jc_job_gm(p.job_id) || '% is below the 45% floor (measured, '
      || public.jc_job_cost_coverage(p.job_id) || '% cost coverage)'
  where p.status <> 'paid' and p.job_id is not null
    and coalesce(p.escalation_approved_by,'') = ''
    and public.jc_job_gm(p.job_id) < 45 and public.jc_job_cost_coverage(p.job_id) >= 25;
  get diagnostics n_block = row_count;

  update payables p set
    escalation_required = false,
    escalation_reason = 'Advisory: job projected GM ' || public.jc_job_gm(p.job_id)
      || '% is below the 45% floor (ESTIMATE-based, ' || public.jc_job_cost_coverage(p.job_id)
      || '% cost coverage) — not held until real costs cover 25% of the job'
  where p.status <> 'paid' and p.job_id is not null
    and coalesce(p.escalation_approved_by,'') = ''
    and public.jc_job_gm(p.job_id) < 45 and public.jc_job_cost_coverage(p.job_id) < 25;
  get diagnostics n_adv = row_count;

  update payables p set escalation_required = false, escalation_reason = null
  where p.status <> 'paid' and coalesce(p.escalation_approved_by,'') = ''
    and (p.escalation_required or p.escalation_reason is not null)
    and (p.job_id is null or public.jc_job_gm(p.job_id) >= 45);
  return jsonb_build_object('escalations_held', n_block, 'advisories', n_adv);
end $function$;

select public.jc_refresh_escalations();
