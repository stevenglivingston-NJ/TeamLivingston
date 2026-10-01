"""Scan-latency analysis for the Fulfillment Issues tab.

For every marketplace outbound label in the window, calls /v2/labels/{id}/track
and measures business days from label creation to the FIRST carrier acceptance
scan. Flags labels where that gap exceeds the threshold, or where the carrier
still has no scan at all ("printed, never collected").

PERFORMANCE OPTIMIZATIONS (2026-06-04):
  * Concurrent tracking via ThreadPoolExecutor (20 workers) — was sequential
  * Per-label cache at data/tracking_cache.json keyed by label_id — once a
    shipment is confirmed scanned/delivered, the result is permanent and we
    skip the API call on subsequent runs. Window-aged-out entries are dropped.
  * SKU enrichment — each row now carries `top_sku`, `sku_breakdown` (per-SKU
    quantity) so the exception scanner can attribute delays to specific SKUs.
"""
import json, datetime as dt, sys, time, threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import server

TODAY = dt.date.today()
WIN_START = (TODAY - dt.timedelta(days=25)).isoformat()
WIN_END = TODAY.isoformat()
THRESHOLD = 2                       # business days
MKT_STORES = {"se-1995856": "Amazon", "se-842576": "Walmart",
              "se-675808": "TikTok", "se-3125042": "TikTok"}
SCANNED = {"AC", "IT", "DE", "AT", "EX", "DY"}      # carrier has the package
TERMINAL = {"DE"}                                   # delivered → cache forever
PARALLEL = 20

CACHE_PATH = Path("data/tracking_cache.json")
CACHE_TTL_DAYS = 30                                  # drop cache entries older than this


def biz_days(d1: dt.date, d2: dt.date) -> int:
    if d2 <= d1:
        return 0
    n, cur = 0, d1
    while cur < d2:
        cur += dt.timedelta(days=1)
        if cur.weekday() < 5:
            n += 1
    return n


def amt(v):
    if isinstance(v, dict):
        try: return float(v.get("amount") or 0)
        except (TypeError, ValueError): return 0.0
    try: return float(v or 0)
    except (TypeError, ValueError): return 0.0


def items_summary(sh):
    """Return (display_summary, total_units, per_sku_dict, top_sku)."""
    parts, units = [], 0
    sku_qty = {}
    for it in sh.get("items") or []:
        q = int(float(it.get("quantity") or 0))
        units += q
        nm = (it.get("name") or "").strip()
        sk = it.get("sku") or ""
        if sk:
            sku_qty[sk] = sku_qty.get(sk, 0) + q
        parts.append(f"{nm} ({sk or '?'}) x{q}" if nm else f"{sk or '?'} x{q}")
    top_sku = max(sku_qty.items(), key=lambda x: x[1])[0] if sku_qty else ""
    return "; ".join(parts[:5]), units, sku_qty, top_sku


def days_since(d: dt.date, today: dt.date) -> int:
    return max(0, (today - d).days)


# ---- load tracking cache --------------------------------------------------
cache = {}
cache_ttl_cutoff = (TODAY - dt.timedelta(days=CACHE_TTL_DAYS)).isoformat()
if CACHE_PATH.exists():
    try:
        cache_raw = json.loads(CACHE_PATH.read_text())
        # Drop entries with a cached_for_date older than the TTL
        cache = {k: v for k, v in cache_raw.items()
                 if v.get("label_date", "1970-01-01") >= cache_ttl_cutoff}
        print(f"tracking cache: loaded {len(cache)} entries ({len(cache_raw) - len(cache)} aged out)",
              file=sys.stderr)
    except Exception as e:
        print(f"tracking cache load error: {e}", file=sys.stderr)
        cache = {}

cache_lock = threading.Lock()


# ---- marketplace shipments (store-filtered) -------------------------------
ship_by_id = {}
win = {"created_at_start": WIN_START + "T00:00:00Z",
       "created_at_end": WIN_END + "T23:59:59Z"}
for sid in sorted(set(MKT_STORES)):
    page, pages = 1, 1
    while page <= pages and page <= 60:
        d = server._get("/shipments", params=dict(win, store_id=sid, page=page, page_size=500))
        pages = d.get("pages", 1) or 1
        for s in d.get("shipments", []):
            ship_by_id[s.get("shipment_id")] = s
        page += 1
print(f"marketplace shipments: {len(ship_by_id)}", file=sys.stderr)

# ---- labels in window -----------------------------------------------------
labels, page, pages = [], 1, 1
while page <= pages and page <= 60:
    d = server.list_labels(created_at_start=WIN_START, created_at_end=WIN_END,
                           page=page, page_size=500)
    pages = d["pages"] or 1
    labels += d["labels"]
    page += 1
print(f"labels in window: {len(labels)}", file=sys.stderr)

# keep marketplace outbound labels
todo = []
for lb in labels:
    if lb.get("voided") or lb.get("is_return_label"):
        continue
    sh = ship_by_id.get(lb.get("shipment_id"))
    if not sh:
        continue
    todo.append((lb, sh))
print(f"marketplace outbound labels to track: {len(todo)}", file=sys.stderr)


# ---- per-label tracking (concurrent + cached) -----------------------------
def fetch_track(label_id):
    """Return (first_scan_date_or_None, terminal_bool, error_string_or_None)."""
    try:
        t = server._get(f"/labels/{label_id}/track")
        evts = t.get("events") or []
        first_scan = None
        terminal = False
        for ev in evts:
            sc = (ev.get("status_code") or "").upper()
            occ = ev.get("occurred_at") or ev.get("carrier_occurred_at")
            if sc in TERMINAL:
                terminal = True
            if sc in SCANNED and occ:
                dd = dt.date.fromisoformat(occ[:10])
                if first_scan is None or dd < first_scan:
                    first_scan = dd
        return (first_scan.isoformat() if first_scan else None, terminal, None)
    except Exception as e:
        return (None, False, str(e)[:80])


def resolve_one(idx_pair):
    """Worker: returns cached result or fetches anew, updates cache."""
    idx, (lb, sh) = idx_pair
    lid = lb["label_id"]
    with cache_lock:
        cached = cache.get(lid)
    if cached and cached.get("terminal"):
        # delivered/cached, no need to refetch
        return (lid, cached["first_scan"], None, True)
    first, terminal, err = fetch_track(lid)
    new_entry = {
        "first_scan": first,
        "terminal": terminal,
        "label_date": (lb.get("created_at") or lb.get("ship_date") or "")[:10],
    }
    with cache_lock:
        cache[lid] = new_entry
    return (lid, first, err, False)


# Run concurrently
print(f"tracking with {PARALLEL} parallel workers...", file=sys.stderr)
start = time.time()
tracking_results = {}  # label_id -> first_scan_iso_or_None
errors = 0
cache_hits = 0
with ThreadPoolExecutor(max_workers=PARALLEL) as ex:
    futures = {ex.submit(resolve_one, (i, pair)): i for i, pair in enumerate(todo)}
    completed = 0
    for fut in as_completed(futures):
        lid, first_scan_iso, err, from_cache = fut.result()
        tracking_results[lid] = first_scan_iso
        if err:
            errors += 1
        if from_cache:
            cache_hits += 1
        completed += 1
        if completed % 500 == 0:
            print(f"  resolved {completed}/{len(todo)} (cache hits: {cache_hits}, errors: {errors})",
                  file=sys.stderr)
elapsed = time.time() - start
print(f"tracking done in {elapsed:.1f}s (cache hits: {cache_hits}, errors: {errors})",
      file=sys.stderr)

# Persist cache (only entries that have been seen this run + were already cached)
CACHE_PATH.parent.mkdir(exist_ok=True)
CACHE_PATH.write_text(json.dumps(cache, separators=(",", ":")))


# ---- build rows -----------------------------------------------------------
rows = []
for lb, sh in todo:
    lid = lb["label_id"]
    created = lb.get("created_at") or lb.get("ship_date") or ""
    if not created:
        continue
    cdate = dt.date.fromisoformat(created[:10])
    first_scan_iso = tracking_results.get(lid)
    first_scan = dt.date.fromisoformat(first_scan_iso) if first_scan_iso else None
    if first_scan:
        latency = biz_days(cdate, first_scan)
        state = "late_scan" if latency > THRESHOLD else "ok"
    else:
        latency = biz_days(cdate, TODAY)
        state = "no_scan"
    if state == "ok":
        continue
    isum, units, sku_qty, top_sku = items_summary(sh)
    to = sh.get("ship_to") or {}
    odate = (sh.get("created_at") or created)[:10]
    rows.append({
        "order": sh.get("external_order_id") or sh.get("shipment_number") or lid,
        "store": MKT_STORES.get(sh.get("store_id"), "—"),
        "carrier": (lb.get("carrier_code") or "").upper(),
        "service": lb.get("service_code") or "",
        "tracking": lb.get("tracking_number") or "",
        "order_date": odate,
        "days_since": days_since(dt.date.fromisoformat(odate), TODAY),
        "label_date": created[:10],
        "first_scan": first_scan.isoformat() if first_scan else None,
        "latency_biz_days": latency,
        "state": state,
        "units": units,
        "items": isum,
        "top_sku": top_sku,                # NEW: most-shipped SKU on this label
        "sku_breakdown": sku_qty,          # NEW: full per-SKU qty dict
        "value": round(amt(sh.get("amount_paid")), 2),
        "customer": to.get("name", ""),
        "phone": to.get("phone", "") or "",
        "email": to.get("email", "") or "",
        "state_province": to.get("state_province", ""),
    })

rows.sort(key=lambda r: (r["state"] != "no_scan", -r["latency_biz_days"]))

no_scan = [r for r in rows if r["state"] == "no_scan"]
late = [r for r in rows if r["state"] == "late_scan"]

# Per-SKU aggregation for the exception scanner
sku_problem_count = {}
sku_problem_value = {}
sku_problem_units = {}
for r in rows:
    for sku, qty in (r.get("sku_breakdown") or {}).items():
        sku_problem_count[sku] = sku_problem_count.get(sku, 0) + 1
        sku_problem_value[sku] = sku_problem_value.get(sku, 0) + r["value"]
        sku_problem_units[sku] = sku_problem_units.get(sku, 0) + qty

problem_skus = sorted(
    [
        {
            "sku": s,
            "delayed_label_count": sku_problem_count[s],
            "delayed_units": sku_problem_units[s],
            "delayed_value": round(sku_problem_value[s], 2),
        }
        for s in sku_problem_count
    ],
    key=lambda x: -x["delayed_label_count"]
)

doc = {
    "generated": dt.datetime.now().isoformat(timespec="seconds"),
    "today": TODAY.isoformat(),
    "window": {"start": WIN_START, "end": WIN_END},
    "threshold_biz_days": THRESHOLD,
    "stores": ["Amazon", "Walmart", "TikTok"],
    "labels_tracked": len(todo),
    "track_errors": errors,
    "cache_hits": cache_hits,
    "rows": rows,
    "problem_skus": problem_skus,           # NEW: per-SKU delay rollup
    "summary": {
        "no_scan_count": len(no_scan),
        "no_scan_value": round(sum(r["value"] for r in no_scan), 2),
        "late_scan_count": len(late),
        "late_scan_value": round(sum(r["value"] for r in late), 2),
        "pct_problem": round(100 * len(rows) / len(todo), 1) if todo else 0,
        "problem_sku_count": len(problem_skus),
    },
}
Path("data/jatalia_latency_data.json").write_text(json.dumps(doc))
print(f"wrote data/jatalia_latency_data.json", file=sys.stderr)
print(f"no_scan={len(no_scan)} late_scan={len(late)} tracked={len(todo)} errors={errors} cache_hits={cache_hits}",
      file=sys.stderr)
