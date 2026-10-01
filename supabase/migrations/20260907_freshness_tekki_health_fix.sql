-- Fix a false-positive stale-agent alert: the freshness watchdog checked
-- section `tekky_status`, which Tekki's current instructions never write
-- (its real output is `tekki_health` — confirmed fresh, 11 rows on 2026-09-06,
-- while `tekky_status` last wrote 2026-09-02 and is orphaned). This was
-- generating a nightly false "Agent has not published today" Slack alert
-- for an agent that was running fine.
--
-- Also: this reconstructs the function AS ACTUALLY DEPLOYED (pulled via
-- pg_get_functiondef) rather than from the last committed migration, which
-- had drifted — the live version already carries per-agent due_hour
-- suppression and several tracked sections (cellar_briefing,
-- harvest_briefing, appt_followups) that were never checked in. Committing
-- this now so the repo stops disagreeing with what's actually running.
create or replace function public.check_agent_freshness()
returns void language plpgsql security definer set search_path = public as $$
declare
  tracked constant jsonb := jsonb_build_object(
    'cellar_briefing',    jsonb_build_object('due_hour',10,'max_age',0),
    'goldeneye_callouts', jsonb_build_object('due_hour',11,'max_age',0),
    'moola_briefing',     jsonb_build_object('due_hour',12,'max_age',0),
    'foreman_briefing',   jsonb_build_object('due_hour',16,'max_age',0),
    'harvest_briefing',   jsonb_build_object('due_hour',18,'max_age',0),
    'tekki_health',       jsonb_build_object('due_hour',19,'max_age',0),
    'organic_report',     jsonb_build_object('due_hour',20,'max_age',0),
    'appt_followups',     jsonb_build_object('due_hour',21,'max_age',0),
    'paid_brief',         jsonb_build_object('due_hour',21,'max_age',0),
    'pipeline_briefing',  jsonb_build_object('due_hour',22,'max_age',0),
    'prospect_report',    jsonb_build_object('due_hour',12,'max_age',8)
  );
  today     date := (now() at time zone 'UTC')::date;
  hour_now  int  := extract(hour from (now() at time zone 'UTC'))::int;
  days_late int;
  rec record;
begin
  delete from public.intranet_records where section = 'system_health';

  for rec in
    select t.key                       as section,
           (t.value->>'due_hour')::int as due_hour,
           (t.value->>'max_age')::int  as max_age,
           (select max(case
                         when r.fields->>'scan_date' ~ '^\d{4}-\d{2}-\d{2}$'
                           then (r.fields->>'scan_date')::date
                         else (r.created_at at time zone 'UTC')::date
                       end)
              from public.intranet_records r
             where r.section = t.key) as latest
      from jsonb_each(tracked) t
  loop
    -- Not late at all -> nothing to say.
    continue when rec.latest is not null and rec.latest >= today - rec.max_age;

    -- Late by exactly one period (i.e. only today's run is missing) AND the agent's
    -- due hour has not arrived yet -> it may still be about to run; stay quiet.
    -- Anything further behind is reported at every hour of the day.
    continue when rec.latest is not null
              and rec.latest >= today - rec.max_age - 1
              and hour_now < rec.due_hour;

    days_late := case when rec.latest is null then null else today - rec.latest end;

    insert into public.intranet_records(section, brand, sort_order, fields)
    values ('system_health', 'Both', 1, jsonb_build_object(
      'agent',            rec.section,
      'severity',         case when rec.latest is null or days_late >= 2
                               then 'urgent' else 'warn' end,
      'title',            rec.section || ' has not published today',
      'latest_scan_date', coalesce(rec.latest::text, 'never'),
      'days_late',        coalesce(days_late::text, 'never published'),
      'due_hour_utc',     rec.due_hour,
      'checked_at',       now()));

    if not exists (
      select 1 from public.notify_queue
       where source = 'freshness:' || rec.section || ':' || today::text
    ) then
      insert into public.notify_queue(kind, subject, body, source)
      values ('system',
        '[Axyom] Agent has not published today: ' || rec.section,
        'The ' || rec.section || ' section has no scan for ' || today::text ||
          ' (latest: ' || coalesce(rec.latest::text, 'never') ||
          '). Its scheduled run was due by ' || rec.due_hour || ':00 UTC and may be failing.',
        'freshness:' || rec.section || ':' || today::text);
    end if;
  end loop;
end $$;
revoke all on function public.check_agent_freshness() from anon, authenticated;
