-- Restore the owner-only finance gate on intranet_records.
--
-- 20260712_finance_gate_report_cashflow put every Moola/Axyom finance section
-- behind has_finance_access(). On 2026-10-02 the live policy was found
-- replaced (outside this repo) by one that excludes only 'moola_briefing',
-- and only from non-admins. Result: the three `homeservices` logins could
-- read AND write bank balances, AR, AP, the cash ledger, runway and the
-- vendor cash-flow view; admins without finance_access could read the briefing.
--
-- This puts the 07-12 gate back. The non-finance branch keeps the wider
-- brand list the live policy had picked up since (Shared, KTU/BTU, Combined,
-- Ops, Jatalia, earth) so no other tab changes for anyone.

drop policy if exists intranet_records_rw on public.intranet_records;
create policy intranet_records_rw on public.intranet_records
for all to authenticated
using (
  case
    when section = any (array[
      'moola_briefing','moola_balances','moola_ar','moola_ap','moola_cashledger',
      'moola_runway','moola_report','moola_cashflow','axyom_recurring','axyom_ledger',
      'axyom_agreements','docs_finance'])
    then public.has_finance_access()
    else (
      public.is_admin()
      or (public.app_role() = 'homeservices' and coalesce(brand,'Both') = any (array['KTU','BTU','Both','Shared','KTU/BTU','Combined','Ops']))
      or (public.app_role() = 'ecommerce'    and coalesce(brand,'Both') = any (array['Earthwise','Both','Shared','Jatalia','earth']))
    )
  end
)
with check (
  case
    when section = any (array[
      'moola_briefing','moola_balances','moola_ar','moola_ap','moola_cashledger',
      'moola_runway','moola_report','moola_cashflow','axyom_recurring','axyom_ledger',
      'axyom_agreements','docs_finance'])
    then public.has_finance_access()
    else (
      public.is_admin()
      or (public.app_role() = 'homeservices' and coalesce(brand,'Both') = any (array['KTU','BTU','Both','Shared','KTU/BTU','Combined','Ops']))
      or (public.app_role() = 'ecommerce'    and coalesce(brand,'Both') = any (array['Earthwise','Both','Shared','Jatalia','earth']))
    )
  end
);
