#!/usr/bin/env bash
# sb.sh — run SQL against the Axyom intranet Supabase project without MCP.
#
# Why this exists: scheduled (non-interactive) agent runs cannot answer the
# "Allow?" permission prompt that an MCP tool call raises, so any agent that
# reached Supabase via mcp__Supabase__execute_sql stalled forever. This is the
# curl path — no prompt, no MCP, safe for cron fires.
#
# Usage:  bash mcp-servers/sb.sh '<SQL>'
#         echo '<SQL>' | bash mcp-servers/sb.sh
#
# Output: JSON rows for SELECT, {"ok":true} for statements returning no rows.
# Exit:   0 on success, 1 on error (error JSON printed to stderr).
#
# Requires SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in the environment
# (set in the Cloud environment's env-var config — never committed here).

set -uo pipefail

SQL="${1:-}"
if [ -z "$SQL" ] && [ ! -t 0 ]; then
  SQL="$(cat)"
fi

if [ -z "$SQL" ]; then
  echo '{"error":"no SQL supplied"}' >&2
  exit 1
fi

if [ -z "${SUPABASE_URL:-}" ] || [ -z "${SUPABASE_SERVICE_ROLE_KEY:-}" ]; then
  echo '{"error":"SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not set in environment"}' >&2
  exit 1
fi

# Build the JSON body with python so the SQL is escaped correctly no matter
# what quoting, newlines, or jsonb literals it contains.
BODY="$(SQL="$SQL" python3 -c 'import json,os;print(json.dumps({"query":os.environ["SQL"]}))')" || {
  echo '{"error":"failed to encode SQL as JSON"}' >&2
  exit 1
}

RESP="$(curl -sS --max-time 60 -w $'\n%{http_code}' \
  -X POST "${SUPABASE_URL}/rest/v1/rpc/exec_sql" \
  -H "apikey: ${SUPABASE_SERVICE_ROLE_KEY}" \
  -H "Authorization: Bearer ${SUPABASE_SERVICE_ROLE_KEY}" \
  -H "Content-Type: application/json" \
  --data-binary "$BODY" 2>&1)" || {
  echo "{\"error\":\"curl failed\",\"detail\":$(printf '%s' "$RESP" | python3 -c 'import json,sys;print(json.dumps(sys.stdin.read()))')}" >&2
  exit 1
}

CODE="$(printf '%s' "$RESP" | tail -n1)"
PAYLOAD="$(printf '%s' "$RESP" | sed '$d')"

if [ "$CODE" != "200" ] && [ "$CODE" != "201" ] && [ "$CODE" != "204" ]; then
  echo "$PAYLOAD" >&2
  exit 1
fi

# exec_sql returns null for statements that produce no result set (INSERT/UPDATE/
# DELETE without RETURNING). A SELECT that matched nothing returns [] — keep those
# distinct, so callers can tell "write succeeded" from "query found no rows".
case "$(printf '%s' "$PAYLOAD" | tr -d '[:space:]')" in
  ""|"null") echo '{"ok":true}' ;;
  *)         echo "$PAYLOAD" ;;
esac
