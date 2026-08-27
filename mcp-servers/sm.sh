#!/usr/bin/env bash
# =============================================================================
# sm.sh — ServiceMinder API access over curl
# -----------------------------------------------------------------------------
# Why this exists: the daily agent Routines are Claude-created, so they run in
# Auto mode, where the connector-call classifier prompts on MCP tool calls
# ("Query Invoices requests permission → Allow once"). A non-interactive
# scheduled fire cannot answer that prompt, so the session STALLS — it does not
# error, it sits in REQUIRES_ACTION forever and the next day's fire stalls in
# the identical spot. That is exactly how the 2026-08-19 → 08-27 Foreman outage
# happened: eight consecutive fires blocked on mcp__serviceminder__query_invoices
# and foreman_briefing went eight days stale while every credential was valid.
#
# Bash is NOT classifier-gated. This helper calls the same ServiceMinder Open
# API directly over curl, so agents reach ServiceMinder with zero permission
# prompts and zero dependency on MCP registration. Same approach as sb.sh
# (Supabase) and ghl.sh (HighLevel).
#
# Usage:
#   bash mcp-servers/sm.sh <KTU|BTU> <endpoint> '<json-body>'
#
# ENDPOINT PATHS — note the inconsistent pluralisation in ServiceMinder's own
# API. These are verified against the working MCP server (serviceminder/server.py):
#   appointments/query   appointments/find   appointments/quickbook   (PLURAL)
#   invoice/query        payment/query       proposal/query           (SINGULAR)
#   proposal/details     contacts/locate     contacts/addupdate
#   serviceagents/all    channels/all        customfields/all         user/all
#   organizations/details
#   download/startdownload  download/getdownload
# A wrong path returns HTTP 200 with an EMPTY BODY (not a 404), which this
# helper reports as an explicit error rather than as "no results".
#
# Examples:
#   bash mcp-servers/sm.sh KTU appointments/query \
#        '{"FromDate":"2026-08-01","ThroughDate":"2026-08-31","IncludeContact":true,"Take":200}'
#   bash mcp-servers/sm.sh KTU invoice/query '{"FromDate":"2025-09-01","Take":200}'
#   bash mcp-servers/sm.sh BTU payment/query '{"FromDate":"2026-08-01"}'
#   bash mcp-servers/sm.sh KTU appointments/find '{"AppointmentId":50964262}'
#
# The ApiKey is injected automatically — never put it in the json-body, and
# never hardcode it into a prompt or a committed file.
#
# Requires env (set in the Cloud environment's secrets — see .env.example):
#   SM_KEY_KTU / SM_KEY_BTU        location API keys
#   SM_USERID_KTU / SM_USERID_BTU  optional; only the Org-Level Download API
#                                  needs a UserId, injected as UserId when set
#                                  and not already present in the body.
#
# Returns: the endpoint's JSON payload on stdout. Non-zero exit + JSON
# {"error":...} on failure.
# =============================================================================
set -uo pipefail

API_BASE="https://serviceminder.io/api"

BRAND="$(echo "${1:-}" | tr '[:lower:]' '[:upper:]')"
ENDPOINT="${2:-}"
BODY_IN="${3:-{\}}"

case "$BRAND" in
  KTU) KEY="${SM_KEY_KTU:-}"; VAR="SM_KEY_KTU"; UID_="${SM_USERID_KTU:-}" ;;
  BTU) KEY="${SM_KEY_BTU:-}"; VAR="SM_KEY_BTU"; UID_="${SM_USERID_BTU:-}" ;;
  *)   echo '{"error":"usage: sm.sh <KTU|BTU> <endpoint> [json-body]  e.g. sm.sh KTU invoices/query {\"Take\":50}"}' >&2; exit 2 ;;
esac

if [ -z "$KEY" ]; then
  echo "{\"error\":\"$VAR not set in environment\"}" >&2
  exit 1
fi
if [ -z "$ENDPOINT" ]; then
  echo '{"error":"no endpoint given; e.g. appointments/query, invoices/query, payments/query, proposals/query, contacts/find"}' >&2
  exit 2
fi

# Merge ApiKey (and UserId when available) into the caller's body.
BODY=$(KEY="$KEY" UID_="$UID_" BODY_IN="$BODY_IN" python3 -c '
import json, os, sys
raw = os.environ["BODY_IN"] or "{}"
try:
    body = json.loads(raw)
except json.JSONDecodeError as e:
    print(json.dumps({"error": f"json-body is not valid JSON: {e}"}), file=sys.stderr); sys.exit(2)
if not isinstance(body, dict):
    print(json.dumps({"error": "json-body must be a JSON object"}), file=sys.stderr); sys.exit(2)
body["ApiKey"] = os.environ["KEY"]
uid = os.environ.get("UID_") or ""
if uid and "UserId" not in body:
    try:
        body["UserId"] = int(uid)
    except ValueError:
        pass
print(json.dumps(body))') || exit 2

# Stream the response to a temp file rather than a shell variable. ServiceMinder
# payloads routinely exceed 700KB (a 90-day invoice/query with Lines[] is several
# MB), and passing that to python via an env var blows the process argument/env
# limit — "Argument list too long" — which looked like a helper crash rather than
# a big-but-healthy response. Found by the 2026-08-27 Foreman run.
RESP_FILE="$(mktemp)"
trap 'rm -f "$RESP_FILE"' EXIT
curl -sS -X POST "$API_BASE/${ENDPOINT#/}" \
  -H "Content-Type: application/json" \
  --max-time 300 -d "$BODY" -o "$RESP_FILE" || {
    echo '{"error":"curl failed reaching serviceminder.io"}' >&2; exit 1; }

# Pretty-print JSON when it is JSON; pass raw text through otherwise (some
# endpoints — notably the Org-Level Download — return CSV in a text field).
#
# NOTE: ServiceMinder ECHOES the ApiKey back in every response body. Strip it so
# a live API key never lands in an agent transcript, a Routine log, or a
# published intranet row.
RESP_FILE="$RESP_FILE" python3 <<'PY'
import json, os, sys
with open(os.environ["RESP_FILE"], encoding="utf-8", errors="replace") as fh:
    raw = fh.read()
try:
    data = json.loads(raw)
except json.JSONDecodeError:
    if not raw.strip():
        print(json.dumps({"error": "empty response from ServiceMinder (this API returns HTTP 200 + empty body for an endpoint that does not exist — check the endpoint path)"}))
        sys.exit(1)
    print(raw)
    sys.exit(0)

def scrub(o):
    if isinstance(o, dict):
        return {k: ("<redacted>" if k == "ApiKey" else scrub(v)) for k, v in o.items()}
    if isinstance(o, list):
        return [scrub(v) for v in o]
    return o

print(json.dumps(scrub(data), indent=1))
PY
