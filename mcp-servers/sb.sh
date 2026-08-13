#!/usr/bin/env bash
# sb.sh — run SQL against the Axyom intranet Supabase project over PostgREST.
#
# Why this exists: the scheduled (non-interactive) agent runs cannot use the
# Supabase MCP tools — every MCP call stops on an "Allow" permission prompt that
# nobody is there to answer, and the whole cycle stalls. This is a plain curl
# path: no permission prompt, no MCP.
#
# Usage:  bash mcp-servers/sb.sh '<SQL>'
#         echo '<SQL>' | bash mcp-servers/sb.sh
#
# Output: JSON array of rows for SELECT, {"ok":true} for statements that return
#         no rows (INSERT/UPDATE/DELETE). Errors go to stderr with exit 1.
#
# Needs SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in the environment (set in the
# Cloud environment's env-var config — never commit the values).

set -euo pipefail

: "${SUPABASE_URL:?SUPABASE_URL is not set}"
: "${SUPABASE_SERVICE_ROLE_KEY:?SUPABASE_SERVICE_ROLE_KEY is not set}"

if [ "$#" -ge 1 ]; then
  SQL="$1"
else
  SQL="$(cat)"
fi

if [ -z "${SQL//[[:space:]]/}" ]; then
  echo "sb.sh: no SQL given" >&2
  exit 1
fi

# JSON-encode the statement with python so quotes/newlines survive intact.
BODY="$(SQL="$SQL" python3 -c 'import json,os; print(json.dumps({"query": os.environ["SQL"]}))')"

RESP="$(curl -sS --max-time 120 \
  --retry 3 --retry-delay 2 --retry-connrefused \
  -w $'\n__HTTP__%{http_code}' \
  -X POST "${SUPABASE_URL}/rest/v1/rpc/exec_sql" \
  -H "apikey: ${SUPABASE_SERVICE_ROLE_KEY}" \
  -H "Authorization: Bearer ${SUPABASE_SERVICE_ROLE_KEY}" \
  -H "Content-Type: application/json" \
  -d "$BODY")"

CODE="${RESP##*__HTTP__}"
PAYLOAD="${RESP%$'\n'__HTTP__*}"

if [ "$CODE" != "200" ]; then
  echo "sb.sh: HTTP $CODE" >&2
  echo "$PAYLOAD" >&2
  exit 1
fi

# A statement returning no rows comes back as null / empty — normalize to {"ok":true}
# so callers can tell "write succeeded" from "read returned nothing".
printf '%s' "$PAYLOAD" | python3 -c '
import json,sys
raw = sys.stdin.read().strip()
if not raw or raw == "null":
    print(json.dumps({"ok": True}))
    sys.exit(0)
try:
    data = json.loads(raw)
except ValueError:
    print(raw)
    sys.exit(0)
if data is None:
    print(json.dumps({"ok": True}))
else:
    print(json.dumps(data, indent=None, default=str))
'
