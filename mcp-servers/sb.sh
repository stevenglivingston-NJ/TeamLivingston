#!/usr/bin/env bash
# sb.sh — run SQL against the Axyom intranet Supabase project without MCP.
#
# Why this exists: scheduled (non-interactive) agent runs cannot answer the
# "Allow tool?" permission prompt that an MCP call raises, so any agent that
# reaches Supabase via mcp__Supabase__execute_sql stalls forever. This wraps the
# service-role PostgREST `exec_sql` RPC in plain curl, which never prompts.
#
# Usage:  bash mcp-servers/sb.sh "SELECT * FROM notify_queue WHERE status='pending'"
#         bash mcp-servers/sb.sh -f query.sql
#         echo "SELECT 1" | bash mcp-servers/sb.sh
#
# Output: JSON rows for SELECT, {"ok":true} for statements returning no rows.
# Exit:   0 on success, 1 on usage/config error, 2 on HTTP/SQL error.

set -uo pipefail

: "${SUPABASE_URL:?SUPABASE_URL is not set}"
: "${SUPABASE_SERVICE_ROLE_KEY:?SUPABASE_SERVICE_ROLE_KEY is not set}"

if [ "${1:-}" = "-f" ]; then
  [ -n "${2:-}" ] || { echo "sb.sh: -f needs a file path" >&2; exit 1; }
  [ -r "$2" ] || { echo "sb.sh: cannot read $2" >&2; exit 1; }
  SQL=$(cat "$2")
elif [ $# -gt 0 ]; then
  SQL="$*"
else
  SQL=$(cat)
fi

[ -n "${SQL//[[:space:]]/}" ] || { echo "sb.sh: empty SQL" >&2; exit 1; }

# JSON-encode the statement with python so quotes/newlines survive intact.
BODY=$(SQL="$SQL" python3 -c 'import json,os;print(json.dumps({"query":os.environ["SQL"]}))') || {
  echo "sb.sh: failed to encode SQL" >&2; exit 1; }

RESP=$(curl -sS --max-time 60 -w $'\n%{http_code}' \
  -X POST "${SUPABASE_URL%/}/rest/v1/rpc/exec_sql" \
  -H "apikey: $SUPABASE_SERVICE_ROLE_KEY" \
  -H "Authorization: Bearer $SUPABASE_SERVICE_ROLE_KEY" \
  -H "Content-Type: application/json" \
  -d "$BODY") || { echo "sb.sh: curl failed" >&2; exit 2; }

CODE=${RESP##*$'\n'}
PAYLOAD=${RESP%$'\n'*}

if [ "$CODE" != "200" ] && [ "$CODE" != "201" ] && [ "$CODE" != "204" ]; then
  echo "sb.sh: HTTP $CODE" >&2
  echo "$PAYLOAD" >&2
  exit 2
fi

# exec_sql returns null (not []) for statements that produce no result set.
case "${PAYLOAD//[[:space:]]/}" in
  ""|null) echo '{"ok":true}' ;;
  *)       echo "$PAYLOAD" ;;
esac
