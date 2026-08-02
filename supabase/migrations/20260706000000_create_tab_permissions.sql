-- Per-role tab/section visibility overrides for the Axyom intranet.
-- Default visibility is computed client-side from the existing scope rules
-- (see TAB_SECTIONS/defaultTabVisible in ktubtuintranet.html); a row here
-- overrides that default for a given (role, tab) pair. Admin is intentionally
-- never gated by this table (enforced client-side) so a bad override can't
-- lock the owner out of the console that manages it.
create table if not exists public.tab_permissions (
  role text not null,
  tab text not null,
  visible boolean not null,
  updated_at timestamptz not null default now(),
  updated_by uuid references public.profiles(id),
  primary key (role, tab)
);

alter table public.tab_permissions enable row level security;

create policy "read own-role permissions or admin reads all"
  on public.tab_permissions for select
  using (is_admin() or role = app_role());

create policy "admin writes permissions"
  on public.tab_permissions for all
  using (is_admin())
  with check (is_admin());
