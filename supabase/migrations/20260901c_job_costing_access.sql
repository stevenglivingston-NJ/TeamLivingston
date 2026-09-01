-- Job-costing access — least privilege for the queue operator.
-- Steven named Sonya as the person who works the exceptions queue and updates
-- job costing (2026-09-01). But `payables` is RLS-gated to has_finance_access(),
-- and Sonya's profile has finance_access = false — deliberately, because that
-- flag also opens owner-only Financial Reporting / Cash Flow (business P&L and
-- personal financials). Granting her finance_access would over-share.
-- So: a dedicated `jc_access` capability that opens job costing and nothing else.

alter table public.profiles add column if not exists jc_access boolean not null default false;

create or replace function public.has_jc_access()
returns boolean language sql stable security definer set search_path = public as $$
  select exists (
    select 1 from public.profiles
    where id = auth.uid() and (jc_access = true or finance_access = true)
  );
$$;

-- Sonya operates the queue; the owner accounts already hold finance_access.
update public.profiles set jc_access = true where lower(email) = 'sonya@goaxyom.com';

-- payables: finance OR the job-costing operator
drop policy if exists payables_finance on public.payables;
create policy payables_finance on public.payables
  for all to authenticated using (public.has_jc_access()) with check (public.has_jc_access());

-- The jc_* tables were open to every authenticated user; close them to the same
-- capability so hiding the tab is not the only thing protecting the data.
do $$
declare t text;
begin
  foreach t in array array['jc_jobs','jc_forecast_lines','jc_actual_costs','jc_labor_allocations'] loop
    execute format('drop policy if exists %I on public.%I', t||'_authed', t);
    execute format('drop policy if exists %I on public.%I', replace(t,'jc_','jc_')||'_jc', t);
    execute format('create policy %I on public.%I for all to authenticated using (public.has_jc_access()) with check (public.has_jc_access())', t||'_jc', t);
  end loop;
end $$;
drop policy if exists jc_actuals_authed on public.jc_actual_costs;
drop policy if exists jc_forecast_authed on public.jc_forecast_lines;
drop policy if exists jc_labor_authed on public.jc_labor_allocations;

-- Override/escalation log: readable by the same group, never writable from the app
-- (only the trigger writes it, and that runs with table-owner rights).
drop policy if exists jc_override_read on public.jc_override_log;
create policy jc_override_read on public.jc_override_log
  for select to authenticated using (public.has_jc_access());
