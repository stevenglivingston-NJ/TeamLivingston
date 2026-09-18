#!/usr/bin/env python3
"""
jc-labor-sync.py — CompanyCam hours -> job costing labor, and back out to
ServiceMinder and JobTread.

WHAT IT DOES, in order:
  1. pull   CompanyCam users + projects + time entries      -> jc_cc_time_entries
  2. match  CompanyCam project -> jc_jobs (trigram)         -> jc_cc_project_map
  3. split  each unallocated payroll week pro rata by hours -> jc_labor_allocations
            (via jc_allocate_week(); mirrors into jc_actual_costs)
  4. push   a cost summary to ServiceMinder as a contact note
  5. push   actual-cost lines into the JobTread job budget

THE RULE THIS OBEYS (Steven, 2026-09-18): hours are the ALLOCATION KEY, never a
dollar source. CompanyCam has no pay-rate field and the QBO/Gusto sweep already
books the weekly lump — so multiplying hours by an invented rate would charge
every job for labor twice. Payroll supplies the dollars; hours only decide how
they split. See docs/JOB_COSTING_DESIGN.md §7 and the migration header.

TRANSPORT: everything goes through curl, never through mcp__* tools. Scheduled
Routines run in Auto mode, where a connector-call classifier prompts before an
unapproved mcp__* call; a non-interactive fire cannot answer, so the session
STALLS in REQUIRES_ACTION forever rather than erroring and the board silently
goes stale. That cost eight days in August 2026. See CLAUDE.md.

KNOWN BLOCKER (probed 2026-09-18, read before debugging a zero-row run):
  * CompanyCam time-tracking IS enabled on company 592669, but ZERO hours have
    been logged by anyone. Empty means no adoption, not a broken pipe.
  * COMPANYCAM_TOKEN cannot read time entries. /v2/projects, /v2/users,
    /v2/company, /v2/webhooks, /v2/tags, /v2/groups all return 200; every
    time-entry path variant returns 302 -> /users/sign_in. That is a scope
    symptom on a static API token, not a wrong path — CompanyCam's time
    tracking is busybusy-backed (see webhook 263822 on this company), and the
    MCP connector's OAuth identity reads it where the static token does not.
    Until the token is re-minted with time-entry scope, use --from-json to
    ingest entries exported by an interactive session.

Usage:
  python3 mcp-servers/jc-labor-sync.py --dry-run
  python3 mcp-servers/jc-labor-sync.py --pull --days 14
  python3 mcp-servers/jc-labor-sync.py --from-json /tmp/entries.json
  python3 mcp-servers/jc-labor-sync.py --match                  # propose job matches
  python3 mcp-servers/jc-labor-sync.py --allocate               # split ready weeks
  python3 mcp-servers/jc-labor-sync.py --push-sm --push-jt      # outbound
  python3 mcp-servers/jc-labor-sync.py --all                    # the nightly run
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import defaultdict

SUPA = os.environ.get("SUPABASE_URL", "https://tguwpswcneywvscxzyef.supabase.co").replace(".supabase.com", ".supabase.co")
SRK = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
CC_TOKEN = os.environ.get("COMPANYCAM_TOKEN", "")
JT_KEY = os.environ.get("JOBTREAD_GRANT_KEY", "")
SM_KEYS = {"KTU": os.environ.get("SM_KEY_KTU", ""), "BTU": os.environ.get("SM_KEY_BTU", "")}

CC_BASE = "https://api.companycam.com"
SM_BASE = "https://serviceminder.io/api"
TZ = "America/New_York"

# Steven's decision, 2026-09-18: auto-write JobTread cost lines above this match
# confidence rather than staging every line for confirmation. He was told the
# risk — JobTread has no hard key to ServiceMinder, only fuzzy name+address, so
# a same-surname collision writes real money into the wrong job budget with
# nobody watching. The mitigation is jc_jobtread_cost_log: every auto-written
# line records its cost-item id and the confidence it went in at, so a bad
# match is reversible by query instead of hunted through JobTread by hand.
JT_AUTOWRITE_THRESHOLD = 0.85

# Project-name matching never auto-CONFIRMS below this; it only proposes.
MATCH_MIN = 0.45

DEGRADATIONS: list[str] = []


def degrade(msg: str) -> None:
    """Record a pipe that failed. An empty result next to a degradation is
    UNVERIFIED, not clean — the caller must never report it as 'no labor'."""
    DEGRADATIONS.append(msg)
    print(f"  !! DEGRADED: {msg}", file=sys.stderr)


def curl(args, timeout=120):
    r = subprocess.run(["curl", "-sS", "--max-time", str(timeout)] + args,
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"curl failed: {r.stderr[:300]}")
    return r.stdout


def sb(sql):
    out = curl(["-X", "POST", f"{SUPA}/rest/v1/rpc/exec_sql",
                "-H", f"apikey: {SRK}", "-H", f"Authorization: Bearer {SRK}",
                "-H", "Content-Type: application/json",
                "-d", json.dumps({"query": sql})], timeout=180)
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        raise RuntimeError(f"supabase returned non-JSON: {out[:300]}")


def q(v):
    """Quote a value for inline SQL."""
    if v is None or v == "":
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    return "'" + str(v).replace("'", "''") + "'"


def cc(path, qs=""):
    """CompanyCam GET. Returns None (and degrades) rather than raising, so one
    dead endpoint cannot take down the whole nightly run."""
    url = f"{CC_BASE}/{path.lstrip('/')}" + (f"?{qs}" if qs else "")
    # Accept: application/json is load-bearing. Without it the time-tracking
    # routes answer a browser-shaped request with 302 -> /users/sign_in, which
    # looks like a wrong path; with it they return an honest 401.
    out = curl(["-X", "GET", url,
                "-H", f"Authorization: Bearer {CC_TOKEN}",
                "-H", "Accept: application/json",
                "-H", "Content-Type: application/json",
                "-w", "\n%{http_code}"])
    body, _, code = out.rpartition("\n")
    code = code.strip()
    if code in ("401", "302"):
        degrade(f"CompanyCam {path} -> {code}. The route is real and the token is "
                f"live (it returns 200 on /v2/projects and /v2/users), but the "
                f"time-tracking surface rejects this credential with 'Bad "
                f"credentials' — time tracking authorizes separately from the "
                f"rest of the v2 API and is absent from the public API docs "
                f"entirely. Supply a credential the time-tracking surface "
                f"accepts, or feed entries via --from-json.")
        return None
    if code.startswith(("4", "5")):
        degrade(f"CompanyCam {path} -> HTTP {code}")
        return None
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        degrade(f"CompanyCam {path} returned non-JSON")
        return None


def sm(location, endpoint, body):
    """ServiceMinder POST. The API takes ApiKey INSIDE the json body, and
    signals 'no such endpoint' with an empty 200 body rather than a 404."""
    payload = dict(body)
    payload["ApiKey"] = SM_KEYS.get(location, "")
    out = curl(["-X", "POST", f"{SM_BASE}/{endpoint}",
                "-H", "Content-Type: application/json",
                "-d", json.dumps(payload)])
    if not out.strip():
        return None
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return None


def jt(query):
    payload = {"query": {"$": {"grantKey": JT_KEY}, **query}}
    out = curl(["-X", "POST", "https://api.jobtread.com/pave",
                "-H", "Content-Type: application/json", "-d", json.dumps(payload)])
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        degrade(f"JobTread returned non-JSON: {out[:200]}")
        return None


# ---------------------------------------------------------------------------
# 1) PULL — CompanyCam time entries into jc_cc_time_entries
# ---------------------------------------------------------------------------
def monday(d: dt.date) -> dt.date:
    return d - dt.timedelta(days=d.weekday())


def cc_people():
    """CompanyCam user id -> display name. Entries carry a user id only."""
    users = cc("/v2/users", "per_page=100")
    if not users:
        return {}
    out = {}
    for u in users:
        name = f"{(u.get('first_name') or '').strip()} {(u.get('last_name') or '').strip()}".strip()
        out[str(u["id"])] = name or u.get("email_address") or f"user {u['id']}"
    return out


def normalise_entry(e, people):
    """CompanyCam's shape varies across surfaces (REST vs the connector), so
    read defensively rather than assuming one key spelling."""
    eid = str(e.get("id") or e.get("entry_id") or "")
    if not eid:
        return None
    uid = str(e.get("user_id") or (e.get("user") or {}).get("id") or "")
    proj = e.get("project_id") or (e.get("project") or {}).get("id")
    proj = str(proj) if proj else None

    def ts(v):
        if v in (None, ""):
            return None
        if isinstance(v, (int, float)):
            return dt.datetime.fromtimestamp(v, dt.timezone.utc)
        try:
            return dt.datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        except ValueError:
            return None

    tin = ts(e.get("clock_in_at") or e.get("start_at") or e.get("started_at"))
    tout = ts(e.get("clock_out_at") or e.get("end_at") or e.get("ended_at"))
    if not tin:
        return None

    secs = e.get("duration_seconds") or e.get("duration")
    if secs is None and tout:
        secs = (tout - tin).total_seconds()
    hours = round(float(secs) / 3600.0, 3) if secs else None

    status = e.get("status") or ("completed" if tout else "active")
    if status not in ("completed", "active"):
        status = "completed" if tout else "active"

    # Bucket the work DATE in the company's own timezone. A 7pm clock-in in NJ
    # is already "tomorrow" in UTC, which would push the shift into the wrong
    # week and silently mis-split that week's payroll.
    local = tin.astimezone(dt.timezone(dt.timedelta(hours=-4)))  # ET, DST-approx
    wdate = local.date()

    return {
        "cc_entry_id": eid,
        "cc_user_id": uid,
        "person": people.get(uid, f"user {uid}"),
        "cc_project_id": proj,
        "clock_in_at": tin.isoformat(),
        "clock_out_at": tout.isoformat() if tout else None,
        "duration_seconds": secs,
        "hours": hours,
        "status": status,
        "work_date": wdate.isoformat(),
        "week_start": monday(wdate).isoformat(),
        "deleted_at": e.get("deleted_at"),
        "raw": e,
    }


def pull_entries(days, from_json=None, dry=False):
    people = cc_people()
    if from_json:
        raw = json.load(open(from_json))
        raw = raw.get("data", raw) if isinstance(raw, dict) else raw
        print(f"  reading {len(raw)} entries from {from_json}")
    else:
        since = (dt.date.today() - dt.timedelta(days=days)).isoformat()
        got = cc("/v2/timeentries", f"per_page=100&start_date={since}&end_date={dt.date.today().isoformat()}")
        if got is None:
            print("  no entries pulled (see degradations) — nothing written")
            return 0
        raw = got.get("data", got) if isinstance(got, dict) else got

    rows = [r for r in (normalise_entry(e, people) for e in raw) if r]
    if not rows:
        print("  0 time entries. If the pipe is healthy this means NOBODY CLOCKED IN, "
              "which is the current state — not a sync failure.")
        return 0

    if dry:
        print(f"  [dry-run] would upsert {len(rows)} entries")
        for r in rows[:5]:
            print(f"    {r['work_date']} {r['person']:<20} {r['hours']}h proj={r['cc_project_id']}")
        return len(rows)

    vals = ",".join(
        f"({q(r['cc_entry_id'])},{q(r['cc_user_id'])},{q(r['person'])},{q(r['cc_project_id'])},"
        f"{q(r['clock_in_at'])}::timestamptz,{q(r['clock_out_at'])}::timestamptz,"
        f"{q(r['duration_seconds'])},{q(r['hours'])},{q(r['status'])},"
        f"{q(r['work_date'])}::date,{q(r['week_start'])}::date,{q(r['deleted_at'])}::timestamptz,"
        f"{q(json.dumps(r['raw']))}::jsonb)"
        for r in rows)
    sb(f"""
      insert into jc_cc_time_entries
        (cc_entry_id,cc_user_id,person,cc_project_id,clock_in_at,clock_out_at,
         duration_seconds,hours,status,work_date,week_start,deleted_at,raw)
      values {vals}
      on conflict (cc_entry_id) do update set
        person=excluded.person, cc_project_id=excluded.cc_project_id,
        clock_out_at=excluded.clock_out_at, duration_seconds=excluded.duration_seconds,
        hours=excluded.hours, status=excluded.status, work_date=excluded.work_date,
        week_start=excluded.week_start, deleted_at=excluded.deleted_at,
        raw=excluded.raw, synced_at=now();
    """)
    print(f"  upserted {len(rows)} time entries")
    return len(rows)


# ---------------------------------------------------------------------------
# 2) MATCH — CompanyCam project -> jc_jobs
# ---------------------------------------------------------------------------
STOP = re.compile(r"\b(kitchen|bath|bathroom|reface|refacing|remodel|renovation|"
                  r"project|job|install|installation|ktu|btu|tune-?up)\b", re.I)


def norm_name(s):
    s = (s or "").lower()
    s = STOP.sub(" ", s)
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def match_projects(dry=False, actor="jc-labor-sync"):
    """Propose a job for every CompanyCam project that has hours on it.

    This is a PROPOSAL, never a confirmation. There is no hard key between
    CompanyCam and ServiceMinder — only customer name and address — and
    same-surname collisions are a documented live failure mode in this data.
    A proposal becomes authoritative only when a human confirms it in the
    intranet, which is what stamps confirmed_by/confirmed_at.
    """
    projects = cc("/v2/projects", "per_page=100") or []
    by_id = {str(p["id"]): p for p in projects}

    seen = sb("""
      select distinct t.cc_project_id
        from jc_cc_time_entries t
        left join jc_cc_project_map m on m.cc_project_id = t.cc_project_id
       where t.cc_project_id is not null
         and (m.cc_project_id is null or m.confirmed_at is null)
    """) or []
    if not seen:
        print("  no unconfirmed CompanyCam projects carrying hours — nothing to match")
        return 0

    jobs = sb("select id, brand, customer_name, coalesce(address,'') as address from jc_jobs "
              "where status in ('approved','in_progress')") or []
    if not jobs:
        degrade("no open jc_jobs to match against")
        return 0

    written = 0
    for row in seen:
        pid = row["cc_project_id"]
        proj = by_id.get(pid, {})
        pname = proj.get("name") or ""
        paddr = " ".join(str(v) for v in (proj.get("address") or {}).values() if v)
        pn = norm_name(pname)

        scored = []
        for j in jobs:
            jn = norm_name(j["customer_name"])
            if not jn or not pn:
                continue
            # token overlap — surname-level matching, which is the granularity
            # CompanyCam project names actually carry.
            a, b = set(pn.split()), set(jn.split())
            if not a or not b:
                continue
            score = len(a & b) / len(a | b)
            # an address hit is much stronger evidence than a name hit
            if j["address"] and paddr:
                ja = norm_name(j["address"])[:18]
                if ja and ja in norm_name(paddr):
                    score = max(score, 0.95)
            if score >= MATCH_MIN:
                scored.append((score, j))

        scored.sort(key=lambda x: -x[0])
        if not scored:
            best, conf, method = None, None, None
        elif len(scored) > 1 and abs(scored[0][0] - scored[1][0]) < 0.15:
            # Two jobs fit about equally — that is exactly the same-surname
            # collision. Refuse to propose; a human picks.
            best, conf, method = None, scored[0][0], "ambiguous"
        else:
            best, conf = scored[0][1], scored[0][0]
            method = "address" if conf >= 0.95 else "trigram_name"

        if dry:
            print(f"    {pid} {pname[:34]:<34} -> "
                  f"{best['customer_name'] if best else '(needs a human)'} "
                  f"{('%.2f' % conf) if conf else ''} {method or ''}")
            continue

        sb(f"""
          insert into jc_cc_project_map
            (cc_project_id, cc_project_name, cc_address, job_id, bucket,
             match_confidence, match_method)
          values ({q(pid)}, {q(pname)}, {q(paddr)}, {q(str(best['id'])) if best else 'null'}::uuid,
                  {q('job' if best else 'unmapped')}, {q(conf)}, {q(method)})
          on conflict (cc_project_id) do update set
            cc_project_name = excluded.cc_project_name,
            cc_address      = excluded.cc_address,
            job_id          = case when jc_cc_project_map.confirmed_at is null
                                   then excluded.job_id else jc_cc_project_map.job_id end,
            bucket          = case when jc_cc_project_map.confirmed_at is null
                                   then excluded.bucket else jc_cc_project_map.bucket end,
            match_confidence= excluded.match_confidence,
            match_method    = excluded.match_method
          where jc_cc_project_map.confirmed_at is null;
        """)
        written += 1

    print(f"  proposed matches for {written} CompanyCam project(s)")
    return written


# ---------------------------------------------------------------------------
# 3) ALLOCATE — split payroll weeks by hours
# ---------------------------------------------------------------------------
def allocate(dry=False, actor="jc-labor-sync", force_unmapped=False):
    """Split every payroll week that is ready.

    A week is NOT ready while any of its hours sit on an unmapped CompanyCam
    project: allocating then would silently dump those hours into a bucket and
    understate the jobs they belong to. Such weeks stay on the queue with
    has_unmapped_projects=true until someone maps the project. --force-unmapped
    overrides that when the unmapped time genuinely is shop/bench work.
    """
    queue = sb("select * from jc_labor_queue order by week_start, person") or []
    if not queue:
        print("  allocation queue empty — no unallocated payroll weeks")
        return 0

    done = 0
    for p in queue:
        blocked = p["has_unmapped_projects"] and not force_unmapped
        tag = "BLOCKED (unmapped projects)" if blocked else ("no hours -> bench" if p["no_hours"] else "ready")
        print(f"    {p['week_start']} {p['person']:<20} ${p['allocatable']:>9} "
              f"{p['clocked_hours']:>6}h  {tag}")
        if blocked or dry:
            continue
        sb(f"select * from jc_allocate_week({q(p['payroll_period_id'])}::uuid, {q(actor)})")
        done += 1

    print(f"  allocated {done} payroll week(s)")
    return done


# ---------------------------------------------------------------------------
# 4) PUSH -> ServiceMinder (contact note — the only write surface that exists)
# ---------------------------------------------------------------------------
def sm_note_body(j):
    contract = float(j["contract_total"] or 0)
    added = float(j["added_revenue_post_sale"] or 0)
    revenue = contract + added
    labor = float(j["labor_cost"] or 0)
    materials = float(j["materials_cost"] or 0)
    other = float(j["other_cost"] or 0)
    total = labor + materials + other
    gp = revenue - total
    gpct = (gp / revenue * 100) if revenue else 0

    lines = [
        "JOB COSTING — from the Axyom intranet",
        f"Proposal #{j['sm_proposal_id'] or '(none)'} · {j['customer_name']} ({j['brand']})",
        f"as of {dt.date.today().isoformat()}",
        "",
        f"Contract price      {contract:>12,.2f}",
    ]
    if added:
        lines.append(f"Change orders       {added:>12,.2f}")
        lines.append(f"Total revenue       {revenue:>12,.2f}")
    lines += [
        "",
        f"Labor (actual)      {labor:>12,.2f}   {j['hours'] or 0:g} clocked hours",
        f"Materials (actual)  {materials:>12,.2f}",
        f"Other (actual)      {other:>12,.2f}",
        f"Total cost          {total:>12,.2f}",
        "",
        f"Gross profit        {gp:>12,.2f}   {gpct:.1f}%",
        "",
        "Labor is CompanyCam clocked hours splitting actual payroll —",
        "not an estimate. ServiceMinder exposes no cost API, so this",
        "note is the record here; the live figures are on the intranet.",
    ]
    return "\n".join(lines)


def push_serviceminder(dry=False, actor="jc-labor-sync", auto_queue=False):
    """Drain the ServiceMinder push queue, and optionally top it up.

    TWO REASONS THIS IS A QUEUE RATHER THAN A DIRECT WRITE:

    1. ServiceMinder has NO API path that posts a cost against a job or a
       proposal. Probed 2026-09-18 across 15 endpoint spellings (jobcost, cost,
       margin, purchaseorder, vendorinvoice, posting, expense, joblines --
       singular and plural); every one returns SM's empty-200 "no such
       endpoint" signature. Custom fields are 48 contact-level + 1
       appointment-level, none at proposal or job level and none cost-related.
       A contact note is the entire write surface. It is visible in SM and it
       names the proposal, but it will NOT appear in the Margins panel and SM
       will not compute with it.

    2. SM authenticates with its ApiKey inside the request body, so the
       intranet (a browser app on the anon key) must never post directly --
       that would ship a live key to every open tab. The person confirms the
       job/proposal and previews the note in the UI, which queues a `pending`
       row; this function, running server side with the key, sends it.
    """
    posted = failed = 0

    if auto_queue:
        # Optional: queue any job whose summary has changed since last time.
        # Off by default -- Steven's flow is that a PERSON confirms which SM
        # proposal is being updated before anything is written there.
        for j in _costed_jobs():
            body = sm_note_body(j)
            h = hashlib.sha256(body.encode()).hexdigest()[:32]
            if sb(f"select 1 from jc_sm_note_log where job_id={q(j['id'])}::uuid "
                  f"and note_hash={q(h)} and status<>'failed'"):
                continue
            if dry:
                print(f"    [dry-run] would QUEUE {j['customer_name']} -> SM contact {j['sm_contact_id']}")
                continue
            sb(f"""insert into jc_sm_note_log
                     (job_id,brand,sm_contact_id,sm_proposal_id,note_hash,note_body,
                      status,requested_by,requested_at)
                   values ({q(j['id'])}::uuid,{q(j['brand'])},{q(j['sm_contact_id'])},
                           {q(j['sm_proposal_id'])},{q(h)},{q(body)},'pending',{q(actor)},now())
                   on conflict do nothing""")

    pending = sb("""
      select id, job_id, brand, sm_contact_id, sm_proposal_id, note_body, requested_by
        from jc_sm_note_log
       where status = 'pending'
       order by requested_at
    """) or []

    if not pending:
        print("  ServiceMinder queue empty — nothing confirmed for posting")
        return 0

    for n in pending:
        if dry:
            print(f"    [dry-run] would post to SM {n['brand']} contact {n['sm_contact_id']} "
                  f"(proposal #{n['sm_proposal_id']}), queued by {n['requested_by']}")
            posted += 1
            continue

        if not SM_KEYS.get(n["brand"]):
            degrade(f"no SM key for brand {n['brand']} — cannot post note {n['id']}")
            continue

        resp = sm(n["brand"], "contacts/addnote", {
            "ContactId": int(n["sm_contact_id"]),
            "Note": {"Title": f"Job Costing — Proposal #{n['sm_proposal_id'] or 'n/a'}",
                     "Body": n["note_body"]},
        })

        if resp is None:
            # Empty body from SM is its "no such endpoint" signal, which here
            # means the note did NOT land. Mark it failed rather than silently
            # logging a success nobody can see in ServiceMinder.
            sb(f"""update jc_sm_note_log
                      set status='failed',
                          error='ServiceMinder returned an empty body (its no-such-endpoint / rejected signal)'
                    where id={q(n['id'])}::uuid""")
            degrade(f"SM addnote rejected for contact {n['sm_contact_id']} (job {n['job_id']})")
            failed += 1
            continue

        sb(f"""update jc_sm_note_log
                  set status='posted', posted_at=now(), posted_by={q(actor)},
                      response={q(json.dumps(resp))}::jsonb, error=null
                where id={q(n['id'])}::uuid""")
        posted += 1

    print(f"  posted {posted} ServiceMinder note(s); {failed} failed")
    return posted


def _costed_jobs():
    return sb("""
      select j.id, j.brand, j.customer_name, j.sm_contact_id, j.sm_proposal_id,
             j.contract_total, j.added_revenue_post_sale,
             coalesce(l.hours,0)      as hours,
             coalesce(l.labor_cost,0) as labor_cost,
             coalesce((select sum(a.amount) from jc_actual_costs a
                        where a.job_id=j.id and a.category='direct_materials'),0) as materials_cost,
             coalesce((select sum(a.amount) from jc_actual_costs a
                        where a.job_id=j.id and a.category in ('other','sales_commission')),0) as other_cost
        from jc_jobs j
        left join jc_job_labor l on l.job_id = j.id
       where j.sm_contact_id is not null
         and j.status in ('approved','in_progress','complete')
         and (coalesce(l.labor_cost,0) > 0
              or exists (select 1 from jc_actual_costs a where a.job_id=j.id))
    """) or []


# ---------------------------------------------------------------------------
# 5) PUSH -> JobTread actual cost lines
# ---------------------------------------------------------------------------
def push_jobtread(dry=False, actor="jc-labor-sync"):
    """Write labor actuals into the JobTread job budget as cost items.

    Auto-writes at >= JT_AUTOWRITE_THRESHOLD per Steven's 2026-09-18 decision.
    Everything below that is listed and left for a human — a low-confidence
    match here writes real money into someone else's job.
    """
    rows = sb(f"""
      select l.id as alloc_id, l.job_id, l.person, l.week_start, l.hours, l.amount,
             l.labor_kind, j.jobtread_job_id, j.customer_name,
             coalesce(m.match_confidence, 1.0) as confidence
        from jc_labor_allocations l
        join jc_jobs j on j.id = l.job_id
        left join jc_cc_project_map m on m.cc_project_id = l.cc_project_id
       where j.jobtread_job_id is not null
         and l.amount > 0
         and not exists (
           select 1 from jc_jobtread_cost_log g
            where g.job_id = l.job_id and g.week_start = l.week_start
              and g.person = l.person and g.reversed_at is null)
       order by l.week_start, j.customer_name
    """) or []

    if not rows:
        print("  no new labor lines to push to JobTread")
        return 0

    wrote = skipped = 0
    for r in rows:
        conf = float(r["confidence"] or 0)
        if conf < JT_AUTOWRITE_THRESHOLD:
            print(f"    HELD  {r['customer_name']:<26} {r['week_start']} "
                  f"${r['amount']:>9} conf={conf:.2f} < {JT_AUTOWRITE_THRESHOLD} — needs a human")
            skipped += 1
            continue

        name = f"Labor — {r['person']} wk {r['week_start']}"
        payload = {
            "createCostItem": {
                "$": {
                    "jobId": r["jobtread_job_id"],
                    "name": name,
                    "description": f"{r['hours'] or 0:g} clocked hours (CompanyCam). "
                                   f"Share of actual payroll for the week — not an estimate.",
                    "quantity": 1,
                    "unitCost": float(r["amount"]),
                    "unitPrice": 0,
                    "hasFinalActualCost": True,
                },
                "id": {}, "name": {},
            }
        }

        if dry:
            print(f"    [dry-run] JT <- {r['customer_name']:<26} {r['week_start']} "
                  f"${r['amount']:>9} conf={conf:.2f}")
            wrote += 1
            continue

        resp = jt(payload)
        item_id = None
        if resp and isinstance(resp, dict):
            item_id = ((resp.get("createCostItem") or {}).get("id")
                       or (resp.get("data") or {}).get("createCostItem", {}).get("id"))
        if not item_id:
            degrade(f"JobTread createCostItem returned no id for {r['customer_name']} "
                    f"{r['week_start']} — resp={str(resp)[:200]}")

        sb(f"""insert into jc_jobtread_cost_log
                 (job_id,jobtread_job_id,jt_cost_item_id,week_start,person,category,
                  amount,hours,match_confidence,auto_written,written_by,request,response)
               values ({q(r['job_id'])}::uuid,{q(r['jobtread_job_id'])},{q(item_id)},
                       {q(r['week_start'])}::date,{q(r['person'])},
                       {q('contract_labor' if r['labor_kind']=='contract' else 'employee_labor')},
                       {q(r['amount'])},{q(r['hours'])},{q(conf)},true,{q(actor)},
                       {q(json.dumps(payload))}::jsonb,{q(json.dumps(resp))}::jsonb)""")
        wrote += 1

    print(f"  wrote {wrote} JobTread cost line(s); {skipped} held below "
          f"{JT_AUTOWRITE_THRESHOLD} confidence")
    return wrote


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pull", action="store_true", help="pull CompanyCam time entries")
    ap.add_argument("--from-json", help="ingest entries from a JSON file instead of the API")
    ap.add_argument("--days", type=int, default=14, help="lookback window for --pull")
    ap.add_argument("--match", action="store_true", help="propose CompanyCam project -> job matches")
    ap.add_argument("--allocate", action="store_true", help="split ready payroll weeks by hours")
    ap.add_argument("--force-unmapped", action="store_true",
                    help="allocate even when hours sit on unmapped projects")
    ap.add_argument("--push-sm", action="store_true", help="drain the ServiceMinder note queue")
    ap.add_argument("--auto-queue-sm", action="store_true",
                    help="also queue every changed job summary, without a person confirming the proposal first")
    ap.add_argument("--push-jt", action="store_true", help="write actual cost lines to JobTread")
    ap.add_argument("--all", action="store_true", help="the nightly run: every step")
    ap.add_argument("--dry-run", action="store_true", help="report only, write nothing")
    args = ap.parse_args()

    if not SRK:
        print("SUPABASE_SERVICE_ROLE_KEY not set", file=sys.stderr)
        return 2

    steps = [args.pull, args.from_json, args.match, args.allocate, args.push_sm, args.push_jt]
    if args.all or not any(steps):
        args.pull = args.match = args.allocate = args.push_sm = args.push_jt = True

    dry = args.dry_run
    print(f"jc-labor-sync {'[DRY RUN] ' if dry else ''}{dt.datetime.now().isoformat(timespec='seconds')}")

    if args.pull or args.from_json:
        print("\n[1/5] pull CompanyCam time entries")
        pull_entries(args.days, args.from_json, dry)
    if args.match:
        print("\n[2/5] match CompanyCam projects to jobs")
        match_projects(dry)
    if args.allocate:
        print("\n[3/5] allocate payroll weeks by clocked hours")
        allocate(dry, force_unmapped=args.force_unmapped)
    if args.push_sm:
        print("\n[4/5] push cost summaries to ServiceMinder")
        push_serviceminder(dry, auto_queue=args.auto_queue_sm)
    if args.push_jt:
        print("\n[5/5] push actual cost lines to JobTread")
        push_jobtread(dry)

    if DEGRADATIONS:
        print("\nDEGRADATIONS — an empty result next to one of these is UNVERIFIED, not clean:")
        for d in DEGRADATIONS:
            print(f"  · {d}")
        return 1
    print("\nall pipes healthy")
    return 0


if __name__ == "__main__":
    sys.exit(main())
