"""
Closebot MCP Server
====================
Wraps the Closebot REST API (https://api.closebot.com) as MCP tools.

Auth: API key in `X-CB-KEY` header. Set via env COMPANYCAM_TOKEN
       (yes that's a typo from the user — actually CLOSEBOT_API_KEY) in ~/.claude/settings.json.

Closebot is the AI receptionist running on KTU + BTU sites
(`api.closebot.com/scripts/cb.js`).

Tools mirror the most useful endpoints from the swagger spec:
- test_connection      → GET /bot (verify API key + list bots)
- list_bots            → GET /bot
- get_bot              → GET /bot/{id}
- get_agency_summary   → GET /botMetric/agencySummary (overall KPIs)
- get_messages         → GET /botMetric/messages (conversation history)
- get_message_count    → GET /botMetric/messageCount
- get_actions          → GET /botMetric/actions (bot took an action — e.g. booked)
- get_agency_metric    → GET /botMetric/agencyMetric (responses/bookings/contacts trend)
- get_booking_graph    → GET /botMetric/bookingGraph
- get_leaderboard      → GET /botMetric/leaderboard
- get_message_feedback → GET /botMetric/messageFeedback (quality signals)
- get_lead             → GET /lead/{leadId}
- get_account_balance  → GET /agency/billing/balance
"""

from __future__ import annotations

import os
from typing import Any, Optional

import httpx
from mcp.server.fastmcp import FastMCP

API_BASE = "https://api.closebot.com"
HTTP_TIMEOUT = 60.0


def _get_token() -> str:
    token = os.environ.get("CLOSEBOT_API_KEY", "").strip()
    if not token:
        raise ValueError(
            "CLOSEBOT_API_KEY env var not set. Add it to ~/.claude/settings.json under "
            "mcpServers.closebot.env, then restart Claude Code."
        )
    return token


def _headers() -> dict[str, str]:
    return {
        "X-CB-KEY": _get_token(),
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _get(path: str, params: Optional[dict] = None) -> Any:
    url = f"{API_BASE}{path if path.startswith('/') else '/' + path}"
    with httpx.Client(timeout=HTTP_TIMEOUT) as client:
        resp = client.get(url, headers=_headers(), params=params)
        if resp.status_code == 401:
            raise ValueError(
                "401 Unauthorized — Closebot API key rejected. Verify CLOSEBOT_API_KEY is current."
            )
        if resp.status_code == 410:
            return {"_error": "410 No Account — verify the bot/source/agency exists"}
        if resp.status_code == 420:
            return {"_error": "420 No Credits — Closebot wallet balance is depleted"}
        resp.raise_for_status()
        try:
            return resp.json()
        except Exception:
            return {"raw": resp.text, "status_code": resp.status_code}


# ---------------------------------------------------------------------------
mcp = FastMCP("closebot")


@mcp.tool()
def test_connection() -> dict:
    """Verify API key works. Returns count of bots in the account."""
    try:
        bots = _get("/bot")
        if isinstance(bots, list):
            return {"status": "ok", "bot_count": len(bots), "bots": [{"id": b.get("id"), "name": b.get("name")} for b in bots[:10]]}
        return {"status": "ok", "raw": bots}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@mcp.tool()
def list_bots() -> dict:
    """List all bots configured in the Closebot account.

    For KTU + BTU we expect at least 2 bots (one per site)."""
    return {"bots": _get("/bot")}


@mcp.tool()
def get_bot(bot_id: str) -> dict:
    """Fetch details for a single bot."""
    return _get(f"/bot/{bot_id}")


@mcp.tool()
def get_agency_summary(source_id: Optional[str] = None) -> dict:
    """Overall KPIs for the agency — total bots, messages, bookings, contacts.

    Args:
        source_id: optional filter by source (e.g. KTU vs BTU site)
    """
    params = {}
    if source_id:
        params["sourceId"] = source_id
    return _get("/botMetric/agencySummary", params=params)


@mcp.tool()
def get_messages(
    source_id: Optional[str] = None,
    lead_id: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    max_count: int = 100,
) -> dict:
    """Fetch message history — full conversation transcripts.

    Args:
        source_id: filter by site (KTU vs BTU)
        lead_id: filter to single conversation
        start: ISO datetime
        end: ISO datetime
        max_count: cap (default 100)
    """
    params = {"maxCount": max_count}
    if source_id: params["sourceId"] = source_id
    if lead_id: params["leadId"] = lead_id
    if start: params["start"] = start
    if end: params["end"] = end
    return {"messages": _get("/botMetric/messages", params=params)}


@mcp.tool()
def get_message_count(
    source_id: Optional[str] = None,
    lead_id: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> dict:
    """Get total messages in a date range. Useful for daily volume tracking."""
    params = {}
    if source_id: params["sourceId"] = source_id
    if lead_id: params["leadId"] = lead_id
    if start: params["start"] = start
    if end: params["end"] = end
    return {"count": _get("/botMetric/messageCount", params=params)}


@mcp.tool()
def get_actions(
    source_id: Optional[str] = None,
    bot_id: Optional[str] = None,
    lead_id: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    max_count: int = 100,
) -> dict:
    """Get bot actions — when the bot did something (booked, escalated, captured contact, etc.).

    Critical for measuring conversion rate (messages → bookings).
    """
    params = {"maxCount": max_count}
    if source_id: params["sourceId"] = source_id
    if bot_id: params["botId"] = bot_id
    if lead_id: params["leadId"] = lead_id
    if start: params["start"] = start
    if end: params["end"] = end
    return {"actions": _get("/botMetric/actions", params=params)}


@mcp.tool()
def get_agency_metric(
    metric: str,
    start: Optional[str] = None,
    end: Optional[str] = None,
    resolution: str = "daily",
    source_id: Optional[str] = None,
) -> dict:
    """Time-series KPI data.

    Args:
        metric: "responses" | "bookings" | "activeSources" | "contacts" | "totalStorage" | "revenue"
        resolution: "hourly" | "daily" | "monthly"
    """
    params = {"metric": metric, "resolution": resolution}
    if start: params["start"] = start
    if end: params["end"] = end
    if source_id: params["sourceId"] = source_id
    return _get("/botMetric/agencyMetric", params=params)


@mcp.tool()
def get_booking_graph(
    start: Optional[str] = None,
    end: Optional[str] = None,
    resolution: str = "daily",
    source_id: Optional[str] = None,
) -> dict:
    """Booking conversion graph over time."""
    params = {"resolution": resolution}
    if start: params["start"] = start
    if end: params["end"] = end
    if source_id: params["sourceId"] = source_id
    return _get("/botMetric/bookingGraph", params=params)


@mcp.tool()
def get_leaderboard(
    metric: str = "bookings",
    start: Optional[str] = None,
    end: Optional[str] = None,
    num_top_leaders: int = 10,
) -> dict:
    """Top performing bots/sources by metric.

    Args:
        metric: "responses" | "bookings" | "contacts"
    """
    params = {"metric": metric, "numTopLeaders": num_top_leaders}
    if start: params["start"] = start
    if end: params["end"] = end
    return {"leaderboard": _get("/botMetric/leaderboard", params=params)}


@mcp.tool()
def get_message_feedback(lead_id: str) -> dict:
    """Quality signals — thumbs up/down feedback from users for a specific lead's messages."""
    return _get("/botMetric/messageFeedback", params={"leadId": lead_id})


@mcp.tool()
def get_lead(lead_id: str) -> dict:
    """Get full lead record (Closebot's view of a contact)."""
    return _get(f"/lead/{lead_id}")


@mcp.tool()
def get_account_balance() -> dict:
    """Current wallet balance (for credit-based usage)."""
    return _get("/agency/billing/balance")


@mcp.tool()
def get_billing_usage(start: Optional[str] = None, end: Optional[str] = None) -> dict:
    """Billed usage in date range — track Closebot cost trend."""
    params = {}
    if start: params["startTime"] = start
    if end: params["endTime"] = end
    return {"usages": _get("/agency/billing/usages", params=params)}


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    mcp.run()
