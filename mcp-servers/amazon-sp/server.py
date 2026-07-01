"""
Amazon Selling Partner (SP-API) MCP Server
==========================================
Wraps the Amazon SP-API as MCP tools for the Jatalia Seeds seller account.

Auth: LWA OAuth2 (Login with Amazon) - client credentials + refresh token.

Required env vars:
  AMAZON_SP_CLIENT_ID      - LWA client identifier
  AMAZON_SP_CLIENT_SECRET   - LWA client secret
  AMAZON_SP_REFRESH_TOKEN   - SP-API refresh token
"""

from __future__ import annotations

import os
import time
from typing import Any, Optional

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("amazon-sp")

SP_API_BASE = "https://sellingpartnerapi-na.amazon.com"
LWA_TOKEN_URL = "https://api.amazon.com/auth/o2/token"
HTTP_TIMEOUT = 30.0
MARKETPLACE_US = "ATVPDKIKX0DER"

_token_cache: dict[str, Any] = {"token": None, "expires_at": 0}


def _get_access_token() -> str:
    now = time.time()
    if _token_cache["token"] and _token_cache["expires_at"] > now + 60:
        return _token_cache["token"]

    client_id = os.environ.get("AMAZON_SP_CLIENT_ID", "").strip()
    client_secret = os.environ.get("AMAZON_SP_CLIENT_SECRET", "").strip()
    refresh_token = os.environ.get("AMAZON_SP_REFRESH_TOKEN", "").strip()
    if not all([client_id, client_secret, refresh_token]):
        raise ValueError("AMAZON_SP_CLIENT_ID, AMAZON_SP_CLIENT_SECRET, and AMAZON_SP_REFRESH_TOKEN must be set.")

    with httpx.Client(timeout=HTTP_TIMEOUT) as client:
        resp = client.post(LWA_TOKEN_URL, data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
            "client_secret": client_secret,
        })
        resp.raise_for_status()
        data = resp.json()

    _token_cache["token"] = data["access_token"]
    _token_cache["expires_at"] = now + data.get("expires_in", 3600)
    return _token_cache["token"]


def _headers() -> dict[str, str]:
    return {
        "x-amz-access-token": _get_access_token(),
        "Content-Type": "application/json",
    }


def _get(path: str, params: Optional[dict] = None) -> Any:
    url = f"{SP_API_BASE}{path}"
    with httpx.Client(timeout=HTTP_TIMEOUT) as client:
        resp = client.get(url, headers=_headers(), params=params)
        resp.raise_for_status()
        return resp.json()


def _post(path: str, json_body: Optional[dict] = None) -> Any:
    url = f"{SP_API_BASE}{path}"
    with httpx.Client(timeout=HTTP_TIMEOUT) as client:
        resp = client.post(url, headers=_headers(), json=json_body or {})
        resp.raise_for_status()
        return resp.json()


# ---------- Connection ----------

@mcp.tool()
def test_connection() -> dict[str, Any]:
    """Verify Amazon SP-API credentials by fetching marketplace participations."""
    try:
        data = _get("/sellers/v1/marketplaceParticipations")
        participations = data.get("payload", [])
        markets = [
            {
                "marketplace": p.get("marketplace", {}).get("name"),
                "country": p.get("marketplace", {}).get("countryCode"),
                "marketplace_id": p.get("marketplace", {}).get("id"),
                "is_participating": p.get("participation", {}).get("isParticipating"),
            }
            for p in participations
        ]
        return {"status": "ok", "marketplace_count": len(markets), "marketplaces": markets}
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ---------- Orders ----------

@mcp.tool()
def list_orders(
    created_after: Optional[str] = None,
    created_before: Optional[str] = None,
    last_updated_after: Optional[str] = None,
    order_statuses: Optional[str] = None,
    max_results: int = 20,
    next_token: Optional[str] = None,
) -> dict[str, Any]:
    """List orders from Amazon.

    created_after/created_before: ISO 8601 (e.g. '2026-01-01T00:00:00Z')
    order_statuses: comma-separated, e.g. 'Unshipped,PartiallyShipped'
      Valid: PendingAvailability, Pending, Unshipped, PartiallyShipped,
             Shipped, InvoiceUnconfirmed, Canceled, Unfulfillable
    """
    params: dict[str, Any] = {
        "MarketplaceIds": MARKETPLACE_US,
        "MaxResultsPerPage": min(max_results, 100),
    }
    if created_after:
        params["CreatedAfter"] = created_after
    if created_before:
        params["CreatedBefore"] = created_before
    if last_updated_after:
        params["LastUpdatedAfter"] = last_updated_after
    if order_statuses:
        params["OrderStatuses"] = order_statuses
    if next_token:
        params["NextToken"] = next_token
    return _get("/orders/v0/orders", params)


@mcp.tool()
def get_order(order_id: str) -> dict[str, Any]:
    """Get details for a single order by Amazon order ID."""
    return _get(f"/orders/v0/orders/{order_id}")


@mcp.tool()
def get_order_items(order_id: str) -> dict[str, Any]:
    """Get line items for an order."""
    return _get(f"/orders/v0/orders/{order_id}/orderItems")


# ---------- Inventory ----------

@mcp.tool()
def get_inventory_summaries(
    seller_skus: Optional[str] = None,
    granularity_type: str = "Marketplace",
    next_token: Optional[str] = None,
) -> dict[str, Any]:
    """Get FBA inventory summaries.

    seller_skus: comma-separated list of SKUs to filter
    granularity_type: 'Marketplace' (default)
    """
    params: dict[str, Any] = {
        "granularityType": granularity_type,
        "granularityId": MARKETPLACE_US,
        "marketplaceIds": MARKETPLACE_US,
    }
    if seller_skus:
        params["sellerSkus"] = seller_skus
    if next_token:
        params["nextToken"] = next_token
    return _get("/fba/inventory/v1/summaries", params)


# ---------- Catalog / Products ----------

@mcp.tool()
def search_catalog(
    keywords: str,
    page_size: int = 10,
    next_token: Optional[str] = None,
) -> dict[str, Any]:
    """Search the Amazon catalog by keywords.

    Returns ASINs, titles, and basic product info.
    """
    params: dict[str, Any] = {
        "marketplaceIds": MARKETPLACE_US,
        "keywords": keywords,
        "pageSize": min(page_size, 20),
        "includedData": "summaries,images",
    }
    if next_token:
        params["pageToken"] = next_token
    return _get("/catalog/2022-04-01/items", params)


@mcp.tool()
def get_catalog_item(asin: str) -> dict[str, Any]:
    """Get detailed catalog info for an ASIN."""
    params = {
        "marketplaceIds": MARKETPLACE_US,
        "includedData": "summaries,attributes,images,productTypes,salesRanks",
    }
    return _get(f"/catalog/2022-04-01/items/{asin}", params)


@mcp.tool()
def get_my_listings(
    seller_sku: Optional[str] = None,
    next_token: Optional[str] = None,
) -> dict[str, Any]:
    """Get your active listings / offers.

    seller_sku: filter to a specific SKU
    """
    params: dict[str, Any] = {
        "marketplaceIds": MARKETPLACE_US,
        "includedData": "summaries,offers,fulfillmentAvailability",
        "pageSize": 20,
    }
    if seller_sku:
        params["sellerSku"] = seller_sku
    if next_token:
        params["pageToken"] = next_token
    return _get("/listings/2021-08-01/items", params)


@mcp.tool()
def get_competitive_pricing(asin: str) -> dict[str, Any]:
    """Get competitive pricing for an ASIN (Buy Box, lowest prices)."""
    params = {
        "MarketplaceId": MARKETPLACE_US,
        "Asins": asin,
        "ItemType": "Asin",
    }
    return _get("/products/pricing/v0/competitivePrice", params)


# ---------- Reports ----------

@mcp.tool()
def create_report(
    report_type: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> dict[str, Any]:
    """Request an Amazon report.

    report_type examples:
      GET_FLAT_FILE_OPEN_LISTINGS_DATA - active listings
      GET_MERCHANT_LISTINGS_ALL_DATA - all listings
      GET_FBA_MYI_UNSUPPRESSED_INVENTORY_DATA - FBA inventory
      GET_FLAT_FILE_ORDERS_DATA - orders (flat file)
      GET_AMAZON_FULFILLED_SHIPMENTS_DATA_GENERAL - FBA shipments
      GET_FBA_FULFILLMENT_CUSTOMER_RETURNS_DATA - FBA returns
      GET_SALES_AND_TRAFFIC_REPORT - business reports
    start_date/end_date: ISO 8601 for date-ranged reports
    """
    body: dict[str, Any] = {
        "reportType": report_type,
        "marketplaceIds": [MARKETPLACE_US],
    }
    if start_date or end_date:
        dr: dict[str, str] = {}
        if start_date:
            dr["dataStartTime"] = start_date
        if end_date:
            dr["dataEndTime"] = end_date
        body["dataStartTime"] = start_date
        if end_date:
            body["dataEndTime"] = end_date
    return _post("/reports/2021-06-30/reports", body)


@mcp.tool()
def get_report(report_id: str) -> dict[str, Any]:
    """Check the status of a report request."""
    return _get(f"/reports/2021-06-30/reports/{report_id}")


@mcp.tool()
def get_report_document(report_document_id: str) -> dict[str, Any]:
    """Get the download URL for a completed report."""
    return _get(f"/reports/2021-06-30/documents/{report_document_id}")


# ---------- Finances ----------

@mcp.tool()
def list_financial_events(
    order_id: Optional[str] = None,
    posted_after: Optional[str] = None,
    posted_before: Optional[str] = None,
    next_token: Optional[str] = None,
) -> dict[str, Any]:
    """List financial events (payments, refunds, fees).

    order_id: filter to a specific order
    posted_after/posted_before: ISO 8601
    """
    if order_id:
        return _get(f"/finances/v0/orders/{order_id}/financialEvents")
    params: dict[str, Any] = {}
    if posted_after:
        params["PostedAfter"] = posted_after
    if posted_before:
        params["PostedBefore"] = posted_before
    if next_token:
        params["NextToken"] = next_token
    return _get("/finances/v0/financialEvents", params)


# ---------- FBA Inbound ----------

@mcp.tool()
def list_inbound_shipments(
    shipment_status: str = "WORKING",
    next_token: Optional[str] = None,
) -> dict[str, Any]:
    """List FBA inbound shipments.

    shipment_status: WORKING, SHIPPED, RECEIVING, CANCELLED, DELETED, CLOSED, ERROR, IN_TRANSIT, DELIVERED, CHECKED_IN
    """
    params: dict[str, Any] = {
        "MarketplaceId": MARKETPLACE_US,
        "ShipmentStatusList": shipment_status,
        "QueryType": "SHIPMENT",
    }
    if next_token:
        params["NextToken"] = next_token
    return _get("/fba/inbound/v0/shipments", params)


if __name__ == "__main__":
    mcp.run()
