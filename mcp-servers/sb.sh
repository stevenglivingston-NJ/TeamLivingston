#!/usr/bin/env bash
# Supabase SQL helper — runs raw SQL via PostgREST's rpc/exec_sql (schema "api"),
# using service-role auth so RLS never blocks it. No MCP tool, no permission prompt.
#
# Usage: bash sb.sh '<SQL>'
#   SELECT ... -> prints the JSON array of rows
#   INSERT/UPDATE/DELETE ... -> prints {"ok":true} on success
#
# Requires SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in the environment.
set -euo pipefail

if [[ -z "${1:-}" ]]; then
  echo '{"error":"usage: sb.sh <SQL>"}' >&2
  exit 1
fi

if [[ -z "${SUPABASE_URL:-}" || -z "${SUPABASE_SERVICE_ROLE_KEY:-}" ]]; then
  echo '{"error":"SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY not set in environment"}' >&2
  exit 1
fi

SQL="$1"

# Build JSON body safely with python3 (available in this image) to avoid shell-escaping bugs.
BODY=$(python3 -c 'import json,sys; print(json.dumps({"query": sys.argv[1]}))' "$SQL")

RESP=$(curl -sS -X POST "$SUPABASE_URL/rest/v1/rpc/exec_sql" \
  -H "apikey: $SUPABASE_SERVICE_ROLE_KEY" \
  -H "Authorization: Bearer $SUPABASE_SERVICE_ROLE_KEY" \
  -H "Content-Type: application/json" \
  -w '\n%{http_code}' \
  -d "$BODY")

HTTP_STATUS=$(echo "$RESP" | tail -n1)
PAYLOAD=$(echo "$RESP" | sed '$d')

if [[ "$HTTP_STATUS" -ge 200 && "$HTTP_STATUS" -lt 300 ]]; then
  echo "$PAYLOAD"
else
  echo "{\"error\":true,\"http_status\":$HTTP_STATUS,\"body\":$PAYLOAD}" >&2
  exit 1
fi
