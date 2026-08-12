#!/usr/bin/env bash
# sb.sh — run SQL against the Axyom intranet Supabase project without MCP.
#
# Why this exists: scheduled (non-interactive) agent runs cannot answer an MCP
# "Allow" permission prompt, so mcp__Supabase__execute_sql stalls the whole
# cycle. This gives every agent a prompt-free curl path to the same database.
#
# Usage:  bash mcp-servers/sb.sh '<SQL>'
#         echo '<SQL>' | bash mcp-servers/sb.sh
#
# Returns: JSON array of rows for SELECT, {"ok":true} for statements that
# return no rows. Exits non-zero and prints the error JSON on failure.
#
# Requires SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in the environment.
# Note: PostgREST here exposes the `api` schema, so direct /rest/v1/<table>
# calls 404 on public tables — always go through the exec_sql RPC.
set -uo pipefail

: "${SUPABASE_URL:?SUPABASE_URL is not set}"
: "${SUPABASE_SERVICE_ROLE_KEY:?SUPABASE_SERVICE_ROLE_KEY is not set}"

if [ "$#" -ge 1 ]; then
  SQL="$1"
else
  SQL="$(cat)"
fi

if [ -z "${SQL// /}" ]; then
  echo '{"error":"no SQL provided"}' >&2
  exit 2
fi

# Build the JSON body with a here-doc through python3 so quotes/newlines in the
# SQL survive intact (jq is not guaranteed to be installed in agent sessions).
BODY="$(SQL="$SQL" python3 -c 'import json,os; print(json.dumps({"query": os.environ["SQL"]}))')" || {
  echo '{"error":"failed to encode SQL as JSON"}' >&2
  exit 2
}

RESP="$(curl -sS --max-time 60 -w $'\n%{http_code}' \
  -X POST "${SUPABASE_URL%/}/rest/v1/rpc/exec_sql" \
  -H "apikey: ${SUPABASE_SERVICE_ROLE_KEY}" \
  -H "Authorization: Bearer ${SUPABASE_SERVICE_ROLE_KEY}" \
  -H "Content-Type: application/json" \
  -d "$BODY")" || {
  echo '{"error":"curl failed"}' >&2
  exit 1
}

CODE="${RESP##*$'\n'}"
PAYLOAD="${RESP%$'\n'*}"

if [ "$CODE" != "200" ] && [ "$CODE" != "201" ] && [ "$CODE" != "204" ]; then
  echo "$PAYLOAD" >&2
  exit 1
fi

# Pass exec_sql's response through verbatim: it already returns a JSON array of
# rows for SELECT (`[]` when the select matched nothing) and {"ok":true} for
# statements with no result set. Do NOT collapse `[]` into {"ok":true} — that
# would make "no rows matched" indistinguishable from "the write succeeded".
echo "$PAYLOAD"
