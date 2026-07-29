-- Every resource can carry a Google Drive link + a last-updated timestamp.
-- The Librarian agent maps Drive files to resources (drive_url, drive_file_name,
-- drive_synced_at); a human can override/update any of it. url stays the general
-- login/weblink; drive_url is the dedicated Drive mapping.
alter table public.resources add column if not exists drive_url text;
alter table public.resources add column if not exists drive_file_name text;
alter table public.resources add column if not exists drive_synced_at timestamptz;
alter table public.resources add column if not exists updated_at timestamptz not null default now();
alter table public.resources add column if not exists updated_by text;

-- Bump updated_at on every row update (so "last updated" is always truthful).
create or replace function public.touch_resources_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at := now();
  return new;
end;
$$;
drop trigger if exists trg_resources_updated_at on public.resources;
create trigger trg_resources_updated_at before update on public.resources
  for each row execute function public.touch_resources_updated_at();
