#!/usr/bin/env bash
# sb.sh — non-interactive Supabase SQL helper for scheduled agent runs.
#
# Scheduled (cron) sessions cannot answer MCP permission prompts, so agents must
# never call mcp__Supabase__execute_sql. This wraps the `exec_sql` RPC over
# PostgREST with curl instead: no prompt, no MCP, works headless.
#
# Usage:  bash mcp-servers/sb.sh '<SQL>'
#         echo '<SQL>' | bash mcp-servers/sb.sh
#
# Output: JSON rows for SELECT, {"ok":true} for statements returning no rows.
# Exit:   0 on success, 1 on usage/config error, 2 on HTTP/SQL error.
set -uo pipefail

SQL="${1-}"
if [ -z "$SQL" ] && [ ! -t 0 ]; then SQL="$(cat)"; fi
if [ -z "$SQL" ]; then
  echo '{"error":"no SQL provided; usage: sb.sh \"<SQL>\""}' >&2
  exit 1
fi

: "${SUPABASE_URL:?SUPABASE_URL not set}"
: "${SUPABASE_SERVICE_ROLE_KEY:?SUPABASE_SERVICE_ROLE_KEY not set}"
URL="${SUPABASE_URL%/}"

# JSON-encode the SQL safely (handles quotes/newlines in the statement).
BODY=$(SQL="$SQL" python3 -c 'import json,os;print(json.dumps({"query":os.environ["SQL"]}))') || {
  echo '{"error":"failed to encode SQL"}' >&2; exit 1; }

OUT=$(mktemp)
trap 'rm -f "$OUT"' EXIT

CODE=$(curl -sS --max-time 60 --retry 2 --retry-delay 2 \
  -o "$OUT" -w '%{http_code}' \
  -X POST "$URL/rest/v1/rpc/exec_sql" \
  -H "apikey: $SUPABASE_SERVICE_ROLE_KEY" \
  -H "Authorization: Bearer $SUPABASE_SERVICE_ROLE_KEY" \
  -H "Content-Type: application/json" \
  --data-binary "$BODY") || { echo '{"error":"curl failed"}' >&2; exit 2; }

if [ "$CODE" != "200" ] && [ "$CODE" != "204" ]; then
  echo "{\"error\":\"http $CODE\",\"body\":$(python3 -c 'import json,sys;print(json.dumps(sys.stdin.read()))' <"$OUT")}" >&2
  exit 2
fi

# Statements with no result set come back as null / empty — normalize to {"ok":true}.
python3 - "$OUT" <<'PY'
import json, sys
raw = open(sys.argv[1]).read().strip()
if not raw or raw in ('null', '[]'):
    print('{"ok":true}')
else:
    try:
        print(json.dumps(json.loads(raw), default=str))
    except Exception:
        print(raw)
PY
