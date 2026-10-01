"""
Amazon Ads API MCP Server
=========================
Wraps the Amazon Advertising API as MCP tools for the Jatalia / Earthwise Seeds
seller account. Harvest's demand/ROAS lane (counterpart to amazon-sp's ops lane).

Auth: LWA OAuth2 (Login with Amazon) — client credentials + refresh token, same
flow as amazon-sp but a SEPARATE Ads-API app + refresh token and an Ads profile.

Required env vars (see mcp-servers/.env.example):
  AMAZON_ADS_CLIENT_ID       - LWA client identifier (Ads API app)
  AMAZON_ADS_CLIENT_SECRET   - LWA client secret
  AMAZON_ADS_REFRESH_TOKEN   - Ads API refresh token
  AMAZON_ADS_PROFILE_ID      - Ads profile id (the account scope; e.g. 1035588453215307)
  AMAZON_ADS_REGION          - NA (default) | EU | FE
"""
from __future__ import annotations

import os
import time
from typing import Any, Optional

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("amazon-ads")

LWA_TOKEN_URL = "https://api.amazon.com/auth/o2/token"
HTTP_TIMEOUT = 30.0
_REGION_BASE = {
    "NA": "https://advertising-api.amazon.com",
    "EU": "https://advertising-api-eu.amazon.com",
    "FE": "https://advertising-api-fe.amazon.com",
}

_token_cache: dict[str, Any] = {"token": None, "expires_at": 0}


def _region_base() -> str:
    return _REGION_BASE.get(os.environ.get("AMAZON_ADS_REGION", "NA").strip().upper(), _REGION_BASE["NA"])


def _get_access_token() -> str:
    now = time.time()
    if _token_cache["token"] and _token_cache["expires_at"] > now + 60:
        return _token_cache["token"]

    client_id = os.environ.get("AMAZON_ADS_CLIENT_ID", "").strip()
    client_secret = os.environ.get("AMAZON_ADS_CLIENT_SECRET", "").strip()
    refresh_token = os.environ.get("AMAZON_ADS_REFRESH_TOKEN", "").strip()
    if not all([client_id, client_secret, refresh_token]):
        raise ValueError("AMAZON_ADS_CLIENT_ID, AMAZON_ADS_CLIENT_SECRET, and AMAZON_ADS_REFRESH_TOKEN must be set.")

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


def _headers(extra: Optional[dict] = None) -> dict[str, str]:
    h = {
        "Amazon-Advertising-API-ClientId": os.environ.get("AMAZON_ADS_CLIENT_ID", "").strip(),
        "Authorization": f"Bearer {_get_access_token()}",
        "Content-Type": "application/json",
    }
    profile = os.environ.get("AMAZON_ADS_PROFILE_ID", "").strip()
    if profile:
        h["Amazon-Advertising-API-Scope"] = profile
    if extra:
        h.update(extra)
    return h


def _get(path: str, params: Optional[dict] = None, extra_headers: Optional[dict] = None) -> Any:
    url = f"{_region_base()}{path}"
    with httpx.Client(timeout=HTTP_TIMEOUT) as client:
        resp = client.get(url, headers=_headers(extra_headers), params=params)
        resp.raise_for_status()
        return resp.json()


def _post(path: str, json_body: Optional[dict] = None, extra_headers: Optional[dict] = None) -> Any:
    url = f"{_region_base()}{path}"
    with httpx.Client(timeout=HTTP_TIMEOUT) as client:
        resp = client.post(url, headers=_headers(extra_headers), json=json_body or {})
        resp.raise_for_status()
        return resp.json()


# ---------- Connection ----------

@mcp.tool()
def test_connection() -> dict[str, Any]:
    """Verify Amazon Ads credentials by listing the account's ad profiles."""
    try:
        profiles = _get("/v2/profiles")
        return {
            "status": "ok",
            "profile_count": len(profiles) if isinstance(profiles, list) else 0,
            "scoped_profile": os.environ.get("AMAZON_ADS_PROFILE_ID", "").strip() or None,
            "region": os.environ.get("AMAZON_ADS_REGION", "NA"),
        }
    except Exception as e:  # noqa: BLE001 — surface any auth/HTTP error to the caller
        return {"status": "error", "error": str(e)}


@mcp.tool()
def list_profiles() -> Any:
    """List all Amazon Ads profiles (accounts/marketplaces) the credentials can access."""
    return _get("/v2/profiles")


# ---------- Sponsored Products ----------

@mcp.tool()
def list_sp_campaigns(state_filter: Optional[str] = None, max_results: int = 100) -> Any:
    """List Sponsored Products campaigns for the scoped profile.

    state_filter: optional comma-separated states — ENABLED, PAUSED, ARCHIVED.
    """
    body: dict[str, Any] = {"maxResults": min(max_results, 500)}
    if state_filter:
        body["stateFilter"] = {"include": [s.strip().upper() for s in state_filter.split(",")]}
    return _post("/sp/campaigns/list", body, extra_headers={
        "Content-Type": "application/vnd.spCampaign.v3+json",
        "Accept": "application/vnd.spCampaign.v3+json",
    })


@mcp.tool()
def list_sp_ad_groups(campaign_id: Optional[str] = None, max_results: int = 100) -> Any:
    """List Sponsored Products ad groups, optionally filtered to one campaign."""
    body: dict[str, Any] = {"maxResults": min(max_results, 500)}
    if campaign_id:
        body["campaignIdFilter"] = {"include": [str(campaign_id)]}
    return _post("/sp/adGroups/list", body, extra_headers={
        "Content-Type": "application/vnd.spAdGroup.v3+json",
        "Accept": "application/vnd.spAdGroup.v3+json",
    })


@mcp.tool()
def request_sp_report(start_date: str, end_date: str, group_by: str = "campaign") -> Any:
    """Request an async Sponsored Products performance report (v3 reporting).

    start_date/end_date: YYYY-MM-DD. group_by: campaign | adGroup | keyword.
    Returns a report id; poll get_report(report_id) until status is COMPLETED,
    then download the url it returns.
    """
    columns = ["impressions", "clicks", "cost", "purchases30d", "sales30d",
               "campaignName", "campaignId"]
    body = {
        "name": f"SP {group_by} {start_date}..{end_date}",
        "startDate": start_date,
        "endDate": end_date,
        "configuration": {
            "adProduct": "SPONSORED_PRODUCTS",
            "groupBy": [group_by],
            "columns": columns,
            "reportTypeId": "spCampaigns",
            "timeUnit": "SUMMARY",
            "format": "GZIP_JSON",
        },
    }
    return _post("/reporting/reports", body)


@mcp.tool()
def get_report(report_id: str) -> Any:
    """Check status / fetch the download url for a report from request_sp_report."""
    return _get(f"/reporting/reports/{report_id}")


if __name__ == "__main__":
    mcp.run()
