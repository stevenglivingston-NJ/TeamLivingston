-- Post-consult survey by text through HighLevel (2026-09-28).
--
-- consult-completion-tagger v2 reads COMPLETED consultations from ServiceMinder (the system of
-- record) and tags the matching HighLevel contact `appointment-completed`; a HighLevel workflow then
-- texts "reply 1-5", and HighLevel's "Customer replied" webhook calls consult-sms-reply, which
-- records the rating. The log row is how a reply is tied back to the ServiceMinder appointment.

alter table public.consult_completion_log
  add column if not exists sm_contact_id bigint,
  add column if not exists sm_appt_id    bigint,
  add column if not exists agent_name    text;

create index if not exists consult_completion_log_contact_idx
  on public.consult_completion_log (brand, hl_contact_id, processed_at desc);

-- Plain config, not secrets. tagger_mode: off | dry_run | live.
--   dry_run (the default) reads ServiceMinder + HighLevel and reports what it WOULD tag, writing
--   nothing -- so deploying this never texts a client until the owner has built the HighLevel
--   workflows and switches it to live.
create table if not exists public.consult_survey_config (
  key        text primary key,
  value      text not null,
  updated_at timestamptz not null default now()
);
alter table public.consult_survey_config enable row level security;
insert into public.consult_survey_config (key, value) values ('tagger_mode', 'dry_run')
  on conflict (key) do nothing;

comment on table public.consult_survey_config is
  'Post-consult survey switches. tagger_mode = off | dry_run | live (consult-completion-tagger).';
