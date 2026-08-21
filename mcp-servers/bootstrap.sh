#!/usr/bin/env bash
# =============================================================================
# Axyom / KTU-BTU-Jatalia — MCP bootstrap
# -----------------------------------------------------------------------------
# Registers every custom stdio MCP server so that FRESH sessions (the ones the
# daily agent triggers — Goldeneye, Moola, Paid — spawn) have the direct MCP
# connections, not just the account's claude.ai connectors.
#
# Run this from the environment SETUP SCRIPT (Cloud env → Setup script). Use the
# PATH-ROBUST form below — it never exits 127 if the repo isn't at the expected
# path yet (the old `git -C /home/user/TeamLivingston …` form returned empty and
# tried `bash /mcp-servers/bootstrap.sh` → "No such file or directory" → exit 127):
#
#   for d in /home/user/TeamLivingston /workspace/TeamLivingston "$HOME/TeamLivingston"; do
#     [ -f "$d/mcp-servers/bootstrap.sh" ] && { bash "$d/mcp-servers/bootstrap.sh"; break; }
#   done
#
# (Falls through quietly if none exist yet — a later session re-runs setup.)
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

# ---- 0. Self-heal: guarantee sb.sh exists ----------------------------------
# sb.sh is the ONLY prompt-free Supabase path the scheduled agents have. A
# non-interactive fire cannot answer the "Allow?" prompt that
# mcp__Supabase__execute_sql raises, so without sb.sh the whole cycle stalls.
#
# It goes missing because every Ax/agent Routine fire is cut onto a NEW branch
# whose lineage has NO MERGE BASE with origin/main — and sb.sh only ever landed
# on main (973d508). Restoring it by hand was costing one manual repair per
# hourly fire, and any fire that died mid-repair ran blind against Supabase.
#
# This block lives INSIDE bootstrap.sh on purpose: a separate helper file would
# be just as absent on those branches as sb.sh is. bootstrap.sh predates the
# divergence, so it is present on every lineage.
#
# Order matters — this runs before the pip install so a slow/failing dep step
# can never leave the session without its database access.
ensure_sb_helper() {
  local sb="$DIR/sb.sh"
  [ -s "$sb" ] && return 0

  echo "⚠ bootstrap: mcp-servers/sb.sh missing — restoring (agents' only prompt-free Supabase path)"
  local repo; repo="$(cd "$DIR/.." && pwd)"

  # Preferred: take the real file from main so it can never drift from source.
  if git -C "$repo" rev-parse --git-dir >/dev/null 2>&1; then
    GIT_TERMINAL_PROMPT=0 timeout 60 git -C "$repo" fetch --depth 1 origin main >/dev/null 2>&1
    for ref in FETCH_HEAD origin/main; do
      if git -C "$repo" show "$ref:mcp-servers/sb.sh" > "$sb" 2>/dev/null && [ -s "$sb" ]; then
        chmod +x "$sb"
        echo "  ✓ sb.sh restored from $ref"
        return 0
      fi
    done
  fi

  # Fallback: no git / no network. Write an embedded copy so the fire still runs.
  # Keep this in sync with mcp-servers/sb.sh if that file's contract changes.
  rm -f "$sb"
  cat > "$sb" <<'SBEOF'
#!/usr/bin/env bash
# sb.sh — Supabase over curl (PostgREST rpc/exec_sql). Bash is not permission-
# gated, so scheduled fires read/write the intranet DB with no "Allow?" prompt.
# Emitted by bootstrap.sh's embedded fallback; canonical copy lives on main.
# Usage: bash mcp-servers/sb.sh 'SELECT 1'   |   echo "UPDATE …" | bash mcp-servers/sb.sh
set -euo pipefail
URL="${SUPABASE_URL:-https://tguwpswcneywvscxzyef.supabase.co}"
URL="${URL/.supabase.com/.supabase.co}"
KEY="${SUPABASE_SERVICE_ROLE_KEY:-}"
if [ -z "$KEY" ]; then
  echo '{"error":"SUPABASE_SERVICE_ROLE_KEY not set in environment"}' >&2
  exit 1
fi
SQL="${1:-}"
[ -n "$SQL" ] || SQL="$(cat)"
if command -v jq >/dev/null 2>&1; then
  BODY="$(jq -n --arg q "$SQL" '{query:$q}')"
else
  BODY="$(python3 -c 'import json,sys;print(json.dumps({"query":sys.argv[1]}))' "$SQL")"
fi
curl -sS -X POST "$URL/rest/v1/rpc/exec_sql" \
  -H "apikey: $KEY" \
  -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" \
  -d "$BODY"
SBEOF
  chmod +x "$sb"
  echo "  ✓ sb.sh restored from bootstrap's embedded fallback copy"
}
ensure_sb_helper

# ---- 1. Python deps (union of every requirements.txt) ----------------------
# NOTE: `--ignore-installed PyJWT` is required because the base image ships a
# Debian-packaged PyJWT with no RECORD file, so pip cannot uninstall it to
# satisfy google-ads' pin ("Cannot uninstall PyJWT … RECORD file not found").
# Without this the whole pip install aborts and the google-ads / gmb stdio
# servers start with missing deps and fail to register (connector flapping).
# `--break-system-packages` tolerates PEP-668 externally-managed environments.
echo "▸ Installing Python deps…"
PIP_DEPS=( "mcp[cli]>=1.2.0,<2.0.0" "httpx>=0.27.0" "google-ads>=25.0.0" "google-auth>=2.0.0" )
pip install --quiet --disable-pip-version-check --ignore-installed PyJWT "${PIP_DEPS[@]}" 2>/dev/null \
  || pip install --quiet --disable-pip-version-check --break-system-packages --ignore-installed PyJWT "${PIP_DEPS[@]}" 2>/dev/null \
  || echo "  (pip install had warnings — continuing; stdio servers may lack deps)"

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
  reg serviceminder "{\"command\":\"python3\",\"args\":[\"$DIR/serviceminder/server.py\"],\"env\":{\"SM_KEY_KTU\":\"$SM_KEY_KTU\",\"SM_KEY_BTU\":\"$SM_KEY_BTU\",\"SM_USERID_KTU\":\"${SM_USERID_KTU:-}\",\"SM_USERID_BTU\":\"${SM_USERID_BTU:-}\"}}"
else skipped+=("serviceminder (SM_KEY_KTU/SM_KEY_BTU)"); fi

if require GOOGLE_ADS_DEVELOPER_TOKEN GOOGLE_ADS_CLIENT_ID GOOGLE_ADS_CLIENT_SECRET GOOGLE_ADS_REFRESH_TOKEN; then
  reg google-ads "{\"command\":\"python3\",\"args\":[\"$DIR/google-ads/server.py\"],\"env\":{\"GOOGLE_ADS_DEVELOPER_TOKEN\":\"$GOOGLE_ADS_DEVELOPER_TOKEN\",\"GOOGLE_ADS_CLIENT_ID\":\"$GOOGLE_ADS_CLIENT_ID\",\"GOOGLE_ADS_CLIENT_SECRET\":\"$GOOGLE_ADS_CLIENT_SECRET\",\"GOOGLE_ADS_REFRESH_TOKEN\":\"$GOOGLE_ADS_REFRESH_TOKEN\",\"GOOGLE_ADS_LOGIN_CUSTOMER_ID\":\"${GOOGLE_ADS_LOGIN_CUSTOMER_ID:-}\"}}"
else skipped+=("google-ads (GOOGLE_ADS_* x4)"); fi

if require GOOGLE_ADS_CLIENT_ID GOOGLE_ADS_CLIENT_SECRET GOOGLE_ADS_REFRESH_TOKEN GMB_ACCOUNT_ID GMB_LOCATION_KTU GMB_LOCATION_BTU; then
  reg gmb "{\"command\":\"python3\",\"args\":[\"$DIR/gmb/server.py\"],\"env\":{\"GOOGLE_ADS_CLIENT_ID\":\"$GOOGLE_ADS_CLIENT_ID\",\"GOOGLE_ADS_CLIENT_SECRET\":\"$GOOGLE_ADS_CLIENT_SECRET\",\"GOOGLE_ADS_REFRESH_TOKEN\":\"$GOOGLE_ADS_REFRESH_TOKEN\",\"GMB_ACCOUNT_ID\":\"$GMB_ACCOUNT_ID\",\"GMB_LOCATION_KTU\":\"$GMB_LOCATION_KTU\",\"GMB_LOCATION_BTU\":\"$GMB_LOCATION_BTU\"}}"
else skipped+=("gmb (GMB_* + GOOGLE_ADS OAuth)"); fi

# google-analytics: direct GA4 Data API, replacing the Zapier raw-request path in
# paid.md. Deliberately requires its OWN refresh token (GA4_REFRESH_TOKEN), not
# GOOGLE_ADS_REFRESH_TOKEN — verified 2026-08-21 that token carries only
# adwords + business.manage scopes and 403s on analyticsdata.googleapis.com
# (ACCESS_TOKEN_SCOPE_INSUFFICIENT). A fresh OAuth consent for the same client
# with the added analytics.readonly scope is required; this cannot be minted
# non-interactively, so this server stays unregistered until that token exists.
if require GA4_REFRESH_TOKEN; then
  reg google-analytics "{\"command\":\"python3\",\"args\":[\"$DIR/google-analytics/server.py\"],\"env\":{\"GA4_CLIENT_ID\":\"${GA4_CLIENT_ID:-$GOOGLE_ADS_CLIENT_ID}\",\"GA4_CLIENT_SECRET\":\"${GA4_CLIENT_SECRET:-$GOOGLE_ADS_CLIENT_SECRET}\",\"GA4_REFRESH_TOKEN\":\"$GA4_REFRESH_TOKEN\",\"GA4_PROPERTY_ID_KTU\":\"${GA4_PROPERTY_ID_KTU:-}\",\"GA4_PROPERTY_ID_BTU\":\"${GA4_PROPERTY_ID_BTU:-}\"}}"
else skipped+=("google-analytics (GA4_REFRESH_TOKEN — needs a fresh OAuth consent with analytics.readonly, not the google-ads token)"); fi

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
  reg ghl-ktu "{\"type\":\"http\",\"url\":\"https://services.leadconnectorhq.com/mcp/\",\"headers\":{\"Authorization\":\"Bearer $GHL_PIT_KTU\",\"locationId\":\"nHLCxHPidnhV1NFzRtZZ\"}}"
else skipped+=("ghl-ktu (GHL_PIT_KTU)"); fi

if require GHL_PIT_BTU; then
  reg ghl-btu "{\"type\":\"http\",\"url\":\"https://services.leadconnectorhq.com/mcp/\",\"headers\":{\"Authorization\":\"Bearer $GHL_PIT_BTU\",\"locationId\":\"0uWA8M5BzHrrcJftuaDe\"}}"
else skipped+=("ghl-btu (GHL_PIT_BTU)"); fi

# ---- 4. Shared ------------------------------------------------------------

if require CLOUDFLARE_API_TOKEN CLOUDFLARE_ACCOUNT_ID; then
  reg cloudflare "{\"command\":\"python3\",\"args\":[\"$DIR/cloudflare/server.py\"],\"env\":{\"CLOUDFLARE_API_TOKEN\":\"$CLOUDFLARE_API_TOKEN\",\"CLOUDFLARE_ACCOUNT_ID\":\"$CLOUDFLARE_ACCOUNT_ID\"}}"
else skipped+=("cloudflare (CLOUDFLARE_API_TOKEN/ACCOUNT_ID)"); fi

# ---- 5. Clarity — direct live-insights + optional npm Data-Export ----------
# clarity-live: direct Python stdio MCP wrapping the Clarity live-insights
# endpoint (https://www.clarity.ms/export-data/api/v1/project-live-insights)
# for both KTU (2708513173760009) and BTU (2789761772911940). Uses the same
# CLARITY_KTU_TOKEN / CLARITY_BTU_TOKEN as the npm servers below; requires at
# least one of the two to register. Rate-limited ~10 calls/project/day (shared
# across all three clarity server variants).
if require CLARITY_KTU_TOKEN || require CLARITY_BTU_TOKEN; then
  ENV_JSON="{\"CLARITY_KTU_TOKEN\":\"${CLARITY_KTU_TOKEN:-}\",\"CLARITY_BTU_TOKEN\":\"${CLARITY_BTU_TOKEN:-}\""
  [ -n "${CLARITY_KTU_PROJECT_ID:-}" ] && ENV_JSON="$ENV_JSON,\"CLARITY_KTU_PROJECT_ID\":\"$CLARITY_KTU_PROJECT_ID\""
  [ -n "${CLARITY_BTU_PROJECT_ID:-}" ] && ENV_JSON="$ENV_JSON,\"CLARITY_BTU_PROJECT_ID\":\"$CLARITY_BTU_PROJECT_ID\""
  ENV_JSON="$ENV_JSON}"
  reg clarity-live "{\"command\":\"python3\",\"args\":[\"$DIR/clarity/server.py\"],\"env\":$ENV_JSON}"
else skipped+=("clarity-live (CLARITY_KTU_TOKEN or CLARITY_BTU_TOKEN required)"); fi

# clarity-ktu-export / clarity-btu-export: npm @microsoft/clarity-mcp-server —
# broader set of Clarity Data-Export tools (dashboard, recordings, docs).
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

# ---- 6b. Render-hosted Google Ads + LSA (HTTP transport, static bearer) ----
# The ktubtu-mcp-google-ads Render service wraps the Google Ads API — search
# campaigns / keywords / geo AND Local Services Ads (LSA) — for KTU (2579406186)
# and BTU (4477036900). The Google OAuth creds live in Render's env, so Cloud
# sessions (the paid agent) reach it here with just the service's static bearer,
# no Google creds in Cloud env. claude.ai connectors can't register it (OAuth-
# only), same as clarity/ghl. Registers under the name `google-ads`; if the stdio
# google-ads block above is ALSO configured (GOOGLE_ADS_* set) this HTTP one runs
# later and wins. Token = the service's MCP_AUTH_TOKEN (Render → service → Env).
if require GOOGLEADS_MCP_AUTH_TOKEN; then
  reg google-ads "{\"type\":\"http\",\"url\":\"https://ktubtu-mcp-google-ads.onrender.com/mcp\",\"headers\":{\"Authorization\":\"Bearer $GOOGLEADS_MCP_AUTH_TOKEN\"}}"
else skipped+=("google-ads HTTP (GOOGLEADS_MCP_AUTH_TOKEN)"); fi

# ---- summary --------------------------------------------------------------
echo ""
echo "▸ Registered (${#ok[@]}): ${ok[*]:-none}"
[ ${#skipped[@]} -gt 0 ] && echo "▸ Skipped  (${#skipped[@]}): ${skipped[*]}"
echo "▸ MCP bootstrap complete. claude.ai connectors (Gmail, HighLevel, QuickBooks,"
echo "  Bank Connection, Shopify, monday, Slack, Zapier, Facebook) load"
echo "  automatically from the account and are unaffected by this script."
exit 0
