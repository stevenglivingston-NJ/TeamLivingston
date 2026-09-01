#!/usr/bin/env python3
"""Walmart Marketplace returns feed for the Jatalia / Earthwise sweep.

Cloud-adapted port of walmart-mcp/walmart_pull_returns.py: reads creds from ENV
(no .env file), uses httpx (not requests), and writes into the sweep's data dir.
Feeds the sweep's returns_summary (billing) and RETURNS_HIGH (exceptions).

Auth (Cloud env → Environment variables; see mcp-servers/.env.example):
  WMT_CLIENT_ID  WMT_CLIENT_SECRET   (client_credentials → Basic auth, no signature)
Optional:
  WMT_SELLER_ID
  WALMART_RETURNS_OUT   output path (default ./data/walmart_returns.json next to this file)

Skips cleanly (exit 0, no file overwrite) if creds are absent — Walmart is optional
to the sweep; a missing feed just leaves returns_summary at zero.
"""
import base64
import datetime as dt
import json
import os
import sys
import uuid

import httpx

TOKEN_URL = "https://marketplace.walmartapis.com/v3/token"
API_BASE = "https://marketplace.walmartapis.com/v3"
WINDOW_DAYS = 90
PAGE_LIMIT = 200
_here = os.path.dirname(os.path.abspath(__file__))
OUT = os.environ.get("WALMART_RETURNS_OUT", os.path.join(_here, "data", "walmart_returns.json"))


def _svc_headers(extra=None):
    h = {
        "WM_QOS.CORRELATION_ID": str(uuid.uuid4()),
        "WM_SVC.NAME": "Walmart Marketplace",
        "Accept": "application/json",
    }
    if extra:
        h.update(extra)
    return h


def get_token(cid, sec):
    basic = base64.b64encode(f"{cid}:{sec}".encode()).decode()
    with httpx.Client(timeout=30) as c:
        r = c.post(TOKEN_URL,
                   headers=_svc_headers({"Authorization": f"Basic {basic}",
                                         "Content-Type": "application/x-www-form-urlencoded"}),
                   data={"grant_type": "client_credentials"})
        r.raise_for_status()
        return r.json()["access_token"]


def fetch_returns(token, start, end):
    out, offset = [], 0
    with httpx.Client(timeout=45) as c:
        while True:
            r = c.get(f"{API_BASE}/returns",
                      headers=_svc_headers({"WM_SEC.ACCESS_TOKEN": token}),
                      params={"createdStartDate": start, "createdEndDate": end,
                              "limit": PAGE_LIMIT, "offset": offset})
            r.raise_for_status()
            data = r.json()
            orders = (data.get("returnOrders") or data.get("returnOrderLines") or [])
            if not orders:
                break
            out.extend(orders)
            if len(orders) < PAGE_LIMIT:
                break
            offset += PAGE_LIMIT
            if offset > 20000:  # safety backstop
                break
    return out


def normalize(orders):
    """Flatten Walmart's nested return payload into flat lines + a per-SKU rollup."""
    lines, rollup = [], {}
    ret_count = 0
    refund_total = 0.0
    for o in orders:
        oid = o.get("returnOrderId") or o.get("purchaseOrderId") or ""
        cust = o.get("customerOrderId") or ""
        for ln in (o.get("returnOrderLines") or [o]):
            sku = (ln.get("sku") or ((ln.get("item") or {}).get("sku")) or "").strip()
            qty = int(float(ln.get("returnQuantity", {}).get("amount", ln.get("quantity", 1)) or 1)) \
                if isinstance(ln.get("returnQuantity"), dict) else int(float(ln.get("quantity", 1) or 1))
            refund = 0.0
            charges = ln.get("refund", {}).get("refundCharges", []) if isinstance(ln.get("refund"), dict) else []
            for ch in charges:
                amt = ((ch.get("charge") or {}).get("chargeAmount") or {}).get("amount")
                try:
                    refund += float(amt or 0)
                except (TypeError, ValueError):
                    pass
            ret_count += 1
            refund_total += refund
            lines.append({"returnOrderId": oid, "customerOrderId": cust, "sku": sku,
                          "quantity": qty, "refundAmount": round(refund, 2),
                          "returnReason": ln.get("returnReason") or ln.get("reason") or "",
                          "status": ln.get("status") or o.get("status") or ""})
            if sku:
                rk = rollup.setdefault(sku, {"return_count": 0, "units": 0, "refund_total": 0.0})
                rk["return_count"] += 1
                rk["units"] += qty
                rk["refund_total"] = round(rk["refund_total"] + refund, 2)
    return lines, rollup, ret_count, round(refund_total, 2)


def main():
    cid = os.environ.get("WMT_CLIENT_ID", "").strip()
    sec = os.environ.get("WMT_CLIENT_SECRET", "").strip()
    if not (cid and sec):
        sys.stderr.write("walmart_pull: WMT_CLIENT_ID/WMT_CLIENT_SECRET not set — skipping (optional).\n")
        return 0

    today = dt.date.fromisoformat(os.environ["SWEEP_TODAY"]) if os.environ.get("SWEEP_TODAY") else dt.date.today()
    start = (today - dt.timedelta(days=WINDOW_DAYS)).isoformat()
    end = today.isoformat()
    try:
        token = get_token(cid, sec)
        orders = fetch_returns(token, start, end)
    except Exception as e:  # noqa: BLE001 — Walmart is optional; never abort the sweep
        sys.stderr.write(f"walmart_pull: fetch failed ({e}) — leaving prior returns file intact.\n")
        return 0

    lines, rollup, ret_count, refund_total = normalize(orders)
    doc = {
        "generated": (None if os.environ.get("SWEEP_TODAY")
                      else dt.datetime.now(dt.timezone.utc).isoformat()),
        "window": {"days": WINDOW_DAYS, "start": start, "end": end},
        "summary": {"return_count": ret_count, "refund_total": refund_total},
        "returns": lines,
        "sku_rollup": rollup,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(doc, fh, indent=1)
    sys.stderr.write(f"walmart_pull: {ret_count} returns / ${refund_total:,.2f} refunds -> {OUT}\n")
    print(json.dumps({"returns": ret_count, "refunds": refund_total}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
