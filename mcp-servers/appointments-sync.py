#!/usr/bin/env python3
"""
appointments-sync.py — deterministic refresh of public.appointments (the intranet
Appointments tab + Home snapshot) from ServiceMinder, both brands.

Why a script: Goldeneye spec step 5c asked the LLM to do this through connector
tools. The routine prompt never reached 5c, and connector calls stall scheduled
runs in REQUIRES_ACTION, so the table froze at a 2026-07-10 seed (max appt_at
2026-09-10) while "upcoming" rows aged into the past. This does the same job with
the curl helpers only (sm.sh, sb.sh) — no mcp__* tools, no destructive shell.

What it does, per brand (KTU, BTU):
  1. sm.sh <brand> appointments/query  today-120d .. today+120d, IncludeContact,
     paged with Skip/Take.
  2. Drops test rows (lead-sweep.is_test_row).
  3. Upserts on appointment_id. HUMAN-owned columns next_action / next_action_by
     are never written. proposal_* are filled from the `proposals` section
     (Pipeline/Goldeneye keep it fresh); notes from `appt_followups`.
  4. Re-buckets the WHOLE table (upcoming / past / cancelled) against today (ET),
     so a row can never stay "upcoming" after its date passes.

Usage:  python3 mcp-servers/appointments-sync.py [--days 120] [--dry-run]
Exit 1 if either brand returned zero rows or a write failed (so the caller
reports it instead of looking healthy).
"""
import argparse, datetime as dt, importlib.util, json, os, subprocess, sys
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
ET = ZoneInfo("America/New_York")
STATUS = {0: "scheduled", 1: "scheduled", 2: "scheduled", 3: "completed", 4: "cancelled"}

spec = importlib.util.spec_from_file_location("lead_sweep", os.path.join(HERE, "lead-sweep.py"))
lead_sweep = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lead_sweep)


def sm(brand, endpoint, body):
    out = subprocess.run(["bash", os.path.join(HERE, "sm.sh"), brand, endpoint, json.dumps(body)],
                         capture_output=True, text=True, timeout=180)
    try:
        return json.loads(out.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"sm.sh {brand} {endpoint}: {out.stdout[:200]} {out.stderr[:200]}")


def sb(sql):
    out = subprocess.run(["bash", os.path.join(HERE, "sb.sh")], input=sql,
                         capture_output=True, text=True, timeout=180)
    body = out.stdout.strip()
    if out.returncode != 0 or '"error"' in body[:40] or '"code"' in body[:40]:
        raise RuntimeError(f"sb.sh failed: {body[:300]} {out.stderr[:200]}")
    return json.loads(body) if body else None


def q(v):
    if v is None or v == "":
        return "NULL"
    return "'" + str(v).replace("'", "''") + "'"


def parse_dt(s):
    # "12/17/2026 12:00:00 PM" — ServiceMinder local (Eastern) time
    try:
        return dt.datetime.strptime(s, "%m/%d/%Y %I:%M:%S %p").replace(tzinfo=ET)
    except (TypeError, ValueError):
        return None


def pull(brand, start, end):
    rows, skip, take = [], 0, 500
    while True:
        d = sm(brand, "appointments/query", {"FromDate": start, "ThroughDate": end,
                                             "IncludeContact": True, "Skip": skip, "Take": take})
        if d.get("ResultCode") not in (None, 0):
            raise RuntimeError(f"{brand} appointments/query: {d.get('Message')}")
        batch = d.get("Appointments") or []
        rows += batch
        if len(batch) < take:
            return rows
        skip += take


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=120)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    today = dt.datetime.now(ET).date()
    start = (today - dt.timedelta(days=a.days)).strftime("%m/%d/%Y")
    end = (today + dt.timedelta(days=a.days)).strftime("%m/%d/%Y")
    run_dir = f"/tmp/appointments-sync/run-{dt.datetime.now().strftime('%Y%m%dT%H%M%S')}"
    os.makedirs(run_dir, exist_ok=True)

    report, failed, values = {}, False, []
    for brand in ("KTU", "BTU"):
        try:
            raw = pull(brand, start, end)
        except Exception as e:  # report, keep the other brand going
            report[brand] = {"error": str(e)[:300]}
            failed = True
            continue
        kept = []
        for r in raw:
            c = r.get("Contact") or {}
            if lead_sweep.is_test_row(c.get("Name"), c.get("Email"), c.get("Phone")):
                continue
            when = parse_dt(r.get("DateTime"))
            if not when or not r.get("AppointmentId"):
                continue
            kept.append((r, c, when))
        # a cancelled appointment is a follow-up (rescheduled) if the contact has a
        # later appointment that isn't cancelled
        later_live = {}
        for r, c, when in kept:
            if STATUS.get(r.get("Status"), "scheduled") != "cancelled":
                later_live[r["ContactId"]] = max(later_live.get(r["ContactId"], when), when)
        for r, c, when in kept:
            status = STATUS.get(r.get("Status"), "scheduled")
            seg = None
            if status == "cancelled":
                seg = "follow_up" if later_live.get(r["ContactId"], when) > when else None
            addr = ", ".join(x for x in [c.get("Address1"), c.get("City"), c.get("State"), c.get("Zip")] if x)
            values.append("(" + ",".join([
                str(int(r["AppointmentId"])), q(brand), str(int(r["ContactId"] or 0)) if r.get("ContactId") else "NULL",
                q(c.get("Name")), q(c.get("Phone")), q(c.get("Email")), q(addr),
                q(r.get("ServiceName")), q(r.get("ServiceAgentName")), q(when.isoformat()),
                q(status), q(seg), str(int(r["ProposalId"])) if r.get("ProposalId") else "NULL",
                q(today.isoformat())]) + ")")
        report[brand] = {"pulled": len(raw), "kept": len(kept)}
        if not kept:
            failed = True

    with open(f"{run_dir}/values.sql", "w") as f:
        f.write(",\n".join(values))
    if a.dry_run or not values:
        print(json.dumps({"dry_run": a.dry_run, "report": report, "run_dir": run_dir}))
        return 1 if failed else 0

    upsert = f"""
insert into public.appointments (appointment_id, brand, contact_id, customer_name, customer_phone,
  customer_email, address, service, service_agent, appt_at, status, cancel_segment, proposal_id, scan_date)
values {",".join(values)}
on conflict (appointment_id) do update set
  brand=excluded.brand, contact_id=excluded.contact_id, customer_name=excluded.customer_name,
  customer_phone=coalesce(excluded.customer_phone, appointments.customer_phone),
  customer_email=coalesce(excluded.customer_email, appointments.customer_email),
  address=coalesce(excluded.address, appointments.address), service=excluded.service,
  service_agent=excluded.service_agent, appt_at=excluded.appt_at, status=excluded.status,
  cancel_segment=coalesce(excluded.cancel_segment, nullif(appointments.cancel_segment,'unknown'), 'unknown'),
  proposal_id=coalesce(excluded.proposal_id, appointments.proposal_id),
  scan_date=excluded.scan_date, source='serviceminder (appointments-sync.py)', updated_at=now();
"""
    enrich = """
update public.appointments a set
  proposal_status = case
      when p.fields->>'status' ilike any (array['accepted%','invoiced%','scheduled%','won%']) then 'accepted'
      when p.fields->>'status' ilike any (array['expired%','declined%','lost%']) then 'expired'
      when p.fields->>'status' is not null then 'open' else a.proposal_status end,
  proposal_amount = coalesce(nullif(regexp_replace(p.fields->>'amount','[^0-9.]','','g'),'')::numeric, a.proposal_amount)
from public.intranet_records p
where p.section='proposals' and a.proposal_id is not null and p.fields->>'sm_id' = a.proposal_id::text;
update public.appointments set proposal_status='none' where proposal_id is null and proposal_status is null;
update public.appointments a set notes = f.fields->>'notes'
from public.intranet_records f
where f.section='appt_followups' and f.fields->>'sm_id' = a.appointment_id::text
  and coalesce(f.fields->>'notes','') <> '' and a.notes is distinct from f.fields->>'notes';
"""
    rebucket = """
update public.appointments set bucket = case
    when status = 'cancelled' then 'cancelled'
    when appt_at >= (date_trunc('day', now() at time zone 'America/New_York') at time zone 'America/New_York') then 'upcoming'
    else 'past' end
where bucket is distinct from case
    when status = 'cancelled' then 'cancelled'
    when appt_at >= (date_trunc('day', now() at time zone 'America/New_York') at time zone 'America/New_York') then 'upcoming'
    else 'past' end;
"""
    try:
        sb(upsert)
        sb(enrich)
        sb(rebucket)
        report["table"] = sb("select bucket, count(*) n, max(appt_at)::text latest from public.appointments group by 1 order by 1")
    except Exception as e:
        report["write_error"] = str(e)[:400]
        failed = True
    print(json.dumps({"report": report, "run_dir": run_dir}, default=str))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
