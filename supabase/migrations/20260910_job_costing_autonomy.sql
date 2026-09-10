-- Job costing, part 4: make the actuals ledger self-maintaining and put the
-- daily upkeep on Postgres's own scheduler.
--
-- Two problems this fixes, both found on the 2026-09-08 live audit:
--
-- 1) `jc_actual_costs` was written ONLY by the intranet's jcConfirm() handler.
--    Anything that mapped a payable by another route -- the seed script, a
--    future QBO sync, a hand-fix in SQL -- left the payable `confirmed` with no
--    actual-cost row, so the invoice never reached `jc_job_pnl`. Three seeded
--    confirmations ($30,823) were sitting in exactly that hole. The ledger now
--    follows the payable's mapping state from a trigger, so every path agrees.
--
-- 2) `jc_run_matcher()` and `jc_refresh_escalations()` only ever ran when a
--    human clicked "Run matcher" or an agent session happened to fire. Both are
--    pure SQL, so they belong on pg_cron -- which runs inside Supabase and does
--    not depend on anyone's laptop being awake.
--
-- Applied 2026-09-10.

-- ---------------------------------------------------------------------------
-- 1) Payable mapping -> actuals ledger, on every write path
-- ---------------------------------------------------------------------------

-- Rows this trigger owns carry source='payable_auto'. A human split (several
-- rows against one payable, entered in the UI) is left alone: the operator's
-- allocation beats a generated one, and `jc_split_mismatch` already flags a
-- split whose parts don't sum to the invoice.
create or replace function public.jc_sync_actual_from_payable() returns trigger
language plpgsql security definer set search_path = public as $$
declare
  v_rows  int;
  v_fl    uuid;
  v_cnt   int;
begin
  if new.job_id is not null
     and coalesce(new.jc_category,'') not in ('', 'overhead_non_job')
     and new.mapping_status in ('confirmed','override') then

    select count(*) into v_rows from public.jc_actual_costs where payable_id = new.id;

    if v_rows = 0 then
      -- Best-effort sold-line attach, same rule the UI uses: only when the
      -- job+category resolves to exactly one forecast line is the link safe.
      v_fl := new.forecast_line_id;
      if v_fl is null then
        select (array_agg(id))[1], count(*) into v_fl, v_cnt
          from public.jc_forecast_lines
         where job_id = new.job_id and category = new.jc_category;
        if v_cnt <> 1 then v_fl := null; end if;
      end if;

      insert into public.jc_actual_costs
        (job_id, category, description, vendor, amount, occurred_on, payable_id,
         forecast_line_id, is_unplanned, unplanned_kind, source, created_by)
      values
        (new.job_id, new.jc_category,
         trim(both ' ' from coalesce(new.vendor,'') || ' ' || coalesce(new.invoice_number,'')),
         new.vendor, new.amount, new.invoice_date, new.id,
         v_fl, coalesce(new.is_unplanned,false), new.unplanned_kind,
         'payable_auto', coalesce(new.mapped_by,'system'));

    else
      -- Keep the generated row in step with later edits to the invoice.
      -- Untouched when the operator has hand-split the payable.
      update public.jc_actual_costs
         set job_id         = new.job_id,
             category       = new.jc_category,
             vendor         = new.vendor,
             amount         = new.amount,
             occurred_on    = new.invoice_date,
             is_unplanned   = coalesce(new.is_unplanned,false),
             unplanned_kind = new.unplanned_kind
       where payable_id = new.id and source = 'payable_auto';
    end if;

  else
    -- No longer mapped (back to held/unmapped, or reclassified as overhead):
    -- every actual-cost row derived from this payable is now wrong, splits
    -- included. Costs must come off the job the moment the mapping does.
    delete from public.jc_actual_costs
     where payable_id = new.id and source in ('payable','payable_auto');
  end if;

  return null;
end $$;

drop trigger if exists payables_sync_actuals on public.payables;
create trigger payables_sync_actuals
  after insert or update on public.payables
  for each row execute function public.jc_sync_actual_from_payable();

-- Backfill: every payable already mapped by a non-UI path.
insert into public.jc_actual_costs
  (job_id, category, description, vendor, amount, occurred_on, payable_id,
   is_unplanned, source, created_by)
select p.job_id, p.jc_category,
       trim(both ' ' from coalesce(p.vendor,'') || ' ' || coalesce(p.invoice_number,'')),
       p.vendor, p.amount, p.invoice_date, p.id,
       coalesce(p.is_unplanned,false), 'payable_auto', coalesce(p.mapped_by,'system')
  from public.payables p
 where p.job_id is not null
   and coalesce(p.jc_category,'') not in ('', 'overhead_non_job')
   and p.mapping_status in ('confirmed','override')
   and not exists (select 1 from public.jc_actual_costs a where a.payable_id = p.id);

-- ---------------------------------------------------------------------------
-- 2) Daily upkeep on pg_cron (runs in Supabase, not on anyone's machine)
-- ---------------------------------------------------------------------------

-- One entry point so the schedule has a single thing to call and a single
-- place to add steps later.
create or replace function public.jc_nightly() returns jsonb
language plpgsql security definer set search_path = public as $$
declare v_match jsonb; v_esc jsonb;
begin
  v_match := public.jc_run_matcher();
  v_esc   := public.jc_refresh_escalations();
  return jsonb_build_object('ran_at', now(), 'matcher', v_match, 'escalations', v_esc);
end $$;

revoke all on function public.jc_nightly() from public, anon;
grant execute on function public.jc_nightly() to authenticated, service_role;

-- Hourly at :35. Invoices arrive through the day, so an unmapped bill should
-- not wait for a nightly pass to get its auto-match attempt and its margin
-- escalation recomputed.
select cron.unschedule('jc-match-and-escalate')
 where exists (select 1 from cron.job where jobname = 'jc-match-and-escalate');

select cron.schedule('jc-match-and-escalate', '35 * * * *', $cron$
  select public.jc_nightly();
$cron$);
