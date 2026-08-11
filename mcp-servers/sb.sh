#!/usr/bin/env bash
# sb.sh — run SQL against Supabase via PostgREST's /rpc/exec_sql style bridge.
# Usage: sb.sh '<SQL>'
# Requires SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in the environment.
# Returns JSON rows for SELECT, or the function's own result for writes.
set -euo pipefail

if [ -z "${SUPABASE_URL:-}" ] || [ -z "${SUPABASE_SERVICE_ROLE_KEY:-}" ]; then
  echo '{"error":"SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY not set"}' >&2
  exit 1
fi

SQL="${1:-}"
if [ -z "$SQL" ]; then
  echo '{"error":"usage: sb.sh <SQL>"}' >&2
  exit 1
fi

# Requires a Postgres function `exec_sql(query text)` exposed via PostgREST
# (SECURITY DEFINER, returns jsonb) callable at /rpc/exec_sql.
PAYLOAD=$(python3 -c 'import json,sys; print(json.dumps({"query": sys.argv[1]}))' "$SQL")

curl -sS -X POST "${SUPABASE_URL%/}/rest/v1/rpc/exec_sql" \
  -H "apikey: ${SUPABASE_SERVICE_ROLE_KEY}" \
  -H "Authorization: Bearer ${SUPABASE_SERVICE_ROLE_KEY}" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD"
