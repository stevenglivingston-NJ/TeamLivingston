-- Register the weekly Prospect agent (prospect_report) with the freshness
-- watchdog. Rewrites check_agent_freshness() with per-section max-age windows:
-- daily agents keep their 1-day window; Prospect runs Mondays, so it gets 8
-- days before it is flagged stale.
create or replace function public.check_agent_freshness()
returns void language plpgsql security definer set search_path = public as $$
declare
  tracked constant jsonb := jsonb_build_object(
    'moola_briefing', 1, 'goldeneye_callouts', 1, 'foreman_briefing', 1,
    'paid_brief', 1, 'pipeline_briefing', 1, 'organic_report', 1,
    'tekky_status', 1, 'prospect_report', 8);
  rec record;
begin
  delete from public.intranet_records where section = 'system_health';
  for rec in
    select t.key as section, (t.value)::int as max_age,
           (select max((r.fields->>'scan_date')::date)
              from public.intranet_records r where r.section = t.key) as latest
    from jsonb_each_text(tracked) t
  loop
    if rec.latest is null or rec.latest < current_date - rec.max_age then
      insert into public.intranet_records(section, brand, sort_order, fields)
      values ('system_health', 'Both', 1, jsonb_build_object(
        'agent', rec.section,
        'severity', case when rec.latest is null then 'urgent' else 'warn' end,
        'title', rec.section || ' is stale',
        'latest_scan_date', coalesce(rec.latest::text, 'never'),
        'checked_at', now()));
      if not exists (
        select 1 from public.notify_queue
        where source = 'freshness:' || rec.section || ':' || current_date::text
      ) then
        insert into public.notify_queue(kind, subject, body, source)
        values ('system',
          '[Axyom] Agent stale: ' || rec.section,
          'The ' || rec.section || ' section has not updated (latest: ' ||
            coalesce(rec.latest::text, 'never') || '). Its scheduled run may be failing.',
          'freshness:' || rec.section || ':' || current_date::text);
      end if;
    end if;
  end loop;
end $$;
revoke all on function public.check_agent_freshness() from anon, authenticated;
