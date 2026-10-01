-- Recovery Desk shared state (2026-08-30)
-- ---------------------------------------------------------------------------
-- Backs the self-hosted Recovery Desk at ktubloomfield.com/follow-up, which is
-- the same work list as the published Artifact but hosted by us, because
-- artifact sharing is off for this account.
--
-- Deliberate split: this table holds ONLY the work — who owns a row, where it
-- got to, what to do next. The customer roster (names, phones, addresses) is
-- NOT here; it ships inside the passcode-gated page. So the anon key that this
-- page necessarily exposes cannot be used to pull a customer list.

create table if not exists public.recovery_desk (
  id            text primary key,      -- matches the row id baked into the page
  assignee      text not null default 'Unassigned',
  status        text not null default 'todo',
  next_step     text not null default '',
  last_contact  date,
  method        text not null default '—',
  notes         text not null default '',
  updated_by    text not null default '',
  updated_at    timestamptz not null default now()
);

alter table public.recovery_desk enable row level security;

-- The page is reached through a passcode-gated Worker, and holds no customer
-- identifiers, so the anon role may read and write it. Nothing else is exposed.
drop policy if exists recovery_desk_rw on public.recovery_desk;
create policy recovery_desk_rw on public.recovery_desk
  for all to anon, authenticated using (true) with check (true);

create or replace function public.touch_recovery_desk()
returns trigger language plpgsql as $$
begin new.updated_at = now(); return new; end $$;
drop trigger if exists trg_touch_recovery_desk on public.recovery_desk;
create trigger trg_touch_recovery_desk before update on public.recovery_desk
  for each row execute function public.touch_recovery_desk();

-- Realtime so Ben and Sonya see each other's edits without refreshing.
do $$
begin
  if not exists (select 1 from pg_publication_tables
                 where pubname='supabase_realtime' and tablename='recovery_desk') then
    alter publication supabase_realtime add table public.recovery_desk;
  end if;
end $$;
