#!/usr/bin/env bash
# Supabase SQL helper — runs arbitrary SQL against the intranet DB via the
# exec_sql PostgREST RPC (service role, no MCP permission prompt).
# Usage: sb.sh '<SQL>'
# SELECT ... -> prints JSON array of rows
# INSERT/UPDATE/DELETE -> prints {"ok":true} on 2xx HTTP status
set -euo pipefail

if [ -z "${1:-}" ]; then
  echo '{"error":"usage: sb.sh <SQL>"}' >&2
  exit 1
fi

: "${SUPABASE_URL:?SUPABASE_URL not set}"
: "${SUPABASE_SERVICE_ROLE_KEY:?SUPABASE_SERVICE_ROLE_KEY not set}"

QUERY="$1"

BODY=$(python3 -c 'import json,sys; print(json.dumps({"query": sys.argv[1]}))' "$QUERY")

RESP=$(curl -s -w '\n%{http_code}' -X POST "${SUPABASE_URL}/rest/v1/rpc/exec_sql" \
  -H "apikey: ${SUPABASE_SERVICE_ROLE_KEY}" \
  -H "Authorization: Bearer ${SUPABASE_SERVICE_ROLE_KEY}" \
  -H "Content-Type: application/json" \
  -d "$BODY")

HTTP_CODE=$(echo "$RESP" | tail -n1)
PAYLOAD=$(echo "$RESP" | sed '$d')

if [ "$HTTP_CODE" -ge 200 ] && [ "$HTTP_CODE" -lt 300 ]; then
  if [ -z "$PAYLOAD" ] || [ "$PAYLOAD" = "null" ]; then
    echo '{"ok":true}'
  else
    echo "$PAYLOAD"
  fi
else
  echo "$PAYLOAD" >&2
  exit 1
fi
