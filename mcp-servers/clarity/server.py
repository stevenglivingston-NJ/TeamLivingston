"""
Microsoft Clarity Data-Export MCP Server for KTU + BTU.

Direct replacement for @microsoft/clarity-mcp-server (npm), which has a
confirmed bug: given two distinct, correctly-scoped CLARITY_API_TOKEN values
in two separate processes, it returns identical (wrong-project) data for
both. Verified 2026-07-19 by calling the raw Data-Export API directly with
each token and getting genuinely different, correctly-scoped results. This
server wraps that same raw API with no intermediate package.

Required env vars:
  CLARITY_KTU_TOKEN  - Data-Export API token from the KTU Clarity project
                       (Settings -> Data Export)
  CLARITY_BTU_TOKEN  - Data-Export API token from the BTU Clarity project

Rate limit: the Data-Export API allows ~10 calls/project/day. Callers should
budget accordingly (1-2 focused queries per brand per run).
"""

from __future__ import annotations

import os
from typing import Any, Optional

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("clarity")

API_BASE = "https://www.clarity.ms/export-data/api/v1/project-live-insights"
HTTP_TIMEOUT = 30.0

TOKEN_MAP: dict[str, str] = {
    "KTU": "CLARITY_KTU_TOKEN",
    "BTU": "CLARITY_BTU_TOKEN",
}

VALID_DIMENSIONS = {
    "Browser", "Device", "Country", "OS", "Source", "Medium",
    "Campaign", "Channel", "URL",
}


def _token(location: str) -> str:
    loc = location.upper().strip()
    env_var = TOKEN_MAP.get(loc)
    if not env_var:
        valid = ", ".join(sorted(TOKEN_MAP.keys()))
        raise ValueError(f"Unknown location '{location}'. Valid: {valid}")
    tok = os.environ.get(env_var, "").strip()
    if not tok:
        raise ValueError(f"{env_var} env var not set.")
    return tok


@mcp.tool()
def list_locations() -> dict[str, Any]:
    """List configured Clarity locations (KTU, BTU) and whether each token is set."""
    status = {}
    ok = True
    for loc, env_var in TOKEN_MAP.items():
        configured = bool(os.environ.get(env_var))
        status[loc] = {"env_var": env_var, "configured": configured}
        if not configured:
            ok = False
    return {"locations": status, "all_configured": ok}


@mcp.tool()
def test_connection(location: str) -> dict[str, Any]:
    """Verify the token for a location resolves to a live Clarity project (1-day, URL dimension)."""
    try:
        data = query_insights(location, num_of_days=1, dimension1="URL")
        return {"status": "ok", "location": location, "metric_count": len(data)}
    except Exception as e:
        return {"status": "error", "location": location, "error": str(e)}


@mcp.tool()
def query_insights(
    location: str,
    num_of_days: int = 3,
    dimension1: str = "URL",
    dimension2: Optional[str] = None,
    dimension3: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Fetch Clarity landing-page / session-experience metrics for a brand.

    location: 'KTU' or 'BTU'.
    num_of_days: 1, 2, or 3 (API limit).
    dimension1/2/3: optional breakdown dimensions, one of:
      Browser, Device, Country, OS, Source, Medium, Campaign, Channel, URL.

    Returns a list of {metricName, information} covering DeadClickCount,
    RageClickCount, QuickbackClick, ScriptErrorCount, ErrorClickCount,
    ExcessiveScroll, ScrollDepth, Traffic, EngagementTime — the landing-page
    experience signals (dead/rage clicks, JS errors, quick-backs, traffic).
    """
    if num_of_days not in (1, 2, 3):
        raise ValueError("num_of_days must be 1, 2, or 3 (Clarity Data-Export API limit).")
    for dim in (dimension1, dimension2, dimension3):
        if dim is not None and dim not in VALID_DIMENSIONS:
            raise ValueError(f"Invalid dimension '{dim}'. Valid: {', '.join(sorted(VALID_DIMENSIONS))}")

    token = _token(location)
    params: dict[str, Any] = {"numOfDays": num_of_days, "dimension1": dimension1}
    if dimension2:
        params["dimension2"] = dimension2
    if dimension3:
        params["dimension3"] = dimension3

    with httpx.Client(timeout=HTTP_TIMEOUT) as client:
        resp = client.get(
            API_BASE,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            params=params,
        )
        resp.raise_for_status()
        return resp.json()


if __name__ == "__main__":
    mcp.run()
