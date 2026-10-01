-- Monday AP reconciliation moved off Claude Routines (2026-09-30).
-- APPLIED LIVE 2026-09-30. Replaces routine "Monday AP recon — verify, pull only
-- if Moola didn't" (Mon 15:00 UTC). Its normal path was SQL only; that is all
-- this is. The fallback bank pull used the Truthifi connector, which has no
-- server-side API, so when Moola has not synced this digest SAYS so instead of
-- pulling. (A scheduled Claude session could not have made that connector call
-- either: it stalls on the permission prompt.)
--
-- Never sets payables.status — candidates are for Steven to confirm.

create or replace function public.ap_recon_digest(dry boolean default false)
returns jsonb language plpgsql security definer set search_path = public as $$
declare
  today     date := (now() at time zone 'UTC')::date;
  last_sync timestamptz;
  states    text;
  likely    text;
  unmatched text;
  body      text;
begin
  select max(synced_at) into last_sync from bank_transactions;

  select string_agg(format('• %s: %s bill(s), $%s', reconciled_state, n, to_char(amt, 'FM999,999,990.00')), E'\n' order by reconciled_state)
    into states from (select reconciled_state, count(*) n, sum(amount) amt from payables_reconciled group by 1) s;

  select string_agg(format('• %s %s — $%s, bank outflow %s $%s "%s"', brand, coalesce(nullif(vendor,''), invoice_number, '(no vendor)'), to_char(amount, 'FM999,999,990.00'),
                           candidate_paid_on, to_char(abs(candidate_amount), 'FM999,999,990.00'), left(coalesce(candidate_description, ''), 60)), E'\n')
    into likely from payables_reconciled where reconciled_state like 'likely paid%';

  select string_agg(format('• %s %s $%s "%s"', posted_on, coalesce(account_name, institution, ''), to_char(abs(amount), 'FM999,999,990.00'),
                           left(coalesce(party, description, ''), 60)), E'\n' order by abs(amount) desc)
    into unmatched
    from (select * from bank_transactions_explained
           where direction = 'out' and abs(amount) > 500 and payable_id is null
             and not coalesce(is_internal, false) and explanation = 'UNEXPLAINED'
             and posted_on > current_date - 14
           order by abs(amount) desc limit 12) u;

  body := case when last_sync is null or last_sync < now() - interval '24 hours'
            then format(E'Bank feed NOT refreshed today (last sync %s). Moola owns the Monday pull and missed it — the figures below are as of that sync.\n\n',
                        coalesce(to_char(last_sync at time zone 'America/New_York', 'Mon DD HH24:MI "ET"'), 'never'))
            else '' end ||
          E'Payables:\n' || coalesce(states, '• none') || E'\n\n' ||
          E'Likely paid — confirm (bank outflow matches):\n' || coalesce(likely, '• none') || E'\n\n' ||
          E'Unexplained outflows over $500, last 14 days (no bill, no rule):\n' || coalesce(unmatched, '• none') ||
          E'\n\nNothing was marked paid. Confirm candidates on the intranet Payables tab.';

  if dry then return jsonb_build_object('body', body); end if;
  if not exists (select 1 from notify_queue where source = 'ap-recon:' || today) then
    insert into notify_queue(kind, recipient_email, subject, body, source)
    values ('system', 'slivingston@kitchentuneup.com', '[Axyom] Monday AP reconciliation', body, 'ap-recon:' || today);
  end if;
  return jsonb_build_object('queued', true);
end $$;
revoke execute on function public.ap_recon_digest(boolean) from public, anon, authenticated;

select cron.unschedule('ap-recon-monday') where exists (select 1 from cron.job where jobname='ap-recon-monday');
select cron.schedule('ap-recon-monday', '0 15 * * 1', $$ select public.ap_recon_digest(); $$);
