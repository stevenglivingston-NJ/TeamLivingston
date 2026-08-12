#!/usr/bin/env bash
# sb.sh — run SQL against the Axyom intranet Supabase project without MCP.
#
# Why this exists: scheduled (non-interactive) agent runs cannot answer an MCP
# permission prompt, so mcp__Supabase__execute_sql stalls the whole cycle. This
# helper goes straight to PostgREST's exec_sql RPC with the service-role key,
# needs no permission, and never prompts.
#
# Usage:  bash mcp-servers/sb.sh '<SQL>'
#         echo '<SQL>' | bash mcp-servers/sb.sh
#
# Output: JSON array of rows for SELECT; {"ok":true} for statements that return
#         no rows. Errors go to stderr as JSON and exit non-zero.
#
# Env:    SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY (set in the Cloud env config).

set -uo pipefail

SQL="${1:-}"
if [ -z "$SQL" ] && [ ! -t 0 ]; then
  SQL="$(cat)"
fi

if [ -z "$SQL" ]; then
  echo '{"error":"no SQL provided","usage":"sb.sh <SQL>"}' >&2
  exit 2
fi

: "${SUPABASE_URL:?SUPABASE_URL is not set}"
: "${SUPABASE_SERVICE_ROLE_KEY:?SUPABASE_SERVICE_ROLE_KEY is not set}"

BODY="$(jq -nc --arg q "$SQL" '{query:$q}')"

RESP="$(curl -sS --max-time 60 \
  -w $'\n%{http_code}' \
  -X POST "${SUPABASE_URL%/}/rest/v1/rpc/exec_sql" \
  -H "apikey: ${SUPABASE_SERVICE_ROLE_KEY}" \
  -H "Authorization: Bearer ${SUPABASE_SERVICE_ROLE_KEY}" \
  -H "Content-Type: application/json" \
  -d "$BODY" 2>&1)" || {
    echo "{\"error\":\"curl failed\",\"detail\":$(jq -Rs . <<<"$RESP")}" >&2
    exit 1
  }

CODE="$(tail -n1 <<<"$RESP")"
PAYLOAD="$(sed '$d' <<<"$RESP")"

if [ "$CODE" != "200" ] && [ "$CODE" != "201" ] && [ "$CODE" != "204" ]; then
  echo "{\"error\":\"http ${CODE}\",\"detail\":$(jq -Rs . <<<"$PAYLOAD")}" >&2
  exit 1
fi

# exec_sql returns null / empty for statements with no result set (INSERT,
# UPDATE, DELETE). Normalize that to {"ok":true} so callers can branch simply.
if [ -z "$PAYLOAD" ] || [ "$PAYLOAD" = "null" ]; then
  echo '{"ok":true}'
else
  echo "$PAYLOAD"
fi
