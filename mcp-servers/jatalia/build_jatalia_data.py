"""Build the data file for the Jatalia <- Earthwise intercompany billing dashboard.

Pulls ShipStation shipments (marketplace stores), buckets them into 14-day
billing periods anchored on the last billed period (Apr 27 - May 10, 2026),
joins Shopify/COGS unit costs, and emits JSON for the dashboard.
"""
import json, os, datetime as dt, collections, sys
import server  # the shipstation MCP module

ANCHOR = dt.date(2026, 4, 27)          # start of last-billed period (fixed)
PERIOD_DAYS = 14
PULL_START = "2025-08-01"
PULL_END   = (dt.date.today() + dt.timedelta(days=30)).isoformat()

STORES = {  # marketplace channels Jatalia resells through
    "se-1995856": "Amazon",
    "se-842576":  "Walmart",
    "se-675808":  "TikTok",
    "se-3125042": "TikTok",
}
SHIPPED_STATUSES = {"label_purchased", "shipped", "delivered", "completed"}

# ---- cost map -------------------------------------------------------------
import re
cost = {}        # sku -> {"cost": float, "name": str}
name_index = {}  # (family, size) -> {"cost": float, "name": str}  (fallback match)

# distinct product-family keywords — longest/most-specific first
FAMILIES = [
    "northeast native and naturalized", "northeast native & naturalized",
    "northeast native wildflower", "southeast native meadow",
    "southwest native meadow", "midwest native", "western wonders",
    "monarch meadow", "pollinator paradise", "hummingbird haven",
    "shady native", "knee high", "no deer here", "lone star",
    "ecoseed", "truegrass", "fireguard", "petlawn", "low grow",
    "microclover", "ultimate clover", "tri-clover", "tri clover",
    "white dutch clover", "crimson clover", "red velvet",
    "creeping smartweed", "dandipure", "dandilawn", "greenboost",
    "seed-tac", "seed tac", "thyme for a change", "yellow sweet clover",
    "foothill clover", "meadowscaping",
]
def _fam(text):
    t = (text or "").lower().replace(" & ", " and ")
    for f in FAMILIES:
        if f.replace(" & ", " and ") in t:
            return f.replace("tri clover", "tri-clover").replace("seed tac", "seed-tac")
    return None
def _size(text):
    m = re.search(r'(\d+\s*/\s*\d+|\d+(?:\.\d+)?)\s*(lb|oz)', (text or "").lower())
    return (m.group(1).replace(" ", "") + m.group(2)) if m else None

# Shopify variant cost export (EW SKUs) — persistent copy in data/
SHOP = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    "data", "shopify_costs.json")
try:
    for r in json.load(open(SHOP))["results"]:
        e = r["edges"]; sku = (e.get("sku") or "").strip()
        c = e.get("inventoryItem_unitCost_amount")
        if c in (None, ""):
            continue
        ptitle = e.get("product_title", "")
        try: sp = float(e.get("price") or 0) or None
        except (TypeError, ValueError): sp = None
        # variant size parsed from variant title (e.g. "1/2 lb - Covers ...")
        vsize = _size(e.get("title", "")) or _size(ptitle)
        rec = {"cost": float(c), "name": ptitle, "price": sp, "size": vsize}
        if sku:
            cost[sku] = rec
        # build (family, size) fallback index from product + variant title
        fam = _fam(ptitle)
        if fam and vsize:
            name_index.setdefault((fam, vsize), rec)
except Exception as ex:
    print("WARN shopify cost load:", ex, file=sys.stderr)

# Helium 10 filled CSV (Amazon merchant SKUs)
import csv
CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "data", "amazon_cogs.csv")
try:
    for row in csv.DictReader(open(CSV, encoding="utf-8-sig")):
        sku = (row.get("SKU") or "").strip()
        asin = (row.get("ASIN") or "").strip()
        ew = (row.get("SHOPIFY_SKU") or "").strip()
        try: c = float(row.get("PRODUCT COST") or 0)
        except ValueError: c = 0.0
        if c > 0:
            # inherit the Shopify retail price via the SHOPIFY_SKU cross-ref
            sp = cost[ew].get("price") if ew and ew in cost else None
            rec = {"cost": c, "name": row.get("TITLE", ""), "price": sp}
            if sku:  cost.setdefault(sku, rec)
            if asin: cost.setdefault(asin, rec)   # also index by ASIN
except Exception as ex:
    print("WARN csv cost load:", ex, file=sys.stderr)

print(f"cost map: {len(cost)} keys", file=sys.stderr)


def resolve(sku: str, name: str = ""):
    """Cost lookup: exact SKU, FBA-suffix strip, then product name + size match."""
    if sku:
        if sku in cost:
            return cost[sku]
        if sku.upper().endswith("FBA") and sku[:-3] in cost:
            return cost[sku[:-3]]
    # fallback: match by product family + size parsed from the item name
    fam = _fam(name)
    size = _size(name)
    if fam and size:
        return name_index.get((fam, size))
    return None

# ---- periods --------------------------------------------------------------
def period_for(d: dt.date):
    delta = (d - ANCHOR).days
    k = delta // PERIOD_DAYS                     # floor division -> aligned bucket
    start = ANCHOR + dt.timedelta(days=k * PERIOD_DAYS)
    end = start + dt.timedelta(days=PERIOD_DAYS - 1)
    return start, end

def plabel(start, end):
    if start.year == end.year:
        return f"{start:%b %-d} – {end:%b %-d}, {end.year}"
    return f"{start:%b %-d, %Y} – {end:%b %-d, %Y}"

def mkperiod(s, e):
    return {"id": s.isoformat(), "start": s.isoformat(), "end": e.isoformat(),
            "label": plabel(s, e), "billed": (s == ANCHOR),
            "rows": collections.defaultdict(lambda: {"units": 0.0, "sales": 0.0}),
            "stotals": collections.defaultdict(
                lambda: {"shipping_collected": 0.0, "shipping_cost": 0.0})}

# pre-generate the full period axis (historic + a few future)
periods = {}
d = dt.date(2025, 8, 1)
axis_end = dt.date.today() + dt.timedelta(days=45)
while d <= axis_end:
    s, e = period_for(d)
    if s.isoformat() not in periods:
        periods[s.isoformat()] = mkperiod(s, e)
    d += dt.timedelta(days=1)

# ---- pull shipments (per marketplace store; store_id filter is server-side) -
allsh = []
win = {"created_at_start": PULL_START + "T00:00:00Z",
       "created_at_end": PULL_END + "T23:59:59Z"}
for store_id in sorted(set(STORES)):
    cnt = 0
    page, pages = 1, 1
    while page <= pages and page <= 120:        # 120 * 500 = 60k cap per store
        data = server._get("/shipments", params=dict(
            win, store_id=store_id, page=page, page_size=500))
        pages = data.get("pages", 1) or 1
        batch = data.get("shipments", []) or []
        allsh += batch
        cnt += len(batch)
        page += 1
    print(f"  {store_id} ({STORES[store_id]}): {cnt} shipments", file=sys.stderr)
print(f"pulled {len(allsh)} marketplace shipments", file=sys.stderr)

def amt(v):
    if isinstance(v, dict):
        try: return float(v.get("amount") or 0)
        except (TypeError, ValueError): return 0.0
    try: return float(v or 0)
    except (TypeError, ValueError): return 0.0

unmatched_sku = collections.Counter()
ship_loc = {}          # shipment_id -> (period_id, store)  for label-cost join
used = skipped_store = skipped_status = 0
for s in allsh:
    sid = s.get("store_id")
    if sid not in STORES:
        skipped_store += 1; continue
    if s.get("shipment_status") not in SHIPPED_STATUSES:
        skipped_status += 1; continue
    ds = s.get("ship_date") or s.get("created_at")
    if not ds: continue
    d = dt.date.fromisoformat(ds[:10])
    st, en = period_for(d)
    pid = st.isoformat()
    if pid not in periods:
        periods[pid] = mkperiod(st, en)
    store = STORES[sid]
    used += 1
    ship_loc[s.get("shipment_id")] = (pid, store)
    periods[pid]["stotals"][store]["shipping_collected"] += amt(s.get("shipping_paid"))
    for it in s.get("items") or []:
        sku = (it.get("sku") or "").strip()
        qty = float(it.get("quantity") or 0)
        if qty <= 0: continue
        price = amt(it.get("unit_price"))
        iname = it.get("name") or ""
        key = (store, sku)
        rec = periods[pid]["rows"][key]
        rec["units"] += qty
        rec["sales"] += price * qty
        if not rec.get("item_name"):
            rec["item_name"] = iname
        if resolve(sku, iname) is None:
            unmatched_sku[sku or "(no sku)"] += qty

# ---- shipping COST: pull recent labels, join to shipments by id -----------
# (label shipment_cost = what Jatalia paid the carrier; only on the label)
LABEL_DAYS = 25   # trailing window for shipping-cost label join (covers tracked periods)
lwin = {"created_at_start": (dt.date.today() - dt.timedelta(days=LABEL_DAYS)).isoformat() + "T00:00:00Z",
        "created_at_end": dt.date.today().isoformat() + "T23:59:59Z"}
lbl_matched = 0
page, pages = 1, 1
while page <= pages and page <= 80:
    dl = server._get("/labels", params=dict(lwin, page=page, page_size=500))
    pages = dl.get("pages", 1) or 1
    for lb in dl.get("labels", []) or []:
        if lb.get("voided") or lb.get("is_return_label"):
            continue
        loc = ship_loc.get(lb.get("shipment_id"))
        if not loc:
            continue                       # not a tracked marketplace shipment
        pid_, store_ = loc
        periods[pid_]["stotals"][store_]["shipping_cost"] += amt(lb.get("shipment_cost"))
        lbl_matched += 1
    page += 1
print(f"shipping-cost labels matched: {lbl_matched} (last {LABEL_DAYS}d)", file=sys.stderr)

# ---- realized Amazon selling price per SKU (sales / units, Amazon store) --
_apx = {}
for _p in periods.values():
    for (st, sk), rec in _p["rows"].items():
        if st == "Amazon":
            a = _apx.setdefault(sk, {"s": 0.0, "u": 0.0})
            a["s"] += rec["sales"]; a["u"] += rec["units"]
amazon_price = {sk: round(v["s"] / v["u"], 2) for sk, v in _apx.items() if v["u"] > 0}

# ---- assemble output ------------------------------------------------------
out_periods = []
for pid in sorted(periods):
    p = periods[pid]
    skus = []
    for (store, sku), rec in p["rows"].items():
        iname = rec.get("item_name", "")
        c = resolve(sku, iname) or {}
        unit_cost = c.get("cost", 0.0)
        # Shopify retail price: from the resolved record, else name-fallback match
        sp = c.get("price")
        if sp is None:
            fam, size = _fam(iname), _size(iname)
            if fam and size:
                nm = name_index.get((fam, size))
                if nm:
                    sp = nm.get("price")
        skus.append({
            "store": store, "sku": sku,
            "name": c.get("name", "") or iname or sku,
            "units": round(rec["units"], 2),
            "sales": round(rec["sales"], 2),
            "unit_cost": unit_cost,
            "cogs": round(rec["units"] * unit_cost, 2),
            "amazon_price": amazon_price.get(sku),
            "shopify_price": sp,
            "costed": c != {},
        })
    skus.sort(key=lambda r: r["cogs"], reverse=True)
    store_summary = {st: {"shipping_collected": round(v["shipping_collected"], 2),
                          "shipping_cost": round(v["shipping_cost"], 2)}
                     for st, v in p["stotals"].items()}
    out_periods.append({k: p[k] for k in ("id", "start", "end", "label", "billed")}
                       | {"skus": skus, "store_summary": store_summary})

# ---- price master (for the Price Update tab) ------------------------------
# Amazon SKU / ASIN cross-ref by EW (Shopify) SKU, from amazon_cogs.csv
amz_xref = {}
try:
    for row in csv.DictReader(open(CSV, encoding="utf-8-sig")):
        ew = (row.get("SHOPIFY_SKU") or "").strip()
        if ew and ew not in ("#N/A", ""):
            amz_xref.setdefault(ew, {"amazon_sku": (row.get("SKU") or "").strip(),
                                     "asin": (row.get("ASIN") or "").strip()})
except Exception as ex:
    print("WARN xref load:", ex, file=sys.stderr)

# Walmart catalog (Walmart item report) — real Walmart SKU + live published
# price per variant. Join to EW products by EW-SKU when present, else by
# product family + size parsed from the item name.
WMT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "data", "walmart_items.csv")
wmt_by_ew = {}          # EW sku -> {"sku","price"}
wmt_by_famsize = {}     # (family,size) -> {"sku","price"}
try:
    for row in csv.DictReader(open(WMT, encoding="utf-8-sig")):
        wsku = (row.get("SKU") or "").strip()
        if not wsku or (row.get("Status") or "").strip().upper() != "PUBLISHED":
            continue
        nm = row.get("Item Name") or ""
        try: wp = float(row.get("Price (USD)") or 0) or None
        except (TypeError, ValueError): wp = None
        entry = {"sku": wsku, "price": wp}
        if wsku.upper().startswith("EW"):
            wmt_by_ew[wsku.upper()] = entry
        fam, size = _fam(nm), _size(nm)
        if fam and size:
            wmt_by_famsize.setdefault((fam, size), entry)
except Exception as ex:
    print("WARN walmart catalog load:", ex, file=sys.stderr)
print(f"walmart catalog: {len(wmt_by_ew)} EW-keyed + "
      f"{len(wmt_by_famsize)} family/size", file=sys.stderr)

# realized Walmart price by SKU
_wpx = {}
for _p in periods.values():
    for (st, sk), rec in _p["rows"].items():
        if st == "Walmart" and rec["units"] > 0:
            w = _wpx.setdefault(sk, {"s": 0.0, "u": 0.0})
            w["s"] += rec["sales"]; w["u"] += rec["units"]
walmart_price = {sk: round(v["s"] / v["u"], 2) for sk, v in _wpx.items() if v["u"] > 0}

# 1.6 — Build a complete EW-SKU universe from shopify_costs.json (not just
# `cost` which is filtered by presence of unit_cost). This surfaces SKUs that
# exist in Shopify but lack a COGS / aren't on marketplaces yet.
all_ew_skus = {}  # ew_sku -> {name, cost (or None), price}
try:
    for r in json.load(open(SHOP))["results"]:
        e = r["edges"]
        sk = (e.get("sku") or "").strip()
        if not sk.startswith("EW"):
            continue
        try: sp = float(e.get("price") or 0) or None
        except (TypeError, ValueError): sp = None
        uc_raw = e.get("inventoryItem_unitCost_amount")
        try:
            uc = float(uc_raw) if uc_raw not in (None, "") else None
        except (TypeError, ValueError):
            uc = None
        ptitle = e.get("product_title", "")
        vsize = _size(e.get("title", "")) or _size(ptitle)
        existing = all_ew_skus.get(sk)
        rec = {"cost": uc, "name": ptitle, "price": sp, "size": vsize}
        # Last-write-wins on collision — match the cost dict's behavior
        if not existing or (uc is not None and existing.get("cost") is None):
            all_ew_skus[sk] = rec
except Exception as ex:
    print(f"WARN price_master shopify scan: {ex}", file=sys.stderr)
print(f"all_ew_skus (incl. no-cost): {len(all_ew_skus)}", file=sys.stderr)

price_master = []
for ew_sku, rec in sorted(all_ew_skus.items()):
    if not ew_sku.startswith("EW"):
        continue
    xr = amz_xref.get(ew_sku, {})
    amz_sku = xr.get("amazon_sku", "")
    # Walmart catalog match: direct EW-SKU, else product family + size
    wm = wmt_by_ew.get(ew_sku.upper())
    if not wm:
        fam, size = _fam(rec.get("name", "")), rec.get("size")
        if fam and size:
            wm = wmt_by_famsize.get((fam, size))
    wm = wm or {}
    # 1.6 — keep ALL Shopify EW SKUs even if they have neither Amazon nor Walmart
    # presence yet. Lets us flag SKUs that exist in Shopify but aren't listed on
    # marketplaces (= an action item, not "out of scope").
    # Previously: dropped rows missing both amz_sku and wm.
    price_master.append({
        "ew_sku": ew_sku,
        "name": rec.get("name", ""),
        "unit_cost": rec.get("cost"),
        "shopify_price": rec.get("price"),
        "amazon_sku": amz_sku,
        "asin": xr.get("asin", ""),
        "amazon_price": amazon_price.get(amz_sku),
        "walmart_sku": wm.get("sku", ""),
        "walmart_price": wm.get("price") if wm.get("price") is not None
                         else walmart_price.get(ew_sku),
        "walmart_id": "",                 # Walmart Product ID — user-editable
    })
price_master.sort(key=lambda r: r["name"])

# 1.2 — Returns aggregation from walmart_returns.json (Amazon side pending SP-API).
# Bucket each return into its billing period by returnCreatedDate, then attach a
# per-SKU returns rollup to each period (units returned, refund $) so the UI
# can show a "Returns" column next to "Units" on the Billing per-SKU table.
RETURNS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "data", "walmart_returns.json")
returns_summary = {"walmart": {"window_days": None, "return_count": 0, "refund_total": 0.0}}
try:
    rdata = json.load(open(RETURNS_PATH))
    rwin = rdata.get("window", {})
    returns_summary["walmart"] = {
        "window_days": rwin.get("days"),
        "window_start": rwin.get("start"),
        "window_end": rwin.get("end"),
        "return_count": rdata.get("summary", {}).get("return_count", 0),
        "refund_total": rdata.get("summary", {}).get("refund_total", 0.0),
        "generated": rdata.get("generated"),
    }
    # Bucket per-period per-SKU
    for ret in rdata.get("returns", []):
        d = (ret.get("returnCreatedDate") or "")[:10]
        if not d: continue
        # Find matching period
        for p in out_periods:
            if p["start"] <= d <= p["end"]:
                p_returns = p.setdefault("returns", {})
                sku = ret.get("sku") or ""
                if not sku: continue
                key = f"Walmart::{sku}"
                bucket = p_returns.setdefault(key, {
                    "store": "Walmart", "sku": sku,
                    "name": ret.get("productName", "")[:80],
                    "units_returned": 0, "refund_total": 0.0,
                    "return_orders": 0,
                })
                bucket["units_returned"] += int(ret.get("quantity") or 0)
                bucket["refund_total"]  += float(ret.get("refundAmount") or 0)
                bucket["return_orders"] += 1
                break
    # Round refund_totals
    for p in out_periods:
        for v in (p.get("returns") or {}).values():
            v["refund_total"] = round(v["refund_total"], 2)
except FileNotFoundError:
    print("WARN walmart_returns.json missing — skip returns aggregation", file=sys.stderr)
except Exception as ex:
    print(f"WARN returns aggregation: {ex}", file=sys.stderr)

doc = {
    "generated": dt.datetime.now().isoformat(timespec="seconds"),
    "anchor": ANCHOR.isoformat(),
    "last_billed": {"start": ANCHOR.isoformat(),
                    "end": (ANCHOR + dt.timedelta(days=13)).isoformat()},
    "stores": sorted(set(STORES.values())),
    "period_days": PERIOD_DAYS,
    "price_master": price_master,
    "returns_summary": returns_summary,
    "diagnostics": {
        "shipments_pulled": len(allsh),
        "shipments_used": used,
        "skipped_non_marketplace_store": skipped_store,
        "skipped_status": skipped_status,
        "unmatched_skus": dict(unmatched_sku.most_common(20)),
    },
    "periods": out_periods,
}
open("data/jatalia_billing_data.json", "w").write(json.dumps(doc))
print("wrote data/jatalia_billing_data.json", file=sys.stderr)
print("periods:", len(out_periods), "| used shipments:", used,
      "| unmatched skus:", len(unmatched_sku), file=sys.stderr)
