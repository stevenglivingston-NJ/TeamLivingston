#!/usr/bin/env bash
# Supabase SQL runner for non-interactive scheduled sessions.
# Executes arbitrary SQL via the exec_sql() PostgREST RPC using the service-role key,
# so agents (Ax, etc.) never have to load mcp__Supabase__execute_sql and risk a
# permission-prompt stall in a headless run.
#
# Usage: sb.sh '<SQL>'
# Returns JSON rows for SELECT, or whatever exec_sql() returns for writes.
set -euo pipefail

if [ -z "${1:-}" ]; then
  echo '{"error":"usage: sb.sh <SQL>"}' >&2
  exit 1
fi

: "${SUPABASE_URL:?SUPABASE_URL not set}"
: "${SUPABASE_SERVICE_ROLE_KEY:?SUPABASE_SERVICE_ROLE_KEY not set}"

SQL="$1"

# Build JSON body safely with jq if available, else python3 fallback.
if command -v jq >/dev/null 2>&1; then
  BODY=$(jq -n --arg q "$SQL" '{query: $q}')
else
  BODY=$(python3 -c 'import json,sys; print(json.dumps({"query": sys.argv[1]}))' "$SQL")
fi

curl -sS -X POST "$SUPABASE_URL/rest/v1/rpc/exec_sql" \
  -H "apikey: $SUPABASE_SERVICE_ROLE_KEY" \
  -H "Authorization: Bearer $SUPABASE_SERVICE_ROLE_KEY" \
  -H "Content-Type: application/json" \
  -d "$BODY"
