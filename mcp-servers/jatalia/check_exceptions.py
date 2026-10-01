"""Daily exception scan for the Jatalia ops dashboard.

Runs after refresh_and_deploy.sh's build steps complete. Reads the freshly
generated jatalia_billing_data.json + jatalia_latency_data.json and flags:

  1. AMAZON_BELOW_SHOPIFY  — per-SKU Amazon listing price < Shopify retail
  2. SHIPPING_NEGATIVE     — shipping_cost > shipping_collected per store/period
  3. LOW_MARGIN            — GM% < 65% per active SKU (last 90 days)
  4. RETURNS_HIGH          — returns / units sold > 5% (STUBBED — Amazon SP-API
                              + Walmart Marketplace returns pull not yet built)

Output:
  data/exceptions_YYYY-MM-DD.json   structured
  data/exceptions_latest.txt        human-readable (consumed by send_alert.py)

Exit codes:
  0 = no exceptions raised (silent day)
  1 = exceptions found and report written
"""
import json, datetime as dt, sys
from pathlib import Path
from collections import defaultdict

DATA = Path(__file__).resolve().parent / "data"
TODAY = dt.date.today()

billing = json.loads((DATA / "jatalia_billing_data.json").read_text())
try:
    latency = json.loads((DATA / "jatalia_latency_data.json").read_text())
except Exception:
    latency = None

# 1.5 — Data-age guard: skip delayed-shipment alerts if latency data is
# >36h old (treat as stale; daily cron should produce fresh data every 24h)
import datetime as _dtm
def _hours_since(iso_ts):
    if not iso_ts: return float("inf")
    try:
        d = _dtm.datetime.fromisoformat(iso_ts)
    except Exception:
        return float("inf")
    return (_dtm.datetime.now() - d).total_seconds() / 3600

if latency:
    age_h = _hours_since(latency.get("generated"))
    if age_h > 36:
        print(f"check_exceptions.py — WARN: latency data is {age_h:.1f}h old; "
              f"skipping delayed-shipment alert to avoid false positives.",
              file=sys.stderr)
        latency = {"_stale": True, "_age_hours": age_h, "summary": {}, "problem_skus": [], "rows": []}
try:
    walmart_returns = json.loads((DATA / "walmart_returns.json").read_text())
except Exception:
    walmart_returns = None
try:
    amazon_returns = json.loads((DATA / "amazon_returns.json").read_text())
except Exception:
    amazon_returns = None

# ---------------------------------------------------------------------------
# 1) AMAZON_BELOW_SHOPIFY — per-SKU live price check from price_master
# ---------------------------------------------------------------------------
amazon_below = []
for r in billing.get("price_master", []):
    sp, ap = r.get("shopify_price"), r.get("amazon_price")
    if sp is None or ap is None or sp <= 0 or ap <= 0:
        continue
    sp, ap = float(sp), float(ap)
    if ap < sp:
        amazon_below.append({
            "ew_sku": r["ew_sku"],
            "name": r.get("name",""),
            "shopify_price": sp,
            "amazon_price": ap,
            "gap_dollars": round(sp - ap, 2),
            "gap_pct": round((sp - ap) / sp * 100, 1),
        })
# Sort biggest gap first
amazon_below.sort(key=lambda x: -x["gap_dollars"])

# ---------------------------------------------------------------------------
# 2) SHIPPING_NEGATIVE — per-store per-period
# ---------------------------------------------------------------------------
shipping_negative = []
for p in billing.get("periods", []):
    for store, summary in (p.get("store_summary") or {}).items():
        cost = summary.get("shipping_cost", 0) or 0
        collected = summary.get("shipping_collected", 0) or 0
        if cost > collected and cost > 0:
            shipping_negative.append({
                "period": p["label"],
                "store": store,
                "shipping_collected": round(collected, 2),
                "shipping_cost": round(cost, 2),
                "loss": round(cost - collected, 2),
            })
shipping_negative.sort(key=lambda x: -x["loss"])
# Cap to the trailing 6 periods (~12 weeks) — anything older we've already seen
shipping_negative = shipping_negative[:30]

# ---------------------------------------------------------------------------
# 3) LOW_MARGIN — GM% < 65% per SKU last 90 days
# ---------------------------------------------------------------------------
# Walk recent periods, aggregate per SKU
MARGIN_TARGET = 0.65
cutoff = (TODAY - dt.timedelta(days=90)).isoformat()
agg = defaultdict(lambda: {"units":0, "sales":0.0, "cogs":0.0, "name":"", "stores":set()})
for p in billing.get("periods", []):
    if p["end"] < cutoff: continue
    for s in p.get("skus", []):
        sku = s.get("sku") or "(no SKU)"
        bucket = agg[sku]
        bucket["units"] += s.get("units", 0) or 0
        bucket["sales"] += s.get("sales", 0) or 0
        bucket["cogs"]  += s.get("cogs",  0) or 0
        bucket["name"]   = s.get("name", bucket["name"])
        if s.get("store"): bucket["stores"].add(s["store"])

# Apply inter-co markup of 10% (default in dashboard markup() input)
MARKUP = 0.10
low_margin = []
for sku, b in agg.items():
    if b["sales"] <= 0 or b["units"] < 3:
        continue  # ignore SKUs with no/very-low sales noise
    total_cost = b["cogs"] * (1 + MARKUP)
    gross = b["sales"] - total_cost
    gm = gross / b["sales"] if b["sales"] else None
    if gm is not None and gm < MARGIN_TARGET:
        low_margin.append({
            "sku": sku,
            "name": b["name"][:80],
            "stores": sorted(b["stores"]),
            "units_90d": int(b["units"]),
            "sales_90d": round(b["sales"], 2),
            "cogs_landed_90d": round(total_cost, 2),
            "gross_90d": round(gross, 2),
            "gm_pct": round(gm * 100, 1),
            "delta_vs_target_pts": round((MARGIN_TARGET - gm) * 100, 1),
        })
low_margin.sort(key=lambda x: x["gm_pct"])

# ---------------------------------------------------------------------------
# 4) DELAYED_SHIPMENTS — labels printed but no carrier scan, or scan > 2 biz days
# ---------------------------------------------------------------------------
delayed_summary = None
delayed_top_skus = []
delayed_worst_orders = []
if latency:
    s = latency.get("summary", {}) or {}
    delayed_summary = {
        "no_scan_count":   s.get("no_scan_count", 0),
        "no_scan_value":   s.get("no_scan_value", 0),
        "late_scan_count": s.get("late_scan_count", 0),
        "late_scan_value": s.get("late_scan_value", 0),
        "pct_problem":     s.get("pct_problem", 0),
        "tracked_labels":  latency.get("labels_tracked", 0),
        "window":          latency.get("window", {}),
    }
    delayed_top_skus = (latency.get("problem_skus") or [])[:15]
    # Worst 10 individual orders by latency_biz_days
    delayed_worst_orders = sorted(
        latency.get("rows") or [],
        key=lambda r: -r.get("latency_biz_days", 0)
    )[:10]

# ---------------------------------------------------------------------------
# 5) RETURNS_HIGH — returns/units sold > 5% per SKU per store
# Walmart side LIVE (walmart_returns.json); Amazon side pending SP-API access
# ---------------------------------------------------------------------------
RETURN_THRESHOLD = 0.05

# Build units sold per SKU per store from billing periods (90d window)
units_sold = defaultdict(lambda: defaultdict(int))     # store -> sku -> qty
for p in billing.get("periods", []):
    if p.get("end", "1970-01-01") < cutoff: continue
    for s in p.get("skus", []):
        sku = s.get("sku") or "(no SKU)"
        store = s.get("store") or "?"
        units_sold[store][sku] += int(s.get("units", 0) or 0)

returns_high = []
returns_summary = {"sources": {}}

if walmart_returns:
    wm_rollup = walmart_returns.get("sku_rollup", {})
    wm_window = walmart_returns.get("window", {})
    returns_summary["sources"]["walmart"] = {
        "return_count": walmart_returns.get("summary", {}).get("return_count", 0),
        "refund_total": walmart_returns.get("summary", {}).get("refund_total", 0),
        "window": wm_window,
        "generated": walmart_returns.get("generated"),
    }
    for sku, r in wm_rollup.items():
        sold = units_sold.get("Walmart", {}).get(sku, 0)
        if sold < 5:
            continue   # too few sales to compute meaningful return rate
        rate = r["units"] / sold if sold else 0
        if rate > RETURN_THRESHOLD:
            returns_high.append({
                "store": "Walmart",
                "sku": sku,
                "units_sold_90d": sold,
                "units_returned_90d": r["units"],
                "return_count": r["return_count"],
                "refund_total": r["refund_total"],
                "return_rate_pct": round(rate * 100, 1),
            })

if amazon_returns:
    az_rollup = amazon_returns.get("sku_rollup", {})
    returns_summary["sources"]["amazon"] = {
        "return_count": amazon_returns.get("summary", {}).get("return_count", 0),
        "refund_total": amazon_returns.get("summary", {}).get("refund_total", 0),
        "window": amazon_returns.get("window", {}),
        "generated": amazon_returns.get("generated"),
    }
    for sku, r in az_rollup.items():
        sold = units_sold.get("Amazon", {}).get(sku, 0)
        if sold < 5: continue
        rate = r["units"] / sold if sold else 0
        if rate > RETURN_THRESHOLD:
            returns_high.append({
                "store": "Amazon",
                "sku": sku,
                "units_sold_90d": sold,
                "units_returned_90d": r["units"],
                "return_count": r["return_count"],
                "refund_total": r["refund_total"],
                "return_rate_pct": round(rate * 100, 1),
            })
else:
    returns_summary["amazon_status"] = (
        "PENDING — Amazon SP-API access needs Selling Partner role added to "
        "LWA app at developer.amazon.com. See CLAUDE.md."
    )

returns_high.sort(key=lambda x: -x["return_rate_pct"])

# ---------------------------------------------------------------------------
# Write outputs
# ---------------------------------------------------------------------------
out = {
    "scanned_at": dt.datetime.now().isoformat(timespec="seconds"),
    "data_generated_at": billing.get("generated"),
    "latency_generated_at": (latency or {}).get("generated"),
    "AMAZON_BELOW_SHOPIFY": amazon_below,
    "SHIPPING_NEGATIVE": shipping_negative,
    "LOW_MARGIN": low_margin,
    "DELAYED_SHIPMENTS": {
        "summary": delayed_summary,
        "top_problem_skus": delayed_top_skus,
        "worst_orders": delayed_worst_orders,
    },
    "RETURNS_HIGH": {
        "threshold_pct": int(RETURN_THRESHOLD * 100),
        "flagged": returns_high,
        "summary": returns_summary,
    },
}
DATA.mkdir(exist_ok=True)
(DATA / f"exceptions_{TODAY}.json").write_text(json.dumps(out, indent=2))

# Human-readable summary
lines = [
    f"Jatalia daily exception scan — {TODAY.isoformat()}",
    f"Data generated: {billing.get('generated')}",
    f"Latency data generated: {(latency or {}).get('generated','(missing)')}",
    "",
]

if amazon_below:
    lines.append(f"🔴 AMAZON BELOW SHOPIFY — {len(amazon_below)} SKU(s)")
    for r in amazon_below[:25]:
        lines.append(
            f"  {r['ew_sku']}  Shopify ${r['shopify_price']:.2f}  "
            f"Amazon ${r['amazon_price']:.2f}  gap -${r['gap_dollars']:.2f} "
            f"(-{r['gap_pct']}%)  {r['name'][:50]}"
        )
    if len(amazon_below) > 25:
        lines.append(f"  …and {len(amazon_below)-25} more")
    lines.append("")
else:
    lines.append("✓ AMAZON BELOW SHOPIFY — none\n")

if shipping_negative:
    lines.append(f"🔴 SHIPPING NEGATIVE — {len(shipping_negative)} period/store pair(s)")
    for r in shipping_negative[:15]:
        lines.append(
            f"  {r['period']:30}  {r['store']:8}  "
            f"collected ${r['shipping_collected']:>8,.2f}  "
            f"cost ${r['shipping_cost']:>8,.2f}  LOSS ${r['loss']:>8,.2f}"
        )
    lines.append("")
else:
    lines.append("✓ SHIPPING NEGATIVE — none\n")

if low_margin:
    lines.append(f"🔴 LOW MARGIN <65% (last 90d) — {len(low_margin)} SKU(s)")
    for r in low_margin[:25]:
        lines.append(
            f"  {r['sku']:20}  {r['gm_pct']:>5.1f}%  "
            f"(target 65%, -{r['delta_vs_target_pts']} pts)  "
            f"units {r['units_90d']:>4}  sales ${r['sales_90d']:>8,.2f}  "
            f"{r['name'][:40]}"
        )
    if len(low_margin) > 25:
        lines.append(f"  …and {len(low_margin)-25} more")
    lines.append("")
else:
    lines.append("✓ LOW MARGIN — none below 65%\n")

if delayed_summary and (delayed_summary["no_scan_count"] + delayed_summary["late_scan_count"]) > 0:
    s = delayed_summary
    lines.append(
        f"🔴 DELAYED SHIPMENTS — {s['no_scan_count']} no-scan (${s['no_scan_value']:,.2f}) + "
        f"{s['late_scan_count']} late-scan (${s['late_scan_value']:,.2f}) "
        f"= {s['pct_problem']}% of {s['tracked_labels']} tracked labels"
    )
    if delayed_top_skus:
        lines.append("  Top problem SKUs (most-delayed-labels):")
        for r in delayed_top_skus[:10]:
            lines.append(
                f"    {r['sku']:24}  {r['delayed_label_count']:>3} labels  "
                f"{r['delayed_units']:>3} units  ${r['delayed_value']:>8,.2f}"
            )
    if delayed_worst_orders:
        lines.append("  Worst individual orders (by biz-day latency):")
        for r in delayed_worst_orders[:6]:
            lines.append(
                f"    {r['order']:24}  {r['store']:8}  "
                f"{r['latency_biz_days']:>3} biz days  ${r['value']:>7,.2f}  "
                f"top SKU: {(r.get('top_sku') or '?')[:20]}"
            )
    lines.append("")
elif latency:
    lines.append("✓ DELAYED SHIPMENTS — none above threshold\n")
else:
    lines.append("⚠ DELAYED SHIPMENTS — latency data missing (build_latency_data.py never ran or failed)\n")

if returns_high:
    lines.append(f"🔴 HIGH RETURNS (>{int(RETURN_THRESHOLD*100)}% returned, last 90d) — {len(returns_high)} SKU(s)")
    for r in returns_high[:15]:
        lines.append(
            f"  {r['store']:8} {r['sku']:24}  "
            f"{r['return_rate_pct']:>5.1f}% returned  "
            f"({r['units_returned_90d']}/{r['units_sold_90d']} units)  "
            f"refunds ${r['refund_total']:,.2f}"
        )
    lines.append("")
else:
    sources_seen = []
    if walmart_returns: sources_seen.append("Walmart")
    if amazon_returns: sources_seen.append("Amazon")
    if sources_seen:
        lines.append(f"✓ HIGH RETURNS — none above {int(RETURN_THRESHOLD*100)}% threshold ({'/'.join(sources_seen)})\n")
    else:
        lines.append("⚠ HIGH RETURNS — no returns data on file (needs Walmart + Amazon pullers)\n")

if not amazon_returns:
    lines.append("⚠ AMAZON RETURNS pending — needs SP-API role enabled on LWA app")

(DATA / "exceptions_latest.txt").write_text("\n".join(lines))

# Surface counts to stdout so cron logs are useful
delay_total = (delayed_summary or {}).get("no_scan_count", 0) + (delayed_summary or {}).get("late_scan_count", 0)
total_exceptions = len(amazon_below) + len(shipping_negative) + len(low_margin) + (1 if delay_total > 0 else 0)
print(f"check_exceptions.py — {total_exceptions} exception block(s) found "
      f"({len(amazon_below)} Amz<Shop, {len(shipping_negative)} ship-loss, "
      f"{len(low_margin)} low-margin, {delay_total} delayed-shipment labels)")

sys.exit(1 if total_exceptions else 0)
