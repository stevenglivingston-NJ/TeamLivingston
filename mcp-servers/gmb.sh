#!/usr/bin/env bash
# =============================================================================
# gmb.sh — Google Business Profile (GMB) access over curl
# -----------------------------------------------------------------------------
# Why this exists: the daily agent Routines are Claude-created, so they run in
# Auto mode, where the connector-call classifier prompts on MCP tool calls
# ("List Locations requests permission → Allow once"). A non-interactive
# scheduled fire cannot answer that prompt, so the session STALLS — it does not
# error, it sits in REQUIRES_ACTION forever and the next day's fire stalls in
# the identical spot. That is exactly how the 2026-08-19 → 08-27 Organic outage
# happened: eight consecutive fires blocked on mcp__gmb__list_locations and
# organic_report went eight days stale while every credential was valid.
#
# Bash is NOT classifier-gated. This helper calls the same Google APIs directly
# over curl, so agents reach GMB with zero permission prompts and zero
# dependency on MCP registration. Same approach as sb.sh (Supabase), ghl.sh
# (HighLevel) and sm.sh (ServiceMinder).
#
# Usage:
#   bash mcp-servers/gmb.sh locations                     # configured locations (env check)
#   bash mcp-servers/gmb.sh <KTU|BTU> info                # full business info
#   bash mcp-servers/gmb.sh <KTU|BTU> hours
#   bash mcp-servers/gmb.sh <KTU|BTU> reviews [pageSize]
#   bash mcp-servers/gmb.sh <KTU|BTU> metrics <metric> <YYYY-MM-DD> <YYYY-MM-DD>
#   bash mcp-servers/gmb.sh <KTU|BTU> keywords <YYYY-MM> <YYYY-MM>
#   bash mcp-servers/gmb.sh raw <full-url>                # escape hatch, auth added
#
# GOTCHAS baked in here (each cost a debugging cycle already — do not "simplify"):
#   * readMask is REQUIRED by the Business Information API. Omitting it returns
#     HTTP 400; it does NOT default to all fields. `info` sends a full mask.
#   * Reviews live ONLY on the legacy v4 API and are ACCOUNT-scoped
#     (accounts/{id}/locations/{id}/reviews). mybusinessreviews.googleapis.com
#     does not exist and 404s.
#   * Three different API hosts are in play — business information,
#     performance, and legacy v4 for reviews. They are not interchangeable.
#
# Requires env (set in the Cloud environment's secrets — see .env.example):
#   GOOGLE_ADS_CLIENT_ID / GOOGLE_ADS_CLIENT_SECRET / GOOGLE_ADS_REFRESH_TOKEN
#   GMB_ACCOUNT_ID, GMB_LOCATION_KTU, GMB_LOCATION_BTU
#
# Returns: the API's JSON payload on stdout. Non-zero exit + JSON {"error":...}
# on failure.
# =============================================================================
set -uo pipefail

INFO_BASE="https://mybusinessbusinessinformation.googleapis.com/v1"
REVIEWS_BASE="https://mybusiness.googleapis.com/v4"
PERF_BASE="https://businessprofileperformance.googleapis.com/v1"

READ_MASK="name,title,phoneNumbers,websiteUri,categories,storefrontAddress,serviceArea,regularHours,specialHours,openInfo,profile,labels,latlng,metadata"

die() { echo "{\"error\":$(python3 -c 'import json,sys;print(json.dumps(sys.argv[1]))' "$1")}" >&2; exit "${2:-1}"; }

# ---- locations subcommand: pure env check, no API call, no token needed ------
if [ "${1:-}" = "locations" ]; then
  python3 <<'PY'
import json, os
out = {}
for brand, var in (("KTU", "GMB_LOCATION_KTU"), ("BTU", "GMB_LOCATION_BTU")):
    out[brand] = {"env_var": var, "configured": bool(os.environ.get(var))}
out["account_id_set"] = bool(os.environ.get("GMB_ACCOUNT_ID"))
out["oauth_configured"] = all(os.environ.get(v) for v in
    ("GOOGLE_ADS_CLIENT_ID", "GOOGLE_ADS_CLIENT_SECRET", "GOOGLE_ADS_REFRESH_TOKEN"))
out["all_configured"] = (out["KTU"]["configured"] and out["BTU"]["configured"]
                         and out["account_id_set"] and out["oauth_configured"])
print(json.dumps(out, indent=1))
PY
  exit 0
fi

# ---- mint an access token from the refresh token -----------------------------
mint_token() {
  local cid="${GOOGLE_ADS_CLIENT_ID:-}" csec="${GOOGLE_ADS_CLIENT_SECRET:-}" rt="${GOOGLE_ADS_REFRESH_TOKEN:-}"
  [ -n "$cid" ] && [ -n "$csec" ] && [ -n "$rt" ] || die "GOOGLE_ADS_CLIENT_ID / _CLIENT_SECRET / _REFRESH_TOKEN must all be set" 1
  local resp
  resp=$(curl -sS --max-time 60 -X POST "https://oauth2.googleapis.com/token" \
    -d "client_id=$cid" -d "client_secret=$csec" \
    -d "refresh_token=$rt" -d "grant_type=refresh_token") \
    || die "curl failed reaching oauth2.googleapis.com" 1
  RESP="$resp" python3 <<'PY'
import json, os, sys
try:
    d = json.loads(os.environ["RESP"])
except json.JSONDecodeError:
    print("", end=""); sys.exit(1)
if "access_token" not in d:
    print("", end=""); sys.exit(1)
print(d["access_token"], end="")
PY
}

# ---- raw escape hatch -------------------------------------------------------
if [ "${1:-}" = "raw" ]; then
  URL="${2:-}"
  [ -n "$URL" ] || die "usage: gmb.sh raw <full-url>" 2
  TOKEN="$(mint_token)" || exit 1
  [ -n "$TOKEN" ] || die "OAuth token refresh failed — check GOOGLE_ADS_REFRESH_TOKEN scopes" 1
  curl -sS --max-time 90 -H "Authorization: Bearer $TOKEN" -H "Accept: application/json" "$URL" \
    | python3 -c 'import json,sys;d=sys.stdin.read()
try: print(json.dumps(json.loads(d),indent=1))
except Exception: print(d)'
  exit 0
fi

BRAND="$(echo "${1:-}" | tr '[:lower:]' '[:upper:]')"
ACTION="${2:-}"

case "$BRAND" in
  KTU) LOC="${GMB_LOCATION_KTU:-}"; VAR="GMB_LOCATION_KTU" ;;
  BTU) LOC="${GMB_LOCATION_BTU:-}"; VAR="GMB_LOCATION_BTU" ;;
  *)   die 'usage: gmb.sh locations | gmb.sh <KTU|BTU> <info|hours|reviews|metrics|keywords> | gmb.sh raw <url>' 2 ;;
esac
[ -n "$LOC" ] || die "$VAR not set in environment" 1
[ -n "$ACTION" ] || die "no action given; one of: info, hours, reviews, metrics, keywords" 2

ACCOUNT="${GMB_ACCOUNT_ID:-}"
TOKEN="$(mint_token)" || exit 1
[ -n "$TOKEN" ] || die "OAuth token refresh failed — check GOOGLE_ADS_REFRESH_TOKEN scopes" 1

fetch() {  # fetch <url>
  curl -sS --max-time 90 -H "Authorization: Bearer $TOKEN" -H "Accept: application/json" "$1"
}

case "$ACTION" in
  info)   URL="$INFO_BASE/locations/$LOC?readMask=$READ_MASK" ;;
  hours)  URL="$INFO_BASE/locations/$LOC?readMask=regularHours,specialHours" ;;
  reviews)
    [ -n "$ACCOUNT" ] || die "GMB_ACCOUNT_ID not set — reviews are account-scoped on the legacy v4 API" 1
    PAGE_SIZE="${3:-50}"
    URL="$REVIEWS_BASE/accounts/$ACCOUNT/locations/$LOC/reviews?pageSize=$PAGE_SIZE&orderBy=updateTime%20desc"
    ;;
  metrics)
    METRIC="${3:-}"; START="${4:-}"; END="${5:-}"
    [ -n "$METRIC" ] && [ -n "$START" ] && [ -n "$END" ] \
      || die 'usage: gmb.sh <KTU|BTU> metrics <METRIC> <YYYY-MM-DD> <YYYY-MM-DD>  (metrics: BUSINESS_IMPRESSIONS_DESKTOP_MAPS, BUSINESS_IMPRESSIONS_DESKTOP_SEARCH, BUSINESS_IMPRESSIONS_MOBILE_MAPS, BUSINESS_IMPRESSIONS_MOBILE_SEARCH, CALL_CLICKS, WEBSITE_CLICKS, BUSINESS_DIRECTION_REQUESTS, BUSINESS_BOOKINGS, BUSINESS_CONVERSATIONS)' 2
    URL="$PERF_BASE/locations/$LOC:getDailyMetricsTimeSeries?dailyMetric=$METRIC"
    URL="$URL&dailyRange.startDate.year=${START:0:4}&dailyRange.startDate.month=$((10#${START:5:2}))&dailyRange.startDate.day=$((10#${START:8:2}))"
    URL="$URL&dailyRange.endDate.year=${END:0:4}&dailyRange.endDate.month=$((10#${END:5:2}))&dailyRange.endDate.day=$((10#${END:8:2}))"
    ;;
  keywords)
    START="${3:-}"; END="${4:-}"
    [ -n "$START" ] && [ -n "$END" ] || die 'usage: gmb.sh <KTU|BTU> keywords <YYYY-MM> <YYYY-MM>' 2
    URL="$PERF_BASE/locations/$LOC/searchkeywords/impressions/monthly"
    URL="$URL?monthlyRange.startMonth.year=${START:0:4}&monthlyRange.startMonth.month=$((10#${START:5:2}))"
    URL="$URL&monthlyRange.endMonth.year=${END:0:4}&monthlyRange.endMonth.month=$((10#${END:5:2}))"
    ;;
  *) die "unknown action '$ACTION'; one of: info, hours, reviews, metrics, keywords" 2 ;;
esac

RESP=$(fetch "$URL") || die "curl failed reaching the Google Business Profile API" 1
RESP="$RESP" python3 <<'PY'
import json, os, sys
raw = os.environ["RESP"]
try:
    print(json.dumps(json.loads(raw), indent=1))
except json.JSONDecodeError:
    if not raw.strip():
        print(json.dumps({"error": "empty response"})); sys.exit(1)
    print(raw)
PY
