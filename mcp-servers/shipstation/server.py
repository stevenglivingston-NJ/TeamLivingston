"""
ShipStation MCP Server
======================
Wraps the ShipStation REST API v2 as MCP tools.

Auth: V2 API key via Bearer token.
  https://www.shipstation.com/docs/api/

Required env vars:
  SHIPSTATION_API_KEY - V2 API key from ShipStation Settings > API Settings
"""

from __future__ import annotations

import os
from typing import Any, Optional

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("shipstation")

API_BASE = "https://ssapi.shipstation.com"
HTTP_TIMEOUT = 30.0


def _headers() -> dict[str, str]:
    key = os.environ.get("SHIPSTATION_API_KEY", "").strip()
    if not key:
        raise ValueError("SHIPSTATION_API_KEY must be set in env.")
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


def _get(path: str, params: Optional[dict] = None) -> Any:
    url = f"{API_BASE}/{path.lstrip('/')}"
    with httpx.Client(timeout=HTTP_TIMEOUT) as client:
        resp = client.get(url, headers=_headers(), params=params)
        resp.raise_for_status()
        return resp.json()


def _post(path: str, json_body: Optional[dict] = None) -> Any:
    url = f"{API_BASE}/{path.lstrip('/')}"
    with httpx.Client(timeout=HTTP_TIMEOUT) as client:
        resp = client.post(url, headers=_headers(), json=json_body or {})
        resp.raise_for_status()
        return resp.json()


# ---------- Connection ----------

@mcp.tool()
def test_connection() -> dict[str, Any]:
    """Verify ShipStation credentials by listing stores."""
    try:
        stores = _get("/stores")
        return {"status": "ok", "store_count": len(stores) if isinstance(stores, list) else 1, "stores": stores}
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ---------- Orders ----------

@mcp.tool()
def list_orders(
    order_status: str = "awaiting_shipment",
    page: int = 1,
    page_size: int = 100,
    store_id: Optional[int] = None,
    create_date_start: Optional[str] = None,
    create_date_end: Optional[str] = None,
    modify_date_start: Optional[str] = None,
    modify_date_end: Optional[str] = None,
    order_number: Optional[str] = None,
    sort_by: str = "OrderDate",
    sort_dir: str = "DESC",
) -> dict[str, Any]:
    """List orders with filtering.

    order_status: awaiting_payment, awaiting_shipment, shipped, on_hold, cancelled
    Dates: ISO format "2026-01-15" or "2026-01-15T00:00:00"
    sort_by: OrderDate, ModifyDate, CreateDate
    """
    params: dict[str, Any] = {
        "orderStatus": order_status,
        "page": page,
        "pageSize": page_size,
        "sortBy": sort_by,
        "sortDir": sort_dir,
    }
    if store_id is not None:
        params["storeId"] = store_id
    if create_date_start:
        params["createDateStart"] = create_date_start
    if create_date_end:
        params["createDateEnd"] = create_date_end
    if modify_date_start:
        params["modifyDateStart"] = modify_date_start
    if modify_date_end:
        params["modifyDateEnd"] = modify_date_end
    if order_number:
        params["orderNumber"] = order_number
    return _get("/orders", params)


@mcp.tool()
def get_order(order_id: int) -> dict[str, Any]:
    """Get full details of a single order."""
    return _get(f"/orders/{order_id}")


@mcp.tool()
def hold_order(order_id: int, hold_until_date: str) -> dict[str, Any]:
    """Place an order on hold until a specified date. Date: YYYY-MM-DD."""
    return _post("/orders/holduntil", {"orderId": order_id, "holdUntilDate": hold_until_date})


@mcp.tool()
def mark_order_shipped(
    order_id: int,
    carrier_code: str,
    tracking_number: str,
    ship_date: Optional[str] = None,
    notify_customer: bool = True,
) -> dict[str, Any]:
    """Mark an order as shipped with tracking info."""
    body: dict[str, Any] = {
        "orderId": order_id,
        "carrierCode": carrier_code,
        "trackingNumber": tracking_number,
        "notifyCustomer": notify_customer,
    }
    if ship_date:
        body["shipDate"] = ship_date
    return _post("/orders/markasshipped", body)


# ---------- Shipments ----------

@mcp.tool()
def list_shipments(
    page: int = 1,
    page_size: int = 100,
    ship_date_start: Optional[str] = None,
    ship_date_end: Optional[str] = None,
    order_number: Optional[str] = None,
    tracking_number: Optional[str] = None,
    store_id: Optional[int] = None,
    sort_by: str = "ShipDate",
    sort_dir: str = "DESC",
) -> dict[str, Any]:
    """List shipments with filtering."""
    params: dict[str, Any] = {
        "page": page,
        "pageSize": page_size,
        "sortBy": sort_by,
        "sortDir": sort_dir,
    }
    if ship_date_start:
        params["shipDateStart"] = ship_date_start
    if ship_date_end:
        params["shipDateEnd"] = ship_date_end
    if order_number:
        params["orderNumber"] = order_number
    if tracking_number:
        params["trackingNumber"] = tracking_number
    if store_id is not None:
        params["storeId"] = store_id
    return _get("/shipments", params)


@mcp.tool()
def get_rates(
    carrier_code: str,
    from_postal_code: str,
    to_postal_code: str,
    to_country: str = "US",
    weight_oz: float = 16.0,
    length: float = 0,
    width: float = 0,
    height: float = 0,
    confirmation: str = "none",
    residential: bool = True,
) -> dict[str, Any]:
    """Get shipping rates for a package.

    carrier_code: 'stamps_com', 'ups', 'fedex', etc.
    confirmation: 'none', 'delivery', 'signature', 'adult_signature'
    """
    body = {
        "carrierCode": carrier_code,
        "fromPostalCode": from_postal_code,
        "toPostalCode": to_postal_code,
        "toCountry": to_country,
        "weight": {"value": weight_oz, "units": "ounces"},
        "dimensions": {"length": length, "width": width, "height": height, "units": "inches"},
        "confirmation": confirmation,
        "residential": residential,
    }
    return _post("/shipments/getrates", body)


@mcp.tool()
def void_label(shipment_id: int) -> dict[str, Any]:
    """Void a shipping label."""
    return _post("/shipments/voidlabel", {"shipmentId": shipment_id})


# ---------- Products ----------

@mcp.tool()
def list_products(
    page: int = 1,
    page_size: int = 100,
    sku: Optional[str] = None,
    name: Optional[str] = None,
) -> dict[str, Any]:
    """List products/SKUs in ShipStation."""
    params: dict[str, Any] = {"page": page, "pageSize": page_size}
    if sku:
        params["sku"] = sku
    if name:
        params["name"] = name
    return _get("/products", params)


@mcp.tool()
def get_product(product_id: int) -> dict[str, Any]:
    """Get details for a single product."""
    return _get(f"/products/{product_id}")


# ---------- Stores & Warehouses ----------

@mcp.tool()
def list_stores() -> dict[str, Any]:
    """List all connected stores (Shopify, WooCommerce, etc.)."""
    return {"stores": _get("/stores")}


@mcp.tool()
def list_warehouses() -> dict[str, Any]:
    """List all warehouses / ship-from locations."""
    return {"warehouses": _get("/warehouses")}


@mcp.tool()
def list_carriers() -> dict[str, Any]:
    """List all carriers enabled on the account."""
    return {"carriers": _get("/carriers")}


# ---------- Fulfillments ----------

@mcp.tool()
def list_fulfillments(
    page: int = 1,
    page_size: int = 100,
    order_id: Optional[int] = None,
) -> dict[str, Any]:
    """List fulfillments. Optionally filter by order."""
    params: dict[str, Any] = {"page": page, "pageSize": page_size}
    if order_id is not None:
        params["orderId"] = order_id
    return _get("/fulfillments", params)


# ---------- Webhooks ----------

@mcp.tool()
def list_webhooks() -> dict[str, Any]:
    """List all registered webhooks."""
    return {"webhooks": _get("/webhooks")}


if __name__ == "__main__":
    mcp.run()
