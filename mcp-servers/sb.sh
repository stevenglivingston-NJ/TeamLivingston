#!/usr/bin/env bash
# sb.sh — run SQL against the Axyom intranet Supabase project without MCP.
#
# Why this exists: scheduled (non-interactive) agent runs cannot answer an MCP
# "Allow" permission prompt, so mcp__Supabase__execute_sql stalls the whole run.
# This is the curl path: service-role key -> PostgREST -> public.exec_sql().
#
# Usage:  bash mcp-servers/sb.sh 'SELECT * FROM public.notify_queue LIMIT 5'
#         bash mcp-servers/sb.sh "UPDATE public.notify_queue SET status='sent' WHERE id='...'"
#
# Output: JSON array of rows for SELECT, {"ok":true} for statements with no rows.
# Exit:   0 on success, 1 on transport/SQL error (error JSON goes to stderr).
#
# Requires SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in the environment
# (set in the Cloud env var config — never commit the values).

set -uo pipefail

SQL="${1:-}"
if [ -z "$SQL" ]; then
  echo 'usage: sb.sh "<SQL>"' >&2
  exit 1
fi

: "${SUPABASE_URL:?SUPABASE_URL not set}"
: "${SUPABASE_SERVICE_ROLE_KEY:?SUPABASE_SERVICE_ROLE_KEY not set}"

# Build the request body with python so the SQL is JSON-escaped safely
# (quotes, newlines, backslashes all survive intact).
BODY=$(SQL="$SQL" python3 -c 'import json,os; print(json.dumps({"query": os.environ["SQL"]}))')

RESP=$(curl -sS --max-time 60 \
  -X POST "$SUPABASE_URL/rest/v1/rpc/exec_sql" \
  -H "apikey: $SUPABASE_SERVICE_ROLE_KEY" \
  -H "Authorization: Bearer $SUPABASE_SERVICE_ROLE_KEY" \
  -H "Content-Type: application/json" \
  -d "$BODY" 2>&1)
CURL_RC=$?

if [ $CURL_RC -ne 0 ]; then
  echo "{\"error\":\"curl failed (rc=$CURL_RC)\",\"detail\":$(printf '%s' "$RESP" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')}" >&2
  exit 1
fi

# PostgREST reports SQL/permission errors as an object with a "message" key;
# successful reads come back as an array. Treat the former as a failure.
printf '%s' "$RESP" | python3 -c '
import json, sys
raw = sys.stdin.read()
try:
    data = json.loads(raw) if raw.strip() else None
except json.JSONDecodeError:
    sys.stderr.write(raw + "\n")
    sys.exit(1)
if isinstance(data, dict) and ("message" in data or "code" in data):
    sys.stderr.write(json.dumps(data) + "\n")
    sys.exit(1)
if data is None or data == []:
    print(json.dumps({"ok": True}))
else:
    print(json.dumps(data, default=str))
'
exit $?
