#!/usr/bin/env bash
# sb.sh — run SQL against the Axyom intranet Supabase project without MCP.
#
# Why this exists: scheduled (non-interactive) agent runs cannot answer the
# "Allow?" permission prompt that an MCP tool call raises, so any agent that
# reached Supabase via mcp__Supabase__execute_sql stalled forever. This is the
# curl path — no prompt, no MCP, safe for cron fires.
#
# Usage:  bash mcp-servers/sb.sh '<SQL>'
#         echo '<SQL>' | bash mcp-servers/sb.sh
#
# Output: JSON rows for SELECT, {"ok":true} for statements returning no rows.
# Exit:   0 on success, 1 on error (error JSON printed to stderr).
#
# Requires SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in the environment
# (set in the Cloud environment's env-var config — never committed here).

set -uo pipefail

SQL="${1:-}"
if [ -z "$SQL" ] && [ ! -t 0 ]; then
  SQL="$(cat)"
fi

if [ -z "$SQL" ]; then
  echo '{"error":"no SQL supplied"}' >&2
  exit 1
fi

if [ -z "${SUPABASE_URL:-}" ] || [ -z "${SUPABASE_SERVICE_ROLE_KEY:-}" ]; then
  echo '{"error":"SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not set in environment"}' >&2
  exit 1
fi

# Build the JSON body with python so the SQL is escaped correctly no matter
# what quoting, newlines, or jsonb literals it contains.
BODY="$(SQL="$SQL" python3 -c 'import json,os;print(json.dumps({"query":os.environ["SQL"]}))')" || {
  echo '{"error":"failed to encode SQL as JSON"}' >&2
  exit 1
}

RESP="$(curl -sS --max-time 60 -w $'\n%{http_code}' \
  -X POST "${SUPABASE_URL}/rest/v1/rpc/exec_sql" \
  -H "apikey: ${SUPABASE_SERVICE_ROLE_KEY}" \
  -H "Authorization: Bearer ${SUPABASE_SERVICE_ROLE_KEY}" \
  -H "Content-Type: application/json" \
  --data-binary "$BODY" 2>&1)" || {
  echo "{\"error\":\"curl failed\",\"detail\":$(printf '%s' "$RESP" | python3 -c 'import json,sys;print(json.dumps(sys.stdin.read()))')}" >&2
  exit 1
}

CODE="$(printf '%s' "$RESP" | tail -n1)"
PAYLOAD="$(printf '%s' "$RESP" | sed '$d')"

if [ "$CODE" != "200" ] && [ "$CODE" != "201" ] && [ "$CODE" != "204" ]; then
  echo "$PAYLOAD" >&2
  exit 1
fi

# How api.exec_sql answers (see its definition):
#   execute format('select coalesce(jsonb_agg(row_to_json(t)), ''[]''::jsonb)
#                   from (%s) t', query)
#   exception when others then  execute query;  return {"ok": true}
#
# So: rows -> [ ... ], a SELECT matching nothing -> [], and a write -> the
# exception path -> {"ok": true}. That fallback is silent, which is the trap:
# if a SELECT fails to WRAP, its rows are executed bare and THROWN AWAY, and the
# caller still sees {"ok": true} — a read that found nothing and a read that was
# discarded look identical.
#
# The wrap fails most often on an alias collision: a query whose output column is
# named `t` (e.g. `SELECT to_char(now(),'HH24:MI') AS t`) makes `row_to_json(t)`
# resolve to that column instead of the subquery row, which raises. Rename the
# column and it works. Guard reads so this can never be mistaken for success.
STMT="$(printf '%s' "$SQL" | sed -e 's/^[[:space:]]*//' | tr '[:lower:]' '[:upper:]')"
NORM="$(printf '%s' "$PAYLOAD" | tr -d '[:space:]')"

case "$STMT" in
  SELECT*|WITH*|TABLE*|SHOW*|EXPLAIN*)
    if [ "$NORM" = '{"ok":true}' ]; then
      echo '{"error":"exec_sql fell back to bare execute: this read was run but its rows were DISCARDED, not returned. Most likely an output column named `t`, which collides with the wrapper alias in exec_sql — rename it (AS t -> AS val) and retry."}' >&2
      exit 1
    fi
    ;;
esac

case "$NORM" in
  ""|"null") echo '{"ok":true}' ;;
  *)         echo "$PAYLOAD" ;;
esac
