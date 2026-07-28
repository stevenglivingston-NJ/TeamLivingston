-- Lock down ALL finance sections at the database level, not just moola_briefing.
--
-- Before this migration the intranet_records RLS policy excluded only
-- 'moola_briefing' from non-admin access. Every other finance section
-- (the new structured Moola forecast sections, plus the Axyom intercompany
-- tracker and finance doc links) was readable AND writable by any signed-in
-- team member via the anon key — the UI hid the tabs, but the data was not
-- actually protected. This replaces the single-section exclusion with a
-- finance deny-list so those rows require is_admin() for both read and write.
--
-- Deny-listed sections (owner-only):
--   moola_briefing     — CFO daily briefing (already protected; kept)
--   moola_balances     — bank + liability balances, term-bucketed
--   moola_ar           — aged receivables (named)
--   moola_ap           — payables queue (named)
--   moola_cashledger   — dated 90-day inflow/outflow ledger
--   moola_runway       — runway snapshots (trend history)
--   axyom_recurring    — intercompany recurring obligations
--   axyom_ledger       — intercompany one-off ledger
--   axyom_agreements   — intercompany agreements
--   docs_finance       — finance document links
--
-- Non-admin roles keep their existing brand-scoped access to every OTHER
-- section unchanged. Admin (owner) is unaffected — is_admin() short-circuits.

drop policy if exists "intranet_records_rw" on public.intranet_records;

create policy "intranet_records_rw"
  on public.intranet_records for all
  using (
    is_admin() OR (
      section <> ALL (ARRAY[
        'moola_briefing','moola_balances','moola_ar','moola_ap',
        'moola_cashledger','moola_runway','axyom_recurring',
        'axyom_ledger','axyom_agreements','docs_finance'
      ])
      AND (
        (app_role() = 'homeservices' AND COALESCE(brand,'Both') = ANY (ARRAY['KTU','BTU','Both']))
        OR (app_role() = 'ecommerce' AND COALESCE(brand,'Both') = ANY (ARRAY['Earthwise','Both']))
      )
    )
  )
  with check (
    is_admin() OR (
      section <> ALL (ARRAY[
        'moola_briefing','moola_balances','moola_ar','moola_ap',
        'moola_cashledger','moola_runway','axyom_recurring',
        'axyom_ledger','axyom_agreements','docs_finance'
      ])
      AND (
        (app_role() = 'homeservices' AND COALESCE(brand,'Both') = ANY (ARRAY['KTU','BTU','Both']))
        OR (app_role() = 'ecommerce' AND COALESCE(brand,'Both') = ANY (ARRAY['Earthwise','Both']))
      )
    )
  );
