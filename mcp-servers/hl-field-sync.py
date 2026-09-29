#!/usr/bin/env python3
"""
hl-field-sync.py — keep HighLevel's proposal fields filled from ServiceMinder.

ServiceMinder is the source of truth for proposals. For every SM contact whose
proposals changed in the look-back window, this finds the matching HighLevel
contact (same brand's location) and fills what's missing:

  tag  "has proposal"            any SM proposal exists            (add only)
  tag  "won"                     a Complete/Invoiced/Accepted one  (add only, and
                                 only if no won-family tag is already present)
  cf   SM Last Proposal Date     latest non-change-order proposal  (set if blank
  cf   SM Last Proposal Status                                      or stale)

Never removes a tag, never touches any other field, never creates or deletes a
contact. Contradicting tags (lost, uncontacted, ...) are deliberately left
alone — decision 2026-09-22.

Matching (per SM contact): phone (last 10 digits, incl. alt phone) → email →
exact normalized full name when unique. A phone match whose name shares no
token with the SM name, and has no matching email, is AMBIGUOUS: skipped and
reported, never written. SM ids in EXCLUDE_SM_IDS (junk + confirmed
mismatches) and names matching /test|delete me|api probe/i are never written.

Transport is curl only (python-urllib gets a 403 from the session egress proxy).
SM goes through sm.sh; HighLevel uses the PITs directly (REST, not the MCP
endpoint) because the contact search needs filters.

Usage:
  python3 mcp-servers/hl-field-sync.py                 # last 3 days, both brands
  python3 mcp-servers/hl-field-sync.py --days 7
  python3 mcp-servers/hl-field-sync.py --full          # every proposal (backfill)
  python3 mcp-servers/hl-field-sync.py --dry-run --out /tmp/x.json

Env: SM_KEY_KTU/BTU (via sm.sh), GHL_PIT_KTU/BTU.
Output: JSON report on stdout (and --out). Exit 0 unless a brand could not run
at all; per-contact problems are listed in the report, not fatal.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
SM_SH = os.path.join(HERE, "sm.sh")
GHL_API = "https://services.leadconnectorhq.com"

LOCATIONS = {
    "KTU": {"id": "nHLCxHPidnhV1NFzRtZZ", "pit": "GHL_PIT_KTU"},
    "BTU": {"id": "0uWA8M5BzHrrcJftuaDe", "pit": "GHL_PIT_BTU"},
}
DATE_KEY = "contact.sm_last_proposal_date"
STATUS_KEY = "contact.sm_last_proposal_status"
WON_STATUSES = {"Complete", "Invoiced", "Accepted"}
WON_TAGS = {"won", "accepted proposal", "customer", "completed projects", "retarget won"}

# Junk records and confirmed name mismatches from the 2026-09-22 audit
# (signed-clients-audit/REPORT.md). Never written to.
EXCLUDE_SM_IDS = {
    "KTU": {3538202, 5054628, 3250697, 12963507, 4578826, 8962533, 9112312},
    "BTU": {10912289, 11601301},
}


# ---------- helpers ----------

def phone10(x):
    d = re.sub(r"\D", "", x or "")
    d = d[-10:] if len(d) >= 10 else ""
    return d if d and len(set(d)) > 2 else ""


def email_n(x):
    x = (x or "").strip().lower()
    return x if "@" in x else ""


def name_n(x):
    x = re.sub(r"[^a-z ]", "", (x or "").lower())
    x = re.sub(r"\b(mr|mrs|ms|dr|jr|sr|and)\b", "", x)
    return " ".join(x.split())


def tokens(x):
    return set(re.sub(r"[^a-z ]", " ", (x or "").lower()).split()) - {"and", "mr", "mrs", "ms", "dr"}


def sm(brand, endpoint, body):
    r = subprocess.run(["bash", SM_SH, brand, endpoint, json.dumps(body)],
                       capture_output=True, text=True, timeout=180)
    if r.returncode != 0:
        raise RuntimeError(f"sm.sh {brand} {endpoint}: {(r.stderr or r.stdout)[:200]}")
    return json.loads(r.stdout)


def ghl(brand, method, path, body=None):
    tok = os.environ.get(LOCATIONS[brand]["pit"], "")
    cmd = ["curl", "-sS", "--max-time", "60", "-X", method, GHL_API + path,
           "-H", f"Authorization: Bearer {tok}", "-H", "Version: 2021-07-28",
           "-H", "Content-Type: application/json"]
    if body is not None:
        cmd += ["-d", json.dumps(body)]
    last = ""
    for attempt in range(4):
        r = subprocess.run(cmd, capture_output=True, text=True)
        last = r.stdout or r.stderr
        try:
            d = json.loads(r.stdout)
            if isinstance(d, dict) and d.get("statusCode") == 429:
                raise ValueError("rate limited")
            return d
        except ValueError:
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"GHL {method} {path}: {last[:200]}")


# ---------- ServiceMinder ----------

def sm_proposals(brand, updated_from):
    body = {"Scope": "all", "Take": 200, "Proposals": [], "IncludeContact": True}
    if updated_from:
        body["UpdatedFrom"] = updated_from
    out, skip = [], 0
    while True:
        body["Skip"] = skip
        d = sm(brand, "proposal/query", body)
        ps = d.get("Proposals") or []
        for p in ps:
            p.pop("ProposalLines", None)
        out += ps
        skip += len(ps)
        if not ps or skip >= (d.get("Count") or 0):
            return out


def sm_contact_proposals(brand, contact_id):
    d = sm(brand, "proposal/query",
           {"Scope": "all", "ContactId": contact_id, "Take": 200, "Proposals": []})
    return d.get("Proposals") or []


# ---------- HighLevel ----------

def ghl_field_ids(brand):
    d = ghl(brand, "GET", f"/locations/{LOCATIONS[brand]['id']}/customFields?model=contact")
    by_key = {f.get("fieldKey"): f["id"] for f in d.get("customFields", [])}
    return by_key.get(DATE_KEY), by_key.get(STATUS_KEY)


def ghl_search(brand, field, value):
    d = ghl(brand, "POST", "/contacts/search", {
        "locationId": LOCATIONS[brand]["id"], "pageLimit": 20,
        "filters": [{"field": field, "operator": "eq", "value": value}]})
    return d.get("contacts") or []


def match_ghl(brand, c):
    """Return (contacts, how, ambiguous_names)."""
    phones = {phone10(c.get("Phone")), phone10(c.get("AltPhone"))} - {""}
    e = email_n(c.get("Email"))
    hits = {}
    for p in phones:
        for g in ghl_search(brand, "phone", "+1" + p):
            hits[g["id"]] = g
    if hits:
        sm_tok = tokens(c.get("Name"))
        ok = [g for g in hits.values()
              if sm_tok & tokens(f"{g.get('firstName') or ''} {g.get('lastName') or ''}")
              or (e and email_n(g.get("email")) == e)]
        if ok:
            return ok, "phone", []
        return [], "ambiguous", [f"{g.get('firstName')} {g.get('lastName')}" for g in hits.values()]
    if e:
        hits = ghl_search(brand, "email", e)
        if hits:
            return hits, "email", []
    return [], "not_found", []


# ---------- sync ----------

def sync_brand(brand, updated_from, dry_run, rep):
    b = rep["brands"].setdefault(brand, {"sm_contacts_checked": 0, "writes": [], "skipped": [],
                                         "counts": {}})
    cnt = b["counts"]

    def inc(k, n=1):
        cnt[k] = cnt.get(k, 0) + n

    if not os.environ.get(LOCATIONS[brand]["pit"]):
        rep["degradations"].append(f"{brand}: {LOCATIONS[brand]['pit']} not set — skipped brand")
        return
    date_id, status_id = ghl_field_ids(brand)
    if not date_id or not status_id:
        rep["degradations"].append(f"{brand}: SM Last Proposal fields missing in HighLevel — skipped brand")
        return

    touched = sm_proposals(brand, updated_from)
    contacts = {}
    for p in touched:
        contacts.setdefault(p["ContactId"], p.get("Contact") or {})
    inc("sm_proposals_in_window", len(touched))

    for cid, c in contacts.items():
        b["sm_contacts_checked"] += 1
        name = (c.get("Name") or "").strip()
        if cid in EXCLUDE_SM_IDS[brand] or re.search(r"test|delete me|api probe", name, re.I):
            inc("excluded")
            continue
        # Full proposal history for this contact decides tags + latest.
        props = sm_contact_proposals(brand, cid) if updated_from else \
            [p for p in touched if p["ContactId"] == cid]
        if not props:
            continue
        base = [p for p in props if not p.get("ChangeOrderForProposalId")] or props
        latest = max(base, key=lambda p: (p.get("Date") or "", p["Id"]))
        signed = any(p.get("Status") in WON_STATUSES for p in props)

        found, how, amb = match_ghl(brand, c)
        if how == "ambiguous":
            inc("ambiguous")
            b["skipped"].append({"sm_id": cid, "name": name, "reason": "phone match, name differs",
                                 "ghl_names": amb})
            continue
        if how == "not_found":
            inc("not_in_ghl")
            b["skipped"].append({"sm_id": cid, "name": name, "reason": "not found in HighLevel"})
            continue
        inc("matched_" + how)

        for g in found:
            tags = set(g.get("tags") or [])
            cf = {x["id"]: x.get("value") for x in g.get("customFields") or []}
            add = []
            if "has proposal" not in tags:
                add.append("has proposal")
            if signed and not (tags & WON_TAGS):
                add.append("won")
            fields = []
            cur_date = str(cf.get(date_id) or "")[:10]
            if cur_date != latest["Date"]:
                fields.append({"id": date_id, "value": latest["Date"]})
            if (cf.get(status_id) or "") != latest["Status"]:
                fields.append({"id": status_id, "value": latest["Status"]})
            if not add and not fields:
                inc("already_complete")
                continue
            w = {"sm_id": cid, "ghl_id": g["id"], "name": name, "add_tags": add,
                 "set_fields": {"SM Last Proposal Date": latest["Date"],
                                "SM Last Proposal Status": latest["Status"]} if fields else {}}
            if not dry_run:
                ok = True
                if add:
                    r = ghl(brand, "POST", f"/contacts/{g['id']}/tags", {"tags": add})
                    ok &= "tags" in r
                if fields:
                    r = ghl(brand, "PUT", f"/contacts/{g['id']}", {"customFields": fields})
                    ok &= bool(r.get("contact") or r.get("succeded") or r.get("succeeded"))
                w["landed"] = ok
                if not ok:
                    inc("write_failed")
            b["writes"].append(w)
            inc("tags_added", len(add))
            inc("fields_set", 1 if fields else 0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=3)
    ap.add_argument("--full", action="store_true", help="every proposal, not just recently updated")
    ap.add_argument("--brand", choices=["KTU", "BTU"])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out")
    a = ap.parse_args()

    updated_from = None if a.full else (date.today() - timedelta(days=a.days)).isoformat()
    rep = {"run_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "updated_from": updated_from,
           "dry_run": a.dry_run, "brands": {}, "degradations": []}
    fatal = 0
    for brand in ([a.brand] if a.brand else ["KTU", "BTU"]):
        try:
            sync_brand(brand, updated_from, a.dry_run, rep)
        except Exception as e:  # one brand failing must not hide the other
            rep["degradations"].append(f"{brand}: {e}")
            fatal += 1
    for b in rep["brands"].values():
        b["counts"]["writes"] = len(b["writes"])
    txt = json.dumps(rep, indent=1, default=str)
    if a.out:
        with open(a.out, "w") as f:
            f.write(txt)
    print(txt)
    sys.exit(1 if fatal == len(rep["brands"] or [1]) and fatal else 0)


if __name__ == "__main__":
    main()
