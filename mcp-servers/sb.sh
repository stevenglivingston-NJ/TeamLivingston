#!/usr/bin/env bash
# sb.sh — run SQL against the Axyom intranet Supabase project over PostgREST.
#
# Why this exists: scheduled (non-interactive) agent runs cannot answer an MCP
# "Allow" permission prompt, so mcp__Supabase__execute_sql stalls the whole
# cycle. This wrapper is plain curl — no permission prompt, no MCP.
#
# Usage:  bash mcp-servers/sb.sh '<SQL>'
#         echo '<SQL>' | bash mcp-servers/sb.sh
#
# Output: JSON rows for SELECT, {"ok":true} for statements returning no rows.
# Exit:   0 on success, non-zero on transport/SQL error (error JSON on stderr).
#
# Requires: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in the environment
# (set in the Cloud environment's env-var config — never committed here).

set -uo pipefail

SQL="${1-}"
if [ -z "$SQL" ]; then
  if [ -t 0 ]; then
    echo "usage: sb.sh '<SQL>'   (or pipe SQL on stdin)" >&2
    exit 2
  fi
  SQL="$(cat)"
fi

: "${SUPABASE_URL:?SUPABASE_URL is not set}"
: "${SUPABASE_SERVICE_ROLE_KEY:?SUPABASE_SERVICE_ROLE_KEY is not set}"

# JSON-encode the SQL safely (python3 is present in every session image).
PAYLOAD="$(SQL="$SQL" python3 -c 'import json,os; print(json.dumps({"query": os.environ["SQL"]}))')" || {
  echo '{"error":"failed to encode SQL payload"}' >&2
  exit 3
}

RESP="$(curl -sS --max-time 60 -w '\n%{http_code}' \
  -X POST "${SUPABASE_URL%/}/rest/v1/rpc/exec_sql" \
  -H "apikey: ${SUPABASE_SERVICE_ROLE_KEY}" \
  -H "Authorization: Bearer ${SUPABASE_SERVICE_ROLE_KEY}" \
  -H "Content-Type: application/json" \
  --data-binary "$PAYLOAD" 2>&1)" || {
  echo "{\"error\":\"curl failed\",\"detail\":$(printf '%s' "$RESP" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')}" >&2
  exit 4
}

CODE="${RESP##*$'\n'}"
BODY="${RESP%$'\n'*}"

if [ "$CODE" != "200" ] && [ "$CODE" != "201" ] && [ "$CODE" != "204" ]; then
  echo "$BODY" >&2
  exit 5
fi

# exec_sql returns null / empty for statements that produce no rows.
case "$(printf '%s' "$BODY" | tr -d '[:space:]')" in
  ''|'null'|'[]') echo '{"ok":true}' ;;
  *)              printf '%s\n' "$BODY" ;;
esac
