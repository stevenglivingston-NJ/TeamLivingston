#!/usr/bin/env python3
"""
calendar-health.py — daily booking-integration health probe for KTU + BTU.

Answers one question before it costs a booking: **can a lead actually book right
now, and does every layer agree on when?**

Emits a RAG-graded JSON document. Tekki reads the integration half; Pipeline
reads the conversion half. Neither re-derives the analysis.

    python3 mcp-servers/calendar-health.py --out /tmp/calendar-health.json
    python3 mcp-servers/calendar-health.py --brand KTU --verbose

WHY THIS EXISTS — three real failures, all on 2026-09-19, none of which raised an
error anywhere:

1. A partial-body PUT to HighLevel's `update-calendar` reset every field it did
   not send. Open hours went empty; the calendar offered nothing.
2. Writing `openHours` at all **silently detaches every user availability
   schedule** from the calendar. Reproduced twice. The calendar still lists its
   team members, so the UI looks correct, but `calendarIds` on each schedule is
   emptied and nothing is bookable.
3. Echoing `slotDuration: 2` with `slotDurationUnit: "hours"` back to the API
   stored **0.03 hours** — it divided by 60. Two-minute consultation slots.

All three present identically to a lead: no availability. None of them logs a
failure. The only reliable detection is to assert the invariants below on a
schedule.

TRANSPORT: everything goes through `curl` on purpose — python-urllib gets a 403
from the session egress proxy and would silently return nothing. Same reason
`lead-sweep.py` does it.

AUTH: HighLevel needs a token that works outside an interactive session. The
claude.ai OAuth connector cannot be used here — scheduled Routines stall forever
on the connector-permission prompt (see CLAUDE.md, "Scheduled runs stall on MCP
connector calls"). So this reads `GHL_PIT_KTU` / `GHL_PIT_BTU`. If they are
unset, the HighLevel checks report as **degraded, not healthy** — an unverified
calendar is never green.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

HL_API = "https://services.leadconnectorhq.com"
HL_VERSION = "2021-04-15"
CB_API = "https://api.closebot.com"

# Brand wiring. Adding a brand means adding a row here and nothing else.
BRANDS = {
    "KTU": {
        "location_id": "nHLCxHPidnhV1NFzRtZZ",
        "calendar_id": "IezEuyUywqr1OL7tjHEk",
        "calendar_name": "Consultation Calendar",
        "pit_env": "GHL_PIT_KTU",
        "sm_location": "KTU",
        "closebot_bot": "bot_SRQO2QVP9AVZ8SQ4",
        "booking_node": "ba6fe8ee-545d-41d1-a127-a1b667796f1c",
        "booked_node": "3f8f5ec3-1b13-49b7-9a51-03ecb5eab890",
    },
    "BTU": {
        "location_id": "0uWA8M5BzHrrcJftuaDe",
        "calendar_id": "k6bokOz0oIicKYu93zhW",
        "calendar_name": "Consultation Calendar",
        "pit_env": "GHL_PIT_BTU",
        "sm_location": "BTU",
        "closebot_bot": "bot_O8XUQA6CTBLEILUV",
        # BTU books via a staging calendar in the KTU sub-account by design and a
        # workflow transfers the appointment across. Do NOT "fix" this.
        "staging_calendar_id": "kEW9PFmXRzujFf6rQUPp",
        "booking_node": "bcda4208-2523-4e0f-99de-6c989e362671",
        "booked_node": "54f437df-01ab-45aa-bd27-318adf88cab1",
    },
}

# Invariants. Breach any of these and a lead sees no availability.
MIN_SLOT_MINUTES = 30      # anything shorter means the unit conversion corrupted
MAX_SLOT_MINUTES = 480
EXPECTED_PER_SLOT = 1      # per-USER cap; headcount scales capacity, not this
DOW_NAME = {0: "Sunday", 1: "Monday", 2: "Tuesday", 3: "Wednesday",
            4: "Thursday", 5: "Friday", 6: "Saturday"}
SM_DOW = {0: 0, 1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 6}
DAY_TO_IDX = {"sunday": 0, "monday": 1, "tuesday": 2, "wednesday": 3,
              "thursday": 4, "friday": 5, "saturday": 6}

# Sunday is closed for every brand, by policy. An open Sunday is a finding.
CLOSED_DAYS = {0}


def curl_json(url: str, headers: dict, timeout: int = 40):
    """GET url via curl, return (parsed_json_or_None, error_string_or_None).

    Checks the HTTP status explicitly. Both HighLevel and Closebot return errors
    as a 200-shaped JSON body with a 4xx status — e.g. HighLevel answers a
    schedules query missing locationId with 401 {"message": "Location ID is
    required"}. Parsing that as data yields an empty list, which reads exactly
    like "nothing is configured". An error must never be mistakable for a clean
    empty result; that is the whole point of this probe.
    """
    cmd = ["curl", "-sS", "--max-time", str(timeout), "-w", "\n%{http_code}"]
    for k, v in headers.items():
        cmd += ["-H", f"{k}: {v}"]
    cmd.append(url)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 15)
    except subprocess.TimeoutExpired:
        return None, "curl timeout"
    if r.returncode != 0:
        return None, f"curl exit {r.returncode}: {r.stderr.strip()[:200]}"
    raw = r.stdout.rsplit("\n", 1)
    body, status = (raw[0].strip(), raw[1].strip()) if len(raw) == 2 else (r.stdout.strip(), "")
    if status and not status.startswith("2"):
        return None, f"HTTP {status}: {body[:200]}"
    if not body:
        return None, "empty response"
    try:
        doc = json.loads(body)
    except json.JSONDecodeError:
        return None, f"non-JSON response: {body[:200]}"
    if isinstance(doc, dict) and doc.get("error") and doc.get("statusCode"):
        return None, f"API error {doc.get('statusCode')}: {doc.get('message')}"
    return doc, None


def hl_headers(pit: str) -> dict:
    return {"Authorization": f"Bearer {pit}", "Version": HL_VERSION,
            "Accept": "application/json"}


def minutes(h: int, m: int) -> int:
    return h * 60 + m


def merge(intervals):
    out = []
    for s, e in sorted(intervals):
        if out and s <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out


def slot_minutes(cal: dict) -> float | None:
    """Normalise slotDuration to minutes regardless of the unit field."""
    v, unit = cal.get("slotDuration"), (cal.get("slotDurationUnit") or "mins")
    if v is None:
        return None
    return float(v) * 60 if unit == "hours" else float(v)


# ---------------------------------------------------------------- HighLevel --

def check_highlevel(brand: str, cfg: dict, findings: list, degradations: list) -> dict:
    out = {"calendar_id": cfg["calendar_id"], "checked": False}
    pit = os.environ.get(cfg["pit_env"], "").strip()
    if not pit:
        degradations.append({
            "area": f"highlevel:{brand}",
            "detail": f"{cfg['pit_env']} is unset — HighLevel calendar checks did "
                      f"NOT run. This calendar is UNVERIFIED, not healthy. Restore "
                      f"the Private Integration Token to enable this check.",
        })
        return out

    hdr = hl_headers(pit)
    cal_doc, err = curl_json(f"{HL_API}/calendars/{cfg['calendar_id']}", hdr)
    if err or not cal_doc:
        degradations.append({"area": f"highlevel:{brand}",
                             "detail": f"could not read calendar: {err}"})
        return out
    cal = cal_doc.get("calendar", cal_doc)
    out["checked"] = True
    out["name"] = cal.get("name")

    # -- slot sanity. Catches the unit-conversion corruption.
    sm = slot_minutes(cal)
    out["slot_minutes"] = sm
    if sm is None or sm < MIN_SLOT_MINUTES or sm > MAX_SLOT_MINUTES:
        findings.append({
            "severity": "RED", "brand": brand, "check": "slot_duration",
            "detail": f"slotDuration is {sm} minutes (raw {cal.get('slotDuration')} "
                      f"{cal.get('slotDurationUnit')}). Outside the sane range "
                      f"{MIN_SLOT_MINUTES}-{MAX_SLOT_MINUTES}. A unit conversion has "
                      f"corrupted it — leads will be offered nonsense slot lengths.",
        })

    # -- per-slot cap. It is a per-USER cap; >1 overbooks each designer.
    per_slot = cal.get("appointmentPerSlot", cal.get("appoinmentPerSlot"))
    out["appointment_per_slot"] = per_slot
    if per_slot != EXPECTED_PER_SLOT:
        findings.append({
            "severity": "AMBER", "brand": brand, "check": "appointment_per_slot",
            "detail": f"appointmentPerSlot is {per_slot}, expected {EXPECTED_PER_SLOT}. "
                      f"This is a PER-USER cap — raising it lets each designer be "
                      f"booked {per_slot} times in the same slot.",
        })

    members = [m.get("userId") for m in (cal.get("teamMembers") or []) if m.get("userId")]
    out["team_members"] = len(members)
    if not members:
        findings.append({"severity": "RED", "brand": brand, "check": "team_members",
                         "detail": "calendar has no team members — nothing is bookable."})

    # -- linked availability schedules. THE check. Detached schedules leave the
    #    calendar looking correct in the UI while offering zero slots.
    sched_doc, err = curl_json(
        f"{HL_API}/calendars/schedules/search?locationId={cfg['location_id']}"
        f"&calendarId={cfg['calendar_id']}&limit=100", hdr)
    if err:
        degradations.append({"area": f"highlevel:{brand}",
                             "detail": f"could not read availability schedules: {err}"})
        return out
    schedules = (sched_doc or {}).get("schedules", [])
    linked_users = {s.get("userId") for s in schedules}
    out["linked_schedules"] = len(schedules)

    if members and not schedules:
        findings.append({
            "severity": "RED", "brand": brand, "check": "schedules_detached",
            "detail": f"calendar lists {len(members)} team member(s) but ZERO "
                      f"availability schedules are linked to it. Nothing is bookable. "
                      f"This is the known HighLevel defect: writing openHours via the "
                      f"API detaches every schedule. Re-link with "
                      f"PUT /calendars/schedules/{{scheduleId}}/associations/{cfg['calendar_id']}",
        })
    else:
        for uid in members:
            if uid not in linked_users:
                findings.append({
                    "severity": "RED", "brand": brand, "check": "schedule_detached",
                    "detail": f"team member {uid} is on the calendar but has no "
                              f"availability schedule linked to it — they will never "
                              f"be offered.",
                })

    # -- staffed coverage per day. Catches an open day nobody can work.
    staffed = {}
    for s in schedules:
        for rule in (s.get("rules") or []):
            idx = DAY_TO_IDX.get((rule.get("day") or "").lower())
            if idx is None:
                continue
            for iv in (rule.get("intervals") or []):
                try:
                    fh, fm = map(int, iv["from"].split(":"))
                    th, tm = map(int, iv["to"].split(":"))
                except (KeyError, ValueError):
                    continue
                staffed.setdefault(idx, []).append((minutes(fh, fm), minutes(th, tm)))
    staffed = {d: merge(v) for d, v in staffed.items()}
    out["staffed_days"] = {DOW_NAME[d]: [f"{a//60:02d}:{a%60:02d}-{b//60:02d}:{b%60:02d}"
                                         for a, b in v] for d, v in sorted(staffed.items())}

    open_days = {}
    for blk in (cal.get("openHours") or []):
        for d in (blk.get("daysOfTheWeek") or []):
            for h in (blk.get("hours") or []):
                open_days.setdefault(d, []).append(
                    (minutes(h.get("openHour", 0), h.get("openMinute", 0)),
                     minutes(h.get("closeHour", 0), h.get("closeMinute", 0))))
    open_days = {d: merge(v) for d, v in open_days.items()}
    out["open_days"] = {DOW_NAME[d]: [f"{a//60:02d}:{a%60:02d}-{b//60:02d}:{b%60:02d}"
                                      for a, b in v] for d, v in sorted(open_days.items())}

    for d, windows in sorted(open_days.items()):
        if d in CLOSED_DAYS:
            findings.append({
                "severity": "AMBER", "brand": brand, "check": "closed_day_open",
                "detail": f"{DOW_NAME[d]} is open on the calendar but {DOW_NAME[d]} "
                          f"is closed for all brands by policy. Remove the window.",
            })
            continue
        if d not in staffed:
            findings.append({
                "severity": "AMBER", "brand": brand, "check": "unstaffed_day",
                "detail": f"{DOW_NAME[d]} is open on the calendar but no designer has "
                          f"availability that day. The calendar advertises a day nobody "
                          f"can work — leads see nothing and assume you are full.",
            })
            continue
        cov = merge(staffed[d])
        for a, b in windows:
            if not any(cs < b and a < ce for cs, ce in cov):
                findings.append({
                    "severity": "AMBER", "brand": brand, "check": "unstaffed_window",
                    "detail": f"{DOW_NAME[d]} {a//60:02d}:{a%60:02d}-{b//60:02d}:{b%60:02d} "
                              f"is open but no designer covers any of it.",
                })

    # -- staffed but not offered: real capacity the calendar hides.
    for d, cov in sorted(staffed.items()):
        if d in CLOSED_DAYS:
            continue
        if d not in open_days:
            total = sum(b - a for a, b in cov) / 60
            findings.append({
                "severity": "AMBER", "brand": brand, "check": "hidden_capacity",
                "detail": f"{DOW_NAME[d]}: {total:.1f}h of designer availability exists "
                          f"but the calendar is CLOSED that day — bookable capacity is "
                          f"being hidden from leads.",
            })

    lead = cal.get("allowBookingAfter")
    lead_unit = cal.get("allowBookingAfterUnit")
    out["min_notice"] = f"{lead} {lead_unit}"
    lead_hours = (lead or 0) * 24 if lead_unit == "days" else (lead or 0)
    if lead_hours > 24:
        findings.append({
            "severity": "AMBER", "brand": brand, "check": "booking_notice",
            "detail": f"minimum scheduling notice is {lead} {lead_unit}. Anything over "
                      f"24h kills same-day and next-morning booking, which is when "
                      f"motivated leads convert.",
        })
    return out


# ------------------------------------------------------------ ServiceMinder --

def check_serviceminder(brand: str, cfg: dict, hl: dict, findings: list,
                        degradations: list) -> dict:
    """ServiceMinder is the system of record for who works when. HighLevel should
    mirror it; drift means the bot books hours nobody agreed to."""
    out = {"checked": False}
    repo = os.path.dirname(os.path.abspath(__file__))
    try:
        r = subprocess.run(["bash", os.path.join(repo, "sm.sh"), cfg["sm_location"],
                            "serviceagents/all", '{"Matches":[]}'],
                           capture_output=True, text=True, timeout=90)
        doc = json.loads(r.stdout)
    except Exception as e:
        degradations.append({"area": f"serviceminder:{brand}",
                             "detail": f"could not read service agents: {e}"})
        return out

    agents = doc.get("Matches", [])
    out["checked"] = True
    sales_hours, roster = {}, []
    for a in agents:
        slots = [t for t in (a.get("TimeSlots") or [])
                 if t.get("ServiceCategoryName") == "Sales"]
        if not slots:
            continue
        total = sum(t.get("Minutes", 0) for t in slots) / 60
        roster.append({"id": a.get("Id"), "name": a.get("Name"),
                       "email": a.get("Email") or None, "sales_hours_per_week": round(total, 1),
                       "end_date": a.get("EndDate") or None})
        for t in slots:
            d = SM_DOW.get(t.get("DayOfWeek"))
            if d is None:
                continue
            sales_hours.setdefault(d, []).append(
                (t["StartMinute"], t["StartMinute"] + t.get("Minutes", 0)))
    out["sales_agents"] = roster
    out["total_sales_hours"] = round(sum(a["sales_hours_per_week"] for a in roster), 1)

    # Retired-looking agents still holding bookable time.
    for a in roster:
        nm = (a["name"] or "").strip().lower()
        if (not a["email"] or nm in {"delete", "deleted", "inactive", "do not use"}) \
                and not a["end_date"] and a["sales_hours_per_week"] > 0:
            findings.append({
                "severity": "AMBER", "brand": brand, "check": "stale_sales_agent",
                "detail": f"ServiceMinder agent '{a['name']}' (id {a['id']}) has no email "
                          f"and no End Date but still carries {a['sales_hours_per_week']}h/wk "
                          f"of assignable Sales availability. Round-robin can still route a "
                          f"consultation to a record nobody is watching.",
            })

    # Drift: HighLevel offering materially more than ServiceMinder staffs.
    if hl.get("checked") and hl.get("staffed_days") is not None:
        hl_hours = 0.0
        for windows in (hl.get("staffed_days") or {}).values():
            for w in windows:
                a, b = w.split("-")
                ah, am = map(int, a.split(":"))
                bh, bm = map(int, b.split(":"))
                hl_hours += (minutes(bh, bm) - minutes(ah, am)) / 60
        out["highlevel_staffed_hours"] = round(hl_hours, 1)
        sm_h = out["total_sales_hours"]
        if sm_h > 0 and hl_hours > sm_h * 1.25:
            findings.append({
                "severity": "AMBER", "brand": brand, "check": "hl_sm_drift",
                "detail": f"HighLevel offers {hl_hours:.1f}h/wk of designer availability but "
                          f"ServiceMinder only staffs {sm_h:.1f}h/wk of Sales time. The bot "
                          f"can book hours nobody has agreed to work.",
            })
        elif sm_h > 0 and hl_hours < sm_h * 0.6:
            findings.append({
                "severity": "AMBER", "brand": brand, "check": "hl_sm_drift",
                "detail": f"ServiceMinder staffs {sm_h:.1f}h/wk of Sales time but HighLevel "
                          f"only offers {hl_hours:.1f}h/wk. Real capacity is not reaching "
                          f"the booking calendar.",
            })
    return out


# ---------------------------------------------------------------- Closebot ---

def check_closebot(brand: str, cfg: dict, findings: list, degradations: list,
                   days: int) -> dict:
    out = {"checked": False}
    key = os.environ.get("CLOSEBOT_API_KEY", "").strip()
    if not key:
        degradations.append({"area": f"closebot:{brand}",
                             "detail": "CLOSEBOT_API_KEY unset — bot checks did NOT run. "
                                       "Unverified, not healthy."})
        return out
    hdr = {"X-CB-KEY": key, "Accept": "application/json"}

    bot, err = curl_json(f"{CB_API}/bot/{cfg['closebot_bot']}", hdr)
    if err or not bot:
        findings.append({"severity": "RED", "brand": brand, "check": "closebot_unreachable",
                         "detail": f"could not read bot {cfg['closebot_bot']}: {err}. "
                                   f"If this is a 401 the API key is revoked and every "
                                   f"Closebot-dependent report is blind."})
        return out
    out["checked"] = True
    published = [v for v in (bot.get("versions") or []) if v.get("published")]
    out["bot_version"] = published[-1].get("version") if published else None
    out["tools_enabled"] = [t.get("type") for t in (bot.get("tools") or [])]

    end = datetime.now(timezone.utc)
    start = end.replace(hour=0, minute=0, second=0, microsecond=0)
    start = start.fromordinal(start.toordinal() - days)
    # Filter by botId client-side — passing it as a query param returns empty.
    url = (f"{CB_API}/botMetric/actions?start={start:%Y-%m-%d}&end={end:%Y-%m-%d}"
           f"&maxCount=5000")
    actions, err = curl_json(url, hdr, timeout=60)
    if err or actions is None:
        degradations.append({"area": f"closebot:{brand}",
                             "detail": f"could not read bot actions: {err}"})
        return out
    mine = [a for a in actions if a.get("botId") == cfg["closebot_bot"]]
    reached = sum(1 for a in mine if a.get("frontendNodeId") == cfg["booking_node"])
    booked = sum(1 for a in mine if a.get("frontendNodeId") == cfg["booked_node"])
    out["window_days"] = days
    out["booking_attempts"] = reached
    out["bookings"] = booked
    out["booking_conversion_pct"] = round(booked / reached * 100, 1) if reached else None

    if reached >= 5 and booked == 0:
        findings.append({
            "severity": "RED", "brand": brand, "check": "booking_conversion",
            "detail": f"{reached} conversations reached the booking step in the last "
                      f"{days} days and NONE booked. The bot is qualifying leads and "
                      f"then failing to close them — check calendar availability first.",
        })
    elif out["booking_conversion_pct"] is not None and reached >= 10 \
            and out["booking_conversion_pct"] < 15:
        findings.append({
            "severity": "AMBER", "brand": brand, "check": "booking_conversion",
            "detail": f"booking-step conversion is {out['booking_conversion_pct']}% "
                      f"({booked}/{reached}) over {days} days. Historic baseline was 9%; "
                      f"anything under 15% means leads reach the booking step and walk.",
        })
    return out


# -------------------------------------------------------------------- main ---

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--brand", choices=sorted(BRANDS), help="limit to one brand")
    ap.add_argument("--days", type=int, default=30, help="conversion window (default 30)")
    ap.add_argument("--out", help="write JSON here instead of stdout")
    ap.add_argument("--verbose", action="store_true", help="human-readable summary to stderr")
    args = ap.parse_args()

    findings: list = []
    degradations: list = []
    brands = {args.brand: BRANDS[args.brand]} if args.brand else BRANDS
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_days": args.days,
        "brands": {},
    }

    for brand, cfg in brands.items():
        hl = check_highlevel(brand, cfg, findings, degradations)
        sm = check_serviceminder(brand, cfg, hl, findings, degradations)
        cb = check_closebot(brand, cfg, findings, degradations, args.days)
        report["brands"][brand] = {"highlevel": hl, "serviceminder": sm, "closebot": cb}

    reds = [f for f in findings if f["severity"] == "RED"]
    ambers = [f for f in findings if f["severity"] == "AMBER"]
    report["findings"] = reds + ambers
    report["degradations"] = degradations
    report["status"] = "RED" if reds else ("AMBER" if (ambers or degradations) else "GREEN")
    report["summary"] = (f"{len(reds)} red, {len(ambers)} amber, "
                         f"{len(degradations)} unverified")

    payload = json.dumps(report, indent=2)
    if args.out:
        with open(args.out, "w") as fh:
            fh.write(payload)
        print(args.out)
    else:
        print(payload)

    if args.verbose:
        print(f"\n=== calendar health: {report['status']} — {report['summary']} ===",
              file=sys.stderr)
        for f in report["findings"]:
            print(f"  [{f['severity']}] {f['brand']} {f['check']}: {f['detail']}",
                  file=sys.stderr)
        for d in degradations:
            print(f"  [UNVERIFIED] {d['area']}: {d['detail']}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
