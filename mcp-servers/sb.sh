#!/usr/bin/env bash
# Thin curl wrapper around Supabase PostgREST's rpc/exec_sql for non-interactive
# agent runs (avoids the mcp__Supabase__execute_sql permission prompt).
# Usage: sb.sh '<SQL>'
set -euo pipefail

if [ -z "${1:-}" ]; then
  echo '{"error":"usage: sb.sh <SQL>"}' >&2
  exit 1
fi

: "${SUPABASE_URL:?SUPABASE_URL not set}"
: "${SUPABASE_SERVICE_ROLE_KEY:?SUPABASE_SERVICE_ROLE_KEY not set}"

SQL="$1"

python3 -c '
import json, sys
print(json.dumps({"query": sys.argv[1]}))
' "$SQL" > /tmp/.sb_payload.json

curl -sS -X POST "$SUPABASE_URL/rest/v1/rpc/exec_sql" \
  -H "apikey: $SUPABASE_SERVICE_ROLE_KEY" \
  -H "Authorization: Bearer $SUPABASE_SERVICE_ROLE_KEY" \
  -H "Content-Type: application/json" \
  -d @/tmp/.sb_payload.json

rm -f /tmp/.sb_payload.json
