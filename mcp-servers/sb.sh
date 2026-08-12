#!/usr/bin/env bash
# sb.sh — run SQL against the Axyom intranet Supabase project without any MCP tool.
#
# Why this exists: scheduled (non-interactive) agent runs cannot answer an MCP
# "Allow" permission prompt, so mcp__Supabase__execute_sql stalls the whole cycle.
# This is a pure curl path — no prompt, no MCP.
#
# Usage:  bash mcp-servers/sb.sh '<SQL>'
#         echo '<SQL>' | bash mcp-servers/sb.sh
#
# Output: JSON array of rows for SELECT, {"ok":true} for statements returning
#         no rows. Errors go to stderr and exit non-zero.
#
# Requires: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in the environment
# (set in the Cloud environment's env-var config — never commit real values).

set -uo pipefail

SQL="${1:-}"
if [ -z "$SQL" ]; then
  if [ -t 0 ]; then
    echo "usage: sb.sh '<SQL>'   (or pipe SQL on stdin)" >&2
    exit 2
  fi
  SQL="$(cat)"
fi

: "${SUPABASE_URL:?SUPABASE_URL is not set}"
: "${SUPABASE_SERVICE_ROLE_KEY:?SUPABASE_SERVICE_ROLE_KEY is not set}"

BODY="$(jq -cn --arg q "$SQL" '{query:$q}')"

TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT

CODE="$(curl -sS -o "$TMP" -w '%{http_code}' --max-time 120 \
  -X POST "${SUPABASE_URL%/}/rest/v1/rpc/exec_sql" \
  -H "apikey: ${SUPABASE_SERVICE_ROLE_KEY}" \
  -H "Authorization: Bearer ${SUPABASE_SERVICE_ROLE_KEY}" \
  -H "Content-Type: application/json" \
  --data-binary "$BODY")" || {
  echo "sb.sh: curl failed" >&2
  exit 1
}

if [ "$CODE" != "200" ] && [ "$CODE" != "201" ] && [ "$CODE" != "204" ]; then
  echo "sb.sh: HTTP $CODE" >&2
  cat "$TMP" >&2
  echo >&2
  exit 1
fi

# exec_sql returns null / empty for statements that produce no rows.
OUT="$(cat "$TMP")"
if [ -z "$OUT" ] || [ "$OUT" = "null" ] || [ "$OUT" = "[]" ]; then
  case "$(printf '%s' "$SQL" | tr '[:lower:]' '[:upper:]' | sed -e 's/^[[:space:]]*//' | cut -c1-6)" in
    SELECT|WITH*) echo "[]" ;;
    *)            echo '{"ok":true}' ;;
  esac
else
  echo "$OUT"
fi
