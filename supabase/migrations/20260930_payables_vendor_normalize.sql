-- Emailed bills: real vendor names, and non-bills kept out of AP (2026-09-30).
-- APPLIED LIVE 2026-09-30.
--
-- ingest-email (firstgentalent inbox) set payables.vendor to the sender's
-- display name or, failing that, the sender's DOMAIN, and classed anything
-- mentioning "invoice / statement / bill" as a payable. Result on 2026-09-30:
-- $65.6K under "meliopayments.com" (Melio payment NOTIFICATIONS, i.e. payments,
-- not bills), $72.3K of marketing/shipping/customer email counted as owed
-- (Apple launch ads, Floor & Decor promos, Home Depot shipping notices, a
-- customer thread titled "Bill Rutherford"), and 9 forwarded bills with no
-- vendor at all.
--
-- This normalizes every emailed payable in the database, so it works without
-- redeploying the edge function:
--   * vendor_aliases: domain / email / name -> canonical vendor (seeded from
--     the Vendor Directory's websites and emails, plus known senders)
--   * payables_normalize_email(id, dry): resolves the vendor (Melio payee from
--     the body, the original sender of a forward, "due from X", the domain) and
--     sets status 'payment_notice' / 'not_a_bill' / 'duplicate' where it applies
--   * an AFTER INSERT trigger runs it on every new emailed payable
--   * payables_reconciled and the intranet AP list exclude those statuses
-- Nothing is deleted and nothing is marked paid; every change is noted on the
-- row and reversible by resetting status to 'unpaid'.

create table if not exists public.vendor_aliases (
  kind   text not null check (kind in ('domain','email','name')),
  match  text not null,               -- lower-case domain / email / name
  vendor text not null,
  primary key (kind, match)
);
alter table public.vendor_aliases enable row level security;
drop policy if exists vendor_aliases_read on public.vendor_aliases;
create policy vendor_aliases_read on public.vendor_aliases for select to authenticated using (true);

insert into public.vendor_aliases(kind, match, vendor) values
  ('domain','gohfc.com','HFC (Home Franchise Concepts)'),
  ('domain','flooranddecor.com','Floor & Decor'),
  ('domain','homedepot.com','Home Depot'),
  ('domain','tilebar.com','Tile Bar'),
  ('domain','ricciardibrothers.com','Ricciardi Brothers'),
  ('domain','brex.com','Brex'),
  ('domain','thelocalsource.com','The Local Source'),
  ('domain','apple.com','Apple'),
  ('domain','eliaswoodwork.com','Elias Woodwork'),
  ('email','asapstoneworks@gmail.com','ASAP Stonework LLC'),
  ('email','1325jmtt@gmail.com','Touch of Class'),
  ('name','touch of class','Touch of Class'),
  ('name','asap stonework llc','ASAP Stonework LLC'),
  ('name','a.rossi & son plumbing heating & cooling','A. Rossi & Son Plumbing Heating & Cooling')
on conflict (kind, match) do update set vendor = excluded.vendor;

-- Vendor Directory websites and emails (business domains only)
insert into public.vendor_aliases(kind, match, vendor)
select distinct on (d) 'domain', d, fields->>'vendor'
  from (select fields,
               lower(substring(coalesce(fields->>'website', '') from '^(?:https?://)?(?:www\.)?([^/:?#]+)')) d
          from intranet_records where section = 'vendor_directory') x
 where d ~ '\.' and d !~ '(gmail|yahoo|hotmail|outlook|aol|icloud)\.com$'
   and d not in ('homedepot.com','flooranddecor.com','tilebar.com')
on conflict (kind, match) do nothing;
insert into public.vendor_aliases(kind, match, vendor)
select distinct on (e) 'email', e, fields->>'vendor'
  from (select fields, lower(btrim(fields->>'email')) e from intranet_records where section = 'vendor_directory') x
 where e ~ '^[^@\s]+@[^@\s]+\.[a-z]+$'
on conflict (kind, match) do nothing;

create or replace function public.vendor_from_address(addr text) returns text
language sql stable set search_path = public as $$
  select coalesce(
    (select vendor from vendor_aliases where kind = 'email' and match = lower(substring(addr from '[\w.+-]+@[\w.-]+'))),
    (select vendor from vendor_aliases a where a.kind = 'domain'
        and lower(substring(addr from '@([\w.-]+)')) ~ ('(^|\.)' || replace(a.match, '.', '\.') || '$')
      order by length(a.match) desc limit 1));
$$;

create or replace function public.payables_normalize_email(pid uuid, dry boolean default false)
returns jsonb language plpgsql security definer set search_path = public as $$
declare
  p payables; e inbox_emails;
  OWN constant text := '@(kitchentuneup\.com|goaxyom\.com|bathtune-?up\.com)|stevenglivingston@gmail\.com|firstgentalent@gmail\.com';
  v text; st text; why text; inv text; m text[]; a text; dup uuid;
begin
  select * into p from payables where id = pid;
  if p.id is null or p.source_email_id is null then return null; end if;
  select * into e from inbox_emails where id = p.source_email_id;
  if e.id is null then return null; end if;
  st := p.status; inv := p.invoice_number;

  if e.from_addr ~* 'meliopayments\.com' then
    -- A Melio notice records a payment (scheduled / sent / failed / cancelled), not a bill.
    m := regexp_match(coalesce(e.body, ''), 'Vendor name\s+(.+?)\s+Vendor email\s+(\S+)');
    v := coalesce(public.vendor_from_address(m[2]), m[1],
                  (regexp_match(coalesce(e.subject, ''), 'payment to (.+?)(?:\s+(?:was|for|has|fail|failed)\M|$)', 'i'))[1]);
    inv := coalesce((regexp_match(coalesce(e.body, ''), 'Invoice number\s+#?\[?([\w-]+)'))[1], inv);
    st := 'payment_notice'; why := 'Melio payment notification — records a payment, not a bill';
  elsif e.from_addr ~* '^[^<]*<?(news|marketing|promo|deals|offers)@|@(email|mg|news|e|em|mail)\.'
     or e.subject ~* 'order #?\s*\w+ shipped|pre-?order|is here|just landed|clearance|redeem|save on|stock up|% off|rewards points' then
    v := public.vendor_from_address(e.from_addr);
    st := 'not_a_bill'; why := 'Marketing / shipping / rewards email, not a bill';
  else
    v := btrim((regexp_match(coalesce(e.subject, ''), 'due from (.+?)(?:\s+-\s+\$|$)', 'i'))[1]);
    if v is null and e.from_addr !~* OWN then
      v := public.vendor_from_address(e.from_addr);
    end if;
    if v is null then
      -- A forward: take the first sender/recipient in the body outside our own domains.
      for a in select (regexp_matches(coalesce(e.body, ''), '(?:From|To):[^<\n]*<?([\w.+-]+@[\w.-]+)', 'g'))[1] loop
        continue when a ~* OWN;
        v := public.vendor_from_address(a);
        exit when v is not null;
      end loop;
    end if;
  end if;
  v := coalesce((select vendor from vendor_aliases where kind = 'name' and match = lower(btrim(v))), btrim(v), p.vendor);

  if st not in ('payment_notice', 'not_a_bill', 'paid') and v is not null and p.amount is not null then
    select id into dup from payables o
     where o.id <> p.id and lower(o.vendor) = lower(v) and o.amount = p.amount
       and coalesce(o.brand, '') = coalesce(p.brand, '')
       and o.status not in ('payment_notice', 'not_a_bill', 'duplicate')
       and abs(coalesce(o.invoice_date, current_date) - coalesce(p.invoice_date, current_date)) <= 30
       and (o.created_at, o.id) < (p.created_at, p.id)
     order by o.created_at limit 1;
    if dup is not null then st := 'duplicate'; why := 'Duplicate of payable ' || dup || ' (same vendor and amount, forwarded copy)'; end if;
  end if;

  if dry then
    return jsonb_build_object('id', p.id, 'vendor', v, 'status', st, 'invoice_number', inv, 'why', why);
  end if;
  update payables set vendor = v, status = st, invoice_number = inv,
         notes = case when why is null or coalesce(notes, '') like '[auto]%' then notes
                      else '[auto] ' || why || ' | ' || coalesce(notes, '') end
   where id = p.id
     and (vendor is distinct from v or status is distinct from st or invoice_number is distinct from inv);
  return jsonb_build_object('id', p.id, 'vendor', v, 'status', st);
end $$;
revoke execute on function public.payables_normalize_email(uuid, boolean) from public, anon, authenticated;

create or replace function public.payables_normalize_email_trg() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  perform public.payables_normalize_email(new.id);
  return null;
end $$;
drop trigger if exists payables_normalize_email on public.payables;
create trigger payables_normalize_email after insert on public.payables
  for each row when (new.source_email_id is not null and new.status = 'unpaid')
  execute function public.payables_normalize_email_trg();

-- AP views ignore rows that are not money owed
create or replace view public.payables_reconciled with (security_invoker = true) as
 SELECT p.id, p.brand, p.vendor, p.invoice_number, p.amount, p.due_date, p.status, p.paid_date,
    b.external_id AS candidate_txn, b.posted_on AS candidate_paid_on, b.amount AS candidate_amount,
    b.description AS candidate_description,
        CASE
            WHEN (p.status = 'paid'::text) THEN 'paid (marked)'::text
            WHEN (b.external_id IS NOT NULL) THEN 'likely paid — bank outflow matches, needs confirming'::text
            WHEN (p.due_date < CURRENT_DATE) THEN 'past due, no matching payment found'::text
            ELSE 'open'::text
        END AS reconciled_state
   FROM (payables p
     LEFT JOIN bank_transactions b ON (((b.direction = 'out'::text) AND (b.matched_payable_id IS NULL) AND (p.amount IS NOT NULL) AND (abs((b.amount - p.amount)) < 0.01) AND ((b.posted_on >= (COALESCE(p.invoice_date, (p.due_date - 30)) - 7)) AND (b.posted_on <= (COALESCE(p.due_date, (p.invoice_date + 30)) + 90))))))
  WHERE p.status NOT IN ('not_a_bill', 'payment_notice', 'duplicate');
