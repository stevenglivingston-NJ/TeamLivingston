#!/usr/bin/env bash
# Supabase SQL helper — curl -> PostgREST rpc/exec_sql. No MCP, no permission prompt.
# Usage: sb.sh '<SQL>'
set -euo pipefail

ENV_FILE="$(dirname "${BASH_SOURCE[0]}")/.env"
if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

if [ -z "${SUPABASE_URL:-}" ] || [ -z "${SUPABASE_SERVICE_ROLE_KEY:-}" ]; then
  echo '{"error":"SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY not set"}' >&2
  exit 1
fi

if [ $# -lt 1 ]; then
  echo '{"error":"usage: sb.sh <SQL>"}' >&2
  exit 1
fi

SQL="$1"

# JSON-escape the SQL string via python3 (no jq dependency assumed).
PAYLOAD=$(python3 -c 'import json,sys; print(json.dumps({"query": sys.argv[1]}))' "$SQL")

curl -sS -X POST "$SUPABASE_URL/rest/v1/rpc/exec_sql" \
  -H "apikey: $SUPABASE_SERVICE_ROLE_KEY" \
  -H "Authorization: Bearer $SUPABASE_SERVICE_ROLE_KEY" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD"
