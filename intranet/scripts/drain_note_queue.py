#!/usr/bin/env python3
"""
drain_note_queue.py — push queued intranet team notes out to HighLevel.

WHY THIS IS A SCRIPT AND NOT A HANDFUL OF CURLS
-----------------------------------------------
`sm_note_queue` has two INDEPENDENT destination legs (see
supabase/012_note_queue_highlevel_leg.sql). `status` is the ServiceMinder leg
and is drained by contact_id; `ghl_status` is the HighLevel leg and is drained
by PHONE, because the rows that most need it (`appt_upcoming`) carry no
ServiceMinder contact id at all. This script owns the HighLevel leg only — it
never touches `status`.

IDEMPOTENCY IS NOT OPTIONAL HERE. A note is a permanent, human-visible record on
a real customer. Two guards:

  1. Exact-duplicate rows in the queue (same contact + byte-identical body) are
     collapsed: the first is written, the rest are marked 'skipped' naming the
     row that carried it. The intranet UI can produce these — a double-click on
     Save queues twice, and both pairs in the 2026-08-25 backlog are exactly
     that.
  2. Before writing, the contact's existing HighLevel notes are read and the
     rendered body compared. A body already present is marked 'synced' without
     a second write, so re-running after a partial failure cannot duplicate.

Usage:
  python3 intranet/scripts/drain_note_queue.py            # dry run (default)
  python3 intranet/scripts/drain_note_queue.py --apply

Requires: SUPABASE_SERVICE_ROLE_KEY, GHL_PIT_KTU / GHL_PIT_BTU.
"""
import json, os, subprocess, sys, hashlib

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SB   = os.path.join(ROOT, "mcp-servers", "sb.sh")
GHL  = os.path.join(ROOT, "mcp-servers", "ghl.sh")
APPLY = "--apply" in sys.argv
MAX_ATTEMPTS = 3


def sb(sql):
    """Run SQL via sb.sh. Raises on a PostgREST error.

    PostgREST reports failures as an OBJECT ({code,message,...}), not a list.
    Iterating that yields KEYS, which surfaces as a bewildering
    'str has no attribute get' several frames downstream. Fail loudly here.
    """
    out = subprocess.run(["bash", SB], input=sql, capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f"sb.sh failed: {out.stderr.strip()}")
    data = json.loads(out.stdout)
    if isinstance(data, dict) and "message" in data and "ok" not in data:
        raise RuntimeError(f"SQL error: {data['message']} :: {sql[:120]}")
    return data


def ghl(brand, *args):
    out = subprocess.run(["bash", GHL, brand, *args], capture_output=True, text=True)
    try:
        return json.loads(out.stdout)
    except json.JSONDecodeError:
        return {"error": (out.stdout or out.stderr).strip()[:300]}


def q(s):
    """Quote a value for inline SQL (sb.sh takes a statement, not params)."""
    if s is None:
        return "null"
    return "'" + str(s).replace("'", "''") + "'"


def render(row):
    """The body as HighLevel will store it.

    The author prefix matters: these notes were written in the intranet by a
    named person under a SHARED login, so the name is the only attribution that
    survives the hop into HighLevel.
    """
    author = row.get("author") or "Intranet"
    return f"[Intranet · {author}] {row['note']}"


def main():
    rows = sb("""
        select id::text, brand, section, customer, phone, email,
               ghl_contact_id, ghl_attempts, note, author
        from sm_note_queue
        where ghl_status = 'pending' and ghl_attempts < %d
        order by created_at
    """ % MAX_ATTEMPTS)

    print(f"{len(rows)} row(s) pending on the HighLevel leg"
          f"{'' if APPLY else '  [DRY RUN — no writes]'}\n")

    seen = {}          # (contact_key, body_hash) -> queue id that carried it
    contact_cache = {} # phone -> ghl contact id
    stats = {"synced": 0, "skipped": 0, "error": 0}

    for r in rows:
        body = render(r)
        label = f"{r['customer']} ({r['phone'] or r['email'] or 'no key'})"

        if not (r["phone"] or r["email"]):
            print(f"  SKIP  {label}: no phone or email to resolve a contact by")
            if APPLY:
                sb("update sm_note_queue set ghl_status='skipped',"
                   " ghl_error='no phone or email on this row'"
                   f" where id={q(r['id'])}")
            stats["skipped"] += 1
            continue

        # ---- guard 1: byte-identical twin earlier in this same batch --------
        key = (r["phone"] or r["email"], hashlib.md5(body.encode()).hexdigest())
        if key in seen:
            print(f"  SKIP  {label}: duplicate of queue row {seen[key]}")
            if APPLY:
                sb("update sm_note_queue set ghl_status='skipped',"
                   f" ghl_error='duplicate of queue row {seen[key]}'"
                   f" where id={q(r['id'])}")
            stats["skipped"] += 1
            continue

        # ---- resolve the HighLevel contact ---------------------------------
        cid = r["ghl_contact_id"] or contact_cache.get(r["phone"])
        if not cid and r["phone"]:
            res = ghl(r["brand"], "contact-by-phone", r["phone"])
            cid = (res.get("contact") or {}).get("id")
            if cid:
                contact_cache[r["phone"]] = cid
        if not cid:
            msg = "no HighLevel contact matched this phone"
            print(f"  ERR   {label}: {msg}")
            if APPLY:
                sb("update sm_note_queue set ghl_status='error',"
                   f" ghl_attempts=ghl_attempts+1, ghl_error={q(msg)}"
                   f" where id={q(r['id'])}")
            stats["error"] += 1
            continue

        # ---- guard 2: already on the contact in HighLevel -------------------
        existing = ghl(r["brand"], "note-list", cid)
        bodies = {(n.get("body") or "").strip()
                  for n in (existing.get("notes") or [])}
        if body.strip() in bodies:
            print(f"  OK    {label}: already present in HighLevel, marking synced")
            if APPLY:
                sb("update sm_note_queue set ghl_status='synced',"
                   f" ghl_contact_id={q(cid)}, ghl_error=null,"
                   " ghl_synced_at=now()"
                   f" where id={q(r['id'])}")
            seen[key] = r["id"]
            stats["synced"] += 1
            continue

        if not APPLY:
            print(f"  WOULD WRITE  {label} -> contact {cid}")
            print(f"               {body[:100]}")
            seen[key] = r["id"]
            stats["synced"] += 1
            continue

        res = ghl(r["brand"], "note-add", cid, body)
        nid = (res.get("note") or {}).get("id")
        if nid:
            print(f"  WROTE {label} -> contact {cid}, note {nid}")
            sb("update sm_note_queue set ghl_status='synced',"
               f" ghl_contact_id={q(cid)}, ghl_error=null, ghl_synced_at=now()"
               f" where id={q(r['id'])}")
            seen[key] = r["id"]
            stats["synced"] += 1
        else:
            msg = json.dumps(res)[:300]
            print(f"  ERR   {label}: {msg}")
            sb("update sm_note_queue set ghl_status='error',"
               f" ghl_attempts=ghl_attempts+1, ghl_contact_id={q(cid)},"
               f" ghl_error={q(msg)} where id={q(r['id'])}")
            stats["error"] += 1

    print(f"\nsynced={stats['synced']}  skipped={stats['skipped']}  errors={stats['error']}")
    return 1 if stats["error"] else 0


if __name__ == "__main__":
    sys.exit(main())
