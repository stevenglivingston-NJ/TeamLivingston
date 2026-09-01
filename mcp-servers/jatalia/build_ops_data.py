"""Build the data file for the Fulfillment Issues tab.

Two problem sets:
  A) Labels printed but NOT collected by the carrier — label exists, not voided,
     tracking_status still 'unknown' more than 2 business days after creation.
  B) Orders sitting unshipped > 2 business days — shipment in 'pending' status
     (no label bought) older than 2 business days.
"""
import json, datetime as dt, sys
import server

TODAY = dt.date.today()
WINDOW_START = (TODAY - dt.timedelta(days=30)).isoformat()   # ~30-day look-back
WINDOW_END = TODAY.isoformat()
BIZ_THRESHOLD = 2                     # "more than 2 business days"

STORES = {
    "se-1995856": "Amazon", "se-842576": "Walmart",
    "se-675808": "TikTok", "se-3125042": "TikTok", "se-1088993": "Shopify",
}


def biz_days_between(d: dt.date, today: dt.date) -> int:
    """Count business days strictly after d, up to and including today."""
    if d >= today:
        return 0
    n, cur = 0, d
    while cur < today:
        cur += dt.timedelta(days=1)
        if cur.weekday() < 5:          # Mon-Fri
            n += 1
    return n


def amt(v):
    if isinstance(v, dict):
        try: return float(v.get("amount") or 0)
        except (TypeError, ValueError): return 0.0
    try: return float(v or 0)
    except (TypeError, ValueError): return 0.0


def items_summary(sh):
    parts, units = [], 0
    for it in sh.get("items") or []:
        q = int(float(it.get("quantity") or 0))
        units += q
        nm = (it.get("name") or "").strip()
        sk = it.get("sku") or "?"
        parts.append(f"{nm} ({sk}) x{q}" if nm else f"{sk} x{q}")
    return "; ".join(parts[:6]), units


def days_since(d: dt.date, today: dt.date) -> int:
    """Calendar days between an order date and today."""
    return max(0, (today - d).days)


# ---- pull labels (all stores; short window) -------------------------------
labels, page, pages = [], 1, 1
while page <= pages and page <= 60:
    d = server.list_labels(created_at_start=WINDOW_START, created_at_end=WINDOW_END,
                           page=page, page_size=500)
    pages = d["pages"] or 1
    labels += d["labels"]
    page += 1
print(f"labels pulled: {len(labels)}", file=sys.stderr)

# ---- pull shipments (all stores; short window) ----------------------------
ships, page, pages = [], 1, 1
while page <= pages and page <= 80:
    d = server._get("/shipments", params={
        "created_at_start": WINDOW_START + "T00:00:00Z",
        "created_at_end": WINDOW_END + "T23:59:59Z",
        "page": page, "page_size": 500})
    pages = d.get("pages", 1) or 1
    ships += d.get("shipments", [])
    page += 1
print(f"shipments pulled: {len(ships)}", file=sys.stderr)

ship_by_id = {s.get("shipment_id"): s for s in ships}

# ---- A) labels printed but not collected ----------------------------------
not_collected = []
for lb in labels:
    if lb.get("voided") or lb.get("is_return_label"):
        continue
    ts = (lb.get("tracking_status") or "").lower()
    if ts and ts != "unknown":
        continue                       # carrier has scanned it — fine
    created = lb.get("created_at") or lb.get("ship_date")
    if not created:
        continue
    cdate = dt.date.fromisoformat(created[:10])
    age = biz_days_between(cdate, TODAY)
    if age <= BIZ_THRESHOLD:
        continue                       # give the carrier 2 business days
    sh = ship_by_id.get(lb.get("shipment_id"), {})
    isum, units = items_summary(sh)
    not_collected.append({
        "order": sh.get("external_order_id") or lb.get("external_order_id")
                 or sh.get("shipment_number") or lb.get("shipment_id"),
        "store": STORES.get(sh.get("store_id"), "—"),
        "carrier": (lb.get("carrier_code") or "").upper(),
        "service": lb.get("service_code") or "",
        "tracking": lb.get("tracking_number") or "",
        "label_date": created[:10],
        "ship_date": (lb.get("ship_date") or "")[:10],
        "biz_days": age,
        "tracking_status": ts or "unknown",
        "units": units,
        "items": isum,
        "value": round(amt(sh.get("amount_paid")), 2),
        "ship_to": (sh.get("ship_to") or {}).get("name", ""),
        "state": (sh.get("ship_to") or {}).get("state_province", ""),
    })
not_collected.sort(key=lambda r: r["biz_days"], reverse=True)

# ---- B) orders unshipped > 2 business days --------------------------------
unshipped = []
for sh in ships:
    if sh.get("shipment_status") not in ("pending", "awaiting_shipment", "on_hold"):
        continue
    created = sh.get("created_at")
    if not created:
        continue
    cdate = dt.date.fromisoformat(created[:10])
    age = biz_days_between(cdate, TODAY)
    if age <= BIZ_THRESHOLD:
        continue
    isum, units = items_summary(sh)
    to = sh.get("ship_to") or {}
    unshipped.append({
        "order": sh.get("external_order_id") or sh.get("shipment_number")
                 or sh.get("shipment_id"),
        "store": STORES.get(sh.get("store_id"), "—"),
        "status": sh.get("shipment_status"),
        "order_date": created[:10],
        "biz_days": age,
        "days_since": days_since(cdate, TODAY),
        "units": units,
        "items": isum,
        "value": round(amt(sh.get("amount_paid")), 2),
        "customer": to.get("name", ""),
        "phone": to.get("phone", "") or "",
        "email": to.get("email", "") or "",
        "state": to.get("state_province", ""),
    })
unshipped.sort(key=lambda r: r["biz_days"], reverse=True)

doc = {
    "generated": dt.datetime.now().isoformat(timespec="seconds"),
    "today": TODAY.isoformat(),
    "window": {"start": WINDOW_START, "end": WINDOW_END},
    "biz_threshold": BIZ_THRESHOLD,
    "not_collected": not_collected,
    "unshipped": unshipped,
    "summary": {
        "not_collected_count": len(not_collected),
        "not_collected_value": round(sum(r["value"] for r in not_collected), 2),
        "unshipped_count": len(unshipped),
        "unshipped_value": round(sum(r["value"] for r in unshipped), 2),
    },
}
open("data/jatalia_ops_data.json", "w").write(json.dumps(doc))
print("wrote data/jatalia_ops_data.json", file=sys.stderr)
print(f"not_collected: {len(not_collected)} | unshipped: {len(unshipped)}", file=sys.stderr)
