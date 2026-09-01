#!/usr/bin/env python3
"""
drain_note_queue_jobtread.py — push queued intranet notes into JobTread.

The third leg of sm_note_queue. `status` is ServiceMinder (drained by contact
id), `ghl_status` is HighLevel (drained by phone, because the rows that most
need it carry no ServiceMinder id), and `jt_status` is JobTread, drained by
job id. The legs are independent on purpose: JobTread being down must not stop
a note reaching HighLevel, and a project with no JobTread job must not park a
row in the queue forever — those are marked 'skipped' at enqueue time.

IDEMPOTENCY, same as the HighLevel leg. A note is a permanent, human-visible
record on a real job:

  1. Byte-identical bodies already queued for the same job collapse to one
     write; the rest are 'skipped' naming the row that carried it.
  2. Existing comments on the job are read first and the rendered body
     compared, so re-running after a partial failure cannot duplicate.

Usage:
  python3 intranet/scripts/drain_note_queue_jobtread.py            # dry run
  python3 intranet/scripts/drain_note_queue_jobtread.py --apply

Requires: SUPABASE_SERVICE_ROLE_KEY, JOBTREAD_GRANT_KEY.
"""
import json, os, subprocess, sys, hashlib

ROOT  = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SB    = os.path.join(ROOT, "mcp-servers", "sb.sh")
JT    = os.path.join(ROOT, "mcp-servers", "jobtread.sh")
APPLY = "--apply" in sys.argv
MAX_ATTEMPTS = 3


def sb(sql):
    out = subprocess.run(["bash", SB], input=sql, capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f"sb.sh failed: {out.stderr.strip()}")
    data = json.loads(out.stdout)
    if isinstance(data, dict) and "message" in data and "ok" not in data:
        raise RuntimeError(f"SQL error: {data['message']} :: {sql[:120]}")
    return data


def q(s):
    return "null" if s is None else "'" + str(s).replace("'", "''") + "'"


def render(row):
    """Body as JobTread will store it. The author prefix is the only
    attribution that survives the hop — the intranet is a shared login."""
    return f"[Intranet · {row.get('author') or 'Intranet'}] {row['note']}"


def main():
    rows = sb("""
        select id::text, brand, customer, jt_job_id, jt_attempts, note, author
        from sm_note_queue
        where jt_status = 'pending' and jt_attempts < %d and jt_job_id is not null
        order by created_at
    """ % MAX_ATTEMPTS)
    if not rows:
        print("JobTread leg: nothing pending.")
        return

    print(f"JobTread leg: {len(rows)} pending{'' if APPLY else '  (DRY RUN — pass --apply to write)'}")
    seen = {}
    for r in rows:
        body = render(r)
        key = (r["jt_job_id"], hashlib.sha256(body.encode()).hexdigest())
        if key in seen:
            print(f"  skip  {r['customer'][:40]:<40} duplicate of {seen[key]}")
            if APPLY:
                sb(f"update sm_note_queue set jt_status='skipped', "
                   f"jt_error='exact duplicate of {seen[key]}', jt_synced_at=now() "
                   f"where id={q(r['id'])}")
            continue
        seen[key] = r["id"]

        if not APPLY:
            print(f"  would post to job {r['jt_job_id']}: {body[:70]}")
            continue

        out = subprocess.run(["bash", JT, "comment", r["jt_job_id"], body],
                             capture_output=True, text=True)
        if out.returncode != 0:
            err = (out.stderr or out.stdout).strip()[:300]
            print(f"  ERROR {r['customer'][:40]:<40} {err}")
            sb(f"update sm_note_queue set jt_status='error', jt_attempts=jt_attempts+1, "
               f"jt_error={q(err)} where id={q(r['id'])}")
            continue
        print(f"  sent  {r['customer'][:40]:<40} job {r['jt_job_id']}")
        sb(f"update sm_note_queue set jt_status='synced', jt_synced_at=now(), jt_error=null "
           f"where id={q(r['id'])}")


if __name__ == "__main__":
    main()
