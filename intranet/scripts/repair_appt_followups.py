#!/usr/bin/env python3
"""
repair_appt_followups.py — rebuild the Appointment Recovery rows correctly.

WHAT WAS WRONG (found 2026-08-29 from a live SM screenshot of appt 51051472,
Garret Starr, cancelled 8/21):

  1. cancel_reason was a VERBATIM COPY of notes. All 95 rows had
     notes == cancel_reason byte-for-byte. Both held the contact's *intake*
     note ("Booking Details: the lead is interested in a full remodel..."),
     so the Appointment Recovery tab displayed pre-sale wishlist text under a
     header saying "why they cancelled" — Garret read as though he cancelled
     because he wants new cabinets.

  2. Both fields were truncated to 300 characters. Garret's real note is 1,325
     chars; the stored copy stops mid-word at "potentially co", cutting the
     90-day timeline, homeowner status, and the "might have waited a couple of
     years without a compelling offer" line — the actual sales hook.

  3. The structured reason was written as the raw id ("reason id 3523"),
     because the API has no cancel-reason lookup endpoint.

WHAT THIS FIXES

  * cancel_reason  <- the real LABEL, from the org download's "Cancel Reason"
                      column. NEVER a copy of notes. Empty when the rep picked
                      no reason, which is honest: blank means "nobody logged
                      one", and that is a rep-hygiene signal worth seeing.
  * notes          <- every contact note, in full, untruncated, newest first.
  * cancelled_at   <- from the download, so recency ranking stops depending on
                      the appointment date.
  * appt_notes     <- appointment-level notes. The Open API cannot see these
                      (verified: appointments/find returns Notes:null,
                      appointments/query has no note field, the download has no
                      Notes column). Populated by the Liquid feed — see
                      serviceminder/liquid/cancellation_notes.liquid. Left ""
                      here so the field exists and the UI can render a
                      placeholder rather than silently omitting the column.

REASON ID -> LABEL was recovered by joining appointments/query (which returns
CancelReasonId) against the download (which returns the text) on appointment
id, over 659 matched cancelled rows. The mapping came out 1:1 with no
ambiguity. It is inlined below because there is no endpoint to fetch it from.

Usage:
    python3 intranet/scripts/repair_appt_followups.py --dry-run
    python3 intranet/scripts/repair_appt_followups.py --apply
"""
import argparse, csv, json, os, subprocess, sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SB = os.path.join(REPO, "mcp-servers", "sb.sh")
SM = os.path.join(REPO, "mcp-servers", "sm.sh")

# Recovered 2026-08-29 by joining appointments/query CancelReasonId against the
# org-download "Cancel Reason" text over 659 cancelled KTU rows. 1:1, no
# collisions. There is NO API endpoint that returns this map — every candidate
# path (cancelreasons, settings/cancelreasons, lookups/cancelreasons,
# appointmentcancelreasons) answers HTTP 200 with an empty body.
REASON_LABELS = {
    3445: "Price",
    3446: "Service desired not offered",
    3447: "Unable to reach customer",
    3448: "Customer went other direction",
    3450: "Unable to complete w/in timeline",
    3523: "Other",
    4279: "Duplicate Booking",
}

# A row whose customer matches any of these is a staff/test booking, not a lost
# customer. Leaving them in inflates the cancellation rate and puts fake names
# on a call sheet.
TEST_MARKERS = ("test", "holding time slot", "steven livingston", "please1")


def sb(sql):
    r = subprocess.run(["bash", SB, sql], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"sb.sh failed: {r.stderr[:400]}")
    return json.loads(r.stdout or "[]")


def sm(location, endpoint, body):
    r = subprocess.run(["bash", SM, location, endpoint, json.dumps(body)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return {}
    try:
        return json.loads(r.stdout or "{}")
    except json.JSONDecodeError:
        return {}


def download_cancellations(location):
    """Pull the org download and index cancelled rows by appointment id.

    The download is the ONLY source that carries the cancel-reason TEXT. It is
    also, contrary to a note previously recorded in the Goldeneye spec, fully
    capable of returning cancelled rows: this call returns 1,900 of them.
    """
    start = sm(location, "download/startdownload", {
        "Kind": "appointments",
        "Appointments": {"Scheduled": True, "Completed": True, "Canceled": True},
    })
    did = start.get("DownloadId")
    if not did:
        raise RuntimeError(f"no DownloadId returned: {json.dumps(start)[:300]}")
    import time
    for _ in range(60):
        st = sm(location, "download/downloadstatus", {"DownloadId": str(did)})
        if st.get("Ready"):
            break
        time.sleep(5)
    else:
        raise RuntimeError(f"download {did} never became ready")

    r = subprocess.run(["bash", SM, location, "download/getdownload",
                        json.dumps({"DownloadId": str(did)})],
                       capture_output=True, text=True)
    out = {}
    for row in csv.DictReader(r.stdout.splitlines()):
        if row.get("Status") != "Canceled":
            continue
        out[str(row["Id"])] = {
            "cancel_reason": (row.get("Cancel Reason") or "").strip(),
            "cancelled_at": (row.get("Canceled At") or "").strip(),
        }
    return out


def contact_notes(location, contact_id):
    """Every note on the contact, newest first, untruncated.

    Returns [] rather than raising when the contact is gone — a merged or
    deleted contact should not abort a 95-row repair.
    """
    d = sm(location, "contacts/locate", {"IdSearch": str(contact_id)})
    for m in d.get("Matches") or []:
        notes = m.get("Notes") or []
        return sorted(notes, key=lambda n: n.get("Id") or 0, reverse=True)
    return []


def render_notes(notes):
    parts = []
    for n in notes:
        title = (n.get("Title") or "Note").strip()
        body = (n.get("Body") or "").strip()
        if body:
            parts.append(f"{title}: {body}")
    return "\n\n".join(parts)


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    rows = sb("SELECT id, fields FROM intranet_records "
              "WHERE section='appt_followups' ORDER BY sort_order")
    print(f"{len(rows)} appt_followups rows")

    dl = {}
    for loc in ("KTU", "BTU"):
        try:
            got = download_cancellations(loc)
            dl.update(got)
            print(f"  {loc}: {len(got)} cancelled rows in download")
        except Exception as exc:
            print(f"  {loc}: download unavailable ({exc}) — "
                  "cancel_reason will fall back to the id map", file=sys.stderr)

    updates, dropped = [], []
    for row in rows:
        f = row["fields"]
        cust = (f.get("customer") or "").strip()
        if any(t in cust.lower() for t in TEST_MARKERS):
            dropped.append((row["id"], cust))
            continue

        loc = (f.get("brand") or "KTU").upper()
        sm_id = str(f.get("sm_id") or "")
        meta = dl.get(sm_id, {})

        reason = meta.get("cancel_reason", "")
        if not reason:
            # Fall back to the id embedded in the old text, now resolvable.
            old = f.get("cancel_reason") or ""
            for rid, label in REASON_LABELS.items():
                if f"reason id {rid}" in old:
                    reason = label
                    break

        notes = render_notes(contact_notes(loc, f.get("contact_id"))) if f.get("contact_id") else ""
        if not notes:
            # Keep whatever was there rather than blanking a row on a failed
            # lookup — a truncated note still beats an empty one.
            notes = f.get("notes") or ""

        nf = dict(f)
        nf["notes"] = notes
        nf["cancel_reason"] = reason
        nf["cancel_reason_id"] = None
        nf["cancelled_at"] = meta.get("cancelled_at", "")
        nf.setdefault("appt_notes", "")
        if nf != f:
            updates.append((row["id"], f, nf))

    grew = [u for u in updates if len(u[2]["notes"]) > len(u[1].get("notes") or "")]
    lookup_failed = [u for u in updates if not u[2]["notes"]]
    reasoned = [u for u in updates if u[2]["cancel_reason"]]
    print(f"\n{len(updates)} rows to update, {len(dropped)} test rows to delete")
    print(f"  notes recovered in full (grew): {len(grew)}")
    print(f"  contact lookup returned nothing: {len(lookup_failed)}")
    print(f"  now carry a real cancel-reason label: {len(reasoned)}"
          f"  (blank = rep logged none)")
    print(f"\n  largest note recoveries:")
    for _i, o, n in sorted(grew, key=lambda u: -len(u[2]["notes"]))[:5]:
        print(f"    {n.get('customer'):32s} {len(o.get('notes') or ''):5d} -> {len(n['notes']):5d} chars")
    for _id, old, new in updates[:5]:
        print(f"\n  {new.get('customer')}")
        print(f"    cancel_reason: {(old.get('cancel_reason') or '')[:70]!r}")
        print(f"                -> {new['cancel_reason']!r}")
        print(f"    notes len: {len(old.get('notes') or '')} -> {len(new['notes'])}")
    if dropped:
        print("\n  dropping: " + ", ".join(c for _, c in dropped))

    if args.dry_run:
        print("\n(dry run — nothing written)")
        return

    for _id, _old, new in updates:
        sb("UPDATE intranet_records SET fields = "
           + sql_lit(json.dumps(new)) + "::jsonb, updated_at = now() "
           "WHERE id = " + sql_lit(str(_id)) + "::uuid")
    for _id, _c in dropped:
        sb("DELETE FROM intranet_records WHERE id = " + sql_lit(str(_id)) + "::uuid")
    print(f"\napplied: {len(updates)} updated, {len(dropped)} deleted")


def sql_lit(s):
    return "'" + s.replace("'", "''") + "'"


if __name__ == "__main__":
    main()
