"""
Google Business Profile (GMB) MCP Server for KTU + BTU.

Wraps the Google Business Profile API (formerly Google My Business) as MCP tools.
Covers reviews, insights, posts, and business info for both locations.

Required env vars:
  GOOGLE_ADS_CLIENT_ID       - shared with google-ads-mcp
  GOOGLE_ADS_CLIENT_SECRET   - shared with google-ads-mcp
  GOOGLE_ADS_REFRESH_TOKEN   - shared with google-ads-mcp
  GMB_ACCOUNT_ID             - from Business Profile API (accounts.list)
  GMB_LOCATION_KTU           - location ID for KTU
  GMB_LOCATION_BTU           - location ID for BTU
"""

from __future__ import annotations

import os
from typing import Any, Optional

import httpx
from mcp.server.fastmcp import FastMCP
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

mcp = FastMCP("gmb")

API_BASE = "https://mybusinessbusinessinformation.googleapis.com/v1"
REVIEWS_BASE = "https://mybusinessreviews.googleapis.com/v1"
PERFORMANCE_BASE = "https://businessprofileperformance.googleapis.com/v1"
HTTP_TIMEOUT = 30.0

LOCATION_MAP: dict[str, str] = {
    "KTU": "GMB_LOCATION_KTU",
    "BTU": "GMB_LOCATION_BTU",
}


def _oauth_token() -> str:
    creds = Credentials(
        None,
        refresh_token=os.environ["GOOGLE_ADS_REFRESH_TOKEN"],
        client_id=os.environ["GOOGLE_ADS_CLIENT_ID"],
        client_secret=os.environ["GOOGLE_ADS_CLIENT_SECRET"],
        token_uri="https://oauth2.googleapis.com/token",
    )
    creds.refresh(Request())
    return creds.token


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_oauth_token()}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _account_id() -> str:
    aid = os.environ.get("GMB_ACCOUNT_ID", "").strip()
    if not aid:
        raise ValueError("GMB_ACCOUNT_ID env var not set.")
    return aid


def _location_name(location: str) -> str:
    loc = location.upper().strip()
    env_var = LOCATION_MAP.get(loc)
    if not env_var:
        valid = ", ".join(sorted(LOCATION_MAP.keys()))
        raise ValueError(f"Unknown location '{location}'. Valid: {valid}")
    lid = os.environ.get(env_var, "").strip()
    if not lid:
        raise ValueError(f"{env_var} env var not set.")
    return f"locations/{lid}"


def _get(url: str, params: Optional[dict] = None) -> Any:
    with httpx.Client(timeout=HTTP_TIMEOUT) as client:
        resp = client.get(url, headers=_headers(), params=params)
        resp.raise_for_status()
        return resp.json()


def _post(url: str, json_body: Optional[dict] = None) -> Any:
    with httpx.Client(timeout=HTTP_TIMEOUT) as client:
        resp = client.post(url, headers=_headers(), json=json_body or {})
        resp.raise_for_status()
        return resp.json()


def _patch(url: str, json_body: dict, update_mask: str) -> Any:
    with httpx.Client(timeout=HTTP_TIMEOUT) as client:
        resp = client.patch(
            url, headers=_headers(), json=json_body,
            params={"updateMask": update_mask},
        )
        resp.raise_for_status()
        return resp.json()


# ---------- Connection ----------

@mcp.tool()
def list_locations() -> dict[str, Any]:
    """List configured GMB locations and check env vars."""
    ok = True
    status = {}
    for loc, env_var in LOCATION_MAP.items():
        configured = bool(os.environ.get(env_var))
        status[loc] = {"env_var": env_var, "configured": configured}
        if not configured:
            ok = False
    return {
        "locations": status,
        "account_id_set": bool(os.environ.get("GMB_ACCOUNT_ID")),
        "all_configured": ok,
    }


@mcp.tool()
def test_connection(location: str) -> dict[str, Any]:
    """Verify credentials by fetching basic location info."""
    loc_name = _location_name(location)
    url = f"{API_BASE}/{loc_name}?readMask=name,title,storefrontAddress"
    try:
        data = _get(url)
        return {"status": "ok", "location": location, "data": data}
    except Exception as e:
        return {"status": "error", "location": location, "error": str(e)}


# ---------- Reviews ----------

@mcp.tool()
def list_reviews(
    location: str,
    page_size: int = 50,
    page_token: str = "",
    order_by: str = "updateTime desc",
) -> dict[str, Any]:
    """List reviews for a location. order_by: 'updateTime desc' or 'rating desc'."""
    loc_name = _location_name(location)
    params: dict[str, Any] = {"pageSize": page_size, "orderBy": order_by}
    if page_token:
        params["pageToken"] = page_token
    url = f"{REVIEWS_BASE}/{loc_name}/reviews"
    return _get(url, params)


@mcp.tool()
def get_review(location: str, review_id: str) -> dict[str, Any]:
    """Get a single review by ID."""
    loc_name = _location_name(location)
    url = f"{REVIEWS_BASE}/{loc_name}/reviews/{review_id}"
    return _get(url)


@mcp.tool()
def reply_to_review(location: str, review_id: str, comment: str) -> dict[str, Any]:
    """Reply to a review. Updates existing reply if one exists."""
    loc_name = _location_name(location)
    url = f"{REVIEWS_BASE}/{loc_name}/reviews/{review_id}/reply"
    return _patch(url, {"comment": comment}, "comment")


@mcp.tool()
def delete_review_reply(location: str, review_id: str) -> dict[str, Any]:
    """Delete an existing reply to a review."""
    loc_name = _location_name(location)
    url = f"{REVIEWS_BASE}/{loc_name}/reviews/{review_id}/reply"
    with httpx.Client(timeout=HTTP_TIMEOUT) as client:
        resp = client.delete(url, headers=_headers())
        resp.raise_for_status()
        return {"status": "deleted", "review_id": review_id}


# ---------- Performance / Insights ----------

@mcp.tool()
def get_daily_metrics(
    location: str,
    start_date: str,
    end_date: str,
    daily_metric: str = "BUSINESS_IMPRESSIONS_DESKTOP_MAPS",
) -> dict[str, Any]:
    """Get daily performance metrics for a location.

    start_date/end_date: YYYY-MM-DD
    daily_metric options:
      BUSINESS_IMPRESSIONS_DESKTOP_MAPS, BUSINESS_IMPRESSIONS_DESKTOP_SEARCH,
      BUSINESS_IMPRESSIONS_MOBILE_MAPS, BUSINESS_IMPRESSIONS_MOBILE_SEARCH,
      BUSINESS_CONVERSATIONS, BUSINESS_DIRECTION_REQUESTS,
      CALL_CLICKS, WEBSITE_CLICKS, BUSINESS_BOOKINGS
    """
    loc_name = _location_name(location)
    url = (
        f"{PERFORMANCE_BASE}/{loc_name}:getDailyMetricsTimeSeries"
        f"?dailyMetric={daily_metric}"
        f"&dailyRange.startDate.year={start_date[:4]}"
        f"&dailyRange.startDate.month={int(start_date[5:7])}"
        f"&dailyRange.startDate.day={int(start_date[8:10])}"
        f"&dailyRange.endDate.year={end_date[:4]}"
        f"&dailyRange.endDate.month={int(end_date[5:7])}"
        f"&dailyRange.endDate.day={int(end_date[8:10])}"
    )
    return _get(url)


@mcp.tool()
def get_multi_daily_metrics(
    location: str,
    start_date: str,
    end_date: str,
) -> dict[str, Any]:
    """Get all key daily metrics at once for a date range.

    Returns impressions (desktop/mobile, maps/search), calls, website clicks,
    direction requests, bookings, conversations.
    """
    metrics = [
        "BUSINESS_IMPRESSIONS_DESKTOP_MAPS",
        "BUSINESS_IMPRESSIONS_DESKTOP_SEARCH",
        "BUSINESS_IMPRESSIONS_MOBILE_MAPS",
        "BUSINESS_IMPRESSIONS_MOBILE_SEARCH",
        "CALL_CLICKS",
        "WEBSITE_CLICKS",
        "BUSINESS_DIRECTION_REQUESTS",
        "BUSINESS_BOOKINGS",
        "BUSINESS_CONVERSATIONS",
    ]
    results = {}
    for m in metrics:
        try:
            results[m] = get_daily_metrics(location, start_date, end_date, m)
        except Exception as e:
            results[m] = {"error": str(e)}
    return {"location": location, "date_range": {"start": start_date, "end": end_date}, "metrics": results}


@mcp.tool()
def get_search_keywords(
    location: str,
    start_date: str,
    end_date: str,
) -> dict[str, Any]:
    """Get search keywords that surfaced the business profile.

    Returns keyword text and impression count.
    """
    loc_name = _location_name(location)
    url = (
        f"{PERFORMANCE_BASE}/{loc_name}/searchkeywords/impressions/monthly"
        f"?monthlyRange.startMonth.year={start_date[:4]}"
        f"&monthlyRange.startMonth.month={int(start_date[5:7])}"
        f"&monthlyRange.endMonth.year={end_date[:4]}"
        f"&monthlyRange.endMonth.month={int(end_date[5:7])}"
    )
    return _get(url)


# ---------- Business Info ----------

@mcp.tool()
def get_location_info(location: str) -> dict[str, Any]:
    """Get full business info: name, address, phone, hours, categories, etc."""
    loc_name = _location_name(location)
    url = f"{API_BASE}/{loc_name}"
    return _get(url)


@mcp.tool()
def get_location_hours(location: str) -> dict[str, Any]:
    """Get business hours for a location."""
    loc_name = _location_name(location)
    url = f"{API_BASE}/{loc_name}?readMask=regularHours,specialHours"
    return _get(url)


if __name__ == "__main__":
    mcp.run()
