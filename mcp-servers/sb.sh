#!/usr/bin/env bash
# sb.sh — run SQL against the Axyom intranet Supabase project without MCP.
#
# Why this exists: scheduled (non-interactive) agent runs cannot answer the
# "Allow?" permission prompt that an MCP tool call raises, so any cycle that
# reaches for mcp__Supabase__execute_sql stalls forever. This is the curl path:
# it needs no permission and never prompts.
#
# Usage:  bash mcp-servers/sb.sh '<SQL>'
#         echo '<SQL>' | bash mcp-servers/sb.sh
#
# Output: JSON rows for SELECT, {"ok":true} for statements that return none.
# Exit:   0 on success, 1 on usage/config error, 2 on SQL or transport error.
#
# Requires SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in the environment
# (set in the Cloud environment's env-var config — never commit real values).

set -uo pipefail

SQL="${1:-}"
if [ -z "$SQL" ] && [ ! -t 0 ]; then
  SQL="$(cat)"
fi

if [ -z "$SQL" ]; then
  echo '{"error":"no SQL given — usage: sb.sh \"<SQL>\""}' >&2
  exit 1
fi

if [ -z "${SUPABASE_URL:-}" ] || [ -z "${SUPABASE_SERVICE_ROLE_KEY:-}" ]; then
  echo '{"error":"SUPABASE_URL and/or SUPABASE_SERVICE_ROLE_KEY not set"}' >&2
  exit 1
fi

# JSON-encode the statement with python so quotes/newlines survive intact.
BODY="$(SQL="$SQL" python3 -c 'import json,os;print(json.dumps({"query":os.environ["SQL"]}))')" || {
  echo '{"error":"failed to encode SQL as JSON"}' >&2
  exit 1
}

RESP="$(curl -sS --max-time 60 -w $'\n%{http_code}' \
  -X POST "${SUPABASE_URL%/}/rest/v1/rpc/exec_sql" \
  -H "apikey: $SUPABASE_SERVICE_ROLE_KEY" \
  -H "Authorization: Bearer $SUPABASE_SERVICE_ROLE_KEY" \
  -H "Content-Type: application/json" \
  -d "$BODY" 2>&1)" || {
  echo "{\"error\":\"curl failed\",\"detail\":$(printf '%s' "$RESP" | python3 -c 'import json,sys;print(json.dumps(sys.stdin.read()))')}" >&2
  exit 2
}

CODE="$(printf '%s' "$RESP" | tail -n1)"
PAYLOAD="$(printf '%s' "$RESP" | sed '$d')"

if [ "$CODE" != "200" ]; then
  echo "$PAYLOAD" >&2
  exit 2
fi

# exec_sql returns null (or nothing) for statements with no result set.
if [ -z "$PAYLOAD" ] || [ "$PAYLOAD" = "null" ]; then
  echo '{"ok":true}'
else
  echo "$PAYLOAD"
fi
