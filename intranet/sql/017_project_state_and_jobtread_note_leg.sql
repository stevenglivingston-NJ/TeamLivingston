-- Project tracker: per-project hide/close state, and a JobTread leg on the note queue.
--
-- WHY A SEPARATE TABLE: foreman_board is re-seeded daily by Foreman from
-- JobTread + ServiceMinder + CompanyCam. Anything written onto those records is
-- destroyed on the next run. Hide/close are human decisions that must outlive
-- the sync, so they live here keyed by project name and are joined at render
-- time. Same reason the paid-from account on liabilities is stored apart from
-- Moola's rows.
create table if not exists project_state (
  project      text primary key,
  brand        text,
  hidden       boolean not null default false,
  closed       boolean not null default false,
  closed_at    timestamptz,
  closed_by    text,
  close_reason text,
  hidden_at    timestamptz,
  hidden_by    text,
  updated_at   timestamptz not null default now()
);
comment on table project_state is
  'Human hide/close decisions for the project tracker. Keyed by foreman_board.fields.project. Foreman never writes here.';
comment on column project_state.hidden is
  'Hidden = clutter, not finished. Excluded from the default list but still live work; use closed for completed jobs.';
comment on column project_state.closed is
  'Closed = the job is done and should leave the working list permanently.';

alter table project_state enable row level security;
drop policy if exists project_state_rw on project_state;
create policy project_state_rw on project_state
  for all to authenticated using (true) with check (true);

-- JobTread leg on the note queue. ServiceMinder (status) and HighLevel
-- (ghl_status) already exist and drain independently; JobTread is a third
-- destination with its own status so a failure in one never blocks the others.
alter table sm_note_queue add column if not exists jt_job_id     text;
alter table sm_note_queue add column if not exists jt_status     text default 'pending';
alter table sm_note_queue add column if not exists jt_attempts   integer default 0;
alter table sm_note_queue add column if not exists jt_error      text;
alter table sm_note_queue add column if not exists jt_synced_at  timestamptz;
comment on column sm_note_queue.jt_status is
  'JobTread leg: pending|synced|skipped|error. Independent of status (ServiceMinder) and ghl_status (HighLevel) — one destination failing must not hold the others.';

-- A note with no destination id for a given system is 'skipped', not 'pending',
-- so the queue never accumulates rows that can never drain.
create index if not exists sm_note_queue_jt_pending on sm_note_queue (jt_status) where jt_status = 'pending';
