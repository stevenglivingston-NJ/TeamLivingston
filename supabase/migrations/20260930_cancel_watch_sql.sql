-- Cancellation Watch moved off Claude Routines (2026-09-30).
-- APPLIED LIVE 2026-09-30. A PL/pgSQL port of mcp-servers/cancellation-watch.py,
-- run by pg_cron Mondays 08:00 UTC (the routine's slot), ahead of the Monday
-- 7am-ET email that report-dispatch sends from report_snapshots.
-- Uses the synchronous `http` extension, so there is no edge function and no
-- Claude session in the path. Replaces routine "Cancellation Watch — weekly
-- generator". The Python stays as the manual / backfill tool; keep the rules
-- below in step with it.
--
-- Postgres regex notes vs the Python: \y is a word boundary (\b is backspace
-- in Postgres), and matching is case-insensitive via ~*.
--
--   select public.cancel_watch_run();                              -- last full Mon-Sun week, publish
--   select public.cancel_watch_run('2026-09-21','2026-09-27',true); -- a window, dry run

create extension if not exists http with schema extensions;

-- Python round() is half-to-even; match it so counts and percentages agree.
create or replace function public.cw_round_half_even(x numeric) returns bigint
language sql immutable as $$
  select case when x - floor(x) = 0.5 then (floor(x) + (floor(x)::bigint % 2))::bigint
              else round(x)::bigint end;
$$;

create or replace function public.cw_cancel_fragments(t text) returns text
language sql immutable as $$
  select string_agg(btrim(seg), ' | ' order by n)
    from regexp_split_to_table(coalesce(t, ''), '\s*\|+\s*|(?<=[.!?])\s+') with ordinality s(seg, n)
   where btrim(seg) <> ''
     and seg ~* ('cancel|reschedul|re-?book|postpon|push(ed)? (it )?(back|out)|not ready|'
                 'call(ing)? back when|no longer|changed (their|his|her) mind|'
                 'went with|another contractor|competitor|'
                 'out(side)? (of )?(our |the )?(service )?(area|territory)|not (in )?our territory|'
                 'do(es)? not service|don''?t service|transferred to|'
                 'too (high|expensive|much)|over (his|her|their) budget|not in (his|her|their) budget|'
                 'budget is (nowhere|not|too)|can''?t afford|cannot afford|'
                 'no ?show|did not (answer|respond)|never responded|unreachable|'
                 'duplicate|double ?book|'
                 'not off?ered|does not fit our model|no cabinet|repair only');
$$;

-- -> (category, allowed, evidence). Rules ordered most specific first, applied
-- ONLY to fragments that carry cancellation intent.
create or replace function public.cw_classify(note text, out category text, out allowed boolean, out evidence text)
language plpgsql immutable as $$
begin
  evidence := public.cw_cancel_fragments(note);
  if evidence is null or evidence = '' then
    category := 'No reason captured'; allowed := false; evidence := ''; return;
  end if;
  if evidence ~* ('out(side)? (of )?(our |the )?(service )?(area|territory)|not (in )?our territory|'
                  'do(es)? not service|don''?t service|wrong territory|transferred to (other|another)') then
    category := 'Out of territory'; allowed := true;
  elsif evidence ~* ('no cabinet|not cabinet|counter ?tops? only|appliance only|'
                     'service (desired )?not off?ered|does not fit our model|not our (model|scope)') then
    category := 'Non-cabinet scope'; allowed := true;
  elsif evidence ~* '\yrepair(s| only)?\y|handyman|touch ?up only|single door|one door' then
    category := 'Repair only'; allowed := true;
  elsif evidence ~* ('reschedul|re-?book|call(ing)? back when|will call back|another (time|date)|'
                     'push(ed)? (it )?(back|out)|postpon|not ready|next (year|spring|summer|fall)') then
    category := 'Client requested — reschedule or postpone'; allowed := true;
  elsif evidence ~* 'cancel|changed (their|his|her) mind|no longer interested|went a different direction' then
    category := 'Client requested — cancelled'; allowed := true;
  elsif evidence ~* ('too (high|expensive|much)|over (his|her|their) budget|'
                     'not in (his|her|their) budget|budget is (nowhere|not|too)|'
                     'can''?t afford|cannot afford') then
    category := 'Price above budget'; allowed := false;
  elsif evidence ~* 'another contractor|went with|competitor|chose someone' then
    category := 'Lost to a competitor'; allowed := false;
  elsif evidence ~* 'duplicate|double ?book|booked twice|same slot' then
    category := 'Duplicate or booking error'; allowed := false;
  elsif evidence ~* 'no ?show|did not (answer|respond)|unreachable|never responded|could not (reach|contact)' then
    category := 'Unreachable / no-show'; allowed := false;
  else
    category := 'Reason logged but unclassified'; allowed := false;
  end if;
end $$;

create or replace function public.cw_is_junk(name text, phone text, city text, api_key text) returns boolean
language sql immutable as $$
  select coalesce(name, '') || ' ' || coalesce(city, '') ~* '\ytest\w*\y|testing|^z+ |demo|do not use|sample|asdf|qwerty|holding time slot'
      or regexp_replace(coalesce(phone, ''), '\D', '', 'g') ~ '^(\d)\1{6,}$|^123456|^555'
      or btrim(coalesce(api_key, '')) = 'KTUApp';
$$;

-- Every note on the contact, oldest first; '' when none or on any error.
create or replace function public.cw_contact_notes(sm_key text, cid bigint) returns text
language plpgsql as $$
declare d jsonb; m jsonb; out text;
begin
  select content::jsonb into d
    from extensions.http_post('https://serviceminder.io/api/contacts/locate',
           jsonb_build_object('ApiKey', sm_key, 'IdSearch', cid::text)::text, 'application/json');
  for m in select * from jsonb_array_elements(coalesce(d->'Matches', '[]')) loop
    continue when m->>'Id' is distinct from cid::text;
    select string_agg(btrim(coalesce(btrim(n->>'Title'), '') || ': ' || b, ': ' ) , ' | ' order by (n->>'Id')::bigint nulls first)
      into out
      from (select n,
                   btrim(regexp_replace(regexp_replace(regexp_replace(coalesce(n->>'Body', ''),
                         '<[^>]+>', ' ', 'g'), 'https?://\S+', ' ', 'g'), '\s+', ' ', 'g')) b
              from jsonb_array_elements(coalesce(m->'Notes', '[]')) n) x
     where b <> '' and lower(b) not in ('undefined', 'null', 'n/a', '.');
    return coalesce(out, '');
  end loop;
  return '';
exception when others then
  return '';
end $$;

create or replace function public.cancel_watch_run(p_from date default null, p_thru date default null, dry boolean default false)
returns jsonb language plpgsql security definer set search_path = public, extensions as $fn$
declare
  CEILING    constant numeric := 0.25;
  BASIS      constant text := 'Jan-Aug 2026 YTD: 73 of 308 booked consults cancelled for allowed reasons = 23.7%, held as a 25% ceiling';
  CPL        constant int := 210;
  sm_key     text;
  today      date := (now() at time zone 'UTC')::date;
  frm date; thr date; days int; wd int;
  resp jsonb; a jsonb; c jsonb;
  total int := 0; booked int := 0; attended int := 0; ncan int := 0;
  seen text[] := '{}'; k text;
  detail jsonb := '[]';
  cl record; note text; rid bigint; v_cat text; alw boolean; ev text;
  n_allowed int; n_unlogged int; ceiling_n int; over int; in_ceiling boolean;
  cats jsonb; m jsonb; subject text; verdict text; L text[] := '{}'; body text;
  r jsonb; sortn int;
  pct_rate text; pct_allowed text;
begin
  select value into sm_key from app_secrets where key = 'SM_KEY_KTU';
  if sm_key is null then raise exception 'SM_KEY_KTU missing from app_secrets'; end if;

  if p_from is not null and p_thru is not null then
    frm := p_from; thr := p_thru; days := thr - frm + 1;
  else
    wd := extract(isodow from today)::int % 7;          -- Mon=1 .. Sat=6, Sun=0
    thr := today - (case when wd = 0 then 7 else wd end); -- the last Sunday before today
    frm := thr - 6; days := 7;
  end if;

  perform http_set_curlopt('CURLOPT_TIMEOUT', '90');
  select content::jsonb into resp
    from http_post('https://serviceminder.io/api/appointments/query',
           jsonb_build_object('ApiKey', sm_key, 'FromDate', frm::text, 'ThroughDate', thr::text,
                              'Take', 500, 'IncludeContact', true)::text, 'application/json');
  if resp is null or not (resp ? 'Appointments') then
    raise exception 'appointments/query failed: %', left(coalesce(resp::text, 'no response'), 300);
  end if;

  for a in select * from jsonb_array_elements(coalesce(resp->'Appointments', '[]')) loop
    continue when a->>'ServiceName' is distinct from 'Consultation - In-Home';
    total := total + 1;
    c := coalesce(a->'Contact', '{}');
    continue when public.cw_is_junk(btrim(coalesce(c->>'Name', '')), c->>'Phone', btrim(coalesce(c->>'City', '')), a->>'ApiKey');
    k := coalesce(a->>'ContactId', '') || '|' || coalesce(a->>'DateTime', '') || '|' || coalesce(a->>'Status', '');
    continue when k = any(seen);
    seen := seen || k;
    booked := booked + 1;
    if (a->>'Status')::int = 3 then attended := attended + 1; end if;
    if (a->>'Status')::int = 4 then
      ncan := ncan + 1;
      note := public.cw_contact_notes(sm_key, (a->>'ContactId')::bigint);
      select * into cl from public.cw_classify(note);
      v_cat := cl.category; alw := cl.allowed; ev := cl.evidence;
      rid := nullif(a->>'CancelReasonId', '')::bigint;
      if v_cat = 'No reason captured' and rid is not null and rid not in (0, 3523) then
        v_cat := 'Picklist reason ' || rid; alw := true;
      end if;
      detail := detail || jsonb_build_object(
        'i', ncan, 'name', btrim(coalesce(c->>'Name', '')), 'city', btrim(coalesce(c->>'City', '')),
        'phone', coalesce(c->>'Phone', ''), 'email', coalesce(c->>'Email', ''),
        'when', coalesce(a->>'DateTime', ''), 'channel', coalesce(c->>'Channel', ''),
        'campaign', coalesce(c->>'Campaign', ''), 'note', note, 'evidence', ev,
        'category', v_cat, 'allowed', alw);
    end if;
  end loop;

  select count(*) filter (where (d->>'allowed')::boolean),
         count(*) filter (where d->>'category' = 'No reason captured')
    into n_allowed, n_unlogged from jsonb_array_elements(detail) d;
  ceiling_n := public.cw_round_half_even(booked * CEILING);
  over := greatest(0, ncan - ceiling_n);
  in_ceiling := ncan <= ceiling_n;

  -- categories in Counter order: by count desc, then first appearance
  select coalesce(jsonb_agg(jsonb_build_object('cat', cat, 'n', n, 'allowed', any_allowed) order by n desc, first_i), '[]')
    into cats
    from (select d->>'category' cat, count(*) n, min((d->>'i')::int) first_i,
                 bool_or((d->>'allowed')::boolean) any_allowed
            from jsonb_array_elements(detail) d group by 1) g;

  m := jsonb_build_object(
    'window_days', days, 'from', frm::text, 'through', thr::text,
    'booked', booked, 'attended', attended, 'cancelled', ncan, 'junk_excluded', total - booked,
    'cancel_rate', case when booked > 0 then round(ncan::numeric / booked, 4) end,
    'allowed', n_allowed,
    'allowed_rate_of_booked', case when booked > 0 then round(n_allowed::numeric / booked, 4) end,
    'breaches', ncan - n_allowed, 'unlogged', n_unlogged,
    'ceiling', CEILING, 'ceiling_count', ceiling_n, 'ceiling_basis', BASIS,
    'over_ceiling', over, 'spend_impact', over * CPL, 'cost_per_lead', CPL,
    'in_ceiling', in_ceiling, 'throttle', not in_ceiling,
    'categories', (select coalesce(jsonb_object_agg(x->>'cat', (x->>'n')::int), '{}') from jsonb_array_elements(cats) x));

  pct_rate    := case when booked > 0 then public.cw_round_half_even(ncan::numeric * 100 / booked) || '%' else '—' end;
  pct_allowed := case when booked > 0 then public.cw_round_half_even(n_allowed::numeric * 100 / booked) || '%' else '—' end;
  verdict := case when in_ceiling then 'WITHIN CEILING' else 'OVER CEILING — SPEND THROTTLE' end;
  subject := format('[KTU] Cancellation Watch %s → %s — %s/%s cancelled (%s), %s', frm, thr, ncan, booked, pct_rate, verdict);

  L := L || format('KTU in-home consultations · %s to %s', frm, thr) || repeat('=', 64) || ''::text
         || format('  Booked                %s', booked)
         || format('  Attended              %s', attended)
         || format('  Cancelled             %s  (%s of booked)', ncan, pct_rate)
         || ''::text
         || format('  Allowed reasons       %s  (%s of booked)', n_allowed, pct_allowed)
         || format('  Ceiling               %s%% of booked = %s cancellations', (CEILING * 100)::int, ceiling_n)
         || format('  STATUS                %s', verdict);
  if over > 0 then
    L := L || format('  Over by               %s consults', over)
           || format('  Spend throttle        $%s of new-lead spend (%s × $%s/lead)', to_char(over * CPL, 'FM999,999,990'), over, CPL);
  end if;
  L := L || ''::text || 'Allowed = client-requested, out of territory, non-cabinet scope, or repair only.'::text
         || format('Ceiling basis: %s.', BASIS);
  if not in_ceiling then
    L := L || ''::text
           || 'ACTION — spend throttling is triggered. Cancellations are above 25% of'::text
           || 'booked consults, so new-lead spend is throttled until the rate is back'::text
           || 'under the ceiling. Work the booked and recoverable consults first; we are'::text
           || 'not buying leads to refill a funnel that is leaking at this rate.'::text;
  end if;
  L := L || ''::text || 'Cancellations by reason'::text || repeat('-', 64);
  for r in select * from jsonb_array_elements(cats) loop
    L := L || format('  %s  %s  %s', case when (r->>'allowed')::boolean then 'ok ' else 'OUT' end, lpad(r->>'n', 3), r->>'cat');
  end loop;
  L := L || ''::text;

  if n_unlogged > 0 then
    L := L || format('NO REASON CAPTURED — %s of %s', n_unlogged, ncan) || repeat('-', 64)
           || 'These count against the ceiling. Set a real cancel reason on the'::text
           || 'appointment (not "Other") and they classify automatically.'::text;
    for r in select * from jsonb_array_elements(detail) d where d->>'category' = 'No reason captured' order by (d->>'i')::int loop
      L := L || format('  · %s — %s — %s — %s', coalesce(nullif(r->>'name', ''), '(no name)'), r->>'city', left(r->>'when', 10), r->>'phone');
    end loop;
    L := L || ''::text;
  end if;

  if exists (select 1 from jsonb_array_elements(detail) d where not (d->>'allowed')::boolean and d->>'category' <> 'No reason captured') then
    L := L || format('OUTSIDE THE ALLOWED REASONS — %s', (select count(*) from jsonb_array_elements(detail) d
                      where not (d->>'allowed')::boolean and d->>'category' <> 'No reason captured')) || repeat('-', 64);
    for r in select * from jsonb_array_elements(detail) d
              where not (d->>'allowed')::boolean and d->>'category' <> 'No reason captured' order by (d->>'i')::int loop
      L := L || format('  · %s — %s — %s', coalesce(nullif(r->>'name', ''), '(no name)'), r->>'city', r->>'category');
      if coalesce(r->>'evidence', '') <> '' then L := L || ('      ' || left(r->>'evidence', 220)); end if;
    end loop;
    L := L || ''::text;
  end if;

  if total - booked > 0 then
    L := L || format('(%s test/system record(s) excluded from every figure above.)', total - booked);
  end if;
  L := L || 'How this is measured'::text || repeat('-', 64)
         || 'Counts come from ServiceMinder appointments; reasons come from the cancel-'::text
         || 'reason picklist and the contact''s note log. The free-text note typed on the'::text
         || 'appointment itself is NOT readable by any API — only by the manual UI export —'::text
         || 'so a reason written only there shows here as "no reason captured". That is a'::text
         || 'tooling limit, not a judgement: the way to close it is the cancel-reason'::text
         || 'picklist on the appointment, which is currently set on about a fifth of'::text
         || 'cancellations and reads "Other" nine times in ten. Picklist set = classified'::text
         || 'automatically, here and everywhere else.'::text
         || ''::text
         || 'Full detail, history and the recovery list: https://dash.goaxyom.com → Reports'::text
         || 'Change this report''s frequency or recipients on that same tab.'::text;
  body := array_to_string(L, E'\n');

  if dry then
    return jsonb_build_object('subject', subject, 'body', body, 'metrics', m);
  end if;

  insert into report_snapshots(report_key, generated_at, subject, body, metrics)
  values ('cancel_watch', now(), subject, body, m)
  on conflict (report_key) do update
    set generated_at = now(), subject = excluded.subject, body = excluded.body, metrics = excluded.metrics;

  delete from intranet_records where section = 'cancel_watch';
  insert into intranet_records(section, brand, sort_order, fields)
  values ('cancel_watch', 'KTU', 0, jsonb_build_object(
    'kind', 'headline', 'severity', case when in_ceiling then 'ok' else 'urgent' end,
    'title', format('%s of %s consults cancelled (%s) — ', ncan, booked, pct_rate) ||
             case when in_ceiling then 'within the 25% allowed ceiling'
                  else format('%s over the 25%% ceiling — spend throttling triggered on $%s of new-lead spend', over, to_char(over * CPL, 'FM999,999,990')) end,
    'detail', format('%s cancellations were for allowed reasons (%s of booked). %s had no reason captured and count against the ceiling. Ceiling basis — %s.',
                     n_allowed, pct_allowed, n_unlogged, BASIS),
    'window', format('%s to %s', frm, thr),
    'source', 'ServiceMinder appointments/query + contacts/locate',
    'scan_date', today::text, 'report_key', 'cancel_watch'));
  sortn := 0;
  for r in select * from jsonb_array_elements(cats) loop
    sortn := sortn + 1;
    insert into intranet_records(section, brand, sort_order, fields)
    values ('cancel_watch', 'KTU', sortn, jsonb_build_object(
      'kind', 'reason', 'reason', r->>'cat', 'count', (r->>'n')::int,
      'allowed', case when (r->>'allowed')::boolean then 'Allowed' else 'Counts against ceiling' end,
      'severity', case when (r->>'allowed')::boolean then 'ok' else 'warn' end,
      'scan_date', today::text, 'report_key', 'cancel_watch'));
  end loop;
  sortn := 100;
  for r in select * from jsonb_array_elements(detail) d where not (d->>'allowed')::boolean order by (d->>'i')::int loop
    sortn := sortn + 1;
    insert into intranet_records(section, brand, sort_order, fields)
    values ('cancel_watch', 'KTU', sortn, jsonb_build_object(
      'kind', 'breach', 'customer', r->>'name', 'city', r->>'city', 'phone', r->>'phone', 'email', r->>'email',
      'when', left(r->>'when', 16), 'reason', r->>'category', 'note', left(coalesce(r->>'evidence', ''), 500),
      'full_note', left(coalesce(r->>'note', ''), 900), 'channel', r->>'channel', 'campaign', r->>'campaign',
      'severity', 'warn', 'scan_date', today::text, 'report_key', 'cancel_watch'));
  end loop;

  return jsonb_build_object('published', true, 'subject', subject);
end $fn$;
revoke execute on function public.cancel_watch_run(date, date, boolean) from public, anon, authenticated;
revoke execute on function public.cw_contact_notes(text, bigint) from public, anon, authenticated;

select cron.unschedule('cancel-watch-weekly') where exists (select 1 from cron.job where jobname = 'cancel-watch-weekly');
select cron.schedule('cancel-watch-weekly', '0 8 * * 1', $$ select public.cancel_watch_run(); $$);
