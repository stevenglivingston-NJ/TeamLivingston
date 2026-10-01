"""
ShipStation MCP Server (v2 API)
================================
Wraps the ShipStation v2 REST API (https://api.shipstation.com/v2) as MCP tools.

Auth: single API key in the `API-Key` header (v2 has no separate secret).
Credential is read (in priority order) from:
  1. env var  SHIPSTATION_API_KEY
  2. file     ~/.claude/secrets/shipstation-api-key

Get the key in ShipStation: Settings -> Account -> API Settings.

Primary use case: pull label cost data so average shipping cost per SKU can be
computed for the Earthwise Seed (Jatalia) Helium 10 COGS upload.

In v2, cost lives on the *label* (`shipment_cost`) and line items live on the
*shipment* (`items[].sku`). avg_shipping_per_sku joins the two by shipment_id.

Tools:
- test_connection        -> GET /v2/carriers (verify key)
- list_carriers          -> GET /v2/carriers
- list_labels            -> GET /v2/labels (one page; cost per label)
- list_shipments         -> GET /v2/shipments (one page; items per shipment)
- avg_shipping_per_sku   -> joins labels+shipments, allocates label cost across
                            line items by quantity, returns avg shipping per SKU
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Optional

import httpx
from mcp.server.fastmcp import FastMCP

API_BASE = "https://api.shipstation.com/v2"
HTTP_TIMEOUT = 60.0
SECRETS_DIR = Path.home() / ".claude" / "secrets"
PAGE_SIZE = 500
PAGE_CAP = 60  # safety cap (60 * 500 = 30k records per pull)


# ---------------------------------------------------------------------------
# credentials
# ---------------------------------------------------------------------------
def _api_key() -> str:
    val = os.environ.get("SHIPSTATION_API_KEY", "").strip()
    if val:
        return val
    f = SECRETS_DIR / "shipstation-api-key"
    if f.exists():
        val = f.read_text(encoding="utf-8").strip()
    if not val:
        raise ValueError(
            "ShipStation API key missing. Set env SHIPSTATION_API_KEY or write the "
            "key to ~/.claude/secrets/shipstation-api-key. Get it in ShipStation: "
            "Settings -> Account -> API Settings."
        )
    return val


def _headers() -> dict[str, str]:
    return {"API-Key": _api_key(), "Accept": "application/json"}


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def _get(path: str, params: Optional[dict] = None, _retries: int = 6) -> Any:
    """GET with v2 API-Key auth + retry on 429 rate-limit and transient
    network errors (read timeouts, connection resets)."""
    url = f"{API_BASE}{path if path.startswith('/') else '/' + path}"
    with httpx.Client(timeout=HTTP_TIMEOUT) as client:
        for attempt in range(_retries):
            try:
                resp = client.get(url, headers=_headers(), params=params)
            except (httpx.TimeoutException, httpx.TransportError) as e:
                if attempt < _retries - 1:
                    time.sleep(min(3 * (attempt + 1), 30))
                    continue
                raise ValueError(f"ShipStation network error after retries: {e}")
            if resp.status_code == 401:
                raise ValueError(
                    "401 Unauthorized — ShipStation rejected the API key. "
                    "Confirm it is a current v2 key (Settings -> Account -> API Settings)."
                )
            if resp.status_code == 429:
                wait = int(resp.headers.get("Retry-After", "5")) + 1
                if attempt < _retries - 1:
                    time.sleep(min(wait, 60))
                    continue
                raise ValueError("429 Rate limited by ShipStation after retries.")
            resp.raise_for_status()
            try:
                return resp.json()
            except Exception:
                return {"raw": resp.text, "status_code": resp.status_code}
    raise ValueError("ShipStation request failed after retries.")


def _norm_date(d: Optional[str], end: bool = False) -> Optional[str]:
    """Accept 'YYYY-MM-DD' or full ISO; return ISO 8601 the v2 API expects."""
    if not d:
        return None
    if "T" in d:
        return d
    return f"{d}T23:59:59Z" if end else f"{d}T00:00:00Z"


def _amount(obj: Any) -> float:
    """Pull a float amount from a v2 money object {amount,currency} or scalar."""
    if isinstance(obj, dict):
        try:
            return float(obj.get("amount") or 0.0)
        except (TypeError, ValueError):
            return 0.0
    try:
        return float(obj or 0.0)
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------------------
mcp = FastMCP("shipstation")


@mcp.tool()
def test_connection() -> dict:
    """Verify the ShipStation v2 API key works. Returns the configured carriers."""
    try:
        data = _get("/carriers")
        carriers = data.get("carriers", []) if isinstance(data, dict) else []
        return {
            "status": "ok",
            "carrier_count": len(carriers),
            "carriers": [
                {"carrier_id": c.get("carrier_id"),
                 "name": c.get("friendly_name") or c.get("carrier_code")}
                for c in carriers
            ],
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


@mcp.tool()
def list_carriers() -> dict:
    """List shipping carriers connected to the ShipStation account."""
    return _get("/carriers")


@mcp.tool()
def list_labels(
    created_at_start: Optional[str] = None,
    created_at_end: Optional[str] = None,
    page: int = 1,
    page_size: int = 100,
    label_status: Optional[str] = None,
) -> dict:
    """Fetch one page of shipping labels. Each label carries `shipment_cost`.

    Args:
        created_at_start: 'YYYY-MM-DD' or ISO datetime (inclusive)
        created_at_end:   'YYYY-MM-DD' or ISO datetime (inclusive)
        page:             1-indexed page
        page_size:        results per page (max 500)
        label_status:     optional filter, e.g. 'completed', 'voided'
    """
    params: dict[str, Any] = {"page": page, "page_size": min(page_size, PAGE_SIZE)}
    if _norm_date(created_at_start):
        params["created_at_start"] = _norm_date(created_at_start)
    if _norm_date(created_at_end, end=True):
        params["created_at_end"] = _norm_date(created_at_end, end=True)
    if label_status:
        params["label_status"] = label_status
    data = _get("/labels", params=params)
    return {
        "page": data.get("page"),
        "pages": data.get("pages"),
        "total": data.get("total"),
        "labels": data.get("labels", []),
    }


@mcp.tool()
def list_shipments(
    created_at_start: Optional[str] = None,
    created_at_end: Optional[str] = None,
    page: int = 1,
    page_size: int = 100,
) -> dict:
    """Fetch one page of shipments. Each shipment carries `items[]` with sku/quantity.

    Args:
        created_at_start: 'YYYY-MM-DD' or ISO datetime (inclusive)
        created_at_end:   'YYYY-MM-DD' or ISO datetime (inclusive)
        page:             1-indexed page
        page_size:        results per page (max 500)
    """
    params: dict[str, Any] = {"page": page, "page_size": min(page_size, PAGE_SIZE)}
    if _norm_date(created_at_start):
        params["created_at_start"] = _norm_date(created_at_start)
    if _norm_date(created_at_end, end=True):
        params["created_at_end"] = _norm_date(created_at_end, end=True)
    data = _get("/shipments", params=params)
    return {
        "page": data.get("page"),
        "pages": data.get("pages"),
        "total": data.get("total"),
        "shipments": data.get("shipments", []),
    }


def _paginate(path: str, key: str, params: dict) -> list:
    """Pull every page of a v2 list endpoint (up to PAGE_CAP)."""
    out: list = []
    page, pages = 1, 1
    while page <= pages and page <= PAGE_CAP:
        p = dict(params, page=page, page_size=PAGE_SIZE)
        data = _get(path, params=p)
        pages = data.get("pages", 1) or 1
        out.extend(data.get(key, []) or [])
        page += 1
    return out


# Known ShipStation store_ids for this account (Earthwise Seed).
STORES = {
    "amazon": "se-1995856",
    "walmart": "se-842576",
    "tiktok": "se-675808",
    "shopify": "se-1088993",
}


@mcp.tool()
def list_stores(created_at_start: Optional[str] = None,
                created_at_end: Optional[str] = None) -> dict:
    """List ShipStation stores seen in recent shipments, with channel guesses.

    v2 has no stores endpoint, so this samples shipments and groups by store_id,
    classifying the channel from the external order-id format.
    """
    win: dict[str, Any] = {}
    if _norm_date(created_at_start):
        win["created_at_start"] = _norm_date(created_at_start)
    if _norm_date(created_at_end, end=True):
        win["created_at_end"] = _norm_date(created_at_end, end=True)
    shipments = _paginate("/shipments", "shipments", win)
    seen: dict[str, dict] = {}
    for s in shipments:
        sid = s.get("store_id")
        d = seen.setdefault(sid, {"store_id": sid, "shipments": 0, "examples": []})
        d["shipments"] += 1
        eid = s.get("external_order_id") or s.get("external_shipment_id") or ""
        if len(d["examples"]) < 3:
            d["examples"].append(eid)
    known = {v: k for k, v in STORES.items()}
    rows = sorted(seen.values(), key=lambda r: r["shipments"], reverse=True)
    for r in rows:
        r["channel"] = known.get(r["store_id"], "unknown")
    return {"stores": rows}


@mcp.tool()
def avg_shipping_per_sku(
    created_at_start: Optional[str] = None,
    created_at_end: Optional[str] = None,
    store: Optional[str] = None,
    store_id: Optional[str] = None,
    exclude_voided: bool = True,
) -> dict:
    """Average shipping cost per SKU across all labels in a date range.

    In v2, label cost (`shipment_cost`) and line items (`shipment.items[].sku`)
    live on different objects, joined by `shipment_id`. This tool:
      1. pulls every label in the window (cost + shipment_id + voided)
      2. pulls every shipment in the window (items: sku + quantity)
      3. optionally filters shipments to one store/marketplace
      4. joins by shipment_id, sums label cost per shipment
      5. allocates each shipment's cost across its units by quantity
    Per SKU it returns units, shipments, total_allocated_cost, avg per unit.

    This is the figure for the Helium 10 COGS "SHIPPING COST" column.

    Args:
        created_at_start: 'YYYY-MM-DD' (inclusive). Strongly recommended.
        created_at_end:   'YYYY-MM-DD' (inclusive)
        store:            channel name to filter to: 'amazon', 'walmart',
                          'tiktok', or 'shopify'. Omit for all stores.
        store_id:         explicit ShipStation store_id (overrides `store`).
        exclude_voided:   skip voided labels (default True)
    """
    want_store_id = store_id or (STORES.get(store.lower()) if store else None)
    win: dict[str, Any] = {}
    if _norm_date(created_at_start):
        win["created_at_start"] = _norm_date(created_at_start)
    if _norm_date(created_at_end, end=True):
        win["created_at_end"] = _norm_date(created_at_end, end=True)

    labels = _paginate("/labels", "labels", win)
    shipments = _paginate("/shipments", "shipments", win)

    shipments_all = len(shipments)
    if want_store_id:
        shipments = [s for s in shipments if s.get("store_id") == want_store_id]

    # cost per shipment_id (sum if multiple labels on one shipment)
    cost_by_ship: dict[str, float] = {}
    voided_skipped = 0
    for lb in labels:
        if exclude_voided and lb.get("voided"):
            voided_skipped += 1
            continue
        sid = lb.get("shipment_id")
        if not sid:
            continue
        cost_by_ship[sid] = cost_by_ship.get(sid, 0.0) + _amount(lb.get("shipment_cost"))

    per_sku: dict[str, dict[str, float]] = {}
    shipments_matched = 0
    shipments_no_label = 0

    for sh in shipments:
        sid = sh.get("shipment_id")
        cost = cost_by_ship.get(sid)
        if cost is None:
            shipments_no_label += 1
            continue
        items = sh.get("items") or []
        total_units = sum(float(it.get("quantity") or 0) for it in items)
        if total_units <= 0:
            continue
        shipments_matched += 1
        per_unit = cost / total_units
        for it in items:
            qty = float(it.get("quantity") or 0)
            if qty <= 0:
                continue
            sku = (it.get("sku") or "").strip() or "__NO_SKU__"
            acc = per_sku.setdefault(sku, {"units": 0.0, "cost": 0.0, "shipments": 0.0})
            acc["units"] += qty
            acc["cost"] += per_unit * qty
            acc["shipments"] += 1

    rows = []
    for sku, acc in per_sku.items():
        u = acc["units"]
        rows.append({
            "sku": sku,
            "units_shipped": round(u, 2),
            "shipments": int(acc["shipments"]),
            "total_allocated_shipping": round(acc["cost"], 2),
            "avg_shipping_per_unit": round(acc["cost"] / u, 2) if u else 0.0,
        })
    rows.sort(key=lambda r: r["units_shipped"], reverse=True)

    return {
        "date_range": {"start": created_at_start, "end": created_at_end},
        "store_filter": store or want_store_id,
        "labels_pulled": len(labels),
        "labels_voided_skipped": voided_skipped,
        "shipments_pulled_all_stores": shipments_all,
        "shipments_in_store_filter": len(shipments),
        "shipments_matched_to_a_label": shipments_matched,
        "shipments_without_label": shipments_no_label,
        "sku_count": len([r for r in rows if r["sku"] != "__NO_SKU__"]),
        "per_sku": rows,
    }


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    mcp.run()
