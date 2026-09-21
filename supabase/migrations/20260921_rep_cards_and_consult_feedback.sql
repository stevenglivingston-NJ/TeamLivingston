-- Customer-facing rep profiles + consult feedback loop (2026-09-21).
-- Applied directly to the live project (tguwpswcneywvscxzyef) via
-- mcp__Supabase__apply_migration; this file mirrors it here per this repo's
-- convention. Adds nullable customer-facing fields to profiles, a
-- consult_feedback table (written only by the consult-feedback edge
-- function via its service-role key; RLS grants admins read only), and
-- unmapped_agents (daily ServiceMinder agent-name reconciliation, written by
-- the sm-agent-sync edge function).

-- 1. profiles: nullable additions only, no data loss. Verified via read-back
--    that all 6 existing rows kept their original data after this ran.
alter table public.profiles
  add column if not exists hl_user_id text unique,
  add column if not exists sm_agent_name_ktu text,
  add column if not exists sm_agent_name_btu text,
  add column if not exists brands text[],
  add column if not exists customer_title text,
  add column if not exists customer_display_name text,
  add column if not exists photo_url text,
  add column if not exists intro_video_url text,
  add column if not exists customer_facing boolean not null default false;

alter table public.profiles
  drop constraint if exists profiles_brands_check;
alter table public.profiles
  add constraint profiles_brands_check
  check (brands is null or brands <@ array['KTU','BTU']::text[]);

-- 2. consult_feedback — service role writes only (the consult-feedback edge
--    function). Read gated to admins, matching the has_finance_access() /
--    has_jc_access() idiom already used in this project (see
--    20260710_finance_access_owner_only.sql / 20260901c_job_costing_access.sql):
--    no insert policy exists for anon/authenticated at all, so only the
--    service-role key (which bypasses RLS) can write here.
create table if not exists public.consult_feedback (
  id uuid primary key default gen_random_uuid(),
  brand text not null check (brand in ('KTU','BTU')),
  contact_id bigint,
  appt_id bigint unique,
  hl_user_id text,
  agent_name text,
  rating int not null check (rating between 1 and 5),
  missing_items text[],
  feedback_text text check (feedback_text is null or char_length(feedback_text) <= 2000),
  callback_requested boolean not null default false,
  created_at timestamptz not null default now()
);

alter table public.consult_feedback enable row level security;

drop policy if exists consult_feedback_admin_read on public.consult_feedback;
create policy consult_feedback_admin_read on public.consult_feedback
  for select to authenticated using (public.is_admin());

-- 3. unmapped_agents — daily ServiceMinder agent reconciliation upsert target.
create table if not exists public.unmapped_agents (
  brand text not null check (brand in ('KTU','BTU')),
  sm_agent_name text not null,
  first_seen timestamptz not null default now(),
  resolved boolean not null default false,
  primary key (brand, sm_agent_name)
);

alter table public.unmapped_agents enable row level security;

drop policy if exists unmapped_agents_admin_all on public.unmapped_agents;
create policy unmapped_agents_admin_all on public.unmapped_agents
  for all to authenticated using (public.is_admin()) with check (public.is_admin());

-- 4. rep-media public storage bucket (photo uploads from the Admin Console's
--    Customer-facing profile section). Created directly via SQL since this
--    project had no prior bucket to follow as a migration pattern.
insert into storage.buckets (id, name, public)
values ('rep-media', 'rep-media', true)
on conflict (id) do nothing;

-- 5. app_secrets placeholders this feature reads. HL_FEEDBACK_WEBHOOK_KTU/BTU
--    are left empty for Steven to fill in with the real HighLevel inbound
--    webhook URLs — see the deliverable report for details.
insert into public.app_secrets (key, value) values
  ('REP_DEFAULT_KTU', '{"display_name":"Kitchen Tune-Up Team","title":"Design Consultant","photo_url":"","video_url":""}'),
  ('REP_DEFAULT_BTU', '{"display_name":"Bath Tune-Up Team","title":"Design Consultant","photo_url":"","video_url":""}'),
  ('HL_FEEDBACK_WEBHOOK_KTU', ''),
  ('HL_FEEDBACK_WEBHOOK_BTU', '')
on conflict (key) do nothing;

-- 6. Daily ServiceMinder service-agent reconciliation, 6am ET, via pg_cron +
--    net.http_post -> sm-agent-sync edge function. Same mechanism as
--    jc-forecast-sync (20260910b_jc_forecast_sync_schedule.sql): a Claude
--    Code Remote Routine calling mcp__ServiceMinder__* tools would stall
--    forever on a permission prompt in a non-interactive fire (see
--    CLAUDE.md "Scheduled runs stall on MCP connector calls" and
--    .claude/agents/tekki.md / moola.md), so this is serverless instead,
--    reusing the x-cron-secret handshake already stored in dispatch_config.
select cron.unschedule('sm-agent-sync-daily')
 where exists (select 1 from cron.job where jobname = 'sm-agent-sync-daily');

-- 6am ET = 10:00 UTC during EDT (current offset, 2026-09-21). This does not
-- auto-adjust for DST -- same limitation as the existing jc-forecast-index
-- schedule in this project.
select cron.schedule('sm-agent-sync-daily', '0 10 * * *', $cron$
  select net.http_post(
    url     := 'https://tguwpswcneywvscxzyef.supabase.co/functions/v1/sm-agent-sync',
    headers := jsonb_build_object(
                 'Content-Type', 'application/json',
                 'x-cron-secret', (select value from public.dispatch_config where key = 'cron_secret')),
    body    := '{}'::jsonb,
    timeout_milliseconds := 120000);
$cron$);
