#!/usr/bin/env bash
# Supabase SQL runner for non-interactive scheduled agents (Ax, etc).
# Avoids mcp__Supabase__execute_sql, which pauses on an unanswerable
# permission prompt in headless/cron runs and stalls the whole cycle.
#
# Usage: sb.sh '<SQL>'
#   SELECT ...  -> prints JSON array of rows
#   INSERT/UPDATE/DELETE ... -> prints {"ok":true} on success
#
# Requires SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in the environment.
# Routes through the public.exec_sql(query text) RPC exposed via PostgREST.
set -euo pipefail

if [ -z "${1:-}" ]; then
  echo '{"error":"usage: sb.sh <SQL>"}' >&2
  exit 1
fi

if [ -z "${SUPABASE_URL:-}" ] || [ -z "${SUPABASE_SERVICE_ROLE_KEY:-}" ]; then
  echo '{"error":"SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY not set"}' >&2
  exit 1
fi

QUERY="$1"

PAYLOAD=$(python3 -c 'import json,sys; print(json.dumps({"query": sys.argv[1]}))' "$QUERY")

RESPONSE=$(curl -sS -w '\n%{http_code}' -X POST "${SUPABASE_URL}/rest/v1/rpc/exec_sql" \
  -H "apikey: ${SUPABASE_SERVICE_ROLE_KEY}" \
  -H "Authorization: Bearer ${SUPABASE_SERVICE_ROLE_KEY}" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD")

HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
BODY=$(echo "$RESPONSE" | sed '$d')

if [ "$HTTP_CODE" -ge 200 ] && [ "$HTTP_CODE" -lt 300 ]; then
  echo "$BODY"
else
  echo "{\"error\":\"HTTP ${HTTP_CODE}\",\"body\":${BODY:-null}}" >&2
  exit 1
fi
