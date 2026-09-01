#!/usr/bin/env python3
"""jatalia_sweep.py — the deterministic half of Cellar's Earthwise run.

Mirrors mcp-servers/lead-sweep.py (Goldeneye's deterministic half): a single pass
that pulls the marketplace data, computes the exact fulfillment / billing /
exception numbers, and writes them to the intranet's `intranet_records` table so
the Earthwise tabs render precise figures. Cellar reads the emitted JSON digest and
writes the judgment layer (cellar_briefing + exec_summary) — it does NOT re-derive
the analysis.

Pipeline (each step is a tested builder ported from the standalone Jatalia dashboard):
  shopify_costs.py       -> data/shopify_costs.json     (Admin API: prices + unit costs)
  build_jatalia_data.py  -> data/jatalia_billing_data.json
  build_ops_data.py      -> data/jatalia_ops_data.json
  build_latency_data.py  -> data/jatalia_latency_data.json  (ShipStation scan-latency)
  check_exceptions.py    -> data/exceptions_<today>.json

Then translate → upsert to Supabase `intranet_records` (brand='Earthwise'), one
section per tab, write-then-prune by fields->>'scan_date' (insert today first, then
delete that section's non-today rows — stale beats blank), via ../sb.sh (service
role, not permission-gated).

Sections written (Cellar owns cellar_briefing + exec_summary separately):
  cellar_fulfillment  — scan-latency rollup (summary, top problem SKUs, worst orders)
  cellar_orders       — actionable at-risk orders (overdue no-scan, worst late, unshipped)
  cellar_exceptions   — Amazon<Shopify, shipping-negative, low-margin, high-returns
  cellar_billing      — shipping collected vs cost by store, latest period

Env (Cloud env → Environment variables; see mcp-servers/.env.example):
  SHIPSTATION_API_KEY, SHOPIFY_ADMIN_TOKEN, SHOPIFY_SHOP_DOMAIN,
  SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY  (AMAZON_SP_* / WALMART_* optional)

Usage:
  python3 jatalia_sweep.py                 # full run: build + translate + write + digest
  python3 jatalia_sweep.py --skip-build    # reuse existing data/*.json, then write
  python3 jatalia_sweep.py --dry-run       # translate existing data, print rows, write nothing
"""
import argparse
import datetime as dt
import glob
import json
import os
import subprocess
import sys

BRAND = "Earthwise"
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.environ.get("JATALIA_DATA_DIR", os.path.join(HERE, "data"))
SB = os.path.join(HERE, "..", "sb.sh")
DIGEST_OUT = os.environ.get("JATALIA_SWEEP_OUT", os.path.join(DATA, "jatalia_sweep.json"))
TODAY = os.environ.get("SWEEP_TODAY") or dt.date.today().isoformat()

# Builders that must run from HERE so their relative data/ paths resolve.
BUILDERS = [
    ("shopify_costs.py", 180, False),        # (script, timeout_s, required)
    ("walmart_pull.py", 180, False),         # returns feed (optional; skips w/o WMT creds)
    ("build_jatalia_data.py", 420, True),
    ("build_ops_data.py", 300, False),
    ("build_latency_data.py", 900, True),
    ("check_exceptions.py", 120, True),
]


# ----------------------------------------------------------------------------- helpers
def biz_days(d1, d2):
    if d2 <= d1:
        return 0
    n, cur = 0, d1
    while cur < d2:
        cur += dt.timedelta(days=1)
        if cur.weekday() < 5:
            n += 1
    return n


def load(path, default=None):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def latest_exceptions():
    files = sorted(glob.glob(os.path.join(DATA, "exceptions_*.json")))
    files = [f for f in files if os.path.basename(f)[11:15].isdigit()]  # exceptions_YYYY-...
    return load(files[-1], {}) if files else {}


def money(x):
    try:
        return round(float(x or 0), 2)
    except (TypeError, ValueError):
        return 0.0


# ----------------------------------------------------------------------------- translate
def t_fulfillment(latency, exc):
    """cellar_fulfillment — scan-latency rollup. Prefers the exceptions
    DELAYED_SHIPMENTS block (already summarized), falls back to raw latency."""
    rows = []
    ds = (exc or {}).get("DELAYED_SHIPMENTS") or {}
    summ = ds.get("summary") or (latency or {}).get("summary") or {}
    ns_c = summ.get("no_scan_count", 0)
    ns_v = money(summ.get("no_scan_value"))
    la_c = summ.get("late_scan_count", 0)
    la_v = money(summ.get("late_scan_value"))
    pct = summ.get("pct_problem", 0)
    tracked = summ.get("tracked_labels") or (latency or {}).get("labels_tracked", 0)
    sev = "urgent" if pct >= 8 else "warn" if pct >= 4 else "info"
    rows.append({
        "kind": "summary", "severity": sev,
        "title": f"{pct}% of {tracked} labels delayed",
        "detail": (f"{ns_c} printed-no-scan (${ns_v:,.0f}) + {la_c} scanned-late "
                   f">2 biz days (${la_v:,.0f}). Root cause is usually carrier pickup, not stock."),
        "no_scan_count": ns_c, "no_scan_value": ns_v,
        "late_scan_count": la_c, "late_scan_value": la_v,
        "pct_problem": pct, "tracked_labels": tracked,
    })
    # per-carrier split (from raw latency rows, if present)
    carriers = {}
    for r in (latency or {}).get("rows", []):
        if r.get("state") in ("no_scan", "late_scan"):
            c = carriers.setdefault(r.get("carrier", "?"), {"count": 0, "value": 0.0})
            c["count"] += 1
            c["value"] += money(r.get("value"))
    for carrier, agg in sorted(carriers.items(), key=lambda kv: -kv[1]["count"])[:6]:
        rows.append({"kind": "carrier", "severity": "info", "title": carrier,
                     "detail": f"{agg['count']} delayed labels · ${agg['value']:,.0f}",
                     "dimension": carrier, "count": agg["count"], "value": money(agg["value"])})
    # top problem SKUs
    for s in (ds.get("top_problem_skus") or [])[:10]:
        rows.append({"kind": "sku", "severity": "info", "title": s.get("sku", "?"),
                     "detail": (f"{s.get('delayed_label_count', 0)} labels · "
                                f"{s.get('delayed_units', 0)} units · ${money(s.get('delayed_value')):,.0f}"),
                     "sku": s.get("sku"), "labels": s.get("delayed_label_count"),
                     "units": s.get("delayed_units"), "value": money(s.get("delayed_value"))})
    return rows


def t_orders(latency, ops):
    """cellar_orders — actionable at-risk orders (overdue no-scan, worst late, unshipped)."""
    rows = []
    today = dt.date.fromisoformat(TODAY)
    thr = (latency or {}).get("threshold_biz_days", 2)
    problems = [r for r in (latency or {}).get("rows", []) if r.get("state") in ("no_scan", "late_scan")]

    overdue_noscan, late = [], []
    for r in problems:
        if r.get("state") == "no_scan":
            try:
                if biz_days(dt.date.fromisoformat(r["label_date"]), today) > thr:
                    overdue_noscan.append(r)
            except (KeyError, ValueError):
                pass
        else:
            late.append(r)
    late.sort(key=lambda r: -(r.get("latency_biz_days") or 0))

    for r in overdue_noscan:
        rows.append({"ref": r.get("order"), "type": "no-scan", "channel": r.get("store"),
                     "carrier": r.get("carrier"), "severity": "urgent",
                     "status": f"printed {r.get('label_date')} · {r.get('days_since')}d, no carrier scan",
                     "sku": r.get("top_sku"), "item": (r.get("items") or "")[:70],
                     "value": money(r.get("value")), "customer": r.get("customer"),
                     "action": "Confirm carrier pickup / re-label — A-to-z / INR risk"})
    for r in late[:30]:
        rows.append({"ref": r.get("order"), "type": "late-scan", "channel": r.get("store"),
                     "carrier": r.get("carrier"), "severity": "warn",
                     "status": (f"{r.get('latency_biz_days')} biz-day gap "
                                f"(printed {r.get('label_date')} → scan {r.get('first_scan')})"),
                     "sku": r.get("top_sku"), "item": (r.get("items") or "")[:70],
                     "value": money(r.get("value")), "customer": r.get("customer"),
                     "action": "Watch carrier SLA on this lane"})
    for r in (ops or {}).get("unshipped", []):
        rows.append({"ref": r.get("order"), "type": "unshipped", "channel": r.get("store"),
                     "carrier": "", "severity": "warn",
                     "status": f"{r.get('status')} · {r.get('biz_days')} biz days since order",
                     "sku": "", "item": (r.get("items") or "")[:70],
                     "value": money(r.get("value")), "customer": r.get("customer", ""),
                     "action": "Ship or cancel before SLA breach"})
    return rows


def t_exceptions(exc):
    """cellar_exceptions — pricing / margin / shipping / returns anomalies."""
    rows = []
    abs_ = (exc or {}).get("AMAZON_BELOW_SHOPIFY") or []
    if abs_:
        rows.append({"kind": "amazon_below_shopify", "severity": "warn",
                     "title": f"{len(abs_)} SKUs priced below Shopify on Amazon",
                     "detail": "Amazon undercuts the DTC price — margin leak / channel conflict."})
        for it in abs_[:8]:
            rows.append({"kind": "amazon_below_shopify_item", "severity": "info",
                         "title": it.get("ew_sku", "?"),
                         "detail": (f"{it.get('name', '')[:44]} — Shopify ${money(it.get('shopify_price')):,.2f} "
                                    f"vs Amazon ${money(it.get('amazon_price')):,.2f} "
                                    f"(-${money(it.get('gap_dollars')):,.2f}, {it.get('gap_pct')}%)"),
                         "sku": it.get("ew_sku"), "value": money(it.get("gap_dollars"))})
    neg = (exc or {}).get("SHIPPING_NEGATIVE") or []
    if neg:
        loss = sum(money(x.get("loss")) for x in neg)
        rows.append({"kind": "shipping_negative", "severity": "warn",
                     "title": f"{len(neg)} store/period pairs losing money on shipping",
                     "detail": f"Total shipping loss ${loss:,.0f} — collected < label cost."})
        for x in neg[:6]:
            rows.append({"kind": "shipping_negative_item", "severity": "info",
                         "title": f"{x.get('store')} · {x.get('period')}",
                         "detail": (f"collected ${money(x.get('shipping_collected')):,.0f} vs cost "
                                    f"${money(x.get('shipping_cost')):,.0f} → loss ${money(x.get('loss')):,.0f}"),
                         "value": money(x.get("loss"))})
    lm = (exc or {}).get("LOW_MARGIN") or []
    if lm:
        rows.append({"kind": "low_margin", "severity": "warn",
                     "title": f"{len(lm)} SKUs under margin target (last 90d)",
                     "detail": "COGS+landed erodes gross below target — reprice or cut."})
        for x in lm[:8]:
            rows.append({"kind": "low_margin_item", "severity": "info",
                         "title": x.get("sku", "?"),
                         "detail": (f"{x.get('name', '')[:40]} — GM {x.get('gm_pct', '?')}% on "
                                    f"{x.get('units_90d')}u / ${money(x.get('sales_90d')):,.0f}"),
                         "sku": x.get("sku"), "value": money(x.get("gross_90d"))})
    rh = (exc or {}).get("RETURNS_HIGH") or {}
    for x in (rh.get("flagged") or [])[:6]:
        rows.append({"kind": "returns_high", "severity": "info",
                     "title": f"{x.get('store', '')} · {x.get('sku', '?')}",
                     "detail": f"{x.get('return_pct', x.get('returned_pct', '?'))}% returned",
                     "sku": x.get("sku")})
    return rows


def t_billing(billing):
    """cellar_billing — shipping collected vs cost by store, latest period with data."""
    rows = []
    periods = [p for p in (billing or {}).get("periods", []) if p.get("store_summary")]
    if not periods:
        return rows
    p = periods[-1]
    label = p.get("label", p.get("id", ""))
    tot_c = tot_k = 0.0
    for store, agg in (p.get("store_summary") or {}).items():
        col = money(agg.get("shipping_collected"))
        cost = money(agg.get("shipping_cost"))
        net = round(col - cost, 2)
        tot_c += col
        tot_k += cost
        rows.append({"kind": "store", "severity": "warn" if net < 0 else "info",
                     "title": f"{store} — {label}", "store": store, "period": label,
                     "collected": col, "cost": cost, "net": net,
                     "detail": f"shipping collected ${col:,.0f} vs cost ${cost:,.0f} → net ${net:,.0f}"})
    net = round(tot_c - tot_k, 2)
    rows.insert(0, {"kind": "total", "severity": "warn" if net < 0 else "info",
                    "title": f"All stores — {label}", "period": label,
                    "collected": round(tot_c, 2), "cost": round(tot_k, 2), "net": net,
                    "detail": f"shipping collected ${tot_c:,.0f} vs cost ${tot_k:,.0f} → net ${net:,.0f}"})
    return rows


# ----------------------------------------------------------------------------- Supabase write
def _sql_lit(s):
    return "'" + str(s).replace("'", "''") + "'"


def write_section(section, rows):
    """write-then-prune one section into intranet_records via ../sb.sh."""
    if not os.path.exists(SB):
        raise RuntimeError(f"sb.sh not found at {SB}")
    values = []
    for i, r in enumerate(rows):
        fields = dict(r)
        fields["brand"] = BRAND
        fields["scan_date"] = TODAY
        values.append(f"({_sql_lit(section)}, {i}, {_sql_lit(json.dumps(fields))}::jsonb)")
    stmts = []
    if values:
        stmts.append(
            "INSERT INTO intranet_records (section, sort_order, fields) VALUES\n"
            + ",\n".join(values) + ";"
        )
    stmts.append(
        f"DELETE FROM intranet_records WHERE section = {_sql_lit(section)} "
        f"AND (fields->>'scan_date') IS DISTINCT FROM {_sql_lit(TODAY)};"
    )
    sql = "\n".join(stmts)
    proc = subprocess.run(["bash", SB, sql], capture_output=True, text=True)
    ok = proc.returncode == 0 and '"error"' not in (proc.stdout or "")
    return ok, (proc.stdout or proc.stderr or "").strip()[:300]


# ----------------------------------------------------------------------------- run
def run_builders():
    py = sys.executable or "python3"
    for script, timeout, required in BUILDERS:
        path = os.path.join(HERE, script)
        if not os.path.exists(path):
            print(f"⚠ {script}: missing, skipped", file=sys.stderr)
            if required:
                return False
            continue
        print(f"▸ running {script} …", file=sys.stderr)
        try:
            proc = subprocess.run([py, script], cwd=HERE, timeout=timeout)
            if proc.returncode != 0 and required:
                print(f"✗ {script} exited {proc.returncode} (required) — aborting build", file=sys.stderr)
                return False
        except subprocess.TimeoutExpired:
            print(f"✗ {script} timed out after {timeout}s"
                  + (" (required) — aborting" if required else " — continuing"), file=sys.stderr)
            if required:
                return False
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="translate existing data, write nothing")
    ap.add_argument("--skip-build", action="store_true", help="reuse existing data/*.json")
    args = ap.parse_args()

    if not args.dry_run and not args.skip_build:
        if not run_builders():
            print("SWEEP ABORTED: a required builder failed.", file=sys.stderr)
            return 1

    latency = load(os.path.join(DATA, "jatalia_latency_data.json"), {})
    ops = load(os.path.join(DATA, "jatalia_ops_data.json"), {})
    billing = load(os.path.join(DATA, "jatalia_billing_data.json"), {})
    exc = latest_exceptions()

    sections = {
        "cellar_fulfillment": t_fulfillment(latency, exc),
        "cellar_orders": t_orders(latency, ops),
        "cellar_exceptions": t_exceptions(exc),
        "cellar_billing": t_billing(billing),
    }

    # digest for Cellar (the agent narrates from this — it does not re-derive)
    digest = {
        "generated": dt.datetime.now(dt.timezone.utc).isoformat() if not os.environ.get("SWEEP_TODAY") else None,
        "scan_date": TODAY,
        "brand": BRAND,
        "counts": {k: len(v) for k, v in sections.items()},
        "sections": sections,
    }
    try:
        os.makedirs(os.path.dirname(DIGEST_OUT), exist_ok=True)
        with open(DIGEST_OUT, "w") as fh:
            json.dump(digest, fh, indent=1)
    except OSError as e:
        print(f"⚠ could not write digest: {e}", file=sys.stderr)

    print("\nJATALIA SWEEP — " + TODAY, file=sys.stderr)
    for sec, rows in sections.items():
        print(f"  {sec:20} {len(rows):3} rows", file=sys.stderr)

    if args.dry_run:
        print("\n[dry-run] sample rows:", file=sys.stderr)
        for sec, rows in sections.items():
            if rows:
                print(f"  {sec}: {json.dumps(rows[0])[:200]}", file=sys.stderr)
        print(json.dumps(digest["counts"]))
        return 0

    failures = 0
    for sec, rows in sections.items():
        ok, msg = write_section(sec, rows)
        print(f"  {'✓' if ok else '✗'} {sec}: {len(rows)} rows → intranet_records {'' if ok else '| ' + msg}",
              file=sys.stderr)
        failures += (0 if ok else 1)

    print(json.dumps({"scan_date": TODAY, "counts": digest["counts"], "write_failures": failures}))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
