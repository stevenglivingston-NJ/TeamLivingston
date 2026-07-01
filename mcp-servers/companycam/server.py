"""
CompanyCam MCP Server
=====================
Wraps the CompanyCam REST API v2 as MCP tools.

Auth: Bearer token via env var COMPANYCAM_TOKEN (set in ~/.claude/settings.json).

API docs: https://docs.companycam.com/reference (v2 base: https://api.companycam.com/v2)

Endpoints exposed as tools:
  - test_connection         → GET /v2/users/current (verify token + identity)
  - list_projects           → GET /v2/projects (paginated)
  - get_project             → GET /v2/projects/:id
  - search_projects         → GET /v2/projects?query= (server-side search)
  - find_project_by_address → smart match by street/city/zip across paginated list
  - get_project_photos      → GET /v2/projects/:id/photos
  - get_project_notes       → GET /v2/projects/:id/notes
  - get_project_labels      → GET /v2/projects/:id/labels
  - list_recent_photos      → GET /v2/photos (org-wide)
  - list_users              → GET /v2/users
  - list_groups             → GET /v2/groups
  - get_project_documents   → GET /v2/projects/:id/documents
"""

from __future__ import annotations

import os
import sys
import re
from typing import Any, Optional

import httpx
from mcp.server.fastmcp import FastMCP

API_BASE = "https://api.companycam.com/v2"
HTTP_TIMEOUT = 60.0


def _get_token() -> str:
    """Get bearer token from env. Raise if not set."""
    token = os.environ.get("COMPANYCAM_TOKEN", "").strip()
    if not token:
        raise ValueError(
            "COMPANYCAM_TOKEN env var not set. Add it to ~/.claude/settings.json under "
            "mcpServers.companycam.env, then restart Claude Code."
        )
    return token


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_get_token()}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _get(path: str, params: Optional[dict] = None) -> Any:
    """GET a CompanyCam endpoint and return JSON."""
    url = f"{API_BASE}{path if path.startswith('/') else '/' + path}"
    with httpx.Client(timeout=HTTP_TIMEOUT) as client:
        resp = client.get(url, headers=_headers(), params=params)
        if resp.status_code == 401:
            raise ValueError(
                "401 Unauthorized — token rejected. Verify COMPANYCAM_TOKEN is current and "
                "has the right scopes (Projects, Photos, Users)."
            )
        resp.raise_for_status()
        try:
            return resp.json()
        except Exception:
            return {"raw": resp.text, "status_code": resp.status_code}


def _post(path: str, body: dict) -> Any:
    url = f"{API_BASE}{path if path.startswith('/') else '/' + path}"
    with httpx.Client(timeout=HTTP_TIMEOUT) as client:
        resp = client.post(url, headers=_headers(), json=body)
        resp.raise_for_status()
        return resp.json() if resp.content else {"status": "ok"}


def _normalize_addr(s: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace, expand common abbreviations."""
    if not s:
        return ""
    s = s.lower().strip()
    s = re.sub(r"[,.]", " ", s)
    s = re.sub(r"\s+", " ", s)
    # Common abbreviations
    repl = {
        " road": " rd",
        " street": " st",
        " avenue": " ave",
        " drive": " dr",
        " place": " pl",
        " terrace": " ter",
        " court": " ct",
        " boulevard": " blvd",
        " lane": " ln",
        " circle": " cir",
        " parkway": " pkwy",
        " highway": " hwy",
    }
    for k, v in repl.items():
        s = s.replace(k, v)
    return s.strip()


# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------

mcp = FastMCP("companycam")


@mcp.tool()
def test_connection() -> dict:
    """Verify the API token is valid and return the current user identity + company info.

    Use this first to confirm the connection is wired correctly.
    """
    try:
        user = _get("/users/current")
        # CompanyCam sometimes returns the user object directly; sometimes wrapped
        u = user.get("user") if isinstance(user, dict) and "user" in user else user
        return {
            "status": "ok",
            "user_id": u.get("id"),
            "user_email": u.get("email_address") or u.get("email"),
            "user_name": f"{u.get('first_name', '')} {u.get('last_name', '')}".strip(),
            "company_id": u.get("company_id"),
            "company_name": u.get("company_name"),
            "raw": user,
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


@mcp.tool()
def list_projects(
    page: int = 1,
    per_page: int = 50,
    query: Optional[str] = None,
    modified_since: Optional[str] = None,
    status: Optional[str] = None,
) -> dict:
    """List projects with pagination + optional filters.

    Args:
        page: page number (1-indexed)
        per_page: results per page (max 100)
        query: free-text search (matches name/address)
        modified_since: ISO datetime, e.g. "2026-04-01T00:00:00Z"
        status: project status filter (e.g. "active", "archived")
    """
    params: dict = {"page": page, "per_page": min(per_page, 100)}
    if query:
        params["query"] = query
    if modified_since:
        params["modified_since"] = modified_since
    if status:
        params["status"] = status
    return {"projects": _get("/projects", params=params), "page": page, "per_page": per_page}


@mcp.tool()
def get_project(project_id: str) -> dict:
    """Fetch a single project by ID — returns name, address, photos[], notes[], labels[], etc."""
    return _get(f"/projects/{project_id}")


@mcp.tool()
def search_projects(query: str, page: int = 1, per_page: int = 50) -> dict:
    """Server-side search projects by name or address fragment.

    Args:
        query: search string (matches across project name + address fields)
        page: page (default 1)
        per_page: results per page (default 50, max 100)
    """
    params = {"query": query, "page": page, "per_page": min(per_page, 100)}
    return {"results": _get("/projects", params=params), "query": query}


@mcp.tool()
def find_project_by_address(
    street: Optional[str] = None,
    city: Optional[str] = None,
    postal_code: Optional[str] = None,
    name_fallback: Optional[str] = None,
    max_pages: int = 5,
) -> dict:
    """Smart address-match across paginated project list.

    Walks pages of /projects looking for a record whose address matches the supplied
    street/city/zip — using normalized comparison (lowercased, abbreviation-expanded).
    Falls back to fuzzy match by name_fallback if no address match.

    Args:
        street: street address (e.g. "100 Buckingham Road")
        city: city name (e.g. "Montclair")
        postal_code: ZIP (e.g. "07043")
        name_fallback: customer name to try if address strikes out
        max_pages: how many pages to scan (default 5 = 250 projects)
    """
    target_street = _normalize_addr(street or "")
    target_city = _normalize_addr(city or "")
    target_zip = (postal_code or "").strip()
    target_name = (name_fallback or "").strip().lower()

    matches: list[dict] = []
    scanned = 0
    for page in range(1, max_pages + 1):
        data = _get("/projects", params={"page": page, "per_page": 100})
        projects = data if isinstance(data, list) else data.get("projects", []) or []
        if not projects:
            break
        for p in projects:
            scanned += 1
            addr = p.get("address", {}) or {}
            p_street = _normalize_addr(addr.get("street_address_1", "") or "")
            p_city = _normalize_addr(addr.get("city", "") or "")
            p_zip = (addr.get("postal_code", "") or "").strip()
            p_name = (p.get("name", "") or "").lower()

            score = 0
            reasons = []
            if target_zip and p_zip == target_zip:
                score += 3
                reasons.append("zip_match")
            if target_city and p_city == target_city:
                score += 2
                reasons.append("city_match")
            if target_street and (target_street in p_street or p_street in target_street):
                score += 4
                reasons.append("street_match")
            if target_name and (target_name in p_name or any(part in p_name for part in target_name.split() if len(part) > 3)):
                score += 2
                reasons.append("name_fuzzy_match")

            if score >= 4:  # need at least street_match OR (zip+city)
                matches.append({
                    "project_id": p.get("id"),
                    "name": p.get("name"),
                    "address": addr,
                    "photo_count": p.get("photo_count"),
                    "score": score,
                    "match_reasons": reasons,
                    "created_at": p.get("created_at"),
                    "updated_at": p.get("updated_at"),
                    "status": p.get("status"),
                    "public_url": p.get("public_url"),
                })
        if len(projects) < 100:
            break  # last page

    matches.sort(key=lambda m: -m["score"])
    return {
        "matches": matches,
        "best_match": matches[0] if matches else None,
        "scanned_projects": scanned,
        "pages_scanned": page,
        "criteria": {"street": street, "city": city, "postal_code": postal_code, "name_fallback": name_fallback},
    }


@mcp.tool()
def get_project_photos(project_id: str, page: int = 1, per_page: int = 50) -> dict:
    """Fetch photos for a specific project.

    Returns photo URIs (multiple sizes), captured_at, creator, tags.
    """
    params = {"page": page, "per_page": min(per_page, 100)}
    return _get(f"/projects/{project_id}/photos", params=params)


@mcp.tool()
def get_project_notes(project_id: str) -> dict:
    """Fetch notes (project notepad) for a project."""
    return _get(f"/projects/{project_id}/notes")


@mcp.tool()
def get_project_labels(project_id: str) -> dict:
    """Fetch labels/tags applied to a project."""
    return _get(f"/projects/{project_id}/labels")


@mcp.tool()
def get_project_documents(project_id: str) -> dict:
    """Fetch documents attached to a project."""
    return _get(f"/projects/{project_id}/documents")


@mcp.tool()
def list_recent_photos(page: int = 1, per_page: int = 50, modified_since: Optional[str] = None) -> dict:
    """Org-wide photo feed across all projects (most-recent first).

    Useful for: "what photos went up today?", anomaly detection, fleet activity proof.
    """
    params: dict = {"page": page, "per_page": min(per_page, 100)}
    if modified_since:
        params["modified_since"] = modified_since
    return _get("/photos", params=params)


@mcp.tool()
def list_users(page: int = 1, per_page: int = 100) -> dict:
    """List all users (team members) in the CompanyCam company."""
    return _get("/users", params={"page": page, "per_page": per_page})


@mcp.tool()
def list_groups() -> dict:
    """List groups/crews in the CompanyCam company."""
    return _get("/groups")


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    mcp.run()
