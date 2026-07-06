"""
ServiceMinder MCP Server
========================
Wraps the ServiceMinder Open API + Org-Level Download API as MCP tools.

Supports multiple locations via named API keys loaded from environment variables:
  SM_KEY_KTU=<key for KTU location>
  SM_KEY_BTU=<key for BTU location>

Every tool takes a `location` argument (e.g. "KTU" or "BTU") that selects which key to use.

Docs:
  - Open API:           https://serviceminder.io/api
  - Org Download API:   https://serviceminder.knowledgeowl.com/help/org-level-download-api
  - Payload examples:   https://serviceminder.knowledgeowl.com/help/api-payload-examples
"""

from __future__ import annotations

import os
import sys
import time
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Config: API keys per location, loaded from env
# ---------------------------------------------------------------------------

API_BASE = "https://serviceminder.io/api"
HTTP_TIMEOUT = 60.0  # seconds

# Map of location alias -> env var name. Add more here if you onboard new locations.
LOCATION_ENV_VARS: dict[str, str] = {
    "KTU": "SM_KEY_KTU",
    "BTU": "SM_KEY_BTU",
}

# The Org-Level Download API requires a UserId (the export runs "as" a user).
# Default it per location from env so headless/agent runs don't have to look one
# up; callers can still override by passing user_id to start_download().
LOCATION_USERID_ENV_VARS: dict[str, str] = {
    "KTU": "SM_USERID_KTU",
    "BTU": "SM_USERID_BTU",
}


def _get_userid(location: str) -> int | None:
    """Resolve a location's default download UserId from env, or None if unset."""
    env_var = LOCATION_USERID_ENV_VARS.get(location.upper().strip())
    val = os.environ.get(env_var) if env_var else None
    try:
        return int(val) if val else None
    except (TypeError, ValueError):
        return None


def _get_key(location: str) -> str:
    """Resolve a location alias to its API key. Raises ValueError if missing."""
    loc = location.upper().strip()
    env_var = LOCATION_ENV_VARS.get(loc)
    if not env_var:
        valid = ", ".join(sorted(LOCATION_ENV_VARS.keys()))
        raise ValueError(f"Unknown location '{location}'. Valid options: {valid}")
    key = os.environ.get(env_var)
    if not key:
        raise ValueError(
            f"API key for {loc} is not set. Define {env_var} in your environment "
            f"or .env file."
        )
    return key


def _post(endpoint: str, location: str, payload: dict[str, Any]) -> dict[str, Any]:
    """POST a payload to a ServiceMinder endpoint and return the JSON response."""
    api_key = _get_key(location)
    body = dict(payload)
    body["ApiKey"] = api_key
    url = f"{API_BASE}/{endpoint.lstrip('/')}"
    with httpx.Client(timeout=HTTP_TIMEOUT) as client:
        resp = client.post(url, json=body, headers={"Content-Type": "application/json"})
        resp.raise_for_status()
        try:
            return resp.json()
        except Exception:
            return {"raw": resp.text, "status_code": resp.status_code}


# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------

mcp = FastMCP("serviceminder")


# ---------- Connectivity ----------

@mcp.tool()
def list_locations() -> dict[str, Any]:
    """List configured ServiceMinder locations and whether each has an API key set.

    Use this first if you're unsure which `location` value to pass to other tools.
    """
    out = {}
    for loc, env_var in LOCATION_ENV_VARS.items():
        out[loc] = {
            "env_var": env_var,
            "configured": bool(os.environ.get(env_var)),
        }
    return out


@mcp.tool()
def test_connection(location: str) -> dict[str, Any]:
    """Verify the API key for a location works by hitting the /test/echo endpoint."""
    return _post("test/echo", location, {})


# ---------- Contacts ----------

@mcp.tool()
def find_contact(
    location: str,
    name_search: str = "",
    phone_search: str = "",
    email_search: str = "",
    address_search: str = "",
    id_search: int | None = None,
    skip: int = 0,
    limit: int = 25,
) -> dict[str, Any]:
    """Search for contacts by name, phone, email, address, or ID.

    Pass at least one of the search fields. Returns matching contacts.
    """
    payload: dict[str, Any] = {
        "NameSearch": name_search,
        "PhoneSearch": phone_search,
        "EmailSearch": email_search,
        "AddressSearch": address_search,
        "Skip": skip,
        "Limit": limit,
        "Matches": [],
    }
    if id_search is not None:
        payload["IdSearch"] = id_search
    return _post("contacts/locate", location, payload)


@mcp.tool()
def add_or_update_contact(
    location: str,
    name: str,
    phone: str = "",
    email: str = "",
    address1: str = "",
    city: str = "",
    state: str = "",
    zip_code: str = "",
    company: str = "",
    channel: str = "",
    campaign: str = "",
    tags: list[str] | None = None,
    custom_fields: list[dict[str, Any]] | None = None,
    distribute_lead: bool = False,
) -> dict[str, Any]:
    """Add a new contact or update an existing one (matched on name+phone+email).

    Set distribute_lead=True for lead-capture flows where ServiceMinder should
    route the lead to the right organization based on zip code.

    custom_fields format: [{"Name": "Lot Size", "Value": "275"}, ...]
    """
    contact: dict[str, Any] = {
        "Name": name,
        "Phone": phone,
        "Email": email,
        "Address1": address1,
        "City": city,
        "State": state,
        "Zip": zip_code,
        "Company": company,
        "Channel": channel,
        "Campaign": campaign,
        "Tags": tags or [],
        "CustomFields": custom_fields or [],
    }
    payload = {
        "Matches": [contact],
        "DistributeLead": distribute_lead,
    }
    return _post("contacts/addupdate", location, payload)


@mcp.tool()
def add_contact_note(location: str, contact_id: int, title: str, body: str) -> dict[str, Any]:
    """Attach a note to a contact."""
    return _post(
        "contacts/addnote",
        location,
        {"ContactId": contact_id, "Note": {"Title": title, "Body": body}},
    )


@mcp.tool()
def add_contact_tags(location: str, contact_id: int, tag_names: list[str]) -> dict[str, Any]:
    """Add tags to a contact. Tags are passed by name."""
    return _post(
        "contacts/addtags",
        location,
        {"ContactId": contact_id, "TagList": [{"Name": t} for t in tag_names]},
    )


# ---------- Appointments ----------

@mcp.tool()
def query_appointments(
    location: str,
    from_date: str | None = None,
    through_date: str | None = None,
    contact_id: int | None = None,
    service_agent_id: int | None = None,
    include_contact: bool = False,
    skip: int = 0,
    take: int = 100,
) -> dict[str, Any]:
    """Search appointments by date range, contact, or service agent.

    Dates use ISO format: "2026-01-15" or "2026-01-15T00:00:00".
    """
    payload: dict[str, Any] = {
        "Skip": skip,
        "Take": take,
        "IncludeContact": include_contact,
        "Appointments": [],
    }
    if from_date:
        payload["FromDate"] = from_date
    if through_date:
        payload["ThroughDate"] = through_date
    if contact_id is not None:
        payload["ContactId"] = contact_id
    if service_agent_id is not None:
        payload["ServiceAgentId"] = service_agent_id
    return _post("appointments/query", location, payload)


@mcp.tool()
def quickbook_appointment(
    location: str,
    name: str,
    phone: str,
    email: str,
    address1: str,
    city: str,
    state: str,
    zip_code: str,
    service: str,
    scheduled_start: str,
    duration_minutes: int,
    quantity: float = 1.0,
    notes: str = "",
    confirmed: bool = True,
) -> dict[str, Any]:
    """Create a contact and book an appointment in one call.

    scheduled_start: ISO datetime, e.g. "2026-05-01T10:00:00".
    """
    payload = {
        "Name": name,
        "PriPhone": phone,
        "Email": email,
        "Address1": address1,
        "City": city,
        "State": state,
        "Zip": zip_code,
        "Service": service,
        "ScheduledStart": scheduled_start,
        "Duration": duration_minutes,
        "Quantity": quantity,
        "InternalNotes": notes,
        "Confirmed": confirmed,
    }
    return _post("appointments/quickbook", location, payload)


@mcp.tool()
def slot_search(
    location: str,
    service_id: int,
    contact_id: int,
    target_date: str,
    duration: str = "60",
    quantity: float = 1.0,
    timeframe: str = "Anytime",
    slot_window_days: int = 14,
) -> dict[str, Any]:
    """Find available appointment slots for a service near a target date.

    target_date: "YYYY-MM-DD"
    duration: minutes as string, e.g. "60"
    timeframe: "Anytime", "Morning", "Afternoon", etc.
    """
    return _post(
        "appointments/slotsearch",
        location,
        {
            "ServiceId": service_id,
            "ContactId": contact_id,
            "TargetDate": target_date,
            "Duration": duration,
            "Quantity": quantity,
            "Timeframe": timeframe,
            "SlotWindowDays": slot_window_days,
            "Slots": [],
            "AddOnParts": [],
            "NotificationOptions": [],
        },
    )


# ---------- Invoices ----------

@mcp.tool()
def query_invoices(
    location: str,
    from_date: str | None = None,
    through_date: str | None = None,
    contact_id: int | None = None,
    status: str | None = None,
    include_contact: bool = False,
    skip: int = 0,
    take: int = 100,
) -> dict[str, Any]:
    """Search invoices by date range, contact, or status.

    status: typically "Open", "Paid", "Voided" (omit to include all).
    """
    payload: dict[str, Any] = {
        "Skip": skip,
        "Take": take,
        "IncludeContact": include_contact,
        "Invoices": [],
    }
    if from_date:
        payload["FromDate"] = from_date
    if through_date:
        payload["ThroughDate"] = through_date
    if contact_id is not None:
        payload["ContactId"] = contact_id
    if status:
        payload["Status"] = status
    return _post("invoice/query", location, payload)


@mcp.tool()
def get_invoice(location: str, invoice_id: int, include_contact: bool = True) -> dict[str, Any]:
    """Fetch full details of a single invoice including lines and payments."""
    return _post(
        "invoice/get",
        location,
        {"InvoiceId": invoice_id, "IncludeContact": include_contact},
    )


# ---------- Payments ----------

@mcp.tool()
def query_payments(
    location: str,
    from_date: str | None = None,
    through_date: str | None = None,
    contact_id: int | None = None,
    invoice_id: int | None = None,
    skip: int = 0,
    take: int = 100,
) -> dict[str, Any]:
    """Search payments by date range, contact, or invoice."""
    payload: dict[str, Any] = {"Skip": skip, "Take": take, "Payments": []}
    if from_date:
        payload["FromDate"] = from_date
    if through_date:
        payload["ThroughDate"] = through_date
    if contact_id is not None:
        payload["ContactId"] = contact_id
    if invoice_id is not None:
        payload["InvoiceId"] = invoice_id
    return _post("payment/query", location, payload)


# ---------- Proposals ----------

@mcp.tool()
def query_proposals(
    location: str,
    scope: str = "",
    from_date: str | None = None,
    through_date: str | None = None,
    from_accepted: str | None = None,
    through_accepted: str | None = None,
    contact_id: int | None = None,
    include_contact: bool = False,
    skip: int = 0,
    take: int = 100,
) -> dict[str, Any]:
    """Search proposals by date range, accepted date, or contact.

    scope: "" for all, "open", "accepted", "expired" (check your tenant for exact values).
    """
    payload: dict[str, Any] = {
        "Scope": scope,
        "Skip": skip,
        "Take": take,
        "IncludeContact": include_contact,
        "Proposals": [],
    }
    if from_date:
        payload["FromDate"] = from_date
    if through_date:
        payload["ThroughDate"] = through_date
    if from_accepted:
        payload["FromAccepted"] = from_accepted
    if through_accepted:
        payload["ThroughAccepted"] = through_accepted
    if contact_id is not None:
        payload["ContactId"] = contact_id
    return _post("proposal/query", location, payload)


@mcp.tool()
def get_proposal(location: str, proposal_id: int) -> dict[str, Any]:
    """Fetch full details of a single proposal."""
    return _post("proposal/details", location, {"Id": proposal_id})


# ---------- Reference data ----------

@mcp.tool()
def list_services(
    location: str, include_parts: bool = False, include_inactive: bool = False
) -> dict[str, Any]:
    """List all services configured for the location."""
    return _post(
        "services/all",
        location,
        {
            "IncludeParts": include_parts,
            "IncludeInactive": include_inactive,
            "Matches": [],
        },
    )


@mcp.tool()
def list_service_agents(location: str) -> dict[str, Any]:
    """List all service agents (techs) for the location."""
    return _post("serviceagents/all", location, {"Matches": []})


@mcp.tool()
def list_channels(location: str) -> dict[str, Any]:
    """List all marketing channels and campaigns."""
    return _post("channels/all", location, {"Channels": []})


@mcp.tool()
def list_custom_fields(location: str) -> dict[str, Any]:
    """List all custom field definitions."""
    return _post("customfields/all", location, {"Matches": []})


@mcp.tool()
def list_users(location: str) -> dict[str, Any]:
    """List all users in the organization."""
    return _post("user/all", location, {"Matches": []})


@mcp.tool()
def get_organization_details(location: str) -> dict[str, Any]:
    """Fetch full org details: address, hours, services, agents, custom fields."""
    return _post("organizations/details", location, {})


# ---------- Bulk download (org-level) ----------

@mcp.tool()
def start_download(
    location: str,
    kind: str,
    date_from: str | None = None,
    date_through: str | None = None,
    updated_from: str | None = None,
    updated_through: str | None = None,
    user_id: int | None = None,
    extra_settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Start a bulk data download. Returns a DownloadId for polling.

    kind: typically one of "appointments", "contacts", "invoices", "invoicelines",
          "proposals", "deposits", "payments", "services", "campaignbudgets".
    user_id: REQUIRED by the API. Defaults to SM_USERID_<LOC> from env if unset;
          pass explicitly (any active Owner/Org-Admin UserId from list_users) to override.
    extra_settings: per-kind options. For appointments, the status flags live under an
          "Appointments" object — cancelled rows are OMITTED unless you opt in, e.g.
          {"Appointments": {"Scheduled": true, "Completed": true, "Canceled": true}}.
          NOTE: this appointments dataset does NOT include the free-text Notes column;
          fetch the cancellation reason from the contact via find_contact(id_search=ContactId)
          -> Notes[] (the activity log), then classify it.

    Use poll_download() to wait for completion, then get_download() to retrieve.
    """
    payload: dict[str, Any] = {"Kind": kind}
    if date_from:
        payload["DateFrom"] = date_from
    if date_through:
        payload["DateThrough"] = date_through
    if updated_from:
        payload["UpdatedFrom"] = updated_from
    if updated_through:
        payload["UpdatedThrough"] = updated_through
    uid = user_id if user_id is not None else _get_userid(location)
    if uid is not None:
        payload["UserId"] = uid
    if extra_settings:
        payload.update(extra_settings)
    return _post("download/startdownload", location, payload)


@mcp.tool()
def check_download_status(location: str, download_id: str) -> dict[str, Any]:
    """Check whether a download is ready. Returns Ready=true when done."""
    return _post(
        "download/downloadstatus", location, {"DownloadId": download_id}
    )


@mcp.tool()
def get_download(location: str, download_id: str) -> dict[str, Any]:
    """Retrieve a completed download. Call only when status returned Ready=true."""
    return _post("download/getdownload", location, {"DownloadId": download_id})


@mcp.tool()
def poll_download(
    location: str,
    download_id: str,
    max_wait_seconds: int = 120,
    poll_interval_seconds: int = 5,
) -> dict[str, Any]:
    """Poll a download until ready or timeout, then return the data.

    Convenience wrapper that combines check_download_status + get_download.
    """
    deadline = time.time() + max_wait_seconds
    while time.time() < deadline:
        status = _post(
            "download/downloadstatus", location, {"DownloadId": download_id}
        )
        if status.get("Ready"):
            return _post(
                "download/getdownload", location, {"DownloadId": download_id}
            )
        time.sleep(poll_interval_seconds)
    return {
        "Ready": False,
        "Message": f"Download not ready after {max_wait_seconds}s. Try get_download later.",
        "DownloadId": download_id,
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Sanity check on startup so misconfiguration is loud
    configured = [loc for loc, env in LOCATION_ENV_VARS.items() if os.environ.get(env)]
    if not configured:
        print(
            "WARNING: no ServiceMinder API keys found. Set "
            + ", ".join(LOCATION_ENV_VARS.values())
            + " in your environment.",
            file=sys.stderr,
        )
    else:
        print(f"ServiceMinder MCP ready. Configured locations: {configured}", file=sys.stderr)
    mcp.run()
