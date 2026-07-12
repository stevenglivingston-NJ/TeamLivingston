-- Add the two new finance sections (moola_report exec summary, moola_cashflow
-- vendor-grouped cash flow) to the owner-only finance gate. commissions +
-- exec_summary are intentionally NOT sensitive (commissions live under Operations;
-- exec_summary is a per-tab banner).
drop policy if exists intranet_records_rw on public.intranet_records;
create policy intranet_records_rw on public.intranet_records
for all to public
using (
  case
    when section = any (array[
      'moola_briefing','moola_balances','moola_ar','moola_ap','moola_cashledger',
      'moola_runway','moola_report','moola_cashflow','axyom_recurring','axyom_ledger',
      'axyom_agreements','docs_finance'])
    then has_finance_access()
    else (
      is_admin()
      or ((app_role() = 'homeservices') and (coalesce(brand,'Both') = any (array['KTU','BTU','Both'])))
      or ((app_role() = 'ecommerce')    and (coalesce(brand,'Both') = any (array['Earthwise','Both'])))
    )
  end
)
with check (
  case
    when section = any (array[
      'moola_briefing','moola_balances','moola_ar','moola_ap','moola_cashledger',
      'moola_runway','moola_report','moola_cashflow','axyom_recurring','axyom_ledger',
      'axyom_agreements','docs_finance'])
    then has_finance_access()
    else (
      is_admin()
      or ((app_role() = 'homeservices') and (coalesce(brand,'Both') = any (array['KTU','BTU','Both'])))
      or ((app_role() = 'ecommerce')    and (coalesce(brand,'Both') = any (array['Earthwise','Both'])))
    )
  end
);
