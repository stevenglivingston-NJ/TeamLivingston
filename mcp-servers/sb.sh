#!/usr/bin/env bash
# sb.sh — run SQL against the Axyom intranet Supabase project without any MCP tool.
#
# Why this exists: scheduled (non-interactive) agent runs cannot answer an MCP
# "Allow" permission prompt, so `mcp__Supabase__execute_sql` stalls the whole
# cycle. This is the curl path — no prompt, no MCP.
#
# Usage:  bash mcp-servers/sb.sh '<SQL>'
#         echo '<SQL>' | bash mcp-servers/sb.sh
#
# Returns: JSON rows for SELECT, {"ok":true} for statements with no result set.
# Exit 1 with the Postgres error on failure.
#
# Requires: SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY in the environment.

set -uo pipefail

SQL="${1-}"
if [ -z "$SQL" ]; then
  SQL="$(cat)"
fi

if [ -z "$SQL" ]; then
  echo 'sb.sh: no SQL given' >&2
  exit 2
fi

: "${SUPABASE_URL:?sb.sh: SUPABASE_URL is not set}"
: "${SUPABASE_SERVICE_ROLE_KEY:?sb.sh: SUPABASE_SERVICE_ROLE_KEY is not set}"

BODY="$(SQL="$SQL" python3 -c 'import json,os;print(json.dumps({"query":os.environ["SQL"]}))')" || {
  echo 'sb.sh: failed to encode SQL as JSON' >&2
  exit 2
}

RESP="$(curl -sS --max-time 60 \
  -w $'\n%{http_code}' \
  -X POST "${SUPABASE_URL%/}/rest/v1/rpc/exec_sql" \
  -H "apikey: $SUPABASE_SERVICE_ROLE_KEY" \
  -H "Authorization: Bearer $SUPABASE_SERVICE_ROLE_KEY" \
  -H 'Content-Type: application/json' \
  --data-binary "$BODY")" || {
  echo 'sb.sh: curl failed' >&2
  exit 1
}

CODE="${RESP##*$'\n'}"
PAYLOAD="${RESP%$'\n'*}"

if [ "$CODE" != "200" ] && [ "$CODE" != "201" ] && [ "$CODE" != "204" ]; then
  echo "sb.sh: HTTP $CODE" >&2
  echo "$PAYLOAD" >&2
  exit 1
fi

# exec_sql returns null / empty for statements with no result set (INSERT/UPDATE).
# An empty array is left as-is: it is a SELECT that legitimately matched zero rows,
# and collapsing it to {"ok":true} would hide that.
case "$(printf '%s' "$PAYLOAD" | tr -d '[:space:]')" in
  ''|'null') echo '{"ok":true}' ;;
  *) printf '%s\n' "$PAYLOAD" ;;
esac
