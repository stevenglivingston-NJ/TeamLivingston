#!/usr/bin/env bash
# =============================================================================
# ghl.sh — HighLevel (LeadConnector) MCP access over curl
# -----------------------------------------------------------------------------
# Why this exists: the ghl-ktu / ghl-btu MCP servers are registered by
# bootstrap.sh, which runs from the Cloud environment's SETUP SCRIPT. When that
# setup step doesn't run (or runs after the session's tool list is built), a
# scheduled agent sees NO mcp__ghl-* tools and wrongly reports "HighLevel
# unavailable" — even though the PIT credentials are valid. That happened on the
# 2026-08-21 Foreman run: both PITs returned HTTP 200 the whole time.
#
# This helper calls the same LeadConnector MCP endpoint directly over curl, so
# agents reach HighLevel with zero dependency on MCP registration. Same approach
# as sb.sh (Supabase) and the direct ServiceMinder pull.
#
# Usage:
#   bash mcp-servers/ghl.sh <KTU|BTU> tools                  # list tool names
#   bash mcp-servers/ghl.sh <KTU|BTU> <tool> '<json-args>'   # call a tool
#
# Examples:
#   bash mcp-servers/ghl.sh KTU tools
#   bash mcp-servers/ghl.sh BTU contacts_get-contacts '{"query_limit":5}'
#   bash mcp-servers/ghl.sh KTU calendars_get-calendar-events \
#        '{"query_startTime":"2026-08-21T00:00:00Z","query_endTime":"2026-09-04T00:00:00Z"}'
#
# Requires env (set in the Cloud environment's secrets — see .env.example):
#   GHL_PIT_KTU   Private Integration Token for Kitchen Tune-Up
#   GHL_PIT_BTU   Private Integration Token for Bath Tune-Up
#
# Location IDs are pinned here to match bootstrap.sh (verified 2026-07-03 and
# re-verified 2026-08-21: KTU contacts carry source "Online/kitchentuneup.com",
# BTU contacts carry "Online/bathtune-up.com").
#
# Returns: the tool's JSON payload on stdout (the inner result, unwrapped from
# the MCP/SSE envelope). Non-zero exit + JSON {"error":...} on failure.
# =============================================================================
set -uo pipefail

BRAND="$(echo "${1:-}" | tr '[:lower:]' '[:upper:]')"
TOOL="${2:-}"
ARGS="${3:-{\}}"

case "$BRAND" in
  KTU) LOCATION_ID="nHLCxHPidnhV1NFzRtZZ"; TOKEN="${GHL_PIT_KTU:-}"; VAR="GHL_PIT_KTU" ;;
  BTU) LOCATION_ID="0uWA8M5BzHrrcJftuaDe"; TOKEN="${GHL_PIT_BTU:-}"; VAR="GHL_PIT_BTU" ;;
  *)   echo '{"error":"usage: ghl.sh <KTU|BTU> <tool|tools> [json-args]"}' >&2; exit 2 ;;
esac

if [ -z "$TOKEN" ]; then
  echo "{\"error\":\"$VAR not set in environment\"}" >&2
  exit 1
fi
if [ -z "$TOOL" ]; then
  echo '{"error":"no tool given; use `tools` to list available tool names"}' >&2
  exit 2
fi

if [ "$TOOL" = "tools" ]; then
  BODY='{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
else
  BODY=$(TOOL="$TOOL" ARGS="$ARGS" python3 -c '
import json, os, sys
try:
    args = json.loads(os.environ["ARGS"] or "{}")
except json.JSONDecodeError as e:
    print(json.dumps({"error": f"args is not valid JSON: {e}"}), file=sys.stderr); sys.exit(2)
print(json.dumps({"jsonrpc":"2.0","id":1,"method":"tools/call",
                  "params":{"name":os.environ["TOOL"],"arguments":args}}))') || exit 2
fi

RESP=$(curl -sS -X POST "https://services.leadconnectorhq.com/mcp/" \
  -H "Authorization: Bearer $TOKEN" \
  -H "locationId: $LOCATION_ID" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  --max-time 120 -d "$BODY") || {
    echo '{"error":"curl failed reaching services.leadconnectorhq.com"}' >&2; exit 1; }

# Unwrap: SSE ("data: {...}") -> JSON-RPC envelope -> MCP content -> inner JSON.
RESP="$RESP" python3 <<'PY'
import json, os, re, sys
raw = os.environ["RESP"]
m = re.search(r'^data: (\{.*)$', raw, re.M)
payload = m.group(1) if m else raw
try:
    env = json.loads(payload)
except json.JSONDecodeError:
    print(json.dumps({"error": "unparseable response", "raw": raw[:500]})); sys.exit(1)
if "error" in env:
    print(json.dumps({"error": env["error"]})); sys.exit(1)
res = env.get("result", env)
if isinstance(res, dict) and "tools" in res:
    print(json.dumps(sorted(t["name"] for t in res["tools"]), indent=1)); sys.exit(0)
content = (res or {}).get("content") or []
for blk in content:
    if blk.get("type") == "text":
        try:
            print(json.dumps(json.loads(blk["text"]), indent=1))
        except json.JSONDecodeError:
            print(blk["text"])
        sys.exit(0)
print(json.dumps(res, indent=1))
PY
