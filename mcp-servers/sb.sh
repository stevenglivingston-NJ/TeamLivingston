#!/usr/bin/env bash
# sb.sh — run raw SQL against the Axyom Supabase project via PostgREST, no MCP tool
# (avoids the permission-prompt stall that mcp__Supabase__execute_sql causes in
# non-interactive scheduled runs). Requires SUPABASE_URL and
# SUPABASE_SERVICE_ROLE_KEY in the environment.
#
# Usage: bash sb.sh '<SQL>'
#   SELECT ...   -> prints the JSON array of rows returned by exec_sql
#   INSERT/UPDATE/DELETE/etc -> prints {"ok":true} on success (HTTP 2xx)
#
# On failure (non-2xx or missing env vars), prints an error JSON to stderr and
# exits non-zero — callers should check the exit code, not just parse stdout.

set -euo pipefail

SQL="${1:-}"
if [[ -z "$SQL" ]]; then
  echo '{"error":"usage: sb.sh <SQL>"}' >&2
  exit 1
fi
if [[ -z "${SUPABASE_URL:-}" || -z "${SUPABASE_SERVICE_ROLE_KEY:-}" ]]; then
  echo '{"error":"SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY not set"}' >&2
  exit 1
fi

BODY=$(python3 -c 'import json,sys; print(json.dumps({"query": sys.argv[1]}))' "$SQL")

RESP=$(curl -s -w '\n%{http_code}' -X POST "${SUPABASE_URL%/}/rest/v1/rpc/exec_sql" \
  -H "apikey: ${SUPABASE_SERVICE_ROLE_KEY}" \
  -H "Authorization: Bearer ${SUPABASE_SERVICE_ROLE_KEY}" \
  -H "Content-Type: application/json" \
  -d "$BODY")

HTTP_CODE=$(echo "$RESP" | tail -n1)
PAYLOAD=$(echo "$RESP" | sed '$d')

if [[ "$HTTP_CODE" -lt 200 || "$HTTP_CODE" -ge 300 ]]; then
  echo "$PAYLOAD" >&2
  exit 1
fi

if [[ -z "$PAYLOAD" || "$PAYLOAD" == "null" ]]; then
  echo '{"ok":true}'
else
  echo "$PAYLOAD"
fi
