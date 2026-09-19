#!/usr/bin/env python3
"""Rebuild the intranet 'proposals' section from the ServiceMinder bulk
proposals export (KTU + BTU), last 90 days, filtered/parsed in code.

query_proposals only ever returns OPEN records (server-side status filter
that can't be turned off), so it silently misses the whole Expired/Declined/
Invoiced pipeline. The bulk download is the only path that returns everything
(~2,225 KTU rows / ~182 BTU rows). See CLAUDE.md-adjacent Routine prompt for
the full trap list (Status sub-settings are silently dropped server-side,
DateFrom/DateThrough are not honoured on this endpoint, Created/Sent are
unparseable — filter on 'Date' in code instead).

Run: python3 mcp-servers/proposals-sync.py
All ServiceMinder access goes through sm.sh (curl) — never the mcp__ tools —
so this is safe to run from a non-interactive scheduled Routine.
"""
import csv
import datetime
import io
import json
import subprocess
import sys
import time

TODAY = datetime.date.today()
CUTOFF = TODAY - datetime.timedelta(days=90)
TSTR = TODAY.isoformat()

BRANDS = ["KTU", "BTU"]


def sm(brand, endpoint, body):
    r = subprocess.run(
        ["bash", "mcp-servers/sm.sh", brand, endpoint, json.dumps(body)],
        capture_output=True, text=True, timeout=300,
    )
    return r.stdout


def sb(sql):
    r = subprocess.run(["bash", "mcp-servers/sb.sh", sql], capture_output=True, text=True, timeout=120)
    return r.stdout, r.stderr, r.returncode


def parse_date(s):
    s = (s or "").strip()
    if not s:
        return None
    try:
        m, d, y = s.split("/")
        return datetime.date(int(y), int(m), int(d))
    except Exception:
        return None


def q(s):
    return "'" + str(s).replace("'", "''") + "'"


def fetch_proposals_csv(brand):
    out = sm(brand, "download/startdownload", {"Kind": "proposals", "UserId": 10017})
    try:
        meta = json.loads(out)
    except json.JSONDecodeError:
        print(f"[{brand}] start_download did not return JSON: {out[:300]}", file=sys.stderr)
        return None
    if meta.get("ResultCode") not in (0, None) or not meta.get("DownloadId"):
        print(f"[{brand}] start_download failed: {meta}", file=sys.stderr)
        return None
    dl_id = meta["DownloadId"]

    ready = False
    for attempt in range(40):
        time.sleep(5)
        out = sm(brand, "download/downloadstatus", {"DownloadId": dl_id})
        try:
            status = json.loads(out)
        except json.JSONDecodeError:
            continue
        if status.get("Ready"):
            ready = True
            print(f"[{brand}] download {dl_id} ready after {attempt + 1} polls, {status.get('Records')} records")
            break
    if not ready:
        print(f"[{brand}] download {dl_id} never became ready", file=sys.stderr)
        return None

    raw = sm(brand, "download/getdownload", {"DownloadId": dl_id})
    # A wrong endpoint / failure comes back as JSON {"error": ...}; a good
    # response is bare CSV text (sm.sh passes non-JSON payloads through raw).
    stripped = raw.strip()
    if stripped.startswith("{") and '"error"' in stripped[:200]:
        print(f"[{brand}] get_download errored: {raw[:300]}", file=sys.stderr)
        return None
    return raw


def build_rows(brand, csv_text):
    reader = csv.DictReader(io.StringIO(csv_text))
    rows = []
    for r in reader:
        d = parse_date(r.get("Date"))
        if d is None or d < CUTOFF:
            continue
        addr = ", ".join(x for x in [r.get("Address 1", "").strip()] if x)
        city_state_zip = ", ".join(
            x for x in [r.get("City", "").strip(), f"{r.get('State', '').strip()} {r.get('Zip', '').strip()}".strip()] if x
        )
        full_addr = ", ".join(x for x in [addr, city_state_zip] if x)
        fields = {
            "sm_id": r.get("Id", "").strip(),
            "contact_id": r.get("Contact Id", "").strip(),
            "customer": r.get("Name", "").strip(),
            "amount": r.get("Subtotal", "").strip(),
            "status": r.get("Status", "").strip(),
            "issued": d.isoformat(),
            "brand": brand,
            "address": full_addr,
            "phone": r.get("Phone", "").strip(),
            "owner": r.get("Owner", "").strip(),
            "service": r.get("Service", "").strip(),
            "title": r.get("Title", "").strip(),
            "type": r.get("Type", "").strip(),
            "channel": r.get("Channel", "").strip(),
            "campaign": r.get("Campaign", "").strip(),
            "project_type": r.get("Revenue Category", "").strip(),
            "decline_reason": r.get("Decline Reason", "").strip(),
            "decline_date": r.get("Decline Date", "").strip(),
            "url": "",
            "source": "proposals bulk export (90d refresh) via start_download/downloadstatus/get_download, UserId=10017",
            "scan_date": TSTR,
        }
        rows.append(fields)
    return rows


def main():
    all_rows = []
    for brand in BRANDS:
        csv_text = fetch_proposals_csv(brand)
        if csv_text is None:
            print(f"[{brand}] FAILED to fetch proposals download — leaving existing rows untouched for this brand", file=sys.stderr)
            continue
        rows = build_rows(brand, csv_text)
        print(f"[{brand}] {len(rows)} proposals in the last 90 days (of {csv_text.count(chr(10))} raw rows)")
        all_rows.extend(rows)

    if not all_rows:
        print("No rows built at all — aborting without writing (avoid wiping the section on a total failure)", file=sys.stderr)
        sys.exit(1)

    # status distribution + expired/declined value, for the run report
    from collections import Counter
    dist = Counter((r["brand"], r["status"]) for r in all_rows)
    print("Status distribution (brand, status): count")
    for k in sorted(dist):
        print(f"  {k}: {dist[k]}")
    ed_total = sum(float(r["amount"] or 0) for r in all_rows if r["status"] in ("Expired", "Declined"))
    ed_count = sum(1 for r in all_rows if r["status"] in ("Expired", "Declined"))
    print(f"Expired+Declined: {ed_count} proposals, ${ed_total:,.2f} total value")
    if ed_count == 0:
        print("*** Expired+Declined is ZERO across both brands — this is a FAILURE to report, not a healthy pipeline. ***")

    complete_open_ui = [r for r in all_rows if r["status"] == "Complete"]
    if complete_open_ui:
        print(f"NOTE: {len(complete_open_ui)} proposals have status 'Complete' — these classify as 'open' in the UI per brand status-vocabulary note.")

    # Insert in batches, tag scan_date=TODAY, then prune anything from a prior scan_date.
    BATCH = 200
    for i in range(0, len(all_rows), BATCH):
        chunk = all_rows[i:i + BATCH]
        vals = []
        for idx, f in enumerate(chunk):
            vals.append(f"('proposals',{q(f['brand'])},{i + idx},{q(json.dumps(f))}::jsonb)")
        sql = "INSERT INTO intranet_records (section, brand, sort_order, fields) VALUES " + ", ".join(vals) + ";"
        out, err, rc = sb(sql)
        if rc != 0 or '"error"' in out:
            print(f"INSERT batch {i} failed: rc={rc} out={out[:300]} err={err[:300]}", file=sys.stderr)
            sys.exit(1)

    out, err, rc = sb(f"DELETE FROM intranet_records WHERE section='proposals' AND fields->>'scan_date' <> '{TSTR}';")
    print(f"Pruned stale rows: {out[:200]}")


if __name__ == "__main__":
    main()
