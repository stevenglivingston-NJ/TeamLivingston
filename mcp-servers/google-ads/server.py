"""
Google Ads + Local Services MCP server for KTU, BTU, and Jatalia/Earthwise.

Two APIs wrapped in one server:
  - Google Ads API (search, display, brand, cabinet refacing, etc.) via google-ads SDK
  - Local Services API (LSA / "Google Guaranteed") via REST

All three brands share the same OAuth refresh token (scope: adwords) and the
same Google login (firstgenerationusallc@gmail.com, confirmed 2026-09-13) —
but NOT the same account hierarchy. KTU/BTU sit under the "KTU/BTU Reporting"
MCC (GOOGLE_ADS_LOGIN_CUSTOMER_ID); Earthwise does not and must be queried
without a login_customer_id header, or every call 403s. See
`_MCC_MANAGED_ACCOUNTS` below — this is not optional, it is the fix for a
real PERMISSION_DENIED verified live on 2026-09-13.

Required env vars (set in ~/.claude/settings.json):
  GOOGLE_ADS_DEVELOPER_TOKEN  - from https://ads.google.com/aw/apicenter
  GOOGLE_ADS_CLIENT_ID        - from Google Cloud Console
  GOOGLE_ADS_CLIENT_SECRET    - from Google Cloud Console
  GOOGLE_ADS_REFRESH_TOKEN    - from `python get_refresh_token.py`
  GOOGLE_ADS_LOGIN_CUSTOMER_ID (optional) - only if you have an MCC; leave blank otherwise
"""
import os
import time
from datetime import date, timedelta
from typing import Any
import httpx
from mcp.server.fastmcp import FastMCP
from google.ads.googleads.client import GoogleAdsClient
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google.protobuf.json_format import MessageToDict

mcp = FastMCP("google-ads")

ACCOUNT_MAP: dict[str, str] = {
    "KTU": "2579406186",
    "BTU": "4477036900",
    # Earthwise Seed Co. (Jatalia) — discovered 2026-09-13 via
    # listAccessibleCustomers; was never wired in before, despite ~$300k/30d
    # of live spend. Owned by Harvest, not Paid.
    "EARTHWISE": "7159460368",
}

# Accounts that are clients of the "KTU/BTU Reporting" MCC
# (GOOGLE_ADS_LOGIN_CUSTOMER_ID) and therefore require that MCC's id in the
# login_customer_id header. Earthwise is NOT a client of this MCC — it is
# reachable directly on the same OAuth login — so calling it WITH
# login_customer_id set returns PERMISSION_DENIED (verified live 2026-09-13).
# Any new brand added to ACCOUNT_MAP must be classified here explicitly;
# guessing wrong fails loudly (PERMISSION_DENIED), it does not silently
# return the wrong account's data.
_MCC_MANAGED_ACCOUNTS: set[str] = {
    "2579406186",  # KTU
    "4477036900",  # BTU
    "4668735878",  # BTU Local Ads (LSA) — also an MCC client, not in ACCOUNT_MAP directly
}

# 4278203845 ("KTU Bloomfield NJ") is a third account visible to this login —
# a dormant legacy KTU account (every campaign PAUSED/REMOVED, $0 spend/30d,
# last active ~2023). Deliberately excluded from ACCOUNT_MAP: it is not a
# live reporting gap, just old agency scaffolding nobody archived. Revisit
# only if Steven decides to formally close it out.

LSA_ACCOUNT_MAP: dict[str, str] = {
    "KTU": "2579406186",
    "BTU": "4668735878",
}

def _resolve(location: str) -> str:
    loc = location.upper().strip()
    if loc not in ACCOUNT_MAP:
        valid = ", ".join(sorted(ACCOUNT_MAP.keys()))
        raise ValueError(f"Unknown location '{location}'. Valid: {valid}")
    return ACCOUNT_MAP[loc]


def _check_env() -> tuple[bool, list[str]]:
    required = ["GOOGLE_ADS_DEVELOPER_TOKEN", "GOOGLE_ADS_CLIENT_ID",
                "GOOGLE_ADS_CLIENT_SECRET", "GOOGLE_ADS_REFRESH_TOKEN"]
    missing = [k for k in required if not os.environ.get(k)]
    return (not missing, missing)


def _ads_client(customer_id: str | None = None) -> GoogleAdsClient:
    """Build a client. `customer_id`, when given, decides whether the KTU/BTU
    MCC's login_customer_id is attached — see `_MCC_MANAGED_ACCOUNTS` above.
    Omit it only for calls (like listAccessibleCustomers) that aren't scoped
    to one customer."""
    config: dict[str, Any] = {
        "developer_token": os.environ["GOOGLE_ADS_DEVELOPER_TOKEN"],
        "refresh_token": os.environ["GOOGLE_ADS_REFRESH_TOKEN"],
        "client_id": os.environ["GOOGLE_ADS_CLIENT_ID"],
        "client_secret": os.environ["GOOGLE_ADS_CLIENT_SECRET"],
        "use_proto_plus": True,
    }
    login_id = os.environ.get("GOOGLE_ADS_LOGIN_CUSTOMER_ID", "").strip()
    if login_id and (customer_id is None or customer_id in _MCC_MANAGED_ACCOUNTS):
        config["login_customer_id"] = login_id.replace("-", "")
    return GoogleAdsClient.load_from_dict(config)


def _oauth_token() -> str:
    """Refresh and return a bearer token for REST APIs (LSA)."""
    creds = Credentials(
        None,
        refresh_token=os.environ["GOOGLE_ADS_REFRESH_TOKEN"],
        client_id=os.environ["GOOGLE_ADS_CLIENT_ID"],
        client_secret=os.environ["GOOGLE_ADS_CLIENT_SECRET"],
        token_uri="https://oauth2.googleapis.com/token",
    )
    creds.refresh(Request())
    return creds.token


@mcp.tool()
def list_locations() -> dict[str, Any]:
    """List configured locations (KTU, BTU, EARTHWISE) and their Google Ads
    account IDs."""
    ok, missing = _check_env()
    return {"locations": list(ACCOUNT_MAP.keys()),
            "accounts": ACCOUNT_MAP,
            "env_complete": ok,
            "missing_env": missing}


@mcp.tool()
def test_connection(location: str) -> dict[str, Any]:
    """Smoke test: query a trivial campaign list to verify credentials."""
    customer_id = _resolve(location)
    client = _ads_client(customer_id)
    ga = client.get_service("GoogleAdsService")
    query = "SELECT customer.descriptive_name, customer.currency_code FROM customer LIMIT 1"
    for batch in ga.search_stream(customer_id=customer_id, query=query):
        for row in batch.results:
            return {"status": "ok", "location": location,
                    "account_name": row.customer.descriptive_name,
                    "currency": row.customer.currency_code}
    return {"status": "ok", "location": location, "note": "empty"}


@mcp.tool()
def query_keywords(location: str, days: int = 30, min_spend: float = 0,
                   limit: int = 100) -> dict[str, Any]:
    """Top keywords by spend. Returns keyword text, match type, ad group,
    campaign, spend, clicks, impressions, conversions, CTR, CPC, quality score."""
    customer_id = _resolve(location)
    client = _ads_client(customer_id)
    ga = client.get_service("GoogleAdsService")
    query = f"""
    SELECT
      campaign.name, ad_group.name,
      ad_group_criterion.keyword.text,
      ad_group_criterion.keyword.match_type,
      ad_group_criterion.quality_info.quality_score,
      metrics.cost_micros, metrics.clicks, metrics.impressions,
      metrics.conversions, metrics.ctr, metrics.average_cpc
    FROM keyword_view
    WHERE segments.date DURING LAST_{days}_DAYS
      AND metrics.cost_micros >= {int(min_spend * 1_000_000)}
    ORDER BY metrics.cost_micros DESC
    LIMIT {limit}
    """
    rows = []
    for batch in ga.search_stream(customer_id=customer_id, query=query):
        for r in batch.results:
            rows.append({
                "campaign": r.campaign.name,
                "ad_group": r.ad_group.name,
                "keyword": r.ad_group_criterion.keyword.text,
                "match_type": str(r.ad_group_criterion.keyword.match_type),
                "quality_score": r.ad_group_criterion.quality_info.quality_score,
                "spend": r.metrics.cost_micros / 1_000_000,
                "clicks": r.metrics.clicks,
                "impressions": r.metrics.impressions,
                "conversions": r.metrics.conversions,
                "ctr": r.metrics.ctr,
                "avg_cpc": r.metrics.average_cpc / 1_000_000,
            })
    return {"location": location, "days": days, "rows": rows, "count": len(rows)}


@mcp.tool()
def query_search_terms(location: str, days: int = 30, limit: int = 100) -> dict[str, Any]:
    """Actual user search queries that triggered ads."""
    customer_id = _resolve(location)
    client = _ads_client(customer_id)
    ga = client.get_service("GoogleAdsService")
    query = f"""
    SELECT
      campaign.name, ad_group.name,
      search_term_view.search_term,
      metrics.cost_micros, metrics.clicks, metrics.impressions, metrics.conversions
    FROM search_term_view
    WHERE segments.date DURING LAST_{days}_DAYS
    ORDER BY metrics.cost_micros DESC
    LIMIT {limit}
    """
    rows = []
    for batch in ga.search_stream(customer_id=customer_id, query=query):
        for r in batch.results:
            rows.append({
                "campaign": r.campaign.name,
                "ad_group": r.ad_group.name,
                "search_term": r.search_term_view.search_term,
                "spend": r.metrics.cost_micros / 1_000_000,
                "clicks": r.metrics.clicks,
                "impressions": r.metrics.impressions,
                "conversions": r.metrics.conversions,
            })
    return {"location": location, "days": days, "rows": rows, "count": len(rows)}


@mcp.tool()
def query_geo_performance(location: str, days: int = 30,
                          limit: int = 100) -> dict[str, Any]:
    """Geographic performance by city, region, country."""
    customer_id = _resolve(location)
    client = _ads_client(customer_id)
    ga = client.get_service("GoogleAdsService")
    query = f"""
    SELECT
      campaign.name,
      segments.geo_target_city, segments.geo_target_region,
      metrics.cost_micros, metrics.clicks, metrics.impressions, metrics.conversions
    FROM geographic_view
    WHERE segments.date DURING LAST_{days}_DAYS
    ORDER BY metrics.cost_micros DESC
    LIMIT {limit}
    """
    rows = []
    for batch in ga.search_stream(customer_id=customer_id, query=query):
        for r in batch.results:
            rows.append({
                "campaign": r.campaign.name,
                "city": r.segments.geo_target_city,
                "region": r.segments.geo_target_region,
                "spend": r.metrics.cost_micros / 1_000_000,
                "clicks": r.metrics.clicks,
                "impressions": r.metrics.impressions,
                "conversions": r.metrics.conversions,
            })
    return {"location": location, "days": days, "rows": rows, "count": len(rows)}


@mcp.tool()
def query_negative_keywords(location: str) -> dict[str, Any]:
    """List current negative keywords across the account."""
    customer_id = _resolve(location)
    client = _ads_client(customer_id)
    ga = client.get_service("GoogleAdsService")
    query = """
    SELECT
      campaign.name, ad_group.name,
      ad_group_criterion.keyword.text,
      ad_group_criterion.keyword.match_type
    FROM ad_group_criterion
    WHERE ad_group_criterion.negative = true
    """
    rows = []
    for batch in ga.search_stream(customer_id=customer_id, query=query):
        for r in batch.results:
            rows.append({
                "campaign": r.campaign.name,
                "ad_group": r.ad_group.name,
                "keyword": r.ad_group_criterion.keyword.text,
                "match_type": str(r.ad_group_criterion.keyword.match_type),
            })
    return {"location": location, "rows": rows, "count": len(rows)}


@mcp.tool()
def query_campaigns(location: str, days: int = 30,
                    status_filter: str = "") -> dict[str, Any]:
    """Campaign-level performance with budget, status, and metrics.
    status_filter: 'ENABLED', 'PAUSED', or empty for all."""
    customer_id = _resolve(location)
    client = _ads_client(customer_id)
    ga = client.get_service("GoogleAdsService")
    where = [f"segments.date DURING LAST_{days}_DAYS"]
    if status_filter:
        where.append(f"campaign.status = '{status_filter.upper()}'")
    query = f"""
    SELECT
      campaign.id, campaign.name, campaign.status,
      campaign.advertising_channel_type,
      campaign_budget.amount_micros,
      metrics.cost_micros, metrics.clicks, metrics.impressions,
      metrics.conversions, metrics.ctr, metrics.average_cpc
    FROM campaign
    WHERE {' AND '.join(where)}
    ORDER BY metrics.cost_micros DESC
    """
    rows = []
    for batch in ga.search_stream(customer_id=customer_id, query=query):
        for r in batch.results:
            rows.append({
                "id": r.campaign.id,
                "name": r.campaign.name,
                "status": str(r.campaign.status),
                "channel_type": str(r.campaign.advertising_channel_type),
                "daily_budget": r.campaign_budget.amount_micros / 1_000_000,
                "spend": r.metrics.cost_micros / 1_000_000,
                "clicks": r.metrics.clicks,
                "impressions": r.metrics.impressions,
                "conversions": r.metrics.conversions,
                "ctr": r.metrics.ctr,
                "avg_cpc": r.metrics.average_cpc / 1_000_000,
            })
    return {"location": location, "days": days, "rows": rows, "count": len(rows)}


@mcp.tool()
def query_conversion_actions(location: str, days: int = 30,
                             include_removed: bool = False) -> dict[str, Any]:
    """Full conversion-action audit: every goal, how it is counted, whether it
    is bidding-eligible, and whether it has actually recorded anything.

    This is the tool that answers "is my conversion tracking real?". Read these
    fields together — each hides a different SILENT failure:

    * status REMOVED / enabled False   -> the goal exists but is dead.
    * primary_for_goal False           -> SECONDARY: observed only, Smart
      Bidding does NOT optimize toward it. A booking goal sitting secondary
      while a form-fill sits primary means you bid for the cheaper outcome.
    * type UPLOAD_CLICKS / UPLOAD_CALLS -> OFFLINE IMPORT. Records nothing
      unless something actively uploads (CRM workflow, Zapier, a script). An
      UPLOAD goal with 0 conversions is an unfinished integration, NOT a quiet
      period — never report it as "no conversions yet".
    * type WEBPAGE / GOOGLE_ANALYTICS_4_* -> fires from the site/GA4. Zero here
      usually means the tag or its trigger never fires.
    * conversions == 0 over the window -> not recording. Report loudly: a goal
      that never fires is indistinguishable from one that does not exist,
      except that it silently dilutes bidding.
    * counting_type EVERY vs ONE       -> EVERY on a lead form inflates volume
      when one person submits twice.

    days: metrics window. include_removed: also list REMOVED actions.
    """
    customer_id = _resolve(location)
    client = _ads_client(customer_id)
    ga = client.get_service("GoogleAdsService")

    # Config first, with NO date segment — an action with zero traffic must
    # still appear, and segmenting by date would hide exactly those.
    cfg_query = """
    SELECT
      conversion_action.id, conversion_action.name, conversion_action.status,
      conversion_action.type, conversion_action.category,
      conversion_action.counting_type, conversion_action.primary_for_goal,
      conversion_action.include_in_conversions_metric,
      conversion_action.click_through_lookback_window_days,
      conversion_action.value_settings.default_value,
      conversion_action.value_settings.always_use_default_value,
      conversion_action.origin
    FROM conversion_action
    """
    if not include_removed:
        cfg_query += " WHERE conversion_action.status != 'REMOVED'"

    actions: dict[int, dict[str, Any]] = {}
    for batch in ga.search_stream(customer_id=customer_id, query=cfg_query):
        for r in batch.results:
            ca = r.conversion_action
            actions[ca.id] = {
                "id": ca.id,
                "name": ca.name,
                "status": _enum_name(ca.status),
                "type": _enum_name(ca.type_),
                "category": _enum_name(ca.category),
                "counting_type": _enum_name(ca.counting_type),
                "origin": _enum_name(ca.origin),
                "primary_for_goal": ca.primary_for_goal,
                "counts_in_conversions_metric": ca.include_in_conversions_metric,
                "click_lookback_days": ca.click_through_lookback_window_days,
                "default_value": ca.value_settings.default_value,
                "always_use_default_value": ca.value_settings.always_use_default_value,
                "all_conversions": 0.0,
                "conversion_value": 0.0,
            }

    # ONLY all_conversions* is selectable FROM conversion_action. Selecting
    # metrics.conversions / conversions_value here fails the whole query with
    # PROHIBITED_METRIC_IN_SELECT_OR_WHERE_CLAUSE (verified 2026-08-27) — the
    # conversions metric is incompatible with this resource. all_conversions is
    # the superset (it includes actions not counted in the "Conversions" column),
    # which is exactly what an audit wants: it reveals goals that are firing but
    # excluded from bidding.
    met_query = f"""
    SELECT
      conversion_action.id,
      metrics.all_conversions, metrics.all_conversions_value
    FROM conversion_action
    WHERE segments.date DURING LAST_{days}_DAYS
    """
    metrics_error = None
    try:
        for batch in ga.search_stream(customer_id=customer_id, query=met_query):
            for r in batch.results:
                a = actions.get(r.conversion_action.id)
                if a is not None:
                    a["all_conversions"] += r.metrics.all_conversions
                    a["conversion_value"] += r.metrics.all_conversions_value
    except Exception as exc:  # metrics are a bonus; the config is the point
        metrics_error = str(exc)[:300]

    rows = sorted(actions.values(), key=lambda a: (-a["all_conversions"], a["name"]))

    # Surface the silent failures rather than making every caller re-derive them.
    findings: list[str] = []
    live = [a for a in rows if a["status"] == "ENABLED"]
    primaries = [a for a in live if a["primary_for_goal"]]
    uploads = [a for a in live if a["type"].startswith("UPLOAD")]
    upload_dead = [a for a in uploads if a["all_conversions"] == 0]

    if not primaries:
        findings.append("NO enabled PRIMARY conversion action — Smart Bidding "
                        "has nothing to optimize toward.")
    for a in upload_dead:
        findings.append(
            f"'{a['name']}' is an OFFLINE IMPORT ({a['type']}) with 0 conversions "
            f"in {days}d — nothing is uploading to it. Unfinished integration, "
            f"not a quiet period.")
    for a in live:
        if a["all_conversions"] == 0 and a not in upload_dead:
            findings.append(
                f"'{a['name']}' ({a['type']}, "
                f"{'PRIMARY' if a['primary_for_goal'] else 'secondary'}) recorded "
                f"0 conversions in {days}d — tag or trigger likely never fires.")
        if a["primary_for_goal"] and a["counting_type"] == "MANY_PER_CLICK" \
                and a["category"] in ("SUBMIT_LEAD_FORM", "BOOK_APPOINTMENT",
                                      "REQUEST_QUOTE", "CONTACT"):
            findings.append(
                f"'{a['name']}' is a lead-type PRIMARY goal counting EVERY "
                f"conversion — one person submitting twice counts twice and "
                f"inflates the bidding signal. Usually should be ONE.")

    return {
        "location": location,
        "days": days,
        "count": len(rows),
        "enabled": len(live),
        "primary_count": len(primaries),
        "metrics_error": metrics_error,
        "rows": rows,
        "findings": findings,
    }


_MISSING = object()


def _enum_name(value: Any) -> str:
    """Enum -> bare name ('GOOGLE_ADS_UI'), not 'ChangeClientType.GOOGLE_ADS_UI'."""
    name = getattr(value, "name", None)
    if name:
        return name
    text = str(value)
    return text.rsplit(".", 1)[-1] if "." in text else text


def _changed_values(resource: Any, paths: list[str]) -> dict[str, Any]:
    """Pull only the changed fields out of a ChangedResource proto.

    ChangedResource wraps exactly one resource (campaign, campaign_budget, …)
    and the API populates only the fields named in changed_fields, so unwrap
    the single entry and keep the named paths.
    """
    pb = getattr(resource, "_pb", resource)
    try:
        payload = MessageToDict(pb, preserving_proto_field_name=True)
    except Exception:
        return {}
    flat: dict[str, Any] = {}
    for wrapped in payload.values():
        if isinstance(wrapped, dict):
            flat.update(wrapped)
    # changed_fields paths are dotted ("keyword.text"), so walk them rather
    # than doing a flat lookup — a flat lookup silently drops every nested
    # field, which is most of what makes a keyword change readable.
    out: dict[str, Any] = {}
    for path in paths:
        cursor: Any = flat
        for part in path.split("."):
            if isinstance(cursor, dict) and part in cursor:
                cursor = cursor[part]
            else:
                cursor = _MISSING
                break
        if cursor is not _MISSING:
            out[path] = cursor
    return out


@mcp.tool()
def query_change_history(location: str, days: int = 14, limit: int = 200,
                         resource_type: str = "") -> dict[str, Any]:
    """Who changed what in the account, and when — the UI's Change History.

    Reads the `change_event` resource and returns, per change: the acting
    user's email, the client used (GOOGLE_ADS_UI, GOOGLE_ADS_API,
    GOOGLE_ADS_EDITOR, GOOGLE_ADS_AUTOMATED_RULE, ...), the resource touched,
    the operation, which fields changed, and their old -> new values.

    Use this to attribute a budget/status/keyword change to a person or tool
    rather than inferring it from a before/after snapshot.

    Google retains change history for 30 DAYS ONLY, so `days` is clamped to 30
    and anything older is unrecoverable here.

    resource_type: optional filter, e.g. 'CAMPAIGN', 'CAMPAIGN_BUDGET',
    'AD_GROUP', 'AD_GROUP_CRITERION', 'AD_GROUP_AD', 'CAMPAIGN_CRITERION'.
    Empty returns every type.
    """
    customer_id = _resolve(location)
    days = max(1, min(days, 30))
    limit = max(1, min(limit, 10_000))

    start = date.today() - timedelta(days=days)
    end = date.today() + timedelta(days=1)
    where = [
        f"change_event.change_date_time >= '{start.isoformat()} 00:00:00'",
        f"change_event.change_date_time <= '{end.isoformat()} 00:00:00'",
    ]
    if resource_type:
        where.append(f"change_event.change_resource_type = '{resource_type.upper()}'")

    # change_event REQUIRES an explicit LIMIT and does not support search_stream.
    query = f"""
    SELECT
      change_event.change_date_time,
      change_event.user_email,
      change_event.client_type,
      change_event.change_resource_type,
      change_event.change_resource_name,
      change_event.resource_change_operation,
      change_event.changed_fields,
      change_event.old_resource,
      change_event.new_resource,
      campaign.name,
      ad_group.name
    FROM change_event
    WHERE {' AND '.join(where)}
    ORDER BY change_event.change_date_time DESC
    LIMIT {limit}
    """

    client = _ads_client(customer_id)
    ga = client.get_service("GoogleAdsService")
    rows: list[dict[str, Any]] = []
    for r in ga.search(customer_id=customer_id, query=query):
        ce = r.change_event
        paths = list(ce.changed_fields.paths)
        rows.append({
            "changed_at": str(ce.change_date_time),
            "user_email": ce.user_email,
            "client_type": _enum_name(ce.client_type),
            "resource_type": _enum_name(ce.change_resource_type),
            "operation": _enum_name(ce.resource_change_operation),
            "campaign": r.campaign.name or None,
            "ad_group": r.ad_group.name or None,
            "changed_fields": paths,
            "old": _changed_values(ce.old_resource, paths),
            "new": _changed_values(ce.new_resource, paths),
        })

    editors = sorted({row["user_email"] for row in rows if row["user_email"]})
    return {
        "location": location,
        "days": days,
        "window_start": start.isoformat(),
        "rows": rows,
        "count": len(rows),
        "editors": editors,
        "note": "Google retains change history for 30 days; older changes are unrecoverable.",
    }


LSA_BASE = "https://localservices.googleapis.com/v1"


def _lsa_query(endpoint: str, query: str,
               start_date: "date | None" = None,
               end_date: "date | None" = None) -> dict[str, Any]:
    """Run a LSA REST query."""
    from datetime import date, timedelta
    token = _oauth_token()
    url = f"{LSA_BASE}/{endpoint}:search"
    headers = {"Authorization": f"Bearer {token}"}
    if end_date is None:
        end_date = date.today()
    if start_date is None:
        start_date = end_date - timedelta(days=30)
    params = {
        "query": query,
        "pageSize": 100,
        "startDate.year": start_date.year,
        "startDate.month": start_date.month,
        "startDate.day": start_date.day,
        "endDate.year": end_date.year,
        "endDate.month": end_date.month,
        "endDate.day": end_date.day,
    }
    # The Local Services API rate-limits aggressively: two of these fired
    # concurrently return 403 even though the same call succeeds on its own.
    # Retry the transient statuses rather than surfacing a fake auth failure.
    last_exc: Exception | None = None
    with httpx.Client(timeout=30) as client:
        for attempt in range(3):
            resp = client.get(url, headers=headers, params=params)
            if resp.status_code in (403, 429, 500, 502, 503, 504):
                last_exc = httpx.HTTPStatusError(
                    f"{resp.status_code} from {endpoint}", request=resp.request,
                    response=resp)
                if attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
            resp.raise_for_status()
            return resp.json()
    raise last_exc  # type: ignore[misc]


def _mcc_id() -> str:
    """LSA queries require manager_customer_id (the MCC). No dashes."""
    mcc = os.environ.get("GOOGLE_ADS_LOGIN_CUSTOMER_ID", "").strip().replace("-", "")
    if not mcc:
        raise ValueError(
            "GOOGLE_ADS_LOGIN_CUSTOMER_ID (MCC) is required for LSA queries. "
            "Set it in env (10 digits, no dashes)."
        )
    return mcc


def _resolve_lsa(location: str) -> str:
    """Resolve to LSA Service Provider ID (separate from Google Ads CID)."""
    loc = location.upper().strip()
    if loc not in LSA_ACCOUNT_MAP:
        valid = ", ".join(sorted(LSA_ACCOUNT_MAP.keys()))
        raise ValueError(f"Unknown LSA location '{location}'. Valid: {valid}")
    return LSA_ACCOUNT_MAP[loc]


def _lsa_account_report(location: str, days: int = 30) -> dict[str, Any]:
    """Shared account-report fetch. Returns the resolved LSA id, every account
    visible in the MCC, and this brand's matched report (None if unmatched).

    `days` sets the reporting window. The API derives its currentPeriod* fields
    from that window and its previousPeriod* fields from the equal-length span
    immediately before it, so the two are always like-for-like."""
    from datetime import date, timedelta
    mcc = _mcc_id()
    end = date.today()
    start = end - timedelta(days=days)
    result = _lsa_query("accountReports", f"manager_customer_id:{mcc}",
                        start_date=start, end_date=end)
    target_id = _resolve_lsa(location)
    reports = result.get("accountReports", [])
    matched = [r for r in reports if r.get("accountId") == target_id]
    return {
        "lsa_account_id": target_id,
        "brand": location.upper().strip(),
        "date_range": {"start": start.isoformat(), "end": end.isoformat()},
        "matched_count": len(matched),
        "all_accounts_in_mcc": [
            {"accountId": r.get("accountId"), "businessName": r.get("businessName")}
            for r in reports
        ],
        "report": matched[0] if matched else None,
    }


@mcp.tool()
def query_lsa_account(location: str, days: int = 30) -> dict[str, Any]:
    """LSA account snapshot: business name, average rating, review count,
    weekly budget, total cost current period, charged leads, phone calls.

    `days` is the reporting window (default 30). previousPeriod* fields cover
    the equal-length span immediately before it.

    Note: `impressionsLastTwoDays` reads 0 on accounts that demonstrably served
    and took leads in that window. Do not treat it as a serving signal - use the
    LOCAL_SERVICES campaign's impressions from `query_campaigns` instead."""
    return _lsa_account_report(location, days=days)


def _as_int(value: Any) -> int:
    """LSA reports return counts as strings. Absent/garbage -> 0."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _tally(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    """Count rows by one field, biggest bucket first."""
    counts: dict[str, int] = {}
    for row in rows:
        counts[row[key]] = counts.get(row[key], 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))


LSA_LEAD_FIELDS = """
    local_services_lead.id,
    local_services_lead.lead_type,
    local_services_lead.lead_status,
    local_services_lead.category_id,
    local_services_lead.service_id,
    local_services_lead.contact_details,
    local_services_lead.creation_date_time,
    local_services_lead.lead_charged,
    local_services_lead.lead_feedback_submitted,
    local_services_lead.locale,
    local_services_lead.note.description,
    local_services_lead.credit_details.credit_state,
    local_services_lead.credit_details.credit_state_last_update_date_time
"""


@mcp.tool()
def query_lsa_leads(location: str, days: int = 30) -> dict[str, Any]:
    """Lead-by-lead detail from LSA: type (call/message), job category, charge
    status, dispute/credit state, and the consumer phone number.

    Sourced from the Google Ads API `local_services_lead` resource, NOT the
    Local Services REST `detailedLeadReports` endpoint - that endpoint returns
    zero rows for these accounts while the same leads are readable here.

    Consumer NAME is not exposed by this resource; `contact_details` carries the
    phone number only. Pull names from the LSA console if a brief needs them.

    Returns a `status`: "ok" when the account has readable lead history, or
    "no_data" when the account has none at all while the account report shows
    leads/calls - that combination means the lead pipe is broken, NOT a quiet
    period, and must never be reported as 0 leads.
    """
    from datetime import date, timedelta
    # LSA lead ids live on the LSA account, which is NOT the Google Ads CID for
    # every brand (BTU's differ). Querying the Ads CID returns 0 rows silently.
    cid = _resolve_lsa(location)
    end = date.today()
    start = end - timedelta(days=days)

    # `segments.date` is incompatible with local_services_lead - the query must
    # run unsegmented and be windowed here.
    query = (f"SELECT {LSA_LEAD_FIELDS} FROM local_services_lead "
             "ORDER BY local_services_lead.creation_date_time DESC")
    service = _ads_client(cid).get_service("GoogleAdsService")

    leads: list[dict[str, Any]] = []
    total_in_account = 0
    for row in service.search(customer_id=cid, query=query):
        lead = row.local_services_lead
        total_in_account += 1
        created = lead.creation_date_time or ""
        if not (start.isoformat() <= created[:10] <= end.isoformat()):
            continue
        leads.append({
            "id": str(lead.id),
            "created": created,
            "lead_type": lead.lead_type.name,
            "lead_status": lead.lead_status.name,
            "category": lead.category_id.replace("xcat:service_area_business_", ""),
            "service_id": lead.service_id or None,
            "charged": lead.lead_charged,
            "credit_state": lead.credit_details.credit_state.name,
            "credit_state_updated": (
                lead.credit_details.credit_state_last_update_date_time or None),
            "feedback_submitted": lead.lead_feedback_submitted,
            "phone_number": lead.contact_details.phone_number or None,
            "locale": lead.locale or None,
            "note": lead.note.description or None,
        })

    out: dict[str, Any] = {
        "lsa_account_id": cid,
        "brand": location.upper().strip(),
        "date_range": {"start": start.isoformat(), "end": end.isoformat()},
        "lead_count": len(leads),
        "charged_count": sum(1 for row in leads if row["charged"]),
        "by_type": _tally(leads, "lead_type"),
        "by_status": _tally(leads, "lead_status"),
        "by_category": _tally(leads, "category"),
        "leads": leads,
        "total_leads_in_account_history": total_in_account,
        "status": "ok",
    }
    if total_in_account:
        return out

    # No lead history AT ALL. Before reporting that as a real zero, cross-check
    # the account report: leads/calls there with nothing here means the lead pipe
    # is broken. A bare 0 reads as a genuine result and has already cost a brief
    # its LSA lead-quality section.
    try:
        report = _lsa_account_report(location, days=days).get("report") or {}
    except Exception as exc:
        out["status"] = "no_data"
        out["note"] = (
            f"local_services_lead returned no rows for account {cid}, and the "
            f"account-report cross-check itself failed ({type(exc).__name__}: "
            f"{exc}). Treat LSA lead detail as unavailable.")
        return out

    charged = _as_int(report.get("currentPeriodChargedLeads"))
    calls = _as_int(report.get("currentPeriodPhoneCalls"))
    out["account_report_cross_check"] = {
        "currentPeriodChargedLeads": charged,
        "currentPeriodPhoneCalls": calls,
    }
    if charged or calls:
        out["status"] = "no_data"
        out["note"] = (
            f"local_services_lead returned no rows for account {cid}, but the "
            f"account report shows {charged} charged lead(s) and {calls} phone "
            f"call(s) for {out['brand']}. Lead-level data is NOT reachable - do "
            f"not report 0 LSA leads. Check that {cid} is the right LSA account "
            f"id for this brand and that the token's MCC still links it.")
    else:
        out["note"] = (
            "local_services_lead returned no rows and the account report also "
            "shows no charged leads or phone calls - consistent with an account "
            "that has genuinely never taken a lead.")
    return out


def _period_bounds(today: "date") -> dict[str, tuple["date", "date"]]:
    """WTD / MTD / YTD spans ending today. Week starts Monday (ISO)."""
    return {
        "WTD": (today - timedelta(days=today.weekday()), today),
        "MTD": (today.replace(day=1), today),
        "YTD": (today.replace(month=1, day=1), today),
    }


def _bucket(leads: list[dict[str, Any]], start: "date", end: "date") -> dict[str, Any]:
    """Roll a lead list up over one window."""
    lo, hi = start.isoformat(), end.isoformat()
    rows = [x for x in leads if lo <= x["created"][:10] <= hi]
    return {
        "start": lo,
        "end": hi,
        "days": (end - start).days,
        "leads": len(rows),
        "charged": sum(1 for x in rows if x["charged"]),
        "by_type": _tally(rows, "lead_type"),
        "by_category": _tally(rows, "category"),
    }


@mcp.tool()
def query_lsa_periods(location: str, include_cost: bool = True) -> dict[str, Any]:
    """LSA performance rolled up week-to-date, month-to-date and year-to-date,
    with a prior-year YTD comparison.

    Lead counts come from the Google Ads `local_services_lead` resource, which
    carries full account history, so the windows are computed from real lead
    timestamps rather than a trailing-N-days approximation. Week starts Monday.

    `include_cost=True` additionally fetches the LSA account report once per
    window for spend, phone calls, connected calls and responsiveness. That is
    three REST calls per brand and the endpoint rate-limits, so pass False when
    you only need lead volume.
    """
    from datetime import date
    cid = _resolve_lsa(location)
    today = date.today()
    brand = location.upper().strip()

    # One unsegmented pull of full history, bucketed locally per window.
    query = (f"SELECT {LSA_LEAD_FIELDS} FROM local_services_lead "
             "ORDER BY local_services_lead.creation_date_time DESC")
    service = _ads_client(cid).get_service("GoogleAdsService")
    leads: list[dict[str, Any]] = []
    for row in service.search(customer_id=cid, query=query):
        lead = row.local_services_lead
        leads.append({
            "created": lead.creation_date_time or "",
            "charged": lead.lead_charged,
            "lead_type": lead.lead_type.name,
            "lead_status": lead.lead_status.name,
            "category": lead.category_id.replace("xcat:service_area_business_", ""),
        })

    periods = {name: _bucket(leads, lo, hi)
               for name, (lo, hi) in _period_bounds(today).items()}

    # Prior-year YTD, same calendar span one year back. History may not reach
    # that far - say so rather than reporting a hollow 0 as a real decline.
    py_start = today.replace(year=today.year - 1, month=1, day=1)
    try:
        py_end = today.replace(year=today.year - 1)
    except ValueError:  # Feb 29
        py_end = today.replace(year=today.year - 1, day=28)
    prior = _bucket(leads, py_start, py_end)
    earliest = min((x["created"][:10] for x in leads if x["created"]), default=None)
    if earliest and earliest > py_start.isoformat():
        prior["coverage_note"] = (
            f"lead history starts {earliest}, after {py_start.isoformat()} - "
            f"prior-year YTD is partial, do not report it as a clean YoY")
    periods["prior_year_YTD"] = prior

    out: dict[str, Any] = {
        "brand": brand,
        "lsa_account_id": cid,
        "as_of": today.isoformat(),
        "week_starts": "monday",
        "total_leads_in_account_history": len(leads),
        "periods": periods,
    }

    if not include_cost:
        return out

    # Spend/calls only exist on the account report, and only for the window
    # requested - so one call per window.
    for name in ("WTD", "MTD", "YTD"):
        span = periods[name]
        try:
            report = _lsa_account_report(
                location, days=max(span["days"], 1)).get("report") or {}
        except Exception as exc:
            span["cost_error"] = f"{type(exc).__name__}: {exc}"
            continue
        span["cost"] = report.get("currentPeriodTotalCost")
        span["phone_calls"] = _as_int(report.get("currentPeriodPhoneCalls"))
        span["connected_calls"] = _as_int(
            report.get("currentPeriodConnectedPhoneCalls"))
        out.setdefault("account", {
            "business_name": report.get("businessName"),
            "rating": report.get("averageFiveStarRating"),
            "reviews": _as_int(report.get("totalReview")),
            "weekly_budget": report.get("averageWeeklyBudget"),
            "phone_responsiveness": report.get("phoneLeadResponsiveness"),
        })
    return out


def _text_assets(assets: Any) -> list[dict[str, Any]]:
    """Extract text + pinned slot from a repeated AdTextAsset field (RSA
    headlines/descriptions). `pinned` is None when the asset floats."""
    out = []
    for a in assets:
        pinned = _enum_name(a.pinned_field)
        out.append({
            "text": a.text,
            "pinned": None if pinned in ("UNSPECIFIED", "UNKNOWN") else pinned,
        })
    return out


@mcp.tool()
def query_ads(location: str, days: int = 30, limit: int = 100,
             status_filter: str = "ENABLED") -> dict[str, Any]:
    """Ad-level (ad_group_ad) performance — the creative detail the other
    query_* tools don't reach. Closes the standing "creative-level blind on
    Google" gap (paid.md §4 / Known Breakages) that previously required
    Zapier or hand-built GAQL.

    Returns per ad: campaign, ad group, ad type, ad_strength (RSA quality
    signal that ties directly to landing-page-experience findings), status,
    final URLs, and — for RESPONSIVE_SEARCH_AD ads only — the headline/
    description text with its pinned slot (empty list for other ad types,
    not an error). Use ad_strength plus CTR/cost-per-conversion together to
    name the exact ad to pause or iterate, per §4.

    status_filter: 'ENABLED', 'PAUSED', 'REMOVED', or empty for all.
    """
    customer_id = _resolve(location)
    client = _ads_client(customer_id)
    ga = client.get_service("GoogleAdsService")
    where = [f"segments.date DURING LAST_{days}_DAYS"]
    if status_filter:
        where.append(f"ad_group_ad.status = '{status_filter.upper()}'")
    query = f"""
    SELECT
      campaign.name, ad_group.name,
      ad_group_ad.ad.id, ad_group_ad.ad.type,
      ad_group_ad.ad.final_urls,
      ad_group_ad.ad.responsive_search_ad.headlines,
      ad_group_ad.ad.responsive_search_ad.descriptions,
      ad_group_ad.ad_strength, ad_group_ad.status,
      metrics.cost_micros, metrics.clicks, metrics.impressions,
      metrics.conversions, metrics.ctr, metrics.average_cpc
    FROM ad_group_ad
    WHERE {' AND '.join(where)}
    ORDER BY metrics.cost_micros DESC
    LIMIT {limit}
    """
    rows = []
    for batch in ga.search_stream(customer_id=customer_id, query=query):
        for r in batch.results:
            ad = r.ad_group_ad.ad
            rows.append({
                "campaign": r.campaign.name,
                "ad_group": r.ad_group.name,
                "ad_id": str(ad.id),
                "ad_type": _enum_name(ad.type_),
                "ad_strength": _enum_name(r.ad_group_ad.ad_strength),
                "status": _enum_name(r.ad_group_ad.status),
                "final_urls": list(ad.final_urls),
                "headlines": _text_assets(ad.responsive_search_ad.headlines),
                "descriptions": _text_assets(ad.responsive_search_ad.descriptions),
                "spend": r.metrics.cost_micros / 1_000_000,
                "clicks": r.metrics.clicks,
                "impressions": r.metrics.impressions,
                "conversions": r.metrics.conversions,
                "ctr": r.metrics.ctr,
                "avg_cpc": r.metrics.average_cpc / 1_000_000,
            })
    return {"location": location, "days": days, "rows": rows, "count": len(rows)}


@mcp.tool()
def query_call_assets(location: str) -> dict[str, Any]:
    """Call assets (asset.type = CALL) at both account and campaign level:
    the phone number, its enabled/paused/removed status, and — at campaign
    level — which campaign it's linked to.

    This is the tool the phone-routing audit (paid.md "Phone routing")
    needs to verify a stray or wrong number isn't still live in a paid path,
    without hand-building GAQL against the `asset` resource each run.

    `country_code` is Google's region code for the number (e.g. 'US'), not a
    dial prefix.
    """
    customer_id = _resolve(location)
    client = _ads_client(customer_id)
    ga = client.get_service("GoogleAdsService")

    account_rows = []
    query_account = """
    SELECT
      customer_asset.status,
      asset.id, asset.call_asset.phone_number, asset.call_asset.country_code
    FROM customer_asset
    WHERE asset.type = 'CALL'
    """
    for batch in ga.search_stream(customer_id=customer_id, query=query_account):
        for r in batch.results:
            account_rows.append({
                "asset_id": str(r.asset.id),
                "phone_number": r.asset.call_asset.phone_number,
                "country_code": r.asset.call_asset.country_code,
                "status": _enum_name(r.customer_asset.status),
            })

    campaign_rows = []
    query_campaign = """
    SELECT
      campaign.name, campaign_asset.status,
      asset.id, asset.call_asset.phone_number, asset.call_asset.country_code
    FROM campaign_asset
    WHERE asset.type = 'CALL'
    """
    for batch in ga.search_stream(customer_id=customer_id, query=query_campaign):
        for r in batch.results:
            campaign_rows.append({
                "campaign": r.campaign.name,
                "asset_id": str(r.asset.id),
                "phone_number": r.asset.call_asset.phone_number,
                "country_code": r.asset.call_asset.country_code,
                "status": _enum_name(r.campaign_asset.status),
            })

    return {
        "location": location,
        "account_level": account_rows,
        "campaign_level": campaign_rows,
        "count": len(account_rows) + len(campaign_rows),
    }


if __name__ == "__main__":
    mcp.run()
