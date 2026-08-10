#!/usr/bin/env bash
# sb.sh — run raw SQL against the Axyom Supabase project via PostgREST's exec_sql RPC.
# Usage: bash sb.sh '<SQL>'
# SELECT statements return the JSON row array from exec_sql.
# Writes (INSERT/UPDATE/DELETE) return whatever exec_sql yields for them (commonly []),
# so callers should treat a non-error HTTP response as success rather than parsing rows.
# Requires SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in the environment (service role —
# the anon REST path 401s on these tables).
set -euo pipefail

if [ -z "${1:-}" ]; then
  echo '{"error":"usage: sb.sh <SQL>"}' >&2
  exit 1
fi

if [ -z "${SUPABASE_URL:-}" ] || [ -z "${SUPABASE_SERVICE_ROLE_KEY:-}" ]; then
  echo '{"error":"SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY not set in environment"}' >&2
  exit 1
fi

QUERY="$1"

PAYLOAD=$(python3 -c 'import json,sys; print(json.dumps({"query": sys.argv[1]}))' "$QUERY")

HTTP_STATUS=$(curl -s -o /tmp/sb_sh_response.json -w "%{http_code}" \
  -X POST "$SUPABASE_URL/rest/v1/rpc/exec_sql" \
  -H "apikey: $SUPABASE_SERVICE_ROLE_KEY" \
  -H "Authorization: Bearer $SUPABASE_SERVICE_ROLE_KEY" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD")

BODY=$(cat /tmp/sb_sh_response.json)
rm -f /tmp/sb_sh_response.json

if [ "$HTTP_STATUS" -ge 200 ] && [ "$HTTP_STATUS" -lt 300 ]; then
  echo "$BODY"
else
  echo "{\"error\":\"HTTP $HTTP_STATUS\",\"body\":$BODY}" >&2
  exit 1
fi
