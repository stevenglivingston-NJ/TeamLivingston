"""
Google Analytics 4 (GA4) MCP Server for KTU + BTU.

Wraps the GA4 Data API (analyticsdata.googleapis.com) directly, replacing the
Zapier raw-request path documented in .claude/agents/paid.md.

Required env vars:
  GA4_CLIENT_ID       - Google OAuth client id. Can reuse GOOGLE_ADS_CLIENT_ID
                         (same OAuth app) — the client id/secret only identify
                         the app; scopes live on the refresh token.
  GA4_CLIENT_SECRET    - paired with GA4_CLIENT_ID.
  GA4_REFRESH_TOKEN    - MUST be minted with the analytics.readonly scope.
                         Verified 2026-08-21: the existing GOOGLE_ADS_REFRESH_TOKEN
                         carries only adwords + business.manage — calling GA4 with
                         it fails ACCESS_TOKEN_SCOPE_INSUFFICIENT (403). A fresh
                         OAuth consent (same client, +analytics.readonly scope) is
                         required; this cannot be done non-interactively.
  GA4_PROPERTY_ID_KTU  - optional override, default 453600017 ("In Use" property
                         per paid.md; 349585536 is the dead/retired one).
  GA4_PROPERTY_ID_BTU  - optional override, default 487870392.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

mcp = FastMCP("google-analytics")

API_BASE = "https://analyticsdata.googleapis.com/v1beta"
HTTP_TIMEOUT = 30.0

DEFAULT_PROPERTY_ID: dict[str, str] = {
    "KTU": "453600017",
    "BTU": "487870392",
}


def _oauth_token() -> str:
    creds = Credentials(
        None,
        refresh_token=os.environ["GA4_REFRESH_TOKEN"],
        client_id=os.environ.get("GA4_CLIENT_ID") or os.environ["GOOGLE_ADS_CLIENT_ID"],
        client_secret=os.environ.get("GA4_CLIENT_SECRET") or os.environ["GOOGLE_ADS_CLIENT_SECRET"],
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


def _property_id(brand: str) -> str:
    b = brand.upper().strip()
    if b not in DEFAULT_PROPERTY_ID:
        raise ValueError(f"Unknown brand '{brand}'. Valid options: KTU, BTU.")
    return os.environ.get(f"GA4_PROPERTY_ID_{b}", DEFAULT_PROPERTY_ID[b])


def _run_report(property_id: str, body: dict[str, Any]) -> dict[str, Any]:
    url = f"{API_BASE}/properties/{property_id}:runReport"
    with httpx.Client(timeout=HTTP_TIMEOUT) as client:
        resp = client.post(url, json=body, headers=_headers())
        resp.raise_for_status()
        return resp.json()


@mcp.tool()
def test_connection(brand: str = "KTU") -> dict[str, Any]:
    """Verify the GA4 token works by pulling a 1-day session count for a brand.

    A 403 ACCESS_TOKEN_SCOPE_INSUFFICIENT means GA4_REFRESH_TOKEN was not minted
    with the analytics.readonly scope — re-authorize, this is not a config typo.
    """
    return _run_report(
        _property_id(brand),
        {"dateRanges": [{"startDate": "yesterday", "endDate": "today"}],
         "metrics": [{"name": "sessions"}]},
    )


@mcp.tool()
def run_report(
    brand: str,
    start_date: str,
    end_date: str,
    metrics: list[str],
    dimensions: list[str] | None = None,
    dimension_filter: dict[str, Any] | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Run an arbitrary GA4 report for KTU or BTU.

    `start_date`/`end_date` accept GA4's relative forms ("today", "7daysAgo",
    "yesterday") or absolute YYYY-MM-DD. `metrics`/`dimensions` are GA4 API names
    (e.g. metrics=["sessions","conversions"], dimensions=["sessionDefaultChannelGroup"]).
    `dimension_filter`, if given, is passed through verbatim as the API's
    dimensionFilter object — see GA4 Data API docs for its shape.
    """
    body: dict[str, Any] = {
        "dateRanges": [{"startDate": start_date, "endDate": end_date}],
        "metrics": [{"name": m} for m in metrics],
        "limit": limit,
    }
    if dimensions:
        body["dimensions"] = [{"name": d} for d in dimensions]
    if dimension_filter:
        body["dimensionFilter"] = dimension_filter
    return _run_report(_property_id(brand), body)


@mcp.tool()
def get_channel_performance(brand: str, start_date: str = "30daysAgo", end_date: str = "today") -> dict[str, Any]:
    """Sessions, users, and conversions by default channel group (Organic/Paid/Direct/etc.)."""
    return _run_report(
        _property_id(brand),
        {
            "dateRanges": [{"startDate": start_date, "endDate": end_date}],
            "dimensions": [{"name": "sessionDefaultChannelGroup"}],
            "metrics": [{"name": "sessions"}, {"name": "totalUsers"}, {"name": "conversions"}],
        },
    )


@mcp.tool()
def get_landing_page_performance(brand: str, start_date: str = "30daysAgo", end_date: str = "today") -> dict[str, Any]:
    """Sessions, bounce rate, and conversions by landing page — the Paid spec's
    'tie spend to real customers' and Pipeline's landing-page leak check both
    want this cut."""
    return _run_report(
        _property_id(brand),
        {
            "dateRanges": [{"startDate": start_date, "endDate": end_date}],
            "dimensions": [{"name": "landingPage"}],
            "metrics": [{"name": "sessions"}, {"name": "bounceRate"}, {"name": "conversions"}],
            "limit": 50,
        },
    )


@mcp.tool()
def get_generate_lead_events(brand: str, start_date: str = "7daysAgo", end_date: str = "today") -> dict[str, Any]:
    """Raw generate_lead event count by day. KNOWN OVERFIRE: this event counts
    ~2.3x actual unique leads (includes phone-taps) — never report this number
    as unique leads without dividing down, per paid.md's standing context."""
    return _run_report(
        _property_id(brand),
        {
            "dateRanges": [{"startDate": start_date, "endDate": end_date}],
            "dimensions": [{"name": "date"}],
            "metrics": [{"name": "eventCount"}],
            "dimensionFilter": {
                "filter": {
                    "fieldName": "eventName",
                    "stringFilter": {"value": "generate_lead"},
                }
            },
        },
    )


if __name__ == "__main__":
    mcp.run()
