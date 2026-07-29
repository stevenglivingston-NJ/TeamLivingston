-- Finance access via a per-profile flag (supersedes the is_admin() finance deny-list).
--
-- This migration DOCUMENTS a change that was made directly on the live database
-- (project tguwpswcneywvscxzyef) and was not previously captured in a repo
-- migration. It refines 20260710000000_finance_sections_rls_denylist.sql: instead
-- of gating the finance sections on is_admin(), they are gated on a dedicated
-- profiles.finance_access flag via has_finance_access(). This lets a non-admin
-- profile (e.g. a bookkeeper) be granted finance visibility without full owner
-- rights. The intranet UI mirrors it: canFinance() reads profile.finance_access,
-- and a sensitive-data hide toggle (showSensitive) layers on top for screen-share
-- privacy — presentation only; this policy is the real enforcement.
--
-- Idempotent and matches the current live state; safe to re-apply.

-- 1. profiles gains an owner-granted finance-access flag
alter table public.profiles
  add column if not exists finance_access boolean not null default false;

-- 2. the gate function
create or replace function public.has_finance_access()
  returns boolean
  language sql
  stable
  security definer
  set search_path to 'public'
as $$
  select exists (
    select 1 from public.profiles
    where id = auth.uid() and finance_access = true
  );
$$;

-- 3. finance sections gate on has_finance_access(); everything else keeps the
--    existing role/brand rules
drop policy if exists "intranet_records_rw" on public.intranet_records;

create policy "intranet_records_rw"
  on public.intranet_records for all
  using (
    CASE
      WHEN section = ANY (ARRAY[
        'moola_briefing','moola_balances','moola_ar','moola_ap','moola_cashledger',
        'moola_runway','axyom_recurring','axyom_ledger','axyom_agreements','docs_finance'
      ]) THEN has_finance_access()
      ELSE (
        is_admin()
        OR (app_role() = 'homeservices' AND COALESCE(brand,'Both') = ANY (ARRAY['KTU','BTU','Both']))
        OR (app_role() = 'ecommerce'   AND COALESCE(brand,'Both') = ANY (ARRAY['Earthwise','Both']))
      )
    END
  )
  with check (
    CASE
      WHEN section = ANY (ARRAY[
        'moola_briefing','moola_balances','moola_ar','moola_ap','moola_cashledger',
        'moola_runway','axyom_recurring','axyom_ledger','axyom_agreements','docs_finance'
      ]) THEN has_finance_access()
      ELSE (
        is_admin()
        OR (app_role() = 'homeservices' AND COALESCE(brand,'Both') = ANY (ARRAY['KTU','BTU','Both']))
        OR (app_role() = 'ecommerce'   AND COALESCE(brand,'Both') = ANY (ARRAY['Earthwise','Both']))
      )
    END
  );
