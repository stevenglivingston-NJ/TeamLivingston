#!/usr/bin/env bash
# sb.sh — run SQL against the Axyom intranet Supabase (project tguwpswcneywvscxzyef)
# over curl → PostgREST → public.exec_sql(), using the service-role key.
#
# Why this exists: scheduled (non-interactive) agent runs cannot answer an MCP
# "Allow" permission prompt, so mcp__Supabase__execute_sql stalls the whole run.
# This path needs no permission and never prompts.
#
# Usage:   bash mcp-servers/sb.sh '<SQL>'
#          echo '<SQL>' | bash mcp-servers/sb.sh
# Output:  JSON array of rows for SELECT; {"ok":true} for writes returning no rows.
# Exit:    0 on success, 1 on bad usage/missing env, 2 on HTTP/SQL error.
#
# RLS note: the service-role key bypasses RLS, which is required — the anon REST
# path 401s on intranet_records and the queue tables.

set -uo pipefail

: "${SUPABASE_URL:?SUPABASE_URL is not set in this environment}"
: "${SUPABASE_SERVICE_ROLE_KEY:?SUPABASE_SERVICE_ROLE_KEY is not set in this environment}"

if [ "$#" -ge 1 ]; then
  SQL="$1"
else
  SQL="$(cat)"
fi

if [ -z "${SQL//[[:space:]]/}" ]; then
  echo "usage: sb.sh '<SQL>'   (or pipe SQL on stdin)" >&2
  exit 1
fi

# Build the JSON body with jq so quotes/newlines in the SQL are escaped correctly.
BODY="$(jq -n --arg q "$SQL" '{query: $q}')" || { echo "sb.sh: failed to encode SQL as JSON" >&2; exit 1; }

RESP_FILE="$(mktemp)"
trap 'rm -f "$RESP_FILE"' EXIT

CODE="$(curl -sS -o "$RESP_FILE" -w '%{http_code}' -X POST \
  --max-time 120 --retry 2 --retry-delay 2 --retry-connrefused \
  -H "apikey: ${SUPABASE_SERVICE_ROLE_KEY}" \
  -H "Authorization: Bearer ${SUPABASE_SERVICE_ROLE_KEY}" \
  -H "Content-Type: application/json" \
  -d "$BODY" \
  "${SUPABASE_URL%/}/rest/v1/rpc/exec_sql")" || {
    echo "sb.sh: curl failed reaching ${SUPABASE_URL%/}/rest/v1/rpc/exec_sql" >&2
    exit 2
  }

RESP="$(cat "$RESP_FILE")"

if [ "$CODE" -lt 200 ] || [ "$CODE" -ge 300 ]; then
  echo "sb.sh: HTTP $CODE" >&2
  echo "$RESP" >&2
  exit 2
fi

# A statement that returns no rows (UPDATE/INSERT/DELETE without RETURNING)
# comes back as null or []. Normalize that to {"ok":true} so callers can tell
# "write succeeded" from "select found nothing".
if [ -z "${RESP//[[:space:]]/}" ] || [ "$RESP" = "null" ]; then
  echo '{"ok":true}'
else
  echo "$RESP" | jq -c . 2>/dev/null || echo "$RESP"
fi
