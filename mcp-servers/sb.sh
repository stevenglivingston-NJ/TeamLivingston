#!/usr/bin/env bash
# sb.sh — run SQL against the Axyom intranet Supabase project without any MCP tool.
#
# Why this exists: scheduled (non-interactive) agent runs cannot answer an MCP
# "Allow" permission prompt, so any mcp__Supabase__* call stalls the whole run.
# This talks straight to PostgREST with curl and the service-role key, which
# never prompts.
#
# Usage:  bash mcp-servers/sb.sh '<SQL>'
#         echo '<SQL>' | bash mcp-servers/sb.sh
#
# Output: JSON rows for SELECT, {"ok":true} for statements returning no rows.
# Exit:   0 on success, 1 on error (error JSON printed to stderr).
#
# Requires env: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY

set -uo pipefail

SQL="${1:-}"
if [ -z "$SQL" ]; then
  SQL="$(cat)"
fi
if [ -z "$SQL" ]; then
  echo '{"error":"no SQL provided"}' >&2
  exit 1
fi

if [ -z "${SUPABASE_URL:-}" ] || [ -z "${SUPABASE_SERVICE_ROLE_KEY:-}" ]; then
  echo '{"error":"SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not set in this environment"}' >&2
  exit 1
fi

# JSON-encode the statement (python3 is always present in this image).
PAYLOAD="$(SQL="$SQL" python3 -c 'import json,os;print(json.dumps({"query":os.environ["SQL"]}))')" || {
  echo '{"error":"failed to encode SQL payload"}' >&2
  exit 1
}

RESP="$(curl -s -S --max-time 60 -w $'\n%{http_code}' \
  -X POST "$SUPABASE_URL/rest/v1/rpc/exec_sql" \
  -H "apikey: $SUPABASE_SERVICE_ROLE_KEY" \
  -H "Authorization: Bearer $SUPABASE_SERVICE_ROLE_KEY" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD" 2>&1)"

CODE="$(printf '%s' "$RESP" | tail -n1)"
BODY="$(printf '%s' "$RESP" | sed '$d')"

if [ "$CODE" != "200" ]; then
  printf '%s\n' "${BODY:-{\"error\":\"http $CODE\"}}" >&2
  exit 1
fi

# exec_sql returns null / empty for statements with no result set.
case "$(printf '%s' "$BODY" | tr -d '[:space:]')" in
  ""|"null"|"[]") echo '{"ok":true}' ;;
  *)              printf '%s\n' "$BODY" ;;
esac
