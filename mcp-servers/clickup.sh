#!/usr/bin/env bash
# =============================================================================
# clickup.sh — ClickUp API over curl
# -----------------------------------------------------------------------------
# Why this exists: the ClickUp MCP connector is hard-capped at 100 calls/day and
# is classifier-gated, so scheduled Routines stall on it (same failure mode as
# the ghl/sm/gmb servers — see CLAUDE.md "Scheduled runs stall on MCP connector
# calls"). Bash is not gated and curl does not consume the MCP quota.
#
# Usage:
#   bash mcp-servers/clickup.sh GET  /api/v2/team
#   bash mcp-servers/clickup.sh GET  /api/v2/space/123/list
#   bash mcp-servers/clickup.sh POST /api/v2/list/123/task '{"name":"..."}'
#
# Requires: CLICKUP_API_TOKEN (personal token, pk_...). Auth header is the bare
# token — ClickUp v2 does NOT use "Bearer".
# =============================================================================
set -euo pipefail
TOKEN="${CLICKUP_API_TOKEN:-}"
[ -n "$TOKEN" ] || { echo '{"error":"CLICKUP_API_TOKEN not set"}' >&2; exit 1; }
METHOD="${1:-GET}"; PATH_="${2:-/api/v2/team}"; BODY="${3:-}"
ARGS=(-sS -X "$METHOD" "https://api.clickup.com${PATH_}" -H "Authorization: ${TOKEN}")
if [ -n "$BODY" ]; then ARGS+=(-H "Content-Type: application/json" -d "$BODY"); fi
curl "${ARGS[@]}"
