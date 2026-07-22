-- Separate "can see sensitive financial data" from "is admin" (applied 2026-07-10).
-- Previously all admins (incl. Takia, Sonya) could read the Moola/AP finance data.
-- Owner wants to be the only one — gate sensitive finance on a dedicated
-- finance_access flag, granted only to the owner's accounts.

alter table public.profiles
  add column if not exists finance_access boolean not null default false;

-- Grant finance access to the owner's two accounts only.
update public.profiles set finance_access = true
  where lower(email) in ('slivingston@kitchentuneup.com','stevenglivingston@gmail.com');

-- Helper: does the current auth user have finance access?
create or replace function public.has_finance_access()
returns boolean language sql stable security definer set search_path = public as $$
  select exists (
    select 1 from public.profiles
    where id = auth.uid() and finance_access = true
  );
$$;
revoke all on function public.has_finance_access() from anon;
grant execute on function public.has_finance_access() to authenticated;

-- Sensitive finance sections gate on has_finance_access() (NOT the blanket
-- is_admin() bypass). Everything else keeps prior behavior: admins see all
-- non-sensitive; role/brand scope otherwise.
drop policy if exists intranet_records_rw on public.intranet_records;
create policy intranet_records_rw on public.intranet_records
for all to public
using (
  case
    when section = any (array[
      'moola_briefing','moola_balances','moola_ar','moola_ap','moola_cashledger',
      'moola_runway','axyom_recurring','axyom_ledger','axyom_agreements','docs_finance'])
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
      'moola_runway','axyom_recurring','axyom_ledger','axyom_agreements','docs_finance'])
    then has_finance_access()
    else (
      is_admin()
      or ((app_role() = 'homeservices') and (coalesce(brand,'Both') = any (array['KTU','BTU','Both'])))
      or ((app_role() = 'ecommerce')    and (coalesce(brand,'Both') = any (array['Earthwise','Both'])))
    )
  end
);

-- Lock the payables (AP bills) table to finance access only — it had been wide
-- open to every authenticated user.
drop policy if exists payables_authed on public.payables;
create policy payables_finance on public.payables
for all to authenticated
using (has_finance_access()) with check (has_finance_access());
