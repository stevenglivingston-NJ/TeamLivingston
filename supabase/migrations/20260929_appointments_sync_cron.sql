-- Appointments hub refresh moved off Claude Routines (2026-09-29 audit).
-- APPLIED LIVE 2026-09-29 (migrations appointments_refresh_derived + appointments_sync_cron).
-- A scheduled Claude session runs in Auto mode and also shares the account's usage
-- limit; either can stop it. pg_cron -> edge function has neither problem.
-- Edge function: supabase/functions/appointments-sync (verify_jwt off, x-cron-secret auth).

create or replace function public.appointments_refresh_derived()
returns jsonb language plpgsql security definer set search_path to 'public' as $$
declare n_rebucket int;
begin
  update public.appointments a set
    proposal_status = case
        when p.fields->>'status' ilike any (array['accepted%','invoiced%','scheduled%','won%']) then 'accepted'
        when p.fields->>'status' ilike any (array['expired%','declined%','lost%']) then 'expired'
        when p.fields->>'status' is not null then 'open' else a.proposal_status end,
    proposal_amount = coalesce(nullif(regexp_replace(coalesce(p.fields->>'amount',''),'[^0-9.]','','g'),'')::numeric, a.proposal_amount)
  from public.intranet_records p
  where p.section = 'proposals' and a.proposal_id is not null and p.fields->>'sm_id' = a.proposal_id::text;

  update public.appointments set proposal_status = 'none'
  where proposal_id is null and proposal_status is null;

  update public.appointments a set notes = f.fields->>'notes'
  from public.intranet_records f
  where f.section = 'appt_followups' and f.fields->>'sm_id' = a.appointment_id::text
    and coalesce(f.fields->>'notes','') <> '' and a.notes is distinct from f.fields->>'notes';

  update public.appointments set bucket = case
      when status = 'cancelled' then 'cancelled'
      when appt_at >= (date_trunc('day', now() at time zone 'America/New_York') at time zone 'America/New_York') then 'upcoming'
      else 'past' end
  where bucket is distinct from case
      when status = 'cancelled' then 'cancelled'
      when appt_at >= (date_trunc('day', now() at time zone 'America/New_York') at time zone 'America/New_York') then 'upcoming'
      else 'past' end;
  get diagnostics n_rebucket = row_count;

  return jsonb_build_object('rebucketed', n_rebucket,
    'buckets', (select jsonb_object_agg(bucket, n) from (select bucket, count(*) n from public.appointments group by 1) x));
end $$;
revoke execute on function public.appointments_refresh_derived() from public, anon, authenticated;

-- 06:45 ET (10:45 UTC; 05:45 ET in winter) daily.
select cron.unschedule('appointments-sync-daily') where exists (select 1 from cron.job where jobname='appointments-sync-daily');
select cron.schedule('appointments-sync-daily','45 10 * * *', $$
  select net.http_post(
    url     := 'https://tguwpswcneywvscxzyef.supabase.co/functions/v1/appointments-sync',
    headers := jsonb_build_object('Content-Type','application/json',
               'x-cron-secret',(select value from public.dispatch_config where key='cron_secret')),
    body    := '{}'::jsonb, timeout_milliseconds := 150000);
$$);
