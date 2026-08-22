#!/usr/bin/env python3
"""
lead-sweep.py — daily ad-campaign response + missed-lead + booking-integrity sweep
for Kitchen Tune-Up and Bath Tune-Up (Bloomfield NJ).

Why this exists
---------------
Goldeneye's daily run needs this analysis to be DETERMINISTIC and cheap. Deriving
it conversationally each morning is slow, burns tokens, and drifts. This script
does the whole sweep and emits one JSON document; Goldeneye reads that document,
writes the intranet rows, and raises the Slack alert.

It answers four questions every morning:
  1. Did anyone respond positively to an ad campaign? (and did we act on it)
  2. Which inbound leads reached out and were never worked?
  3. Are inbound calls actually being answered, broken out by tracking number?
  4. Does every booking that someone believes exists actually exist in
     ServiceMinder? (the field team works off SM — a booking that lives only in
     HighLevel or in a Perceptionist note is an appointment nobody will attend)

Usage
-----
  python3 mcp-servers/lead-sweep.py                # trailing 7 days
  python3 mcp-servers/lead-sweep.py --days 1       # since yesterday
  python3 mcp-servers/lead-sweep.py --out sweep.json

Requires env (Cloud environment secrets):
  GHL_PIT_KTU / GHL_PIT_BTU     HighLevel per-location Private Integration Tokens
  SM_KEY_KTU  / SM_KEY_BTU      ServiceMinder per-location API keys

Transport note: every call shells out to `curl`. The session's egress proxy is
honoured by curl but NOT by python-urllib (urllib returns 403 through it), so do
not "simplify" this to urllib/requests — it will silently return zero rows and
the sweep will report a false all-clear.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

ET = timezone(timedelta(hours=-4))  # America/New_York, EDT
GHL_API = "https://services.leadconnectorhq.com"
SM_API = "https://serviceminder.io/api"

LOCATION_ID = {"KTU": "nHLCxHPidnhV1NFzRtZZ", "BTU": "0uWA8M5BzHrrcJftuaDe"}

# ServiceMinder appointment Status codes
SM_STATUS = {1: "scheduled", 3: "completed", 4: "pending", 5: "cancelled"}

# A call shorter than this never reached a human conversation — it rang out,
# hit voicemail, or the caller hung up. Calibrated on 2026-08 KTU/BTU data:
# every call that converted to a booking ran 237s+; every non-converting call
# except one ran under 26s.
ABANDON_SECONDS = 20

# Message types that represent a real human message (everything else is an
# activity-log entry such as "DnD enabled by customer").
REAL_MSG_TYPES = {
    "TYPE_SMS", "TYPE_EMAIL", "TYPE_CALL", "TYPE_WHATSAPP", "TYPE_INSTAGRAM",
    "TYPE_FACEBOOK", "TYPE_WEBCHAT", "TYPE_LIVE_CHAT", "TYPE_GMB",
    "TYPE_CUSTOM_SMS", "TYPE_CUSTOM_EMAIL",
}

OPT_OUT_EXACT = re.compile(
    r"^(stop|quit|unsubscribe|stopall|end|cancel|remove|unsub|optout|opt\s*out)[.!\s]*$", re.I)
OPT_OUT_PHRASE = re.compile(
    r"(take my (number|name) off|remove me|stop (sending|texting)|unsubscribe"
    r"|please stop|not interested|wrong number|do not (contact|text|call))", re.I)

# Positive / booking intent in a reply to a campaign.
INTENT = re.compile(
    r"\b(schedule|book|booking|appointment|interested|call me|quote|estimate"
    r"|how much|pricing|when can|available|consult|yes please|sounds good)\b", re.I)

# A note that asserts an appointment exists.
NOTE_CLAIMS_BOOKING = re.compile(
    r"(scheduled an appointment|has an appointment|appointment (?:is |was )?"
    r"(?:set|scheduled|booked|confirmed)|booked (?:an|the) appointment"
    r"|appointment for \d|consultation (?:is |was )?(?:set|scheduled|booked)"
    r"|scheduled (?:a|an|the) (?:consult|appointment|estimate))", re.I)

# Complaint / service-recovery language from someone already in our system.
COMPLAINT = re.compile(
    r"(not happy|unhappy|disappointed|frustrat|dropped the ball|still waiting"
    r"|no one (called|showed)|nobody (called|showed)|refund|complaint"
    r"|terrible|awful|unacceptable|poor (job|work|service))", re.I)

# Rows that are test scaffolding, not customers.
TEST_ROW = re.compile(r"(^|\s)(test\b|holding time slot|steven livingston)", re.I)
INTERNAL_EMAIL = re.compile(r"@(kitchentuneup|bathtune-up)\.com$", re.I)

# Automated senders talking to us — our own AI responder, the other brand's
# number caught in a blast, carrier autoreplies, domain spam. These produce
# text that trips the intent regex but nobody is on the other end. Without this
# filter the sweep reports phantom "hot leads" and the alert loses credibility.
BOT_NOISE = re.compile(
    r"(i can'?t assist|unable to start a conversation|i'?m an (ai|assistant)"
    r"|automated (reply|response)|this is an automated|do not reply"
    r"|let me know how i can h|as an ai|i own this domain|looking to sell it"
    r"|reply stop to unsubscribe|you have received a new message from a customer)", re.I)

# Our own outbound / tracking numbers. A blast that texts one of these creates a
# fake "lead" that answers itself.
OWN_NUMBERS = {
    "9735215397", "8883422451", "9735429305", "9733812877", "9733812681",
    "9735665882", "9738335069", "9735218971", "9735592992", "9733105682",
    "9733469262",
}


# --------------------------------------------------------------------------
# transport
# --------------------------------------------------------------------------

def _curl(args: list[str], what: str) -> dict:
    p = subprocess.run(args, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"curl failed ({what}): {p.stderr[:200]}")
    try:
        return json.loads(p.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"non-JSON from {what}: {p.stdout[:200]}")


def ghl(brand: str, path: str, params: str = "") -> dict:
    token = os.environ[f"GHL_PIT_{brand}"]
    url = f"{GHL_API}{path}"
    if params:
        url += ("&" if "?" in path else "?") + params
    return _curl(["curl", "-sS", url,
                  "-H", f"Authorization: Bearer {token}",
                  "-H", "Version: 2021-04-15",
                  "-H", "Accept: application/json",
                  "--max-time", "90"], f"GHL {brand} {path}")


def ghl_v2(brand: str, path: str) -> dict:
    """Contacts API uses the 2021-07-28 version header."""
    token = os.environ[f"GHL_PIT_{brand}"]
    return _curl(["curl", "-sS", f"{GHL_API}{path}",
                  "-H", f"Authorization: Bearer {token}",
                  "-H", "Version: 2021-07-28",
                  "-H", "Accept: application/json",
                  "--max-time", "60"], f"GHL {brand} {path}")


def sm(brand: str, endpoint: str, payload: dict) -> dict:
    body = dict(payload)
    body["ApiKey"] = os.environ[f"SM_KEY_{brand}"]
    return _curl(["curl", "-sS", "-X", "POST", f"{SM_API}/{endpoint}",
                  "-H", "Content-Type: application/json",
                  "-d", json.dumps(body), "--max-time", "90"],
                 f"SM {brand} {endpoint}")


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def digits(phone: str | None) -> str:
    return "".join(c for c in (phone or "") if c.isdigit())[-10:]


def mask(phone: str | None) -> str:
    d = digits(phone)
    return f"…{d[-4:]}" if len(d) >= 4 else "…????"


def short_name(name: str | None, phone: str | None = None) -> str:
    """First name + last initial — callouts must never carry a full identity.

    HighLevel fills unknown callers with the number itself or a placeholder like
    "local client". Rendering those through the initials logic produces junk
    ("(973) 5."), so fall back to a clean masked label instead.
    """
    fallback = f"Unknown caller {mask(phone)}" if phone else "Unknown caller"
    if not name:
        return fallback
    cleaned = name.strip()
    # a phone number, or a HighLevel placeholder, is not a name
    if (len(digits(cleaned)) >= 7
            or re.fullmatch(r"[\d\s()+\-.]+", cleaned)
            or re.fullmatch(r"(local (client|customer|user)|prvt call|unknown"
                            r"|no name|caller)", cleaned, re.I)):
        return fallback
    parts = [p for p in re.split(r"\s+", cleaned) if p]
    if not parts:
        return fallback
    if len(parts) == 1:
        return parts[0].title()
    return f"{parts[0].title()} {parts[-1][0].upper()}."


def is_test_row(name: str | None, email: str | None = None,
                phone: str | None = None) -> bool:
    if name and TEST_ROW.search(name):
        return True
    if email and INTERNAL_EMAIL.search(email):
        return True
    if phone and digits(phone) in OWN_NUMBERS:
        return True
    return False


def dedupe(rows: list[dict], *keys: str) -> list[dict]:
    """Collapse rows that describe the same event.

    The same call can surface on more than one conversation thread, and a booking
    gap can be found by both the calendar audit and the note audit. Emitting it
    twice makes the morning card look padded.
    """
    seen, out = set(), []
    for r in rows:
        k = tuple(r.get(x) for x in keys)
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    return out


def sm_appt_date(appt: dict):
    """SM returns DateTime as 'M/D/YYYY h:mm:ss AM'."""
    raw = (appt.get("DateTime") or "").split(" ")[0]
    try:
        return datetime.strptime(raw, "%m/%d/%Y").date()
    except ValueError:
        return None


def et_stamp(iso_or_ms) -> str:
    if isinstance(iso_or_ms, (int, float)):
        dt = datetime.fromtimestamp(iso_or_ms / 1000, tz=timezone.utc)
    else:
        dt = datetime.fromisoformat(str(iso_or_ms).replace("Z", "+00:00"))
    return dt.astimezone(ET).strftime("%a %m/%d %I:%M%p")


# --------------------------------------------------------------------------
# HighLevel collection
# --------------------------------------------------------------------------

def fetch_conversations(brand: str, since_ms: int) -> list[dict]:
    """Page back through conversations until we pass the window start.

    Pages are keyed by startAfterDate (the sort value). Duplicate timestamps can
    repeat rows across pages, so results are de-duplicated by conversation id.
    """
    seen: dict[str, dict] = {}
    cursor = None
    for _ in range(40):
        params = "limit=100&sortBy=last_message_date&sort=desc"
        if cursor:
            params += f"&startAfterDate={cursor}"
        data = ghl(brand, f"/conversations/search?locationId={LOCATION_ID[brand]}", params)
        convs = data.get("conversations") or []
        if not convs:
            break
        for c in convs:
            seen[c["id"]] = c
        last = convs[-1].get("lastMessageDate") or 0
        if last < since_ms:
            break
        cursor = last
    return [c for c in seen.values() if (c.get("lastMessageDate") or 0) >= since_ms]


def fetch_messages(brand: str, conv_id: str) -> list[dict]:
    data = ghl(brand, f"/conversations/{conv_id}/messages", "limit=40")
    msgs = data.get("messages")
    if isinstance(msgs, dict):
        msgs = msgs.get("messages")
    return sorted(msgs or [], key=lambda m: m.get("dateAdded", ""))


# --------------------------------------------------------------------------
# ServiceMinder lookups (memoised — the same phone recurs across checks)
# --------------------------------------------------------------------------

_sm_cache: dict[tuple[str, str], list[dict]] = {}


def sm_contacts_by_phone(brand: str, phone: str) -> list[dict]:
    key = (brand, phone)
    if key not in _sm_cache:
        r = sm(brand, "contacts/locate", {"PhoneSearch": phone, "Limit": 5})
        _sm_cache[key] = r.get("Matches") or []
    return _sm_cache[key]


def sm_appointments(brand: str, contact_id: int) -> list[dict]:
    r = sm(brand, "appointments/query", {
        "ContactId": contact_id,
        "FromDate": "2020-01-01", "ThroughDate": "2030-12-31", "Take": 100})
    return r.get("Appointments") or []


def has_any_appointment(phone: str) -> list[str]:
    """Look in BOTH brands — kitchen leads land on BTU records and vice versa."""
    found = []
    for loc in ("KTU", "BTU"):
        for match in sm_contacts_by_phone(loc, phone):
            for appt in sm_appointments(loc, match["Id"]):
                found.append(
                    f"{loc} {appt.get('DateTimeFormatted')} "
                    f"[{appt.get('ServiceName')}] "
                    f"{SM_STATUS.get(appt.get('Status'), appt.get('Status'))}")
    return found


# --------------------------------------------------------------------------
# self-test — a silent transport or matcher failure must never read as all-clear
# --------------------------------------------------------------------------

def self_test() -> list[str]:
    """Prove each pipe returns data before we trust a zero from it."""
    problems = []
    for brand in ("KTU", "BTU"):
        try:
            r = ghl(brand, f"/conversations/search?locationId={LOCATION_ID[brand]}", "limit=1")
            if not (r.get("conversations")):
                problems.append(f"HighLevel {brand} returned no conversations at all")
        except Exception as exc:
            problems.append(f"HighLevel {brand} unreachable: {exc}")
        try:
            r = sm(brand, "appointments/query", {
                "FromDate": (datetime.now(ET) - timedelta(days=60)).strftime("%Y-%m-%d"),
                "ThroughDate": (datetime.now(ET) + timedelta(days=60)).strftime("%Y-%m-%d"),
                "Take": 5})
            if r.get("ResultCode", 0) != 0:
                problems.append(f"ServiceMinder {brand} error: {r.get('Message')}")
            elif not r.get("Appointments"):
                problems.append(
                    f"ServiceMinder {brand} returned zero appointments in a ±60d window "
                    "— treat booking checks as UNVERIFIED, not clean")
        except Exception as exc:
            problems.append(f"ServiceMinder {brand} unreachable: {exc}")
    # matcher sanity: the SM date parser must survive SM's own format
    probe = sm_appt_date({"DateTime": "8/26/2026 10:00:00 AM"})
    if probe != datetime(2026, 8, 26).date():
        problems.append("FATAL: ServiceMinder date parser broken — booking audit invalid")
    return problems


# --------------------------------------------------------------------------
# the sweep
# --------------------------------------------------------------------------

def sweep(days: int) -> dict:
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    since_ms = int(since.timestamp() * 1000)
    today = datetime.now(ET).date()

    report = {
        "generated_at": now.isoformat(),
        "window_days": days,
        "window_start_et": since.astimezone(ET).strftime("%Y-%m-%d %I:%M%p"),
        "degradations": self_test(),
        "brands": {},
        "buckets": {
            "positive_ad_responses": [],
            "unanswered_customer": [],
            "missed_call": [],
            "lead_never_worked": [],
            "booking_missing_in_serviceminder": [],
            "service_recovery": [],
            "list_damage": [],
        },
    }

    for brand in ("KTU", "BTU"):
        try:
            convs = fetch_conversations(brand, since_ms)
        except Exception as exc:
            report["degradations"].append(f"HighLevel {brand} conversation pull failed: {exc}")
            continue

        stats = {
            "conversations_touched": len(convs),
            "inbound_conversations": 0,
            "opt_outs": 0,
            "dnd_events": 0,
            "calls_total": 0,
            "calls_answered": 0,
            "calls_abandoned": 0,
            "calls_no_answer": 0,
            "campaign_replies_with_intent": 0,
        }
        by_tracking = defaultdict(lambda: {"total": 0, "answered": 0, "abandoned": 0, "no_answer": 0})

        for conv in convs:
            name, phone = conv.get("contactName"), conv.get("phone")
            if is_test_row(name, conv.get("email"), phone):
                continue
            try:
                msgs = fetch_messages(brand, conv["id"])
            except Exception:
                continue

            inbound_recent = [
                m for m in msgs
                if m.get("direction") == "inbound"
                and m.get("dateAdded", "") >= since.isoformat()
            ]
            if inbound_recent:
                stats["inbound_conversations"] += 1

            # --- opt-out / list damage -------------------------------------
            for m in inbound_recent:
                body = (m.get("body") or "").strip()
                if "DnD enabled" in body:
                    stats["dnd_events"] += 1
                if m.get("messageType") == "TYPE_SMS" and body and (
                        OPT_OUT_EXACT.match(body) or OPT_OUT_PHRASE.search(body)):
                    stats["opt_outs"] += 1

            # --- calls -----------------------------------------------------
            source = None
            for m in msgs:
                if m.get("messageType") != "TYPE_CALL":
                    continue
                if m.get("dateAdded", "") < since.isoformat():
                    continue
                if m.get("direction") != "inbound":
                    continue
                dur = ((m.get("meta") or {}).get("call") or {}).get("duration")
                dur = dur if isinstance(dur, (int, float)) else 0
                status = m.get("status")
                stats["calls_total"] += 1
                if source is None:
                    try:
                        source = (ghl_v2(brand, f"/contacts/{conv['contactId']}")
                                  .get("contact") or {}).get("source")
                    except Exception:
                        source = None
                track = source if (source or "").startswith("+") else "(direct / untracked)"
                by_tracking[track]["total"] += 1

                if status == "no-answer":
                    kind = "no_answer"
                    stats["calls_no_answer"] += 1
                elif dur >= ABANDON_SECONDS:
                    kind = "answered"
                    stats["calls_answered"] += 1
                else:
                    kind = "abandoned"
                    stats["calls_abandoned"] += 1
                by_tracking[track][kind] += 1

                if kind == "answered":
                    continue  # a real conversation happened; booking check below covers it

                booked = has_any_appointment(digits(phone)) if digits(phone) else []
                if booked:
                    continue
                report["buckets"]["missed_call"].append({
                    "brand": brand,
                    "who": short_name(name, phone),
                    "phone_masked": mask(phone),
                    "when": et_stamp(m["dateAdded"]),
                    "detail": ("rang out, never answered" if kind == "no_answer"
                               else f"caller hung up after {int(dur)}s"),
                    "tracking_number": track,
                    "action": "Call back today — no appointment exists for this number.",
                })

            # --- inbound messages: intent, complaints, unanswered ----------
            real_inbound = [m for m in inbound_recent if m.get("messageType") in REAL_MSG_TYPES]
            for m in real_inbound:
                body = (m.get("body") or "").strip()
                if not body or OPT_OUT_EXACT.match(body) or BOT_NOISE.search(body):
                    continue
                if INTENT.search(body) and not OPT_OUT_PHRASE.search(body):
                    stats["campaign_replies_with_intent"] += 1
                    booked = has_any_appointment(digits(phone)) if digits(phone) else []
                    report["buckets"]["positive_ad_responses"].append({
                        "brand": brand,
                        "who": short_name(name, phone),
                        "phone_masked": mask(phone),
                        "when": et_stamp(m["dateAdded"]),
                        "said": body[:200],
                        "already_booked": bool(booked),
                        "action": ("Booked — no action." if booked
                                   else "Positive reply with NO booking. Call today."),
                    })
                if COMPLAINT.search(body):
                    report["buckets"]["service_recovery"].append({
                        "brand": brand,
                        "who": short_name(name, phone),
                        "phone_masked": mask(phone),
                        "when": et_stamp(m["dateAdded"]),
                        "said": body[:200],
                        "action": "Service recovery — call before this becomes a review.",
                    })

            # --- last word was theirs and nobody replied --------------------
            substantive = [m for m in msgs if m.get("messageType") in REAL_MSG_TYPES]
            if substantive and substantive[-1].get("direction") == "inbound":
                last = substantive[-1]
                body = (last.get("body") or "").strip()
                if (last.get("dateAdded", "") >= since.isoformat()
                        and body and not OPT_OUT_EXACT.match(body)
                        and not OPT_OUT_PHRASE.search(body)
                        and not BOT_NOISE.search(body)
                        and last.get("messageType") != "TYPE_CALL"):
                    waited = now - datetime.fromisoformat(
                        last["dateAdded"].replace("Z", "+00:00"))
                    report["buckets"]["unanswered_customer"].append({
                        "brand": brand,
                        "who": short_name(name, phone),
                        "phone_masked": mask(phone),
                        "when": et_stamp(last["dateAdded"]),
                        "hours_waiting": round(waited.total_seconds() / 3600, 1),
                        "said": body[:200],
                        "unread": conv.get("unreadCount", 0),
                        "action": "Reply — customer spoke last and nobody answered.",
                    })

        stats["call_answer_rate"] = (
            round(100 * stats["calls_answered"] / stats["calls_total"])
            if stats["calls_total"] else None)
        stats["by_tracking_number"] = {
            k: dict(v, answer_rate=(round(100 * v["answered"] / v["total"]) if v["total"] else None))
            for k, v in by_tracking.items()}
        report["brands"][brand] = stats

        # --- booking integrity: HighLevel calendar vs ServiceMinder ---------
        report["buckets"]["booking_missing_in_serviceminder"] += audit_calendar(brand, today)
        # --- booking integrity: a note claims a booking that does not exist -
        report["buckets"]["booking_missing_in_serviceminder"] += audit_notes(brand, days)

    # --- collapse duplicates ------------------------------------------------
    # The same call can appear on more than one thread, and one booking gap can
    # be caught by both the calendar audit and the note audit.
    b = report["buckets"]
    b["missed_call"] = dedupe(b["missed_call"], "brand", "phone_masked", "when")
    b["booking_missing_in_serviceminder"] = dedupe(
        b["booking_missing_in_serviceminder"], "phone_masked")
    b["positive_ad_responses"] = dedupe(b["positive_ad_responses"], "phone_masked", "when")
    b["unanswered_customer"] = dedupe(b["unanswered_customer"], "phone_masked", "when")
    b["service_recovery"] = dedupe(b["service_recovery"], "phone_masked", "when")

    # --- list damage rollup ------------------------------------------------
    for brand, s in report["brands"].items():
        if s["opt_outs"] or s["dnd_events"]:
            report["buckets"]["list_damage"].append({
                "brand": brand,
                "opt_outs": s["opt_outs"],
                "dnd_events": s["dnd_events"],
                "conversations_touched": s["conversations_touched"],
                "action": ("Review outbound campaign volume — opt-outs are "
                           "burning reusable list."),
            })

    report["rag"] = grade(report)
    return report


def audit_calendar(brand: str, today) -> list[dict]:
    """Every confirmed HighLevel calendar event must exist in ServiceMinder."""
    out = []
    try:
        cals = ghl(brand, f"/calendars/?locationId={LOCATION_ID[brand]}").get("calendars") or []
    except Exception:
        return out
    start = int(datetime.combine(today, datetime.min.time()).timestamp() * 1000)
    end = int((datetime.combine(today, datetime.min.time())
               + timedelta(days=60)).timestamp() * 1000)
    for cal in cals:
        if not cal.get("isActive"):
            continue
        try:
            events = ghl(brand, "/calendars/events",
                         f"locationId={LOCATION_ID[brand]}&calendarId={cal['id']}"
                         f"&startTime={start}&endTime={end}").get("events") or []
        except Exception:
            continue
        for ev in events:
            if ev.get("appointmentStatus") not in ("confirmed", "booked"):
                continue
            try:
                contact = (ghl_v2(brand, f"/contacts/{ev['contactId']}").get("contact") or {})
            except Exception:
                continue
            name, phone = contact.get("contactName"), digits(contact.get("phone"))
            if is_test_row(name, contact.get("email"), phone) or not phone:
                continue
            ev_date = datetime.strptime(ev["startTime"][:10], "%Y-%m-%d").date()
            matched = False
            for loc in ("KTU", "BTU"):
                for m in sm_contacts_by_phone(loc, phone):
                    for appt in sm_appointments(loc, m["Id"]):
                        if sm_appt_date(appt) == ev_date:
                            matched = True
            if not matched:
                out.append({
                    "brand": brand,
                    "who": short_name(name, phone),
                    "phone_masked": mask(phone),
                    "expected": f"{ev_date} {ev['startTime'][11:16]} ({cal.get('name')})",
                    "evidence": "confirmed on the HighLevel calendar",
                    "detail": "No ServiceMinder appointment on that date — "
                              "nobody is scheduled to attend.",
                    "action": "Create the ServiceMinder appointment or cancel the "
                              "HighLevel event. Check for a slot conflict first.",
                })
    return out


def audit_notes(brand: str, days: int) -> list[dict]:
    """A Perceptionist/booking note asserting an appointment that does not exist."""
    out = []
    created_from = (datetime.now(ET) - timedelta(days=max(days, 45))).strftime("%Y-%m-%d")
    contacts, skip = [], 0
    while True:
        try:
            r = sm(brand, "contacts/locate", {
                "CreatedFrom": created_from,
                "CreatedThrough": (datetime.now(ET) + timedelta(days=1)).strftime("%Y-%m-%d"),
                "Skip": skip, "Limit": 100})
        except Exception:
            break
        batch = r.get("Matches") or []
        contacts += batch
        if len(batch) < 100 or skip > 1500:
            break
        skip += 100

    for c in contacts:
        if is_test_row(c.get("Name"), c.get("Email"), c.get("Phone")):
            continue
        notes = c.get("Notes") or []
        blob = " || ".join(f"{n.get('Title')}: {n.get('Body')}" for n in notes)
        if not NOTE_CLAIMS_BOOKING.search(blob):
            continue
        phone = digits(c.get("Phone"))
        # Look in both brands — a kitchen booking often sits on a BTU record.
        if phone and has_any_appointment(phone):
            continue
        if not phone and sm_appointments(brand, c["Id"]):
            continue
        claim = next((f"{n.get('Title')}: {(n.get('Body') or '')[:220]}"
                      for n in notes if NOTE_CLAIMS_BOOKING.search(
                          f"{n.get('Title')}: {n.get('Body')}")), "")
        out.append({
            "brand": brand,
            "who": short_name(c.get("Name"), c.get("Phone")),
            "phone_masked": mask(c.get("Phone")),
            "expected": "per call note (no calendar entry either)",
            "evidence": claim,
            "detail": "The customer believes they have an appointment. "
                      "Nothing exists in ServiceMinder or on the calendar.",
            "action": "Call to confirm a real date, then book it in ServiceMinder.",
        })
    return out


def grade(report: dict) -> dict:
    """Red / amber / green, with the reason stated."""
    b = report["buckets"]
    red_reasons, amber_reasons = [], []

    missing = b["booking_missing_in_serviceminder"]
    if missing:
        red_reasons.append(f"{len(missing)} booking(s) missing from ServiceMinder")

    unbooked_positive = [r for r in b["positive_ad_responses"] if not r["already_booked"]]
    if unbooked_positive:
        red_reasons.append(f"{len(unbooked_positive)} positive ad reply with no booking")

    if b["service_recovery"]:
        red_reasons.append(f"{len(b['service_recovery'])} complaint(s) open")

    stale = [r for r in b["unanswered_customer"] if r["hours_waiting"] >= 24]
    if stale:
        red_reasons.append(f"{len(stale)} customer(s) waiting >24h")

    no_answer = [r for r in b["missed_call"] if "rang out" in r["detail"]]
    if no_answer:
        red_reasons.append(f"{len(no_answer)} call(s) rang out unanswered")

    if b["missed_call"] and not no_answer:
        amber_reasons.append(f"{len(b['missed_call'])} abandoned call(s) never returned")
    if [r for r in b["unanswered_customer"] if r["hours_waiting"] < 24]:
        amber_reasons.append("customers awaiting a reply inside 24h")

    for brand, s in report["brands"].items():
        rate = s.get("call_answer_rate")
        if rate is not None and s["calls_total"] >= 3 and rate < 50:
            red_reasons.append(f"{brand} answered only {rate}% of inbound calls")
        if s["opt_outs"] >= 25:
            amber_reasons.append(f"{brand} took {s['opt_outs']} opt-outs")

    if report["degradations"]:
        amber_reasons.append(f"{len(report['degradations'])} data source(s) degraded")

    if red_reasons:
        return {"status": "red", "symbol": "🔴", "reasons": red_reasons + amber_reasons}
    if amber_reasons:
        return {"status": "amber", "symbol": "🟠", "reasons": amber_reasons}
    return {"status": "green", "symbol": "🟢",
            "reasons": ["No customer waiting, no missed call, no booking gap."]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--out")
    args = ap.parse_args()

    missing = [v for v in ("GHL_PIT_KTU", "GHL_PIT_BTU", "SM_KEY_KTU", "SM_KEY_BTU")
               if not os.environ.get(v)]
    if missing:
        print(json.dumps({"error": f"missing env: {', '.join(missing)}"}), file=sys.stderr)
        return 1

    report = sweep(args.days)
    text = json.dumps(report, indent=1)
    if args.out:
        with open(args.out, "w") as fh:
            fh.write(text)
        counts = {k: len(v) for k, v in report["buckets"].items()}
        print(f"{report['rag']['symbol']} {report['rag']['status'].upper()} -> {args.out}")
        print(json.dumps(counts, indent=1))
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
