"""
Walmart Ads (Walmart Connect / Sponsored Search) MCP Server
===========================================================
Harvest's Walmart demand/ROAS lane. Cloud port of walmart-mcp/walmart_ads_*.py.

Auth: OAuth2 client_credentials (Basic auth → /v3/token), same token endpoint as
the Marketplace API but SEPARATE credentials issued in Ad Center → API Access.
No request signature is required (the older docs claim RSA signing, but the live
API path uses the bearer token only). advertiserId is passed as a query param.

Required env vars (see mcp-servers/.env.example):
  WMT_ADS_CLIENT_ID       - Ad Center API client id
  WMT_ADS_CLIENT_SECRET   - Ad Center API client secret
  WMT_ADS_ADVERTISER_ID   - advertiser id (numeric)
"""
from __future__ import annotations

import base64
import os
import time
import uuid
from typing import Any, Optional

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("walmart-ads")

TOKEN_URL = "https://marketplace.walmartapis.com/v3/token"
ADS_BASE = "https://developer.api.walmart.com/api-proxy/service/WPA/Api/v1"
HTTP_TIMEOUT = 30.0

_token_cache: dict[str, Any] = {"token": None, "expires_at": 0}


def _creds() -> dict[str, str]:
    cid = os.environ.get("WMT_ADS_CLIENT_ID", "").strip()
    sec = os.environ.get("WMT_ADS_CLIENT_SECRET", "").strip()
    adv = os.environ.get("WMT_ADS_ADVERTISER_ID", "").strip()
    if not (cid and sec):
        raise ValueError("WMT_ADS_CLIENT_ID and WMT_ADS_CLIENT_SECRET must be set.")
    return {"client_id": cid, "client_secret": sec, "advertiser_id": adv}


def _get_token() -> str:
    now = time.time()
    if _token_cache["token"] and _token_cache["expires_at"] > now + 60:
        return _token_cache["token"]
    c = _creds()
    basic = base64.b64encode(f"{c['client_id']}:{c['client_secret']}".encode()).decode()
    with httpx.Client(timeout=HTTP_TIMEOUT) as client:
        resp = client.post(TOKEN_URL, headers={
            "Authorization": f"Basic {basic}",
            "WM_QOS.CORRELATION_ID": str(uuid.uuid4()),
            "WM_SVC.NAME": "Walmart Marketplace",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        }, data={"grant_type": "client_credentials"})
        resp.raise_for_status()
        data = resp.json()
    tok = data.get("access_token")
    if not tok:
        raise ValueError(f"No access_token in token response: {data}")
    _token_cache["token"] = tok
    _token_cache["expires_at"] = now + int(data.get("expires_in", 900))
    return tok


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_get_token()}",
        "WM_QOS.CORRELATION_ID": str(uuid.uuid4()),
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _get(path: str, params: Optional[dict] = None) -> Any:
    p = {"advertiserId": _creds()["advertiser_id"]}
    if params:
        p.update(params)
    with httpx.Client(timeout=HTTP_TIMEOUT) as client:
        resp = client.get(f"{ADS_BASE}{path}", headers=_headers(), params=p)
        resp.raise_for_status()
        return resp.json()


def _post(path: str, body: Optional[dict] = None) -> Any:
    with httpx.Client(timeout=HTTP_TIMEOUT) as client:
        resp = client.post(f"{ADS_BASE}{path}", headers=_headers(),
                           params={"advertiserId": _creds()["advertiser_id"]}, json=body or {})
        resp.raise_for_status()
        return resp.json()


# ---------- Connection ----------

@mcp.tool()
def test_connection() -> dict[str, Any]:
    """Verify Walmart Ads credentials by listing campaigns for the advertiser."""
    try:
        data = _get("/api/v1/campaigns")
        n = len(data) if isinstance(data, list) else len(data.get("response", []) if isinstance(data, dict) else [])
        return {"status": "ok", "advertiser_id": _creds()["advertiser_id"], "campaign_count": n}
    except Exception as e:  # noqa: BLE001 — surface auth/HTTP errors to the caller
        return {"status": "error", "error": str(e)}


# ---------- Reads ----------

@mcp.tool()
def list_campaigns() -> Any:
    """List Sponsored Search campaigns for the scoped advertiser."""
    return _get("/api/v1/campaigns")


@mcp.tool()
def list_ad_groups(campaign_id: str) -> Any:
    """List ad groups within a campaign."""
    return _get("/api/v1/adGroups", params={"campaignId": campaign_id})


@mcp.tool()
def list_keywords(ad_group_id: str) -> Any:
    """List keywords within an ad group."""
    return _get("/api/v1/keywords", params={"adGroupId": ad_group_id})


@mcp.tool()
def realtime_stats() -> Any:
    """Real-time performance stats (impressions/clicks/spend/attributed sales)."""
    return _get("/api/v1/stats")


@mcp.tool()
def request_performance_snapshot(start_date: str, end_date: str) -> Any:
    """Request an async performance snapshot report (v2). Dates YYYY-MM-DD.

    Returns a report/snapshot id; poll the download url per Walmart's snapshot flow.
    """
    body = {"startDate": start_date, "endDate": end_date, "reportType": "keyword",
            "format": "JSON"}
    return _post("/api/v2/snapshots", body)


if __name__ == "__main__":
    mcp.run()
