"""
Google Tag Manager MCP Server for KTU + BTU.

Wraps the Tag Manager API v2 (tagmanager.googleapis.com) for the two web
containers:
  KTU  GTM-KLT6WSH4  accounts/6139458547/containers/137178727
  BTU  GTM-PK4HC6SR  accounts/6293468865/containers/219120991

Staging-only by design: no tagmanager.publish scope, so a human always
publishes from the GTM UI. Scope map (verified 2026-08-23):
  tagmanager.edit.containers          -> edit workspaces (tags/triggers/vars)
  tagmanager.edit.containerversions   -> create_container_version. WITHOUT it
                                         that one tool 403s
                                         (ACCESS_TOKEN_SCOPE_INSUFFICIENT);
                                         workspace edits still stage fine and
                                         a human can Submit+Publish in the UI.
Mint tokens with mcp-servers/tools/get_refresh_token.py --preset tagmanager.

Required env vars:
  GTM_REFRESH_TOKEN  - MUST be minted with the tagmanager scopes above (the
                       google-ads and GA4 tokens 403 here — scopes live on
                       the token).
  GTM_CLIENT_ID      - Google OAuth client id; falls back to
                       GOOGLE_ADS_CLIENT_ID. A refresh token is only
                       redeemable by the client that minted it, and the env
                       can carry a GTM_CLIENT_ID from a different client than
                       the token's (observed 2026-08-23: GTM_CLIENT_ID set but
                       401 unauthorized_client; the GOOGLE_ADS client redeems
                       it) — so on unauthorized_client this server retries
                       with the other pair before failing.
  GTM_CLIENT_SECRET  - paired with GTM_CLIENT_ID; falls back to
                       GOOGLE_ADS_CLIENT_SECRET.
"""

from __future__ import annotations

import os
from typing import Any, Optional

import httpx
from mcp.server.fastmcp import FastMCP
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

mcp = FastMCP("gtm")

API_BASE = "https://tagmanager.googleapis.com/tagmanager/v2"
HTTP_TIMEOUT = 30.0

# brand -> (account_id, container_id, public_id)
CONTAINER_MAP: dict[str, tuple[str, str, str]] = {
    "KTU": ("6139458547", "137178727", "GTM-KLT6WSH4"),
    "BTU": ("6293468865", "219120991", "GTM-PK4HC6SR"),
}


def _container_path(brand: str) -> str:
    b = brand.upper().strip()
    if b not in CONTAINER_MAP:
        raise ValueError(f"Unknown brand '{brand}'. Valid options: KTU, BTU.")
    account_id, container_id, _ = CONTAINER_MAP[b]
    return f"accounts/{account_id}/containers/{container_id}"


_working_client: Optional[tuple[str, str]] = None


def _client_pairs() -> list[tuple[str, str]]:
    pairs = []
    for prefix in ("GTM", "GOOGLE_ADS"):
        cid = os.environ.get(f"{prefix}_CLIENT_ID", "").strip()
        secret = os.environ.get(f"{prefix}_CLIENT_SECRET", "").strip()
        if cid and secret and (cid, secret) not in pairs:
            pairs.append((cid, secret))
    if not pairs:
        raise ValueError("No OAuth client configured: set GTM_CLIENT_ID/SECRET "
                         "or GOOGLE_ADS_CLIENT_ID/SECRET.")
    return pairs


def _oauth_token() -> str:
    global _working_client
    pairs = _client_pairs()
    if _working_client in pairs:
        pairs = [_working_client] + [p for p in pairs if p != _working_client]
    last_exc: Exception | None = None
    for cid, secret in pairs:
        creds = Credentials(
            None,
            refresh_token=os.environ["GTM_REFRESH_TOKEN"],
            client_id=cid,
            client_secret=secret,
            token_uri="https://oauth2.googleapis.com/token",
        )
        try:
            creds.refresh(Request())
        except Exception as exc:
            last_exc = exc
            if "unauthorized_client" in str(exc) or "invalid_client" in str(exc):
                continue
            raise
        _working_client = (cid, secret)
        return creds.token
    raise ValueError(
        "GTM_REFRESH_TOKEN could not be redeemed by any configured OAuth client "
        "(tried GTM_CLIENT_ID and GOOGLE_ADS_CLIENT_ID). The token is only "
        "redeemable by the client that minted it — re-mint with "
        f"tools/get_refresh_token.py --preset tagmanager. Last error: {last_exc}")


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_oauth_token()}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _request(method: str, path: str, body: Optional[dict[str, Any]] = None,
             params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    url = f"{API_BASE}/{path}"
    with httpx.Client(timeout=HTTP_TIMEOUT) as client:
        resp = client.request(method, url, json=body, params=params, headers=_headers())
        resp.raise_for_status()
        return resp.json() if resp.content else {}


def _default_workspace_path(brand: str) -> str:
    workspaces = _request("GET", f"{_container_path(brand)}/workspaces").get("workspace", [])
    if not workspaces:
        raise ValueError(f"No workspaces found in the {brand} container.")
    for ws in workspaces:
        if ws.get("name") == "Default Workspace":
            return ws["path"]
    return workspaces[0]["path"]


@mcp.tool()
def test_connection() -> dict[str, Any]:
    """Verify GTM API access: refresh the OAuth token and fetch both containers.

    Returns each brand's container name, public id, and whether it was reachable.
    """
    out: dict[str, Any] = {}
    for brand, (_, _, public_id) in CONTAINER_MAP.items():
        try:
            c = _request("GET", _container_path(brand))
            out[brand] = {"ok": True, "publicId": c.get("publicId", public_id),
                          "name": c.get("name")}
        except Exception as exc:
            out[brand] = {"ok": False, "error": str(exc)}
    return out


@mcp.tool()
def list_workspaces(brand: str) -> dict[str, Any]:
    """List workspaces in a brand's container (KTU or BTU)."""
    return _request("GET", f"{_container_path(brand)}/workspaces")


@mcp.tool()
def list_tags(brand: str, workspace_path: Optional[str] = None) -> dict[str, Any]:
    """List all tags in a workspace. Defaults to the Default Workspace.

    workspace_path, when given, is the full API path
    (accounts/.../containers/.../workspaces/N) from list_workspaces.
    """
    ws = workspace_path or _default_workspace_path(brand)
    return _request("GET", f"{ws}/tags")


@mcp.tool()
def get_tag(brand: str, tag_id: str, workspace_path: Optional[str] = None) -> dict[str, Any]:
    """Fetch one tag by its tagId, including parameters and firing trigger ids."""
    ws = workspace_path or _default_workspace_path(brand)
    return _request("GET", f"{ws}/tags/{tag_id}")


@mcp.tool()
def list_triggers(brand: str, workspace_path: Optional[str] = None) -> dict[str, Any]:
    """List all triggers in a workspace. Built-in triggers (All Pages =
    2147479553, Consent Init = 2147479573) do not appear here but are valid
    firingTriggerId values."""
    ws = workspace_path or _default_workspace_path(brand)
    return _request("GET", f"{ws}/triggers")


@mcp.tool()
def list_variables(brand: str, workspace_path: Optional[str] = None) -> dict[str, Any]:
    """List all user-defined variables in a workspace."""
    ws = workspace_path or _default_workspace_path(brand)
    return _request("GET", f"{ws}/variables")


@mcp.tool()
def create_hostname_regex_trigger(
    brand: str,
    name: str,
    hostname_regex: str,
    workspace_path: Optional[str] = None,
) -> dict[str, Any]:
    """Create a Page View trigger that fires only when {{Page Hostname}}
    matches hostname_regex (full-match RegEx, e.g.
    ^(www\\.)?(example\\.com|sub\\.example\\.com)$).

    Returns the created trigger; use its triggerId in update_tag_firing_triggers.
    """
    ws = workspace_path or _default_workspace_path(brand)
    body = {
        "name": name,
        "type": "pageview",
        "filter": [
            {
                "type": "matchRegex",
                "parameter": [
                    {"type": "template", "key": "arg0", "value": "{{Page Hostname}}"},
                    {"type": "template", "key": "arg1", "value": hostname_regex},
                ],
            }
        ],
    }
    return _request("POST", f"{ws}/triggers", body=body)


@mcp.tool()
def update_tag_firing_triggers(
    brand: str,
    tag_id: str,
    firing_trigger_ids: list[str],
    workspace_path: Optional[str] = None,
) -> dict[str, Any]:
    """Replace a tag's firing triggers with firing_trigger_ids, leaving every
    other field of the tag untouched (the API's PUT replaces the whole tag, so
    this re-sends the fetched tag with only firingTriggerId changed)."""
    ws = workspace_path or _default_workspace_path(brand)
    tag = _request("GET", f"{ws}/tags/{tag_id}")
    tag["firingTriggerId"] = firing_trigger_ids
    fingerprint = tag.pop("fingerprint", None)
    for k in ("path", "accountId", "containerId", "workspaceId", "tagManagerUrl"):
        tag.pop(k, None)
    params = {"fingerprint": fingerprint} if fingerprint else None
    return _request("PUT", f"{ws}/tags/{tag_id}", body=tag, params=params)


@mcp.tool()
def workspace_status(brand: str, workspace_path: Optional[str] = None) -> dict[str, Any]:
    """Show the pending changes in a workspace (what a container version
    created from it would contain) plus any sync conflicts."""
    ws = workspace_path or _default_workspace_path(brand)
    return _request("GET", f"{ws}/status")


@mcp.tool()
def create_container_version(
    brand: str,
    name: str,
    notes: str = "",
    workspace_path: Optional[str] = None,
) -> dict[str, Any]:
    """Stage the workspace's changes as a new container version. Does NOT
    publish — the token has no tagmanager.publish scope, so a human publishes
    from the GTM UI (Versions tab -> the new version -> Publish).

    Requires the tagmanager.edit.containerversions scope on the token; a
    token with only edit.containers 403s here even though workspace edits
    succeed. Fallback in that case: leave the changes in the workspace and
    have a human click Submit (which creates the version) + Publish in the UI.

    Consumes the workspace: GTM deletes the workspace on versioning and
    recreates a fresh Default Workspace."""
    ws = workspace_path or _default_workspace_path(brand)
    body = {"name": name, "notes": notes}
    return _request("POST", f"{ws}:create_version", body=body)


@mcp.tool()
def list_container_versions(brand: str) -> dict[str, Any]:
    """List the container's version headers, newest last. The live version is
    the one whose versionId equals the container's liveVersionId."""
    return _request("GET", f"{_container_path(brand)}/version_headers")


@mcp.tool()
def get_live_version(brand: str) -> dict[str, Any]:
    """Fetch the currently published (live) container version in full."""
    return _request("GET", f"{_container_path(brand)}/versions:live")


if __name__ == "__main__":
    mcp.run()
