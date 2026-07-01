"""
Google Ads + Local Services MCP server for KTU + BTU.

Two APIs wrapped in one server:
  - Google Ads API (search, display, brand, cabinet refacing, etc.) via google-ads SDK
  - Local Services API (LSA / "Google Guaranteed") via REST

Both share the same OAuth refresh token (scope: adwords).

Required env vars (set in ~/.claude/settings.json):
  GOOGLE_ADS_DEVELOPER_TOKEN  - from https://ads.google.com/aw/apicenter
  GOOGLE_ADS_CLIENT_ID        - from Google Cloud Console
  GOOGLE_ADS_CLIENT_SECRET    - from Google Cloud Console
  GOOGLE_ADS_REFRESH_TOKEN    - from `python get_refresh_token.py`
  GOOGLE_ADS_LOGIN_CUSTOMER_ID (optional) - only if you have an MCC; leave blank otherwise
"""
import os
from typing import Any
import httpx
from mcp.server.fastmcp import FastMCP
from google.ads.googleads.client import GoogleAdsClient
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

mcp = FastMCP("google-ads")

ACCOUNT_MAP: dict[str, str] = {
    "KTU": "2579406186",
    "BTU": "4477036900",
}

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


def _ads_client() -> GoogleAdsClient:
    config: dict[str, Any] = {
        "developer_token": os.environ["GOOGLE_ADS_DEVELOPER_TOKEN"],
        "refresh_token": os.environ["GOOGLE_ADS_REFRESH_TOKEN"],
        "client_id": os.environ["GOOGLE_ADS_CLIENT_ID"],
        "client_secret": os.environ["GOOGLE_ADS_CLIENT_SECRET"],
        "use_proto_plus": True,
    }
    login_id = os.environ.get("GOOGLE_ADS_LOGIN_CUSTOMER_ID", "").strip()
    if login_id:
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
    """List configured locations (KTU, BTU) and their Google Ads account IDs."""
    ok, missing = _check_env()
    return {"locations": list(ACCOUNT_MAP.keys()),
            "accounts": ACCOUNT_MAP,
            "env_complete": ok,
            "missing_env": missing}


@mcp.tool()
def test_connection(location: str) -> dict[str, Any]:
    """Smoke test: query a trivial campaign list to verify credentials."""
    customer_id = _resolve(location)
    client = _ads_client()
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
    client = _ads_client()
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
    client = _ads_client()
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
    client = _ads_client()
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
    client = _ads_client()
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
    client = _ads_client()
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
    with httpx.Client(timeout=30) as client:
        resp = client.get(url, headers=headers, params=params)
        resp.raise_for_status()
        return resp.json()


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


@mcp.tool()
def query_lsa_account(location: str, days: int = 30) -> dict[str, Any]:
    """LSA account snapshot: business name, average rating, review count,
    weekly budget, total cost current period, charged leads, phone calls."""
    mcc = _mcc_id()
    query = f"manager_customer_id:{mcc}"
    result = _lsa_query("accountReports", query)
    target_id = _resolve_lsa(location)
    reports = result.get("accountReports", [])
    matched = [r for r in reports if r.get("accountId") == target_id]
    return {
        "lsa_account_id": target_id,
        "brand": location.upper().strip(),
        "matched_count": len(matched),
        "all_accounts_in_mcc": [
            {"accountId": r.get("accountId"), "businessName": r.get("businessName")}
            for r in reports
        ],
        "report": matched[0] if matched else None,
    }


@mcp.tool()
def query_lsa_leads(location: str, days: int = 30) -> dict[str, Any]:
    """Lead-by-lead detail from LSA: type (call/message), customer name,
    job category, dispute status, charge amount."""
    from datetime import date, timedelta
    mcc = _mcc_id()
    target_id = _resolve_lsa(location)
    query = f"manager_customer_id:{mcc}"
    end = date.today()
    start = end - timedelta(days=days)
    result = _lsa_query("detailedLeadReports", query, start_date=start, end_date=end)
    leads = result.get("detailedLeadReports", [])
    brand_leads = [l for l in leads if l.get("accountId") == target_id]
    return {
        "lsa_account_id": target_id,
        "brand": location.upper().strip(),
        "date_range": {"start": start.isoformat(), "end": end.isoformat()},
        "lead_count": len(brand_leads),
        "leads": brand_leads,
        "all_brand_lead_count_in_mcc": len(leads),
    }


if __name__ == "__main__":
    mcp.run()
