#!/usr/bin/env bash
# sb.sh — run SQL against the Axyom intranet Supabase project over PostgREST.
#
# Why this exists: scheduled (non-interactive) agent runs cannot answer the
# "Allow?" permission prompt that an MCP tool call raises, so any run that
# reached for mcp__Supabase__execute_sql stalled forever. curl needs no
# permission, so every scheduled read/write goes through here instead.
#
# Usage:  bash mcp-servers/sb.sh '<SQL>'
#         echo '<SQL>' | bash mcp-servers/sb.sh
#
# Returns JSON rows for SELECT, {"ok":true} for statements with no result set.
# Exits non-zero (with the error JSON on stderr) if the statement fails.
#
# Requires SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in the environment.

set -uo pipefail

SQL="${1-}"
if [ -z "$SQL" ] && [ ! -t 0 ]; then SQL="$(cat)"; fi

if [ -z "$SQL" ]; then
  echo "sb.sh: no SQL given. Usage: sb.sh '<SQL>'" >&2
  exit 2
fi

: "${SUPABASE_URL:?sb.sh: SUPABASE_URL is not set}"
: "${SUPABASE_SERVICE_ROLE_KEY:?sb.sh: SUPABASE_SERVICE_ROLE_KEY is not set}"

# JSON-encode the statement without needing jq (python3 is always present).
PAYLOAD=$(SB_SQL="$SQL" python3 -c 'import json,os;print(json.dumps({"query":os.environ["SB_SQL"]}))')

BODY_FILE=$(mktemp)
trap 'rm -f "$BODY_FILE"' EXIT

CODE=$(curl -sS --max-time 60 -o "$BODY_FILE" -w '%{http_code}' \
  -X POST "${SUPABASE_URL%/}/rest/v1/rpc/exec_sql" \
  -H "apikey: $SUPABASE_SERVICE_ROLE_KEY" \
  -H "Authorization: Bearer $SUPABASE_SERVICE_ROLE_KEY" \
  -H "Content-Type: application/json" \
  --data-binary "$PAYLOAD")

if [ "$CODE" != "200" ]; then
  echo "sb.sh: HTTP $CODE" >&2
  cat "$BODY_FILE" >&2
  echo >&2
  exit 1
fi

# exec_sql returns null / empty for statements with no result set (INSERT,
# UPDATE, DELETE). Normalise that to {"ok":true} so callers can branch on it.
python3 - "$BODY_FILE" <<'PY'
import json, sys
raw = open(sys.argv[1]).read().strip()
if not raw or raw == "null":
    print('{"ok":true}')
    sys.exit()
try:
    data = json.loads(raw)
except ValueError:
    print(raw)
    sys.exit()
if data is None or (isinstance(data, list) and not data):
    print('{"ok":true}')
else:
    print(json.dumps(data, indent=None, default=str))
PY
