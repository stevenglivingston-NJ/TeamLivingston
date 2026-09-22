#!/usr/bin/env bash
# =============================================================================
# cf.sh — Cloudflare API access over curl (no MCP dependency)
# -----------------------------------------------------------------------------
# Why this exists: Tekki's §3b stack-health sweep called `mcp__cloudflare__
# list_zones` directly for its Cloudflare pipe. The doc's own instruction was
# "if it raises a permission prompt, record 🟡 and move on" — but that doesn't
# actually work: a scheduled Routine fire is non-interactive, so a permission
# prompt doesn't return a catchable error the agent can route around, it just
# blocks the whole session turn waiting for an approval nobody is present to
# give. Confirmed 2026-09-22: Tekki's daily trigger has been stuck in
# `SESSION_STATUS_REQUIRES_ACTION` on exactly this call since 2026-09-15 (7
# days), reporting `tekky_status` stale the whole time despite everything else
# in that run being fine. Same failure class as the sm.sh/ghl.sh/gmb.sh
# incidents documented in CLAUDE.md.
#
# This helper calls the Cloudflare REST API directly over curl, so agents
# reach it with zero permission-prompt risk. Same approach as sb.sh
# (Supabase), sm.sh (ServiceMinder), ghl.sh (HighLevel).
#
# Usage:
#   bash mcp-servers/cf.sh zones                     # list zones (name+status)
#   bash mcp-servers/cf.sh worker <script_name>       # get one Worker's info
#   bash mcp-servers/cf.sh workers                    # list Workers (account-scoped Workers API; often empty — Cloudflare's account-level list endpoint doesn't reliably enumerate Workers-for-Platforms-style services, use `worker <name>` for a known script instead)
#
# Requires env (already set in this Cloud environment):
#   CLOUDFLARE_API_TOKEN
#   CLOUDFLARE_ACCOUNT_ID
#
# Returns: JSON on stdout. Non-zero exit + {"error":...} on failure.
# =============================================================================
set -uo pipefail

API_BASE="https://api.cloudflare.com/client/v4"
CMD="${1:-}"

if [ -z "${CLOUDFLARE_API_TOKEN:-}" ]; then
  echo '{"error":"CLOUDFLARE_API_TOKEN not set in environment"}' >&2
  exit 1
fi

case "$CMD" in
  zones)
    curl -sS -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
      "$API_BASE/zones?per_page=50" \
      --max-time 30 || { echo '{"error":"curl failed reaching api.cloudflare.com"}' >&2; exit 1; }
    ;;
  worker)
    SCRIPT="${2:-}"
    if [ -z "$SCRIPT" ]; then echo '{"error":"usage: cf.sh worker <script_name>"}' >&2; exit 2; fi
    if [ -z "${CLOUDFLARE_ACCOUNT_ID:-}" ]; then echo '{"error":"CLOUDFLARE_ACCOUNT_ID not set"}' >&2; exit 1; fi
    curl -sS -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
      "$API_BASE/accounts/$CLOUDFLARE_ACCOUNT_ID/workers/services/$SCRIPT" \
      --max-time 30 || { echo '{"error":"curl failed reaching api.cloudflare.com"}' >&2; exit 1; }
    ;;
  workers)
    if [ -z "${CLOUDFLARE_ACCOUNT_ID:-}" ]; then echo '{"error":"CLOUDFLARE_ACCOUNT_ID not set"}' >&2; exit 1; fi
    curl -sS -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
      "$API_BASE/accounts/$CLOUDFLARE_ACCOUNT_ID/workers/scripts" \
      --max-time 30 || { echo '{"error":"curl failed reaching api.cloudflare.com"}' >&2; exit 1; }
    ;;
  *)
    echo '{"error":"usage: cf.sh <zones|worker <script_name>|workers>"}' >&2
    exit 2
    ;;
esac
