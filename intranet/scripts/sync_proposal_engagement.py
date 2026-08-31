#!/usr/bin/env python3
"""
sync_proposal_engagement.py — add ServiceMinder engagement + notes to the
intranet's Proposals / Proposal Recovery rows.

WHAT THIS ADDS AND WHY
----------------------
The Proposals tab knew a quote's amount, age and outcome, but not whether the
customer ever OPENED it. That is the difference between two completely
different follow-up calls:

    never viewed  ->  "did it actually reach you?"   (a delivery problem)
    viewed, quiet ->  "what's holding it up?"        (a decision problem)

Chasing the second script on the first customer wastes the call. So each row
gains `last_viewed`, `sent`, `last_printed` and `accepted_by`, plus
`customer_notes` — the scope text the rep wrote on the quote.

WHERE EACH FIELD COMES FROM (they are NOT in the same place)
------------------------------------------------------------
  * Engagement (`Last Viewed`, `Sent`, `Last Printed`, `Accepted By`) lives ONLY
    in the org-level `proposals` DOWNLOAD, which returns CSV, not JSON. No
    query endpoint exposes view tracking — `proposal/query` and
    `proposal/details` both return the same 39-field object with no view data.
  * Notes live ONLY on `proposal/details`, one call per proposal.

**`proposal/details` takes `Id`, NOT `ProposalId`.** Passing `ProposalId`
returns `{"ResultCode":1,"Message":"Proposal not found","Id":0}` — a clean
"no such proposal" for a proposal that exists. An earlier sweep read that as
"proposal notes are always empty, they need the Liquid feed"; they are not.
With the right key, `CustomerNotes` comes back populated on 224 of 400 KTU
proposals sampled (56%), up to 1,164 chars.

`ProposalNotes` is a different field — an ARRAY of internal notes, empty on all
30 rows checked. That one really does need the Liquid feed. Do not conflate
them: `CustomerNotes` is a string and is the one worth reading.

Merges are shallow jsonb patches (`fields || patch`), so a row's `team_note`,
`entity_notes` and anything else the team owns survives untouched.

Usage:
  python3 intranet/scripts/sync_proposal_engagement.py            # dry run
  python3 intranet/scripts/sync_proposal_engagement.py --apply
  python3 intranet/scripts/sync_proposal_engagement.py --apply --days 365

Requires: SUPABASE_SERVICE_ROLE_KEY, SM_KEY_KTU / SM_KEY_BTU, SM_USERID_*.
"""
import csv, io, json, os, subprocess, sys, time
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SB = os.path.join(ROOT, "mcp-servers", "sb.sh")
SM = os.path.join(ROOT, "mcp-servers", "sm.sh")
APPLY = "--apply" in sys.argv
DAYS = 180
if "--days" in sys.argv:
    DAYS = int(sys.argv[sys.argv.index("--days") + 1])
BRANDS = ["KTU", "BTU"]


def sb(sql):
    """Run SQL via sb.sh, raising on a PostgREST error object.

    PostgREST reports failure as a dict, not a list. Iterating it yields KEYS,
    which surfaces as an unrelated-looking error several frames later.
    """
    out = subprocess.run(["bash", SB], input=sql, capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f"sb.sh failed: {out.stderr.strip()}")
    data = json.loads(out.stdout)
    if isinstance(data, dict) and "message" in data and "ok" not in data:
        raise RuntimeError(f"SQL error: {data['message']} :: {sql[:120]}")
    return data


def sm(brand, endpoint, body):
    out = subprocess.run(
        ["bash", SM, brand, endpoint, json.dumps(body)], capture_output=True, text=True
    )
    return out.stdout


def sm_json(brand, endpoint, body):
    raw = sm(brand, endpoint, body)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"error": raw[:200]}


def q(s):
    if s is None:
        return "null"
    return "'" + str(s).replace("'", "''") + "'"


def iso(us_date):
    """'6/30/2026' or '6/1/2026 9:11 AM' -> '2026-06-30'. '' -> None.

    The download emits US M/D/YYYY with an optional time. Everything else in
    intranet_records is ISO, and the UI sorts these as strings, so a mixed
    format would sort wrong rather than merely look wrong.
    """
    if not us_date or not us_date.strip():
        return None
    part = us_date.strip().split(" ")[0]
    try:
        m, d, y = (int(x) for x in part.split("/"))
        return f"{y:04d}-{m:02d}-{d:02d}"
    except (ValueError, TypeError):
        return None


def download_proposals(brand, date_from, date_through):
    """Start / poll / fetch the proposals download. Returns {Id: csv row dict}.

    This endpoint returns CSV text, not JSON — unlike every other call in this
    script — so it is parsed with csv.DictReader rather than json.loads.
    """
    started = sm_json(
        brand,
        "download/startdownload",
        {
            "Kind": "proposals",
            "DateFrom": date_from,
            "DateThrough": date_through,
            "Proposals": {"IncludeBundled": True, "IncludeCustomFields": True},
        },
    )
    did = started.get("DownloadId")
    if not did:
        raise RuntimeError(f"{brand}: no DownloadId — {json.dumps(started)[:200]}")

    for _ in range(60):
        if sm_json(brand, "download/downloadstatus", {"DownloadId": did}).get("Ready"):
            break
        time.sleep(3)
    else:
        raise RuntimeError(f"{brand}: download {did} never became ready")

    text = sm(brand, "download/getdownload", {"DownloadId": did})
    rows = list(csv.DictReader(io.StringIO(text)))
    if len(rows) >= 25000:
        # A truncated download is indistinguishable from a complete one; say so
        # rather than silently syncing a partial window.
        print(f"  !! {brand}: {len(rows)} rows — at/over the 25,000 cap, "
              f"page with RowId or narrow --days")
    return {r["Id"]: r for r in rows if r.get("Id")}


def main():
    through = date.today()
    since = through - timedelta(days=DAYS)
    print(f"window {since} .. {through}"
          f"{'' if APPLY else '   [DRY RUN — no writes]'}\n")

    rows = sb("""
        select id::text, brand, fields->>'sm_id' as sm_id,
               fields->>'customer' as customer,
               fields->>'last_viewed' as last_viewed,
               fields->>'customer_notes' as customer_notes
        from intranet_records where section='proposals'
    """)
    by_brand = {}
    for r in rows:
        by_brand.setdefault(r["brand"], []).append(r)

    total = {"engagement": 0, "notes": 0, "unmatched": 0, "viewed": 0, "never": 0}

    for brand in BRANDS:
        mine = by_brand.get(brand, [])
        if not mine:
            print(f"{brand}: no proposal rows, skipping")
            continue
        print(f"{brand}: {len(mine)} rows")
        dl = download_proposals(brand, since.isoformat(), through.isoformat())
        print(f"  download: {len(dl)} proposals in window")

        for r in mine:
            patch = {}
            csv_row = dl.get(r["sm_id"])
            if csv_row:
                lv = iso(csv_row.get("Last Viewed"))
                patch.update({
                    "last_viewed": lv or "",
                    "sent": iso(csv_row.get("Sent")) or "",
                    "last_printed": iso(csv_row.get("Last Printed")) or "",
                    "accepted_by": (csv_row.get("Accepted By") or "").strip(),
                    # Refreshed every run — a quote can be declined after the
                    # row was first written, and the reason lands here later.
                    "status": (csv_row.get("Status") or "").strip(),
                    "decline_reason": (csv_row.get("Decline Reason") or "").strip(),
                    "decline_date": iso(csv_row.get("Decline Date")) or "",
                })
                total["engagement"] += 1
                total["viewed" if lv else "never"] += 1
            else:
                total["unmatched"] += 1

            # One call per row. Skipped when we already have the notes, so a
            # re-run costs almost nothing.
            if not (r.get("customer_notes") or "").strip():
                det = sm_json(brand, "proposal/details", {"Id": int(r["sm_id"])})
                if det.get("ResultCode") == 0:
                    cn = (det.get("CustomerNotes") or "").strip()
                    if cn:
                        patch["customer_notes"] = cn
                        total["notes"] += 1

            if not patch:
                continue
            if APPLY:
                sb("update intranet_records set fields = fields || "
                   f"{q(json.dumps(patch))}::jsonb, updated_at=now() "
                   f"where id={q(r['id'])}")
            else:
                keys = ",".join(sorted(patch))
                print(f"    would patch {r['customer'][:28]:<28} {keys}")

    print(f"\nengagement merged: {total['engagement']}"
          f"   (viewed {total['viewed']} · never viewed {total['never']})")
    print(f"notes fetched:     {total['notes']}")
    print(f"not in download:   {total['unmatched']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
