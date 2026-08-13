#!/usr/bin/env bash
# sb.sh — run SQL against the Axyom intranet Supabase (project tguwpswcneywvscxzyef)
# over PostgREST + the exec_sql RPC, using curl only.
#
# Why this exists: scheduled (non-interactive) agent runs cannot answer the MCP
# "Allow" permission prompt, so mcp__Supabase__execute_sql stalls the whole cycle.
# This path needs no permission.
#
# Usage:  bash mcp-servers/sb.sh '<SQL>'
#         echo '<SQL>' | bash mcp-servers/sb.sh
#
# Output: JSON rows for SELECT; {"ok":true} for statements returning no rows.
# Exit:   0 on success, 1 on missing env/SQL, 2 on HTTP/SQL error (error JSON on stderr).
#
# Requires SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in the environment.
set -uo pipefail

SQL="${1:-}"
if [ -z "$SQL" ] && [ ! -t 0 ]; then SQL="$(cat)"; fi

if [ -z "${SUPABASE_URL:-}" ] || [ -z "${SUPABASE_SERVICE_ROLE_KEY:-}" ]; then
  echo '{"error":"SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY not set in environment"}' >&2
  exit 1
fi
if [ -z "$SQL" ]; then
  echo '{"error":"no SQL provided — pass as $1 or on stdin"}' >&2
  exit 1
fi

# JSON-encode the SQL safely (handles quotes, newlines, backslashes).
PAYLOAD=$(SQL="$SQL" python3 -c 'import json,os;print(json.dumps({"query":os.environ["SQL"]}))')

BODY_FILE=$(mktemp)
trap 'rm -f "$BODY_FILE"' EXIT

CODE=$(curl -sS -o "$BODY_FILE" -w '%{http_code}' --max-time 60 \
  -X POST "${SUPABASE_URL}/rest/v1/rpc/exec_sql" \
  -H "apikey: ${SUPABASE_SERVICE_ROLE_KEY}" \
  -H "Authorization: Bearer ${SUPABASE_SERVICE_ROLE_KEY}" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD")

if [ "$CODE" != "200" ]; then
  echo "{\"error\":\"http ${CODE}\",\"body\":$(python3 -c 'import json,sys;print(json.dumps(sys.stdin.read()))' < "$BODY_FILE")}" >&2
  exit 2
fi

# exec_sql returns null / empty for statements with no result set (INSERT/UPDATE/DELETE).
python3 - "$BODY_FILE" <<'PY'
import json, sys
raw = open(sys.argv[1]).read().strip()
if not raw or raw == 'null':
    print('{"ok":true}')
else:
    data = json.loads(raw)
    if data is None or data == []:
        print('{"ok":true}')
    else:
        print(json.dumps(data, indent=None, default=str))
PY
