#!/usr/bin/env python3
"""Rebuild the intranet 'appt_followups' section: cancelled KTU/BTU appointments
in the last 90 days, with a merged cancellation note (contact notes /
appointment notes / CancelReasonId — see CLAUDE.md "ServiceMinder notes —
where they actually live") and a HighLevel-derived lead_source label.

All ServiceMinder + HighLevel access goes through sm.sh / ghl.sh (curl) —
never the mcp__ tools — so this is safe to run from a non-interactive
scheduled Routine.

Run: python3 mcp-servers/appt-followups-sync.py
"""
import datetime
import json
import re
import subprocess
import sys
import time
from collections import Counter

TODAY = datetime.date.today()
CUTOFF = TODAY - datetime.timedelta(days=90)
TSTR = TODAY.isoformat()
BRANDS = ["KTU", "BTU"]


def sm(brand, endpoint, body, timeout=120):
    r = subprocess.run(
        ["bash", "mcp-servers/sm.sh", brand, endpoint, json.dumps(body)],
        capture_output=True, text=True, timeout=timeout,
    )
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"error": "unparseable", "raw": r.stdout[:300], "stderr": r.stderr[:300]}


def ghl(brand, tool, args, timeout=60):
    r = subprocess.run(
        ["bash", "mcp-servers/ghl.sh", brand, tool, json.dumps(args)],
        capture_output=True, text=True, timeout=timeout,
    )
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"error": "unparseable", "raw": r.stdout[:300], "stderr": r.stderr[:300]}


def sb(sql):
    r = subprocess.run(["bash", "mcp-servers/sb.sh", sql], capture_output=True, text=True, timeout=120)
    return r.stdout, r.stderr, r.returncode


def q(s):
    return "'" + str(s).replace("'", "''") + "'"


def digits(s):
    return re.sub(r"\D", "", s or "")


def fetch_cancelled_appointments(brand):
    appts = []
    skip = 0
    take = 200
    while True:
        resp = sm(brand, "appointments/query", {
            "FromDate": CUTOFF.isoformat(),
            "ThroughDate": TODAY.isoformat(),
            "IncludeContact": False,
            "Skip": skip,
            "Take": take,
        })
        if "error" in resp:
            print(f"[{brand}] appointments/query failed at skip={skip}: {resp}", file=sys.stderr)
            break
        batch = resp.get("Appointments") or []
        appts.extend(batch)
        count = resp.get("Count", 0)
        skip += take
        if skip >= count or not batch:
            break
    cancelled = [a for a in appts if a.get("Status") == 4]
    print(f"[{brand}] {len(appts)} appointments in window, {len(cancelled)} cancelled (Status=4)")
    return cancelled


def get_contact_notes(brand, contact_id):
    resp = sm(brand, "contacts/locate", {"IdSearch": contact_id})
    if "error" in resp:
        return None, [], resp
    matches = resp.get("Matches") or []
    if not matches:
        return None, [], resp
    contact = matches[0]
    notes = contact.get("Notes") or []
    return contact, notes, resp


def best_note_body(notes):
    """Pick the richest non-empty Body, tie-broken by highest Id."""
    candidates = [n for n in notes if (n.get("Body") or "").strip()]
    if not candidates:
        return None
    candidates.sort(key=lambda n: (len(n.get("Body", "").strip()), n.get("Id", 0)))
    return candidates[-1]["Body"].strip()


def derive_label(attribution, top_source):
    def norm(s):
        return (s or "").strip().lower()

    if attribution:
        medium = norm(attribution.get("medium"))
        session = norm(attribution.get("sessionSource"))
        ad_source = norm(attribution.get("adSource"))
        utm_source = norm(attribution.get("utmSource"))
        combined = " ".join([medium, session, ad_source, utm_source])
        if "instagram" in combined:
            return "Instagram"
        if "facebook" in combined:
            return "Facebook"
        if "local service" in combined or " lsa" in f" {combined}":
            return "Google LSA"
        if "google" in combined:
            return "Google Ads"
        if "whatsapp" in combined:
            return "WhatsApp"
        if session in ("organic", "direct traffic", "direct"):
            return "Organic/Direct"
        if "referral" in combined:
            return "Referral"
        if "live chat" in combined or session == "chat":
            return "Live Chat"
        if "call" in combined or "phone" in combined:
            return "Inbound call"
        if "workflow" in combined:
            return "Workflow"
        if session:
            return attribution.get("sessionSource").strip()

    if top_source:
        s = norm(top_source)
        if "instagram" in s:
            return "Instagram"
        if "facebook" in s:
            return "Facebook"
        if "google" in s:
            return "Google Ads"
        if "organic" in s or "direct" in s:
            return "Organic/Direct"
        if "referral" in s:
            return "Referral"
        if "tv" in s:
            return "TV"
        if "signage" in s or "local" in s:
            return "Signage & Local"
        return top_source.strip()

    return None


def lookup_ghl(brand, phone, email):
    """Returns (label_or_None, reason_string) — reason explains a blank."""
    ph = digits(phone)
    contact_id = None
    if ph:
        resp = ghl(brand, "contacts_get-contacts", {"query_query": ph, "query_limit": 5})
        contacts = ((resp.get("data") or {}).get("contacts")) or []
        if contacts:
            contact_id = contacts[0].get("id")
    if not contact_id and email:
        resp = ghl(brand, "contacts_get-contacts", {"query_query": email, "query_limit": 5})
        contacts = ((resp.get("data") or {}).get("contacts")) or []
        if contacts:
            contact_id = contacts[0].get("id")

    if not contact_id:
        return None, "no HighLevel contact found (phone/email search returned nothing)"

    detail = ghl(brand, "contacts_get-contact", {"path_contactId": contact_id})
    c = ((detail.get("data") or {}).get("contact")) or {}
    attribution = c.get("attributionSource") or c.get("lastAttributionSource")
    top_source = c.get("source")

    label = derive_label(attribution, top_source)
    if label:
        return label, None

    # Fallback: opportunity source
    opp_resp = ghl(brand, "opportunities_search-opportunity", {"query_contact_id": contact_id, "query_limit": 5})
    opps = ((opp_resp.get("data") or {}).get("opportunities")) or []
    for opp in opps:
        opp_source = opp.get("source")
        label = derive_label(None, opp_source)
        if label:
            return label, None

    return None, "HighLevel contact found, full detail pulled, but no .source/attributionSource/opportunity source data present"


def main():
    all_rows = []
    stats_by_brand = {}

    for brand in BRANDS:
        cancelled = fetch_cancelled_appointments(brand)
        note_source_counts = Counter()
        lead_source_found = 0
        lead_source_blank_no_contact = 0
        lead_source_blank_no_attribution = 0
        rows = []

        for idx, appt in enumerate(cancelled):
            appt_id = appt.get("AppointmentId")
            contact_id = appt.get("ContactId")
            top_reason_id = appt.get("CancelReasonId")

            contact, contact_notes, _ = get_contact_notes(brand, contact_id) if contact_id else (None, [], None)
            contact_body = best_note_body(contact_notes)

            fa = sm(brand, "appointments/find", {"AppointmentId": appt_id})
            appt_notes_raw = None
            slot_reason_id = None
            if "error" not in fa:
                appt_notes_raw = (fa.get("Notes") or fa.get("UpdateNote") or "").strip() or None
                slots = fa.get("Slots") or []
                if slots:
                    slot_reason_id = slots[0].get("CancelReasonId")

            reason_id = top_reason_id or slot_reason_id or None

            if contact_body:
                primary = contact_body
                note_source_counts["contact_notes"] += 1
            elif appt_notes_raw:
                primary = appt_notes_raw
                note_source_counts["appointment_notes"] += 1
            elif reason_id:
                primary = None
                note_source_counts["reason_id_only"] += 1
            else:
                primary = None
                note_source_counts["nothing"] += 1

            if primary:
                note_text = primary[:300]
                if reason_id:
                    note_text += f" (reason id {reason_id})"
            elif reason_id:
                note_text = f"No written note on file (reason id {reason_id})"
            else:
                note_text = "Customer cancelled"

            phone = (contact or {}).get("Phone") or ""
            email = (contact or {}).get("Email") or ""
            customer = (contact or {}).get("Name") or ""
            address = ", ".join(x for x in [
                (contact or {}).get("Address1", ""),
                ", ".join(y for y in [(contact or {}).get("City", ""),
                                       f"{(contact or {}).get('State','')} {(contact or {}).get('Zip','')}".strip()] if y),
            ] if x)

            lead_source, blank_reason = lookup_ghl(brand, phone, email) if (phone or email) else (
                None, "no phone or email on the ServiceMinder contact to search HighLevel with")
            if lead_source:
                lead_source_found += 1
            else:
                if "no HighLevel contact found" in (blank_reason or ""):
                    lead_source_blank_no_contact += 1
                else:
                    lead_source_blank_no_attribution += 1

            fields = {
                "sm_id": appt_id,
                "contact_id": contact_id,
                "customer": customer,
                "phone": phone,
                "address": address,
                "service": appt.get("ServiceName") or "",
                "owner": appt.get("ServiceAgentName") or "",
                "agent": appt.get("ServiceAgentName") or "",
                "appt_date": appt.get("DateTime") or "",
                "status": "cancelled",
                "brand": brand,
                "cancel_reason": note_text,
                "notes": note_text,
                "source": "appointments/query + contacts/locate + appointments/find + HighLevel (source/attributionSource/opportunities)",
                "scan_date": TSTR,
            }
            if lead_source:
                fields["lead_source"] = lead_source

            rows.append(fields)

            if (idx + 1) % 10 == 0:
                print(f"[{brand}] enriched {idx + 1}/{len(cancelled)}")

        stats_by_brand[brand] = {
            "cancelled": len(cancelled),
            "note_sources": dict(note_source_counts),
            "lead_source_found": lead_source_found,
            "lead_source_blank_no_contact": lead_source_blank_no_contact,
            "lead_source_blank_no_attribution": lead_source_blank_no_attribution,
        }
        all_rows.extend(rows)

    print(json.dumps(stats_by_brand, indent=1))

    if not all_rows:
        print("No cancelled appointments found at all across both brands — aborting without writing", file=sys.stderr)
        sys.exit(1)

    BATCH = 100
    for i in range(0, len(all_rows), BATCH):
        chunk = all_rows[i:i + BATCH]
        vals = []
        for idx, f in enumerate(chunk):
            vals.append(f"('appt_followups',{q(f['brand'])},{i + idx},{q(json.dumps(f))}::jsonb)")
        sql = "INSERT INTO intranet_records (section, brand, sort_order, fields) VALUES " + ", ".join(vals) + ";"
        out, err, rc = sb(sql)
        if rc != 0 or '"error"' in out:
            print(f"INSERT batch {i} failed: rc={rc} out={out[:300]} err={err[:300]}", file=sys.stderr)
            sys.exit(1)

    out, err, rc = sb(f"DELETE FROM intranet_records WHERE section='appt_followups' AND fields->>'scan_date' <> '{TSTR}';")
    print(f"Pruned stale rows: {out[:200]}")


if __name__ == "__main__":
    main()
