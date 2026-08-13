#!/usr/bin/env bash
# sb.sh — run SQL against the Axyom intranet Supabase (project tguwpswcneywvscxzyef)
# over PostgREST with the service-role key. No MCP, no permission prompt.
#
#   bash mcp-servers/sb.sh "SELECT * FROM notify_queue WHERE status='pending'"
#   bash mcp-servers/sb.sh "UPDATE notify_queue SET status='sent' WHERE id='...'"
#
# SELECT -> JSON array of rows. Write statements -> [] (or the RPC's result).
# Requires SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in the environment.
set -euo pipefail

SQL="${1:-}"
if [ -z "$SQL" ]; then
  echo 'usage: sb.sh "<SQL>"' >&2
  exit 2
fi

: "${SUPABASE_URL:?SUPABASE_URL is not set}"
: "${SUPABASE_SERVICE_ROLE_KEY:?SUPABASE_SERVICE_ROLE_KEY is not set}"

# JSON-encode the SQL safely (no hand-rolled escaping).
BODY=$(SQL="$SQL" python3 -c 'import json,os;print(json.dumps({"query":os.environ["SQL"]}))')

RESP=$(curl -sS --max-time 60 \
  -X POST "${SUPABASE_URL%/}/rest/v1/rpc/exec_sql" \
  -H "apikey: $SUPABASE_SERVICE_ROLE_KEY" \
  -H "Authorization: Bearer $SUPABASE_SERVICE_ROLE_KEY" \
  -H "Content-Type: application/json" \
  -w '\n%{http_code}' \
  -d "$BODY")

CODE="${RESP##*$'\n'}"
OUT="${RESP%$'\n'*}"

if [ "$CODE" != "200" ]; then
  echo "sb.sh: HTTP $CODE" >&2
  echo "$OUT" >&2
  exit 1
fi

echo "$OUT"
