"""
Cloudflare MCP Server
=====================
Wraps the Cloudflare REST API v4 as MCP tools.

Covers zones, DNS records, Pages projects/deployments, R2 buckets, and Workers.
Complements the built-in Cloudflare Developer Platform connector which lacks
DNS / Zones / Pages tools.

Required env vars:
  CLOUDFLARE_API_TOKEN - API token with appropriate permissions
  CLOUDFLARE_ACCOUNT_ID - Account ID (used for account-scoped resources)
"""

from __future__ import annotations

import os
from typing import Any, Optional

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("cloudflare")

API_BASE = "https://api.cloudflare.com/client/v4"
HTTP_TIMEOUT = 30.0


def _headers() -> dict[str, str]:
    token = os.environ.get("CLOUDFLARE_API_TOKEN", "").strip()
    if not token:
        raise ValueError("CLOUDFLARE_API_TOKEN must be set in env.")
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def _account_id() -> str:
    aid = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "").strip()
    if not aid:
        raise ValueError("CLOUDFLARE_ACCOUNT_ID must be set in env.")
    return aid


def _get(path: str, params: Optional[dict] = None) -> Any:
    url = f"{API_BASE}{path}"
    with httpx.Client(timeout=HTTP_TIMEOUT) as client:
        resp = client.get(url, headers=_headers(), params=params)
        resp.raise_for_status()
        return resp.json()


def _post(path: str, json_body: Optional[dict] = None) -> Any:
    url = f"{API_BASE}{path}"
    with httpx.Client(timeout=HTTP_TIMEOUT) as client:
        resp = client.post(url, headers=_headers(), json=json_body or {})
        resp.raise_for_status()
        return resp.json()


# ---------- Connection ----------

@mcp.tool()
def test_connection() -> dict[str, Any]:
    """Verify Cloudflare API token by fetching the token's identity."""
    try:
        data = _get("/user/tokens/verify")
        return {
            "status": "ok",
            "token_status": data.get("result", {}).get("status"),
            "account_id_set": bool(os.environ.get("CLOUDFLARE_ACCOUNT_ID")),
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ---------- Zones (Websites) ----------

@mcp.tool()
def list_zones(name: Optional[str] = None, per_page: int = 50) -> dict[str, Any]:
    """List Cloudflare zones (websites/domains).

    name: filter to a specific zone name (e.g. 'jataliamarketplace.com')
    """
    params: dict[str, Any] = {"per_page": per_page}
    if name:
        params["name"] = name
    return _get("/zones", params)


@mcp.tool()
def get_zone(zone_id: str) -> dict[str, Any]:
    """Get full details for a zone by ID."""
    return _get(f"/zones/{zone_id}")


@mcp.tool()
def list_dns_records(
    zone_id: str,
    record_type: Optional[str] = None,
    name: Optional[str] = None,
    per_page: int = 100,
) -> dict[str, Any]:
    """List DNS records for a zone.

    record_type: filter by type (A, AAAA, CNAME, TXT, MX, NS, etc.)
    name: filter by record name
    """
    params: dict[str, Any] = {"per_page": per_page}
    if record_type:
        params["type"] = record_type
    if name:
        params["name"] = name
    return _get(f"/zones/{zone_id}/dns_records", params)


# ---------- Pages ----------

@mcp.tool()
def list_pages_projects() -> dict[str, Any]:
    """List all Cloudflare Pages projects in the account."""
    aid = _account_id()
    return _get(f"/accounts/{aid}/pages/projects")


@mcp.tool()
def get_pages_project(project_name: str) -> dict[str, Any]:
    """Get details for a specific Pages project."""
    aid = _account_id()
    return _get(f"/accounts/{aid}/pages/projects/{project_name}")


@mcp.tool()
def list_pages_deployments(project_name: str, per_page: int = 25) -> dict[str, Any]:
    """List deployments for a Pages project."""
    aid = _account_id()
    return _get(
        f"/accounts/{aid}/pages/projects/{project_name}/deployments",
        {"per_page": per_page},
    )


# ---------- Workers ----------

@mcp.tool()
def list_workers() -> dict[str, Any]:
    """List all Workers scripts in the account."""
    aid = _account_id()
    return _get(f"/accounts/{aid}/workers/scripts")


@mcp.tool()
def get_worker(script_name: str) -> dict[str, Any]:
    """Get metadata for a specific Worker script."""
    aid = _account_id()
    return _get(f"/accounts/{aid}/workers/services/{script_name}")


@mcp.tool()
def list_worker_routes(zone_id: str) -> dict[str, Any]:
    """List Worker routes attached to a zone."""
    return _get(f"/zones/{zone_id}/workers/routes")


# ---------- R2 ----------

@mcp.tool()
def list_r2_buckets() -> dict[str, Any]:
    """List all R2 buckets in the account."""
    aid = _account_id()
    return _get(f"/accounts/{aid}/r2/buckets")


@mcp.tool()
def get_r2_bucket(bucket_name: str) -> dict[str, Any]:
    """Get details for a specific R2 bucket."""
    aid = _account_id()
    return _get(f"/accounts/{aid}/r2/buckets/{bucket_name}")


# ---------- KV ----------

@mcp.tool()
def list_kv_namespaces() -> dict[str, Any]:
    """List all Workers KV namespaces in the account."""
    aid = _account_id()
    return _get(f"/accounts/{aid}/storage/kv/namespaces")


# ---------- Analytics ----------

@mcp.tool()
def get_zone_analytics(zone_id: str, since: str = "-10080") -> dict[str, Any]:
    """Get analytics for a zone.

    since: minutes ago (default '-10080' = 7 days) or ISO timestamp
    """
    return _get(
        f"/zones/{zone_id}/analytics/dashboard",
        {"since": since},
    )


if __name__ == "__main__":
    mcp.run()
