#!/usr/bin/env bash
# =============================================================================
# Axyom / KTU-BTU-Jatalia — MCP bootstrap
# -----------------------------------------------------------------------------
# Registers every custom stdio MCP server so that FRESH sessions (the ones the
# daily agent triggers — Goldeneye, Moola, Paid — spawn) have the direct MCP
# connections, not just the account's claude.ai connectors.
#
# Run this from the environment SETUP SCRIPT (Cloud env → Setup script):
#     bash "$(git -C /home/user/TeamLivingston rev-parse --show-toplevel)/mcp-servers/bootstrap.sh"
# or, if the repo lives elsewhere, just point at this file directly.
#
# SECRETS: this script reads all API keys from ENVIRONMENT VARIABLES. No key is
# ever stored in the repo. Set the vars in the Cloud environment's env-var
# config (see mcp-servers/.env.example for the full list). A server whose
# required vars are missing is SKIPPED with a warning — never registered blank.
#
# Idempotent: safe to run on every session start (remove-then-add per server).
# =============================================================================
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "▸ MCP bootstrap — server dir: $DIR"

# ---- 1. Python deps (union of every requirements.txt) ----------------------
echo "▸ Installing Python deps…"
pip install --quiet --disable-pip-version-check \
  "mcp[cli]>=1.2.0" "httpx>=0.27.0" "google-ads>=25.0.0" "google-auth>=2.0.0" \
  2>/dev/null || echo "  (pip install had warnings — continuing)"

# ---- helpers ---------------------------------------------------------------
ok=(); skipped=()

# require VARS... : returns 0 if all named env vars are non-empty
require() { for v in "$@"; do [ -z "${!v:-}" ] && return 1; done; return 0; }

# reg NAME JSON : (re)register a user-scope stdio MCP server
reg() {
  local name="$1" json="$2"
  claude mcp remove --scope user "$name" >/dev/null 2>&1
  if claude mcp add-json --scope user "$name" "$json" >/dev/null 2>&1; then
    ok+=("$name")
  else
    skipped+=("$name (registration error)")
  fi
}

# ---- 2. KTU / BTU servers --------------------------------------------------

if require CLOSEBOT_API_KEY; then
  reg closebot "{\"command\":\"python3\",\"args\":[\"$DIR/closebot/server.py\"],\"env\":{\"CLOSEBOT_API_KEY\":\"$CLOSEBOT_API_KEY\"}}"
else skipped+=("closebot (CLOSEBOT_API_KEY)"); fi

if require COMPANYCAM_TOKEN; then
  reg companycam "{\"command\":\"python3\",\"args\":[\"$DIR/companycam/server.py\"],\"env\":{\"COMPANYCAM_TOKEN\":\"$COMPANYCAM_TOKEN\"}}"
else skipped+=("companycam (COMPANYCAM_TOKEN)"); fi

if require SM_KEY_KTU SM_KEY_BTU; then
  reg serviceminder "{\"command\":\"python3\",\"args\":[\"$DIR/serviceminder/server.py\"],\"env\":{\"SM_KEY_KTU\":\"$SM_KEY_KTU\",\"SM_KEY_BTU\":\"$SM_KEY_BTU\"}}"
else skipped+=("serviceminder (SM_KEY_KTU/SM_KEY_BTU)"); fi

if require GOOGLE_ADS_DEVELOPER_TOKEN GOOGLE_ADS_CLIENT_ID GOOGLE_ADS_CLIENT_SECRET GOOGLE_ADS_REFRESH_TOKEN; then
  reg google-ads "{\"command\":\"python3\",\"args\":[\"$DIR/google-ads/server.py\"],\"env\":{\"GOOGLE_ADS_DEVELOPER_TOKEN\":\"$GOOGLE_ADS_DEVELOPER_TOKEN\",\"GOOGLE_ADS_CLIENT_ID\":\"$GOOGLE_ADS_CLIENT_ID\",\"GOOGLE_ADS_CLIENT_SECRET\":\"$GOOGLE_ADS_CLIENT_SECRET\",\"GOOGLE_ADS_REFRESH_TOKEN\":\"$GOOGLE_ADS_REFRESH_TOKEN\"}}"
else skipped+=("google-ads (GOOGLE_ADS_* x4)"); fi

if require GOOGLE_ADS_CLIENT_ID GOOGLE_ADS_CLIENT_SECRET GOOGLE_ADS_REFRESH_TOKEN GMB_ACCOUNT_ID GMB_LOCATION_KTU GMB_LOCATION_BTU; then
  reg gmb "{\"command\":\"python3\",\"args\":[\"$DIR/gmb/server.py\"],\"env\":{\"GOOGLE_ADS_CLIENT_ID\":\"$GOOGLE_ADS_CLIENT_ID\",\"GOOGLE_ADS_CLIENT_SECRET\":\"$GOOGLE_ADS_CLIENT_SECRET\",\"GOOGLE_ADS_REFRESH_TOKEN\":\"$GOOGLE_ADS_REFRESH_TOKEN\",\"GMB_ACCOUNT_ID\":\"$GMB_ACCOUNT_ID\",\"GMB_LOCATION_KTU\":\"$GMB_LOCATION_KTU\",\"GMB_LOCATION_BTU\":\"$GMB_LOCATION_BTU\"}}"
else skipped+=("gmb (GMB_* + GOOGLE_ADS OAuth)"); fi

# ---- 3. Jatalia / Earthwise servers ---------------------------------------

if require SHIPSTATION_API_KEY; then
  reg shipstation "{\"command\":\"python3\",\"args\":[\"$DIR/shipstation/server.py\"],\"env\":{\"SHIPSTATION_API_KEY\":\"$SHIPSTATION_API_KEY\"}}"
else skipped+=("shipstation (SHIPSTATION_API_KEY)"); fi

if require AMAZON_SP_CLIENT_ID AMAZON_SP_CLIENT_SECRET AMAZON_SP_REFRESH_TOKEN; then
  reg amazon-sp "{\"command\":\"python3\",\"args\":[\"$DIR/amazon-sp/server.py\"],\"env\":{\"AMAZON_SP_CLIENT_ID\":\"$AMAZON_SP_CLIENT_ID\",\"AMAZON_SP_CLIENT_SECRET\":\"$AMAZON_SP_CLIENT_SECRET\",\"AMAZON_SP_REFRESH_TOKEN\":\"$AMAZON_SP_REFRESH_TOKEN\"}}"
else skipped+=("amazon-sp (AMAZON_SP_* x3)"); fi

# ---- 3b. HighLevel direct MCP (HTTP transport, PIT auth) -------------------
# LeadConnector's hosted MCP endpoint, scoped per sub-account by locationId
# header. Location IDs are public identifiers; the PITs are SECRETS (env vars,
# full value including the "pit-" prefix). Verified 2026-07-03: KTU PIT returns
# Kitchen Tune-Up, BTU PIT returns Bath Tune-Up.

if require GHL_PIT_KTU; then
  reg ghl-ktu "{\"type\":\"http\",\"url\":\"https://services.leadconnectorhq.com/mcp/\",\"headers\":{\"Authorization\":\"$GHL_PIT_KTU\",\"locationId\":\"nHLCxHPidnhV1NFzRtZZ\"}}"
else skipped+=("ghl-ktu (GHL_PIT_KTU)"); fi

if require GHL_PIT_BTU; then
  reg ghl-btu "{\"type\":\"http\",\"url\":\"https://services.leadconnectorhq.com/mcp/\",\"headers\":{\"Authorization\":\"$GHL_PIT_BTU\",\"locationId\":\"0uWA8M5BzHrrcJftuaDe\"}}"
else skipped+=("ghl-btu (GHL_PIT_BTU)"); fi

# ---- 4. Shared ------------------------------------------------------------

if require CLOUDFLARE_API_TOKEN CLOUDFLARE_ACCOUNT_ID; then
  reg cloudflare "{\"command\":\"python3\",\"args\":[\"$DIR/cloudflare/server.py\"],\"env\":{\"CLOUDFLARE_API_TOKEN\":\"$CLOUDFLARE_API_TOKEN\",\"CLOUDFLARE_ACCOUNT_ID\":\"$CLOUDFLARE_ACCOUNT_ID\"}}"
else skipped+=("cloudflare (CLOUDFLARE_API_TOKEN/ACCOUNT_ID)"); fi

# ---- 5. Optional Clarity Data-Export (npm) --------------------------------
# Rate-limited ~10 calls/project/day — agents call sparingly.
if require CLARITY_KTU_TOKEN; then
  reg clarity-ktu-export "{\"command\":\"npx\",\"args\":[\"-y\",\"@microsoft/clarity-mcp-server\"],\"env\":{\"CLARITY_API_TOKEN\":\"$CLARITY_KTU_TOKEN\"}}"
else skipped+=("clarity-ktu-export (CLARITY_KTU_TOKEN)"); fi
if require CLARITY_BTU_TOKEN; then
  reg clarity-btu-export "{\"command\":\"npx\",\"args\":[\"-y\",\"@microsoft/clarity-mcp-server\"],\"env\":{\"CLARITY_API_TOKEN\":\"$CLARITY_BTU_TOKEN\"}}"
else skipped+=("clarity-btu-export (CLARITY_BTU_TOKEN)"); fi

# ---- 6. Render-hosted Clarity Data-Export (HTTP transport, static bearer) --
# The ktubtu-mcp-clarity Render service wraps Clarity's Data-Export API for BOTH
# projects (KTU + BTU) with the landing-page-experience / traffic-by-channel
# tools the paid agent uses. claude.ai connectors CANNOT register it (they force
# an OAuth sign-in; the service uses a static bearer token), so Cloud sessions
# reach it directly here — same static-header pattern as the ghl-* servers.
# Token = the service's auto-generated MCP_AUTH_TOKEN (Render → ktubtu-mcp-clarity
# → Environment). Free instance cold-starts ~50s after idle; agents budget calls.
if require CLARITY_MCP_AUTH_TOKEN; then
  reg clarity "{\"type\":\"http\",\"url\":\"https://ktubtu-mcp-clarity.onrender.com/mcp\",\"headers\":{\"Authorization\":\"Bearer $CLARITY_MCP_AUTH_TOKEN\"}}"
else skipped+=("clarity (CLARITY_MCP_AUTH_TOKEN)"); fi

# ---- summary --------------------------------------------------------------
echo ""
echo "▸ Registered (${#ok[@]}): ${ok[*]:-none}"
[ ${#skipped[@]} -gt 0 ] && echo "▸ Skipped  (${#skipped[@]}): ${skipped[*]}"
echo "▸ MCP bootstrap complete. claude.ai connectors (Gmail, HighLevel, QuickBooks,"
echo "  Bank Connection, Shopify, monday, Slack, Zapier, Facebook) load"
echo "  automatically from the account and are unaffected by this script."
exit 0
