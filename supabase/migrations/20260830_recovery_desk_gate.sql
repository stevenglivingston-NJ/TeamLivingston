-- Recovery Desk gate RPCs (2026-08-30)
-- ---------------------------------------------------------------------------
-- The Worker authenticates visitors, but it holds only the anon key and
-- recovery_desk_config is owner-only — so it could not read the passcode at
-- all and silently fell through to its build-time secret. A passcode changed
-- on the intranet therefore did nothing.
--
-- Fixed with two SECURITY DEFINER functions rather than by loosening RLS or by
-- giving the Worker a service-role key:
--
--   desk_gate(desk, passcode) -> (ok, version)
--       Verifies inside the database. The salt and hash never leave it, so the
--       anon key cannot be used to pull material for an offline guess.
--
--   desk_version(desk) -> text
--       A rotation marker (the config row's updated_at, as epoch seconds).
--       Safe to expose: it is not a secret and cannot forge anything. The
--       Worker binds it into its cookie signature, so rotating a passcode
--       invalidates every session without the Worker ever holding the hash.
--
-- Cookies stay signed with the Worker's own secret. Nothing anon-readable is
-- sufficient to mint one.

create or replace function public.desk_gate(p_desk text, p_passcode text)
returns table (ok boolean, version text)
language plpgsql security definer set search_path = public as $$
declare r public.recovery_desk_config;
begin
  select * into r from public.recovery_desk_config where desk = p_desk;
  if r.desk is null or not r.enabled or r.passcode_hash is null or r.passcode_salt is null then
    return query select false, '0'::text;
    return;
  end if;
  return query select
    encode(extensions.digest(r.passcode_salt || ':' || coalesce(p_passcode,''), 'sha256'), 'hex') = r.passcode_hash,
    extract(epoch from r.updated_at)::bigint::text;
end $$;

create or replace function public.desk_version(p_desk text)
returns text language sql security definer set search_path = public as $$
  select coalesce(
    (select extract(epoch from updated_at)::bigint::text
       from public.recovery_desk_config where desk = p_desk and enabled), '0');
$$;

grant execute on function public.desk_gate(text, text) to anon, authenticated;
grant execute on function public.desk_version(text) to anon, authenticated;
