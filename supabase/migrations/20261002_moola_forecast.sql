-- Moola 13-week cash forecast: inputs + weekly output, owner-only.
--
-- Why tables and not intranet_records sections: intranet_records' RLS only
-- hides `moola_briefing` from non-admins. Every other moola_* section is
-- readable (and writable) by any `homeservices` user. Debt schedules and
-- cash projections must not be, so they live here behind
-- has_finance_access() — owners only, not every admin.
--
-- Moola writes through sb.sh (service role, bypasses RLS). The intranet
-- reads as the signed-in user, so only finance_access profiles see rows.
-- Nothing here is emailed or sent to Slack; the intranet is the only reader.
--
-- No figures live in this file. Inputs are seeded and edited in the database.

create table if not exists public.moola_forecast_inputs (
  id           uuid primary key default gen_random_uuid(),
  entity       text not null check (entity in ('KTU','BTU')),
  kind         text not null check (kind in ('assumption','scheduled_payment','collection')),
  key          text not null,            -- assumption key, payee, or customer/job
  label        text,
  value        numeric,                  -- assumption value (rate as fraction, or $/week)
  amount       numeric,                  -- payment or collection amount ($)
  category     text,                     -- scheduled_payment: 'Debt' | 'Fixed'
  frequency    text check (frequency in ('Weekly','Monthly','Once')),
  day_of_month int check (day_of_month between 1 and 31),
  expected_on  date,                     -- collection / one-off date
  probability  numeric check (probability between 0 and 1),
  balance      numeric,                  -- loan balance, for payoff tracking
  starts_on    date,
  ends_on      date,                     -- payoff date; null = open-ended
  basis        text,                     -- where the number came from
  confirmed    boolean not null default false,
  active       boolean not null default true,
  updated_at   timestamptz not null default now(),
  updated_by   text,
  unique (entity, kind, key)
);

create table if not exists public.moola_forecast_weeks (
  id           uuid primary key default gen_random_uuid(),
  scan_date    date not null,
  entity       text not null check (entity in ('KTU','BTU','Combined')),
  week_no      int  not null check (week_no between 1 and 13),
  week_start   date not null,
  opening      numeric not null,
  inflows      numeric not null,
  outflows     numeric not null,
  closing      numeric not null,
  lines        jsonb not null default '{}'::jsonb,  -- {category: amount}
  flag         text check (flag in ('ok','below_floor','negative')),
  sources      jsonb not null default '{}'::jsonb,  -- {bank: bool, qbo: bool, sm: bool}
  created_at   timestamptz not null default now(),
  unique (scan_date, entity, week_no)
);

create index if not exists moola_forecast_weeks_scan_idx
  on public.moola_forecast_weeks (scan_date desc, entity);

alter table public.moola_forecast_inputs enable row level security;
alter table public.moola_forecast_weeks  enable row level security;

drop policy if exists moola_forecast_inputs_owner on public.moola_forecast_inputs;
create policy moola_forecast_inputs_owner on public.moola_forecast_inputs
  for all to authenticated using (public.has_finance_access()) with check (public.has_finance_access());

drop policy if exists moola_forecast_weeks_owner on public.moola_forecast_weeks;
create policy moola_forecast_weeks_owner on public.moola_forecast_weeks
  for all to authenticated using (public.has_finance_access()) with check (public.has_finance_access());

revoke all on public.moola_forecast_inputs from anon;
revoke all on public.moola_forecast_weeks  from anon;
