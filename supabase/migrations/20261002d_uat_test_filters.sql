-- Test/UAT records out of REPORTING (2026-10-02). NOT YET APPLIED.
--
-- One canonical rule (CLAUDE.md "Test/UAT records"): a record is test when
--   name  ~* \ytest\y  or  zz(test|uat)  or  ^zzz      (\y = word boundary in Postgres)
--   email ~* \+uat\d*@
-- UAT contacts are named "Test ZZUAT-<nn> <KTU|BTU>" with emails
-- stevenglivingston+uat<nn>@gmail.com. Each consumer below EXTENDS its existing
-- filter with the rule; nothing that was excluded before is let back in.
--
-- Reporting only. Processing (syncs that create records, the order flow,
-- customer-journey notifications) deliberately still sees test records, so a
-- UAT run exercises the real path.
--
--   1) public.is_test_record(name, email)  -- the rule, once
--   2) cw_is_junk        (Cancellation Watch counts + weekly email). Body copied
--                        from 20260930_cancel_watch_sql.sql; only the filter
--                        changed. Signature unchanged, so name rule only (the
--                        caller passes no email). Twin: mcp-servers/cancellation-watch.py
--   3) sm_hl_recon_run   (SM<->HL mismatch alert). Body copied from
--                        20260930_sm_hl_recon_sql.sql; only the skip filter changed.
--   4) jc_refresh_escalations (margin escalation flags on payables). Body copied
--                        from 20260930_jc_gate_btu_estimate_advisory.sql; a test
--                        job (jc_jobs.customer_name) is never flagged, and an open
--                        unapproved flag on one is cleared. The payment gate
--                        trigger (jc_payment_gate) is NOT changed.

create or replace function public.is_test_record(name text, email text default null) returns boolean
language sql immutable as $$
  select coalesce(name, '') ~* '\ytest\y|zz(test|uat)'
      or btrim(coalesce(name, '')) ~* '^zzz'
      or coalesce(email, '') ~* '\+uat\d*@';
$$;
grant execute on function public.is_test_record(text, text) to anon, authenticated, service_role;

create or replace function public.jc_job_is_test(p_job uuid) returns boolean
language sql stable security definer set search_path = public as $$
  select coalesce((select public.is_test_record(j.customer_name) from public.jc_jobs j where j.id = p_job), false);
$$;
revoke execute on function public.jc_job_is_test(uuid) from public, anon;
grant execute on function public.jc_job_is_test(uuid) to authenticated, service_role;

-- 2) Cancellation Watch
create or replace function public.cw_is_junk(name text, phone text, city text, api_key text) returns boolean
language sql immutable as $$
  select coalesce(name, '') || ' ' || coalesce(city, '') ~* '\ytest\w*\y|testing|^z+ |demo|do not use|sample|asdf|qwerty|holding time slot'
      or regexp_replace(coalesce(phone, ''), '\D', '', 'g') ~ '^(\d)\1{6,}$|^123456|^555'
      or btrim(coalesce(api_key, '')) = 'KTUApp'
      or public.is_test_record(name);
$$;

-- 3) SM <-> HL reconciliation
create or replace function public.sm_hl_recon_run(dry boolean default false)
returns jsonb language plpgsql security definer set search_path = public, extensions as $fn$
declare
  HL_LOC  constant text := 'nHLCxHPidnhV1NFzRtZZ';
  NOISE   constant text := 'test00|vlad bond|test test|test lead|test fallback|test integration|test 03|sales team|home show';
  sm_key text; tok text;
  frm date := (now() at time zone 'America/New_York')::date;
  resp jsonb; a jsonb; c jsonb; s jsonb; ev jsonb; e jsonb;
  sm_at timestamp; sm_live boolean; phone text; email text; hl_id text;
  best jsonb; best_diff interval; d interval; hl_at timestamp; hl_live boolean;
  findings jsonb := '[]'; f jsonb; fresh jsonb := '[]'; checked int := 0;
  body text; line text;
begin
  select value into sm_key from app_secrets where key = 'SM_KEY_KTU';
  select value into tok    from app_secrets where key = 'HL_TOKEN_KTU';
  if sm_key is null or tok is null then raise exception 'SM_KEY_KTU / HL_TOKEN_KTU missing from app_secrets'; end if;

  perform http_set_curlopt('CURLOPT_TIMEOUT', '60');
  select content::jsonb into resp
    from http_post('https://serviceminder.io/api/appointments/query',
           jsonb_build_object('ApiKey', sm_key, 'FromDate', frm::text, 'ThroughDate', (frm + 14)::text,
                              'IncludeContact', true, 'Take', 500)::text, 'application/json');
  if resp is null or not (resp ? 'Appointments') then
    raise exception 'appointments/query failed: %', left(coalesce(resp::text, 'no response'), 300);
  end if;

  for a in select * from jsonb_array_elements(resp->'Appointments') loop
    continue when coalesce(a->>'ServiceName', '') !~* 'consultation';
    c := coalesce(a->'Contact', '{}');
    continue when coalesce(c->>'Name', '') ~* NOISE
               or public.is_test_record(c->>'Name', c->>'Email')
               or coalesce(c->>'Address1', '') ~* '801 s(outh)? olive'
               or coalesce(c->>'Email', '') ~* 'hybrid-reach\.com';
    sm_at   := to_timestamp(a->>'DateTime', 'FMMM/FMDD/YYYY FMHH12:MI:SS AM')::timestamp;  -- ET wall time
    sm_live := coalesce((a->>'Status')::int, 1) <> 4;
    phone   := right(regexp_replace(coalesce(c->>'Phone', ''), '\D', '', 'g'), 10);
    email   := nullif(btrim(coalesce(c->>'Email', '')), '');
    checked := checked + 1;

    -- HL contact: phone first, then email
    hl_id := null;
    if length(phone) = 10 then
      s := public.cw_hl_get(tok, format('https://services.leadconnectorhq.com/contacts/?locationId=%s&query=%s&limit=5', HL_LOC, phone));
      select x->>'id' into hl_id from jsonb_array_elements(coalesce(s->'contacts', '[]')) x
       where right(regexp_replace(coalesce(x->>'phone', ''), '\D', '', 'g'), 10) = phone limit 1;
    end if;
    if hl_id is null and email is not null then
      s := public.cw_hl_get(tok, format('https://services.leadconnectorhq.com/contacts/?locationId=%s&query=%s&limit=5', HL_LOC, replace(email, '+', '%2B')));
      select x->>'id' into hl_id from jsonb_array_elements(coalesce(s->'contacts', '[]')) x
       where lower(coalesce(x->>'email', '')) = lower(email) limit 1;
    end if;

    if hl_id is null then
      if sm_live then
        findings := findings || jsonb_build_object('kind', 'LOOKUP', 'sm_id', a->>'AppointmentId', 'name', btrim(c->>'Name'),
                      'sm_at', sm_at, 'key', 'LOOKUP|' || (a->>'AppointmentId'),
                      'text', format('not found in HighLevel by phone or email (phone %s)', coalesce(nullif(c->>'Phone', ''), 'none')));
      end if;
      continue;
    end if;

    ev := public.cw_hl_get(tok, format('https://services.leadconnectorhq.com/contacts/%s/appointments', hl_id));
    if ev ? '_error' then
      findings := findings || jsonb_build_object('kind', 'LOOKUP', 'sm_id', a->>'AppointmentId', 'name', btrim(c->>'Name'),
                    'sm_at', sm_at, 'key', 'LOOKUP|' || (a->>'AppointmentId'),
                    'text', format('HighLevel appointments read failed (%s)', ev->>'_error'));
      continue;
    end if;

    -- closest HL appointment within a day
    best := null; best_diff := null;
    for e in select * from jsonb_array_elements(coalesce(ev->'events', '[]')) loop
      continue when e->>'startTime' is null;
      hl_at := (e->>'startTime')::timestamp;
      d := case when hl_at > sm_at then hl_at - sm_at else sm_at - hl_at end;
      continue when d > interval '1 day';
      if best is null or d < best_diff
         or (d = best_diff and coalesce(e->>'appointmentStatus', '') <> 'cancelled') then
        best := e; best_diff := d;
      end if;
    end loop;

    if best is null then
      if sm_live then
        findings := findings || jsonb_build_object('kind', 'MISSING', 'sm_id', a->>'AppointmentId', 'name', btrim(c->>'Name'),
                      'sm_at', sm_at, 'key', 'MISSING|' || (a->>'AppointmentId') || '|' || sm_at,
                      'text', format('no HighLevel appointment (HL contact %s). Customer address: %s', hl_id,
                                     coalesce(nullif(concat_ws(', ', nullif(c->>'Address1', ''), nullif(c->>'City', ''), nullif(c->>'Zip', '')), ''), 'none on file')));
      end if;
      continue;
    end if;

    hl_at   := (best->>'startTime')::timestamp;
    hl_live := coalesce(best->>'appointmentStatus', '') not in ('cancelled', 'invalid', 'noshow');
    if sm_live <> hl_live then
      findings := findings || jsonb_build_object('kind', 'DIVERGENCE', 'sm_id', a->>'AppointmentId', 'name', btrim(c->>'Name'),
                    'sm_at', sm_at, 'key', format('DIV-STATUS|%s|%s|%s', a->>'AppointmentId', sm_live, hl_live),
                    'text', format('ServiceMinder says %s, HighLevel says %s (%s)',
                                   case when sm_live then 'booked' else 'cancelled' end, best->>'appointmentStatus', to_char(hl_at, 'Mon DD HH12:MI AM')));
    elsif sm_live and best_diff >= interval '30 minutes' then
      findings := findings || jsonb_build_object('kind', 'DIVERGENCE', 'sm_id', a->>'AppointmentId', 'name', btrim(c->>'Name'),
                    'sm_at', sm_at, 'key', format('DIV-TIME|%s|%s|%s', a->>'AppointmentId', sm_at, hl_at),
                    'text', format('time differs: ServiceMinder %s, HighLevel %s', to_char(sm_at, 'Mon DD HH12:MI AM'), to_char(hl_at, 'Mon DD HH12:MI AM')));
    end if;
    if coalesce(best->>'address', '') ~* '1285\s*broad' then
      findings := findings || jsonb_build_object('kind', 'ADDRESS', 'sm_id', a->>'AppointmentId', 'name', btrim(c->>'Name'),
                    'sm_at', sm_at, 'key', 'ADDRESS|' || (best->>'id'),
                    'text', 'HighLevel appointment address is the office (1285 Broad)');
    end if;
  end loop;

  if dry then
    return jsonb_build_object('checked', checked, 'findings', findings);
  end if;

  select coalesce(jsonb_agg(f2), '[]') into fresh
    from jsonb_array_elements(findings) f2
   where not exists (select 1 from sm_hl_recon_alerts r where r.finding_key = f2->>'key');

  if jsonb_array_length(fresh) > 0 then
    select string_agg(format('• %s — %s, consult %s: %s', f3->>'kind', f3->>'name',
                             to_char((f3->>'sm_at')::timestamp, 'Dy Mon DD HH12:MI AM'), f3->>'text'), E'\n'
                      order by f3->>'kind', f3->>'sm_at')
      into body from jsonb_array_elements(fresh) f3;
    insert into notify_queue(kind, recipient_email, subject, body, source)
    values ('system', 'slivingston@kitchentuneup.com',
            format('[KTU] ServiceMinder ↔ HighLevel: %s new consultation mismatch(es)', jsonb_array_length(fresh)),
            'KTU consultations, next 14 days (' || checked || ' checked):' || E'\n\n' || body || E'\n\n' ||
            'MISSING = booked in ServiceMinder, not on the HighLevel calendar. Nothing was created in HighLevel ' ||
            'automatically; add it there (or ask to turn auto-push on). Each item alerts once and again if it changes. ' ||
            'Not covered: HighLevel-only bookings (HL has no calendar-wide listing) and BTU.',
            'sm-hl-recon:' || to_char(now(), 'YYYY-MM-DD'));
    insert into sm_hl_recon_alerts(finding_key)
    select f4->>'key' from jsonb_array_elements(fresh) f4 on conflict do nothing;
  end if;

  return jsonb_build_object('checked', checked, 'findings', jsonb_array_length(findings), 'new_alerts', jsonb_array_length(fresh));
end $fn$;
revoke execute on function public.sm_hl_recon_run(boolean) from public, anon, authenticated;

-- 4) Job-costing margin escalations
create or replace function public.jc_refresh_escalations()
 returns jsonb language plpgsql security definer set search_path to 'public' as $function$
declare n_block int; n_adv int;
begin
  update payables p set
    escalation_required = true,
    escalation_reason = 'Job projected GM ' || public.jc_job_gm(p.job_id) || '% is below the 45% floor (measured, '
      || public.jc_job_cost_coverage(p.job_id) || '% cost coverage)'
  where p.status <> 'paid' and p.job_id is not null
    and coalesce(p.escalation_approved_by,'') = ''
    and not public.jc_job_is_test(p.job_id)
    and public.jc_job_gm(p.job_id) < 45 and public.jc_job_cost_coverage(p.job_id) >= 25;
  get diagnostics n_block = row_count;

  update payables p set
    escalation_required = false,
    escalation_reason = 'Advisory: job projected GM ' || public.jc_job_gm(p.job_id)
      || '% is below the 45% floor (ESTIMATE-based, ' || public.jc_job_cost_coverage(p.job_id)
      || '% cost coverage) — not held until real costs cover 25% of the job'
  where p.status <> 'paid' and p.job_id is not null
    and coalesce(p.escalation_approved_by,'') = ''
    and not public.jc_job_is_test(p.job_id)
    and public.jc_job_gm(p.job_id) < 45 and public.jc_job_cost_coverage(p.job_id) < 25;
  get diagnostics n_adv = row_count;

  update payables p set escalation_required = false, escalation_reason = null
  where p.status <> 'paid' and coalesce(p.escalation_approved_by,'') = ''
    and (p.escalation_required or p.escalation_reason is not null)
    and (p.job_id is null or public.jc_job_is_test(p.job_id) or public.jc_job_gm(p.job_id) >= 45);
  return jsonb_build_object('escalations_held', n_block, 'advisories', n_adv);
end $function$;

select public.jc_refresh_escalations();
