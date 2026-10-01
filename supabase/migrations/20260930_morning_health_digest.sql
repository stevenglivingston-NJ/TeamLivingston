-- Morning agent-health digest moved off Claude Routines (2026-09-30).
-- APPLIED LIVE 2026-09-30. Replaces routine "Morning agent-health check + action
-- list" (13:00 UTC), which failed 2026-09-29 on the account usage limit.
--
-- check_agent_freshness() (hourly pg_cron) already alerts on each stale agent;
-- this is the one daily summary on top: stale agents, failures in the Supabase
-- jobs that replaced Claude routines, and the last 30h of RED items. Queued once
-- per day to notify_queue; dispatch-notify delivers it (Slack DM + email).

create or replace function public.morning_health_digest(dry boolean default false)
returns jsonb language plpgsql security definer set search_path = public as $$
declare
  today   date := (now() at time zone 'UTC')::date;
  stale   text;
  jobs    text;
  reds    text;
  appt_ts timestamptz;
  body    text;
begin
  select string_agg(format('• %s — %s', fields->>'agent',
           case when fields->>'days_late' ~ '^\d+$' then (fields->>'days_late') || ' day(s) late'
                else coalesce(fields->>'days_late','?') end), E'\n' order by fields->>'agent')
    into stale from intranet_records where section = 'system_health';

  select string_agg(format('• %s: %s failed run(s)', j.jobname, f.n), E'\n' order by j.jobname)
    into jobs
    from (select jobid, count(*) n from cron.job_run_details
           where status <> 'succeeded' and start_time > now() - interval '24 hours' group by 1) f
    join cron.job j using (jobid);

  select max(updated_at) into appt_ts from appointments;
  if appt_ts is null or appt_ts < now() - interval '26 hours' then
    jobs := coalesce(jobs || E'\n', '') || format('• appointments-sync: table last refreshed %s',
              coalesce(to_char(appt_ts at time zone 'America/New_York', 'Mon DD HH24:MI "ET"'), 'never'));
  end if;
  if exists (select 1 from jc_sync_runs where not ok and ran_at > now() - interval '24 hours') then
    jobs := coalesce(jobs || E'\n', '') || format('• jc-forecast-sync: %s failed run(s) in 24h',
              (select count(*) from jc_sync_runs where not ok and ran_at > now() - interval '24 hours'));
  end if;

  select string_agg(format('• [%s] %s', section, left(coalesce(fields->>'title', fields->>'name', '(untitled)'), 110)), E'\n')
    into reds
    from (select section, fields from intranet_records
           where section <> 'system_health'
             and lower(coalesce(fields->>'rag', fields->>'severity', fields->>'status')) in ('red','urgent','critical')
             and updated_at > now() - interval '30 hours'
           order by section limit 10) r;

  body := 'Agents: ' || coalesce(E'stale —\n' || stale, 'all published on time.') || E'\n\n' ||
          'Supabase jobs: ' || coalesce(E'problems —\n' || jobs, 'all green (24h).') || E'\n\n' ||
          'RED items (30h): ' || coalesce(E'\n' || reds, 'none.') || E'\n\n' ||
          'Open commitments: ClickUp → Axyom Operations → Waiting on Steven.';

  if dry then return jsonb_build_object('body', body); end if;
  if not exists (select 1 from notify_queue where source = 'morning-digest:' || today) then
    insert into notify_queue(kind, recipient_email, subject, body, source)
    values ('system', 'slivingston@kitchentuneup.com',
            '[Axyom] Morning health — ' ||
              case when stale is null and jobs is null then 'all green' else 'needs attention' end,
            body, 'morning-digest:' || today);
  end if;
  return jsonb_build_object('stale', stale is not null, 'job_problems', jobs is not null, 'reds', reds is not null);
end $$;
revoke execute on function public.morning_health_digest(boolean) from public, anon, authenticated;

-- 13:00 UTC (9am ET summer / 8am winter), same slot the routine used.
select cron.unschedule('morning-health-digest') where exists (select 1 from cron.job where jobname='morning-health-digest');
select cron.schedule('morning-health-digest', '0 13 * * *', $$ select public.morning_health_digest(); $$);
