#!/usr/bin/env bash
# sb.sh — run SQL against the Axyom intranet Supabase (project tguwpswcneywvscxzyef)
# via curl → PostgREST rpc/exec_sql. No MCP, no permission prompt.
#
# Usage:  bash mcp-servers/sb.sh '<SQL>'
#         echo '<SQL>' | bash mcp-servers/sb.sh
#
# Output: JSON array of rows for SELECT, {"ok":true} for writes that return nothing.
# Exit:   0 on success, 1 on missing env/SQL, 2 on HTTP/SQL error (error JSON on stderr).
set -uo pipefail

: "${SUPABASE_URL:?SUPABASE_URL not set}"
: "${SUPABASE_SERVICE_ROLE_KEY:?SUPABASE_SERVICE_ROLE_KEY not set}"

SQL="${1-}"
if [ -z "$SQL" ]; then
  if [ ! -t 0 ]; then SQL="$(cat)"; fi
fi
if [ -z "${SQL// /}" ]; then
  echo 'usage: sb.sh "<SQL>"' >&2
  exit 1
fi

PAYLOAD="$(SQL="$SQL" python3 -c 'import json,os;print(json.dumps({"query":os.environ["SQL"]}))')" || {
  echo "sb.sh: failed to encode SQL payload" >&2; exit 1; }

TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT

CODE="$(curl -sS --max-time 60 -o "$TMP" -w '%{http_code}' \
  -X POST "$SUPABASE_URL/rest/v1/rpc/exec_sql" \
  -H "apikey: $SUPABASE_SERVICE_ROLE_KEY" \
  -H "Authorization: Bearer $SUPABASE_SERVICE_ROLE_KEY" \
  -H "Content-Type: application/json" \
  --data-binary "$PAYLOAD")" || { echo "sb.sh: curl failed" >&2; exit 2; }

BODY="$(cat "$TMP")"

if [ "$CODE" != "200" ] && [ "$CODE" != "201" ] && [ "$CODE" != "204" ]; then
  echo "sb.sh: HTTP $CODE" >&2
  echo "$BODY" >&2
  exit 2
fi

# exec_sql returns null / empty for statements with no result set (INSERT/UPDATE/DELETE)
case "${BODY//[$' \t\n\r']/}" in
  ""|"null"|"[]") echo '{"ok":true}' ;;
  *) echo "$BODY" ;;
esac
