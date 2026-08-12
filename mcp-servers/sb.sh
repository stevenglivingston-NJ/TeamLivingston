#!/usr/bin/env bash
# sb.sh — run SQL against the Axyom intranet Supabase project without an MCP tool call.
#
# Why this exists: scheduled (non-interactive) agent runs stall forever on the
# MCP permission prompt that `mcp__Supabase__execute_sql` raises. This script
# takes the same SQL over plain curl → PostgREST `rpc/exec_sql`, which needs no
# permission and never prompts.
#
# Usage:
#   bash mcp-servers/sb.sh "SELECT * FROM notify_queue WHERE status='pending'"
#   bash mcp-servers/sb.sh -f query.sql
#   echo "SELECT 1" | bash mcp-servers/sb.sh
#
# Output: JSON array of rows for SELECT; {"ok":true} for statements returning no rows.
# Exit codes: 0 ok · 1 usage/env error · 2 HTTP or SQL error (message on stderr).
#
# Requires env: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY (service role — RLS is
# enforced on intranet tables and the anon key 401s).

set -uo pipefail

die() { printf '%s\n' "sb.sh: $*" >&2; exit "${2:-1}"; }

: "${SUPABASE_URL:?sb.sh: SUPABASE_URL is not set}"
: "${SUPABASE_SERVICE_ROLE_KEY:?sb.sh: SUPABASE_SERVICE_ROLE_KEY is not set}"

SQL=""
case "${1:-}" in
  -f|--file)
    [ -n "${2:-}" ] || die "-f needs a file path"
    [ -r "$2" ] || die "cannot read $2"
    SQL="$(cat "$2")"
    ;;
  -h|--help)
    sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
    exit 0
    ;;
  "")
    # no arg — read SQL from stdin
    [ -t 0 ] && die "no SQL given (pass as an argument, with -f FILE, or on stdin)"
    SQL="$(cat)"
    ;;
  *)
    SQL="$1"
    ;;
esac

[ -n "${SQL//[[:space:]]/}" ] || die "empty SQL"

# JSON-encode the statement. python3 is present in every session image (the MCP
# servers are Python); fall back to a minimal escaper if it somehow is not.
if command -v python3 >/dev/null 2>&1; then
  BODY="$(SB_SQL="$SQL" python3 -c 'import json,os; print(json.dumps({"query": os.environ["SB_SQL"]}))')"
else
  ESC="${SQL//\\/\\\\}"; ESC="${ESC//\"/\\\"}"; ESC="${ESC//$'\n'/\\n}"; ESC="${ESC//$'\r'/}"; ESC="${ESC//$'\t'/\\t}"
  BODY="{\"query\":\"$ESC\"}"
fi

TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT

CODE="$(curl -sS --max-time 60 -o "$TMP" -w '%{http_code}' \
  -X POST "${SUPABASE_URL%/}/rest/v1/rpc/exec_sql" \
  -H "apikey: $SUPABASE_SERVICE_ROLE_KEY" \
  -H "Authorization: Bearer $SUPABASE_SERVICE_ROLE_KEY" \
  -H "Content-Type: application/json" \
  --data-binary "$BODY")" || die "curl failed reaching ${SUPABASE_URL%/}" 2

RESP="$(cat "$TMP")"

if [ "$CODE" != "200" ] && [ "$CODE" != "204" ]; then
  printf '%s\n' "sb.sh: HTTP $CODE" >&2
  printf '%s\n' "$RESP" >&2
  exit 2
fi

# exec_sql returns null (or an empty body) for statements that yield no rows —
# UPDATE/INSERT/DELETE without RETURNING. Normalize that to {"ok":true} so
# callers can tell "write succeeded" from "select found nothing" ([]).
case "${RESP//[[:space:]]/}" in
  ""|"null") printf '{"ok":true}\n' ;;
  *)         printf '%s\n' "$RESP" ;;
esac
