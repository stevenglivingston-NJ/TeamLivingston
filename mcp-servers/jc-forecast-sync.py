#!/usr/bin/env python3
"""
jc-forecast-sync.py — build the SOLD side of job costing from the real systems.

Populates `jc_forecast_lines` per job from two sources:
  * ServiceMinder accepted proposals  -> source='sm_proposal'      (what we SOLD:
    line description, qty, UnitPrice/UnitCost, ExtendedTotal = amount charged)
  * JobTread job cost items           -> source='jobtread'         (the BREAKOUT:
    costType / costCode / costGroup, unitCost, unitPrice)

Why this matters: vendor invoices map to a SOLD LINE, not just a job. Until these
rows exist the gate can only check job+category. It also replaces the placeholder
`foreman_estimate` category rows seeded on 2026-09-01.

All HTTP goes through curl on purpose — python-urllib gets a 403 from the session
egress proxy and would silently return zero rows (see CLAUDE.md).

Usage:
  python3 mcp-servers/jc-forecast-sync.py --dry-run      # report, write nothing
  python3 mcp-servers/jc-forecast-sync.py --apply        # write jc_forecast_lines
  python3 mcp-servers/jc-forecast-sync.py --apply --job "Maureen  Mycka"
"""
import json, os, subprocess, sys, argparse, re
from collections import defaultdict

SUPA = os.environ.get("SUPABASE_URL", "https://tguwpswcneywvscxzyef.supabase.co").replace(".supabase.com", ".supabase.co")
SRK  = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
JT_KEY = os.environ.get("JOBTREAD_GRANT_KEY", "")
SM_KEYS = {"KTU": os.environ.get("SM_KEY_KTU", ""), "BTU": os.environ.get("SM_KEY_BTU", "")}
SM_BASE = "https://serviceminder.io/api"

def curl(args, timeout=90):
    r = subprocess.run(["curl", "-sS", "--max-time", str(timeout)] + args,
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"curl failed: {r.stderr[:300]}")
    return r.stdout

def sb(sql):
    out = curl(["-X", "POST", f"{SUPA}/rest/v1/rpc/exec_sql",
                "-H", f"apikey: {SRK}", "-H", f"Authorization: Bearer {SRK}",
                "-H", "Content-Type: application/json",
                "-d", json.dumps({"query": sql})])
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        raise RuntimeError(f"supabase returned non-JSON: {out[:300]}")

def sm(location, endpoint, body):
    # ServiceMinder takes the ApiKey INSIDE the json body (not a header), and
    # signals "no such endpoint" with an empty 200 body rather than a 404.
    payload = dict(body); payload["ApiKey"] = SM_KEYS[location]
    out = curl(["-X", "POST", f"{SM_BASE}/{endpoint}",
                "-H", "Content-Type: application/json",
                "-d", json.dumps(payload)])
    if not out.strip():
        return None          # SM signals "no such endpoint" with an empty 200 body
    return json.loads(out)

def jt(query):
    payload = {"query": {"$": {"grantKey": JT_KEY}, **query}}
    out = curl(["-X", "POST", "https://api.jobtread.com/pave",
                "-H", "Content-Type: application/json", "-d", json.dumps(payload)])
    return json.loads(out)

def q(v):
    """Quote a value for inline SQL."""
    if v is None or v == "":
        return "null"
    if isinstance(v, (int, float)):
        return str(v)
    return "'" + str(v).replace("'", "''") + "'"

# --- category mapping -------------------------------------------------------
# JCA categories: direct_materials | contract_labor | employee_labor |
#                 sales_commission | other
LABOR_RX = re.compile(r"\b(labor|labour|install(ation)?|shop|demo|deliver|freight|"
                      r"handling|carpent|plumb|electric|tile setter|painting labor)\b", re.I)
COMMISSION_RX = re.compile(r"commission", re.I)
FEE_RX = re.compile(r"\b(fee|permit|dumpster|general conditions|overhead|contingency)\b", re.I)

JT_COSTTYPE_MAP = {
    "labor": "contract_labor",
    "materials": "direct_materials",
    "fixture": "direct_materials",
    "installation materials": "direct_materials",
    "labor & materials (inclusive)": "direct_materials",
    "other": "other",
    "fee": "other",
    "selection": "other",
}

def categorize(text, cost_type=None, is_internal=False):
    if cost_type:
        m = JT_COSTTYPE_MAP.get(cost_type.strip().lower())
        if m:
            return m
    t = text or ""
    if COMMISSION_RX.search(t):
        return "sales_commission"
    if LABOR_RX.search(t):
        return "employee_labor" if is_internal else "contract_labor"
    if FEE_RX.search(t):
        return "other"
    return "direct_materials"

def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None

# --- load jobs --------------------------------------------------------------
def load_jobs(job_filter=None):
    rows = sb("select id, brand, customer_name, sm_contact_id, sm_proposal_id, "
              "jobtread_job_id, contract_total from jc_jobs order by customer_name")
    if isinstance(rows, dict):
        raise RuntimeError(f"jc_jobs read failed: {rows}")
    if job_filter:
        rows = [r for r in rows if job_filter.lower() in (r["customer_name"] or "").lower()]
    return rows

# --- ServiceMinder: contact -> proposals ------------------------------------
def sm_proposal_index(brand):
    """Invoices carry ProposalId on ~100% of rows; proposals themselves are only
    queryable while OPEN, so we discover accepted proposals invoice-first."""
    idx = defaultdict(set)
    skip, take = 0, 200
    while True:
        res = sm(brand, "invoice/query", {"FromDate": "2025-01-01", "Skip": skip, "Take": take})
        if not res:
            break
        invs = res.get("Invoices") or []
        for inv in invs:
            cid, pid = inv.get("ContactId"), inv.get("ProposalId")
            if cid and pid:
                idx[int(cid)].add(int(pid))
        if len(invs) < take:
            break
        skip += take
    return idx

def sm_proposal_lines(brand, proposal_id):
    res = sm(brand, "proposal/details", {"Id": proposal_id})
    if not res:
        return None
    return res

def lines_from_proposal(prop):
    """Yield (description, category, qty, unit_cost, forecasted_cost,
              amount_charged, source_line_id, is_change_order)."""
    out = []
    for ln in (prop.get("ProposalLines") or []):
        part = ln.get("Part") or {}
        desc = (ln.get("LineDescription") or part.get("Name")
                or part.get("Description") or "").strip()
        if not desc:
            continue
        qty = num(ln.get("Quantity")) or 0
        ucost = num(ln.get("UnitCost"))
        if ucost is None:
            ucost = num(part.get("UnitCost"))
        charged = num(ln.get("ExtendedTotal"))
        internal = bool(ln.get("IsInternal"))
        cat = categorize(desc, is_internal=internal)
        fcost = (qty * ucost) if (ucost is not None and qty) else None
        out.append({
            "description": desc[:400], "category": cat, "qty": qty or 1,
            "unit_cost": ucost, "forecasted_cost": fcost,
            "amount_charged": None if internal else charged,
            "source_line_id": str(ln.get("Id") or ""), "is_change_order": False,
        })
    return out

# --- JobTread: job -> cost items -------------------------------------------
def jt_cost_items(job_id):
    res = jt({"job": {"$": {"id": job_id}, "id": {}, "name": {},
                      "costItems": {"$": {"size": 100}, "nodes": {
                          "id": {}, "name": {}, "description": {}, "quantity": {},
                          "unitCost": {}, "unitPrice": {}, "cost": {}, "price": {},
                          "costType": {"name": {}}, "costCode": {"name": {}},
                          "costGroup": {"name": {}}}}}})
    job = (res or {}).get("job") or {}
    return (job.get("costItems") or {}).get("nodes") or []

def lines_from_jt(items):
    out = []
    for it in items:
        name = (it.get("name") or it.get("description") or "").strip()
        if not name:
            continue
        ctype = ((it.get("costType") or {}) or {}).get("name")
        qty = num(it.get("quantity")) or 0
        ucost = num(it.get("unitCost"))
        cost = num(it.get("cost"))
        price = num(it.get("price"))
        cat = categorize(name, cost_type=ctype)
        out.append({
            "description": name[:400], "category": cat, "qty": qty or 1,
            "unit_cost": ucost,
            "forecasted_cost": cost if cost is not None else ((qty * ucost) if ucost else None),
            "amount_charged": price,
            "cost_code": ((it.get("costCode") or {}) or {}).get("name"),
            "source_line_id": str(it.get("id") or ""),
        })
    return out

def insert_lines(job_id, source, lines):
    if not lines:
        return 0
    vals = []
    for l in lines:
        vals.append("({},{},{},{},{},{},{},{},{},{})".format(
            q(job_id), q(l["description"]), q(l["category"]), q(l["qty"]),
            q(l.get("unit_cost")), q(l.get("forecasted_cost")), q(l.get("amount_charged")),
            q(l.get("cost_code")), q(source), q(l.get("source_line_id"))))
    sql = ("delete from jc_forecast_lines where job_id={} and source={};\n"
           "insert into jc_forecast_lines (job_id,description,category,qty,unit_cost,"
           "forecasted_cost,amount_charged,cost_code,source,source_line_id) values\n{};"
           ).format(q(job_id), q(source), ",\n".join(vals))
    sb(sql)
    return len(vals)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--job", default=None)
    a = ap.parse_args()
    apply = a.apply and not a.dry_run

    jobs = load_jobs(a.job)
    print(f"jobs: {len(jobs)}")
    idx = {b: sm_proposal_index(b) for b in ("KTU", "BTU")}
    print("SM proposal index: " + ", ".join(f"{b}={len(idx[b])} contacts" for b in idx))

    tot_sm = tot_jt = jobs_sm = jobs_jt = 0
    for j in jobs:
        brand, cid = j["brand"], j.get("sm_contact_id")
        # --- ServiceMinder sold lines
        pids = sorted(idx.get(brand, {}).get(int(cid), [])) if cid else []
        sm_lines, chosen = [], None
        for pid in pids:
            prop = sm_proposal_lines(brand, pid)
            if not prop:
                continue
            got = lines_from_proposal(prop)
            if got:
                sm_lines += got
                chosen = chosen or pid
        if sm_lines:
            jobs_sm += 1
            tot_sm += len(sm_lines)
            if apply:
                insert_lines(j["id"], "sm_proposal", sm_lines)
                if chosen and not j.get("sm_proposal_id"):
                    sb(f"update jc_jobs set sm_proposal_id={chosen} where id={q(j['id'])}")
        # --- JobTread breakout
        jt_lines = []
        if j.get("jobtread_job_id"):
            try:
                jt_lines = lines_from_jt(jt_cost_items(j["jobtread_job_id"]))
            except Exception as e:
                print(f"  ! JT {j['customer_name']}: {e}")
        if jt_lines:
            jobs_jt += 1
            tot_jt += len(jt_lines)
            if apply:
                insert_lines(j["id"], "jobtread", jt_lines)
        print(f"  {j['customer_name'][:34]:35s} SM {len(sm_lines):3d}  JT {len(jt_lines):3d}"
              + ("" if (sm_lines or jt_lines) else "   <- no sold lines found"))

    print(f"\n{'APPLIED' if apply else 'DRY RUN'}: "
          f"{tot_sm} SM proposal lines across {jobs_sm} jobs; "
          f"{tot_jt} JobTread cost items across {jobs_jt} jobs")
    if apply:
        # placeholder category rows are superseded once real lines land
        # NOTE: SM proposal lines carry PRICE but (on KTU) almost never UnitCost,
        # so they do NOT supersede the estimate rows — the two are complementary:
        # SM gives the sold-line detail, the estimate gives the cost baseline.
        # Only drop an estimate row where real COSTED lines exist for that job.
        sb("delete from jc_forecast_lines f where f.source='foreman_estimate' "
           "and exists (select 1 from jc_forecast_lines r where r.job_id=f.job_id "
           "and r.source in ('sm_proposal','jobtread') "
           "and coalesce(r.forecasted_cost,0) > 0)")
        print("estimate rows dropped only where real COSTED lines exist")

if __name__ == "__main__":
    main()
