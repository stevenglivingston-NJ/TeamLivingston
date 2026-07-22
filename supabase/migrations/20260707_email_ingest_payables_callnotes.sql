-- Email-driven pipe: the firstgentalent@gmail.com inbox → Supabase.
-- PRIMARY path: the agents pull that inbox DIRECTLY via the Gmail MCP each run —
--   Moola reads invoices → `payables`, Goldeneye reads Perceptionist notes →
--   `call_notes`, and both scrape senders into the `contacts` Directory.
-- OPTIONAL push path: the `ingest-email` edge function + `inbox_emails` raw table
--   (a webhook), kept available if a push source is ever wired. Not required for
--   the live Gmail-pull flow.
-- Tables: inbox_emails (raw/optional), payables (bills we owe), call_notes.
-- Applied 2026-07-07.

-- 1) Raw email capture (the landing zone the Zap/edge function writes to).
create table if not exists public.inbox_emails (
  id uuid primary key default gen_random_uuid(),
  received_at timestamptz,
  from_addr text,
  to_addr text,
  subject text,
  body text,
  kind text default 'unknown',      -- best-effort at ingest: 'invoice'|'call_note'|'unknown'
  brand text,                        -- optional guess: KTU|BTU|Earthwise
  processed boolean default false,   -- an agent has turned it into a payable/call_note
  raw jsonb,
  created_at timestamptz not null default now()
);
create index if not exists inbox_emails_kind_idx on public.inbox_emails(kind, processed);
create index if not exists inbox_emails_received_idx on public.inbox_emails(received_at desc);

-- 2) Payables — bills we owe. Moola-maintained + human-editable in the intranet.
create table if not exists public.payables (
  id uuid primary key default gen_random_uuid(),
  brand text,                        -- KTU|BTU|Earthwise|Both
  vendor text,
  invoice_number text,
  amount numeric,
  invoice_date date,                 -- when it was sent/issued
  due_date date,
  status text not null default 'unpaid',   -- unpaid|scheduled|paid|disputed
  priority text default 'normal',    -- urgent|high|normal|low (Moola computes; human can override)
  category text,
  source text,                       -- 'email:firstgentalent', 'manual', ...
  source_email_id uuid references public.inbox_emails(id) on delete set null,
  notes text,
  paid_date date,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists payables_status_due_idx on public.payables(status, due_date);
create index if not exists payables_vendor_inv_idx on public.payables(lower(vendor), invoice_number);

-- 3) Perceptionist call notes. Goldeneye-maintained + human-editable.
create table if not exists public.call_notes (
  id uuid primary key default gen_random_uuid(),
  brand text,
  caller_name text,
  caller_phone text,
  call_time timestamptz,
  summary text,
  disposition text,                  -- lead|existing|spam|vendor|other
  follow_up boolean default false,
  handled boolean default false,
  source text,
  source_email_id uuid references public.inbox_emails(id) on delete set null,
  created_at timestamptz not null default now()
);
create index if not exists call_notes_time_idx on public.call_notes(call_time desc);

-- updated_at trigger for payables
create or replace function public.touch_updated_at() returns trigger
  language plpgsql as $$ begin new.updated_at = now(); return new; end $$;
drop trigger if exists payables_touch on public.payables;
create trigger payables_touch before update on public.payables
  for each row execute function public.touch_updated_at();

-- RLS: authenticated app users read/write (mirrors contacts/jobs/intranet_records);
-- the edge function uses the service role and bypasses RLS.
alter table public.inbox_emails enable row level security;
alter table public.payables    enable row level security;
alter table public.call_notes  enable row level security;

do $$ begin
  if not exists (select 1 from pg_policies where tablename='inbox_emails' and policyname='inbox_emails_authed') then
    create policy inbox_emails_authed on public.inbox_emails for all to authenticated using (true) with check (true);
  end if;
  if not exists (select 1 from pg_policies where tablename='payables' and policyname='payables_authed') then
    create policy payables_authed on public.payables for all to authenticated using (true) with check (true);
  end if;
  if not exists (select 1 from pg_policies where tablename='call_notes' and policyname='call_notes_authed') then
    create policy call_notes_authed on public.call_notes for all to authenticated using (true) with check (true);
  end if;
end $$;

-- Live updates in the intranet.
do $$ begin
  begin alter publication supabase_realtime add table public.payables; exception when duplicate_object then null; end;
  begin alter publication supabase_realtime add table public.call_notes; exception when duplicate_object then null; end;
  begin alter publication supabase_realtime add table public.inbox_emails; exception when duplicate_object then null; end;
end $$;

-- Shared secret for the ingest edge function (reuse dispatch_config).
insert into public.dispatch_config (key, value)
values ('ingest_secret', encode(gen_random_bytes(24),'hex'))
on conflict (key) do nothing;
