-- Finding lifecycle state, keyed by a stable fingerprint rather than the row,
-- because every agent section is rewritten daily: state written onto the
-- finding row is wiped by the next run. The fingerprint hashes what stays
-- stable (section, kind, brand, the title with its volatile numbers stripped)
-- so today's re-emitted finding re-attaches to yesterday's assignment.
-- Same survival pattern as project_state and the tracker's hide/close.
create table if not exists finding_state (
  fingerprint  text primary key,
  section      text not null,
  brand        text,
  title_at_assign text,
  status       text not null default 'new',     -- new|acknowledged|assigned|resolved|dismissed
  owner        text,
  due_date     date,
  task_id      uuid,                            -- team_tasks row when assigned
  status_by    text,
  status_at    timestamptz,
  last_seen    timestamptz not null default now(), -- bumped when a run re-emits it
  created_at   timestamptz not null default now()
);
comment on table finding_state is
  'Human lifecycle state for agent findings. Keyed by fingerprint so it survives the daily re-seed. Anyone on the shared login may assign (Steven, 2026-09-01).';
alter table finding_state enable row level security;
drop policy if exists finding_state_rw on finding_state;
create policy finding_state_rw on finding_state
  for all to authenticated using (true) with check (true);
