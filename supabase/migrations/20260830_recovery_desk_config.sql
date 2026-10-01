-- Recovery Desk access config (2026-08-30)
-- ---------------------------------------------------------------------------
-- Moves the desk passcode out of a Cloudflare Worker secret and into the
-- database, so the owner can change it from the intranet instead of needing
-- wrangler. Keyed by desk so the Bath Tune-Up desk can be added alongside the
-- Kitchen Tune-Up one without touching the Worker.
--
-- The passcode is NEVER stored in plaintext. We keep a random per-desk salt and
-- SHA-256(salt || ':' || passcode); the Worker hashes what a visitor typed and
-- compares. So a database read does not hand anyone the passcode, and the
-- intranet can set a new one but cannot display the current one — which is the
-- correct trade: whoever sets it is the one who tells the team.

create table if not exists public.recovery_desk_config (
  desk           text primary key,          -- 'ktu', later 'btu'
  brand          text not null,
  label          text not null,
  url            text not null,
  passcode_salt  text,
  passcode_hash  text,                      -- hex sha-256 of salt || ':' || passcode
  enabled        boolean not null default true,
  updated_by     text default '',
  updated_at     timestamptz not null default now()
);

alter table public.recovery_desk_config enable row level security;

-- Owner-only. The Worker reads it with the service key, which bypasses RLS.
drop policy if exists recovery_desk_config_admin on public.recovery_desk_config;
create policy recovery_desk_config_admin on public.recovery_desk_config
  for all to authenticated using (public.is_admin()) with check (public.is_admin());

create or replace function public.touch_recovery_desk_config()
returns trigger language plpgsql as $$
begin new.updated_at = now(); return new; end $$;
drop trigger if exists trg_touch_recovery_desk_config on public.recovery_desk_config;
create trigger trg_touch_recovery_desk_config before update on public.recovery_desk_config
  for each row execute function public.touch_recovery_desk_config();

insert into public.recovery_desk_config (desk, brand, label, url, enabled) values
  ('ktu', 'KTU', 'Kitchen Tune-Up Recovery Desk',
   'https://www.ktubloomfield.com/follow-up', true)
on conflict (desk) do update set label = excluded.label, url = excluded.url;

-- BTU placeholder: registered so the intranet shows it as coming, but disabled
-- and with no passcode, so nothing is reachable until a desk is actually built.
insert into public.recovery_desk_config (desk, brand, label, url, enabled) values
  ('btu', 'BTU', 'Bath Tune-Up Recovery Desk', '', false)
on conflict (desk) do nothing;
