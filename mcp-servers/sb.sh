#!/usr/bin/env bash
# Supabase SQL runner via PostgREST rpc/exec_sql — curl-only, no MCP prompt.
# Usage: sb.sh '<SQL>'
set -euo pipefail

if [ -z "${1:-}" ]; then
  echo "Usage: sb.sh '<SQL>'" >&2
  exit 1
fi

if [ -z "${SUPABASE_URL:-}" ] || [ -z "${SUPABASE_SERVICE_ROLE_KEY:-}" ]; then
  echo '{"error":"SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY not set"}' >&2
  exit 1
fi

QUERY="$1"
PAYLOAD=$(python3 -c 'import json,sys; print(json.dumps({"query": sys.argv[1]}))' "$QUERY")

curl -sS -X POST "${SUPABASE_URL}/rest/v1/rpc/exec_sql" \
  -H "apikey: ${SUPABASE_SERVICE_ROLE_KEY}" \
  -H "Authorization: Bearer ${SUPABASE_SERVICE_ROLE_KEY}" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD"
