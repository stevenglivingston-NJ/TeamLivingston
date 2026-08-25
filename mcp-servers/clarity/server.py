"""
Microsoft Clarity Live Insights MCP Server for KTU + BTU.

Direct stdio MCP wrapping the Clarity Data-Export live-insights endpoint:
  https://www.clarity.ms/export-data/api/v1/project-live-insights

This is the authoritative direct connection — no Render intermediary, no npm
package. Use for live session / traffic queries when low-latency or full
parameter control is needed. Rate limit: ~10 calls/project/day (shared with
clarity-ktu-export / clarity-btu-export if those are also registered).

Required env vars:
  CLARITY_KTU_TOKEN   — API bearer token for KTU project (2708513173760009)
  CLARITY_BTU_TOKEN   — API bearer token for BTU project (2789761772911940)

Optional env vars (override hardcoded project IDs if set):
  CLARITY_KTU_PROJECT_ID  — KTU Clarity project ID (default: 2708513173760009)
  CLARITY_BTU_PROJECT_ID  — BTU Clarity project ID (default: 2789761772911940)
"""

from __future__ import annotations

import os
from typing import Any, Optional

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("clarity-live")

LIVE_INSIGHTS_URL = "https://www.clarity.ms/export-data/api/v1/project-live-insights"
HTTP_TIMEOUT = 30.0

# Hardcoded project IDs — overridable via env vars
_DEFAULT_PROJECT_IDS = {
    "KTU": "2708513173760009",
    "BTU": "2789761772911940",
}
_TOKEN_ENV = {
    "KTU": "CLARITY_KTU_TOKEN",
    "BTU": "CLARITY_BTU_TOKEN",
}
_PROJECT_ID_ENV = {
    "KTU": "CLARITY_KTU_PROJECT_ID",
    "BTU": "CLARITY_BTU_PROJECT_ID",
}


def _project_id(brand: str) -> str:
    brand = brand.upper().strip()
    if brand not in _DEFAULT_PROJECT_IDS:
        raise ValueError(f"Unknown brand '{brand}'. Use 'KTU' or 'BTU'.")
    return os.environ.get(_PROJECT_ID_ENV[brand], "").strip() or _DEFAULT_PROJECT_IDS[brand]


def _token(brand: str) -> str:
    brand = brand.upper().strip()
    if brand not in _TOKEN_ENV:
        raise ValueError(f"Unknown brand '{brand}'. Use 'KTU' or 'BTU'.")
    env_var = _TOKEN_ENV[brand]
    token = os.environ.get(env_var, "").strip()
    if not token:
        raise ValueError(f"{env_var} env var not set — cannot authenticate to Clarity for {brand}.")
    return token


def _get(project_id: str, token: str, params: dict[str, Any]) -> Any:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    full_params = {"projectId": project_id, **params}
    with httpx.Client(timeout=HTTP_TIMEOUT) as client:
        resp = client.get(LIVE_INSIGHTS_URL, headers=headers, params=full_params)
    resp.raise_for_status()
    return resp.json()


@mcp.tool()
def get_live_insights(
    brand: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    granularity: Optional[str] = None,
    dimensions: Optional[str] = None,
    metrics: Optional[str] = None,
    filters: Optional[str] = None,
    num_of_days: Optional[int] = None,
) -> dict:
    """
    Query the Microsoft Clarity live-insights endpoint for KTU or BTU.

    Hits: GET https://www.clarity.ms/export-data/api/v1/project-live-insights

    Args:
        brand: 'KTU' or 'BTU'
        start_date: ISO date string, e.g. '2026-08-01' (inclusive)
        end_date:   ISO date string, e.g. '2026-08-19' (inclusive)
        granularity: 'Daily', 'Weekly', or 'Monthly'
        dimensions: Comma-separated dimension names, e.g. 'Browser,OS,Device'
        metrics: Comma-separated metric names, e.g. 'TotalSessions,ActiveUsers'
        filters: JSON string of filter objects (see Clarity Data-Export docs)
        num_of_days: Shortcut — pull the last N days instead of start/end dates
    Returns:
        Raw JSON response from the Clarity API.
    """
    brand = brand.upper().strip()
    project_id = _project_id(brand)
    token = _token(brand)

    params: dict[str, Any] = {}
    if start_date:
        params["startDate"] = start_date
    if end_date:
        params["endDate"] = end_date
    if granularity:
        params["granularity"] = granularity
    if dimensions:
        params["dimensions"] = dimensions
    if metrics:
        params["metrics"] = metrics
    if filters:
        params["filters"] = filters
    if num_of_days is not None:
        params["numOfDays"] = num_of_days

    return _get(project_id, token, params)


@mcp.tool()
def get_ktu_live_insights(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    granularity: Optional[str] = None,
    dimensions: Optional[str] = None,
    metrics: Optional[str] = None,
    num_of_days: Optional[int] = None,
) -> dict:
    """
    Shortcut: query Clarity live-insights for the KTU project (2708513173760009).

    Hits: GET https://www.clarity.ms/export-data/api/v1/project-live-insights

    Args:
        start_date: ISO date, e.g. '2026-08-01'
        end_date:   ISO date, e.g. '2026-08-19'
        granularity: 'Daily', 'Weekly', or 'Monthly'
        dimensions: Comma-separated, e.g. 'Browser,OS'
        metrics: Comma-separated metric names
        num_of_days: Pull last N days (alternative to start/end)
    """
    return get_live_insights(
        brand="KTU",
        start_date=start_date,
        end_date=end_date,
        granularity=granularity,
        dimensions=dimensions,
        metrics=metrics,
        num_of_days=num_of_days,
    )


@mcp.tool()
def get_btu_live_insights(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    granularity: Optional[str] = None,
    dimensions: Optional[str] = None,
    metrics: Optional[str] = None,
    num_of_days: Optional[int] = None,
) -> dict:
    """
    Shortcut: query Clarity live-insights for the BTU project (2789761772911940).

    Hits: GET https://www.clarity.ms/export-data/api/v1/project-live-insights

    Args:
        start_date: ISO date, e.g. '2026-08-01'
        end_date:   ISO date, e.g. '2026-08-19'
        granularity: 'Daily', 'Weekly', or 'Monthly'
        dimensions: Comma-separated, e.g. 'Browser,OS'
        metrics: Comma-separated metric names
        num_of_days: Pull last N days (alternative to start/end)
    """
    return get_live_insights(
        brand="BTU",
        start_date=start_date,
        end_date=end_date,
        granularity=granularity,
        dimensions=dimensions,
        metrics=metrics,
        num_of_days=num_of_days,
    )


@mcp.tool()
def test_connection() -> dict:
    """
    Verify CLARITY_KTU_TOKEN and CLARITY_BTU_TOKEN are set and accepted by the
    Clarity live-insights endpoint. Makes one lightweight call per project.
    Returns token presence status and API reachability for each brand.
    """
    results: dict[str, Any] = {}
    for brand in ("KTU", "BTU"):
        env_var = _TOKEN_ENV[brand]
        token = os.environ.get(env_var, "").strip()
        if not token:
            results[brand] = {"status": "missing_token", "env_var": env_var}
            continue
        project_id = _project_id(brand)
        try:
            _get(project_id, token, {"numOfDays": 1})
            results[brand] = {
                "status": "ok",
                "project_id": project_id,
                "env_var": env_var,
                "endpoint": LIVE_INSIGHTS_URL,
            }
        except httpx.HTTPStatusError as exc:
            results[brand] = {
                "status": "api_error",
                "http_status": exc.response.status_code,
                "detail": exc.response.text[:300],
            }
        except Exception as exc:
            results[brand] = {"status": "error", "detail": str(exc)[:300]}
    return results


if __name__ == "__main__":
    mcp.run(transport="stdio")
