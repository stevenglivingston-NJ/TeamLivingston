#!/usr/bin/env bash
# =============================================================================
# ghl.sh — HighLevel (LeadConnector) MCP access over curl
# -----------------------------------------------------------------------------
# Why this exists: the ghl-ktu / ghl-btu MCP servers are registered by
# bootstrap.sh, which runs from the Cloud environment's SETUP SCRIPT. When that
# setup step doesn't run (or runs after the session's tool list is built), a
# scheduled agent sees NO mcp__ghl-* tools and wrongly reports "HighLevel
# unavailable" — even though the PIT credentials are valid. That happened on the
# 2026-08-21 Foreman run: both PITs returned HTTP 200 the whole time.
#
# This helper calls the same LeadConnector MCP endpoint directly over curl, so
# agents reach HighLevel with zero dependency on MCP registration. Same approach
# as sb.sh (Supabase) and the direct ServiceMinder pull.
#
# Usage:
#   bash mcp-servers/ghl.sh <KTU|BTU> tools                  # list tool names
#   bash mcp-servers/ghl.sh <KTU|BTU> <tool> '<json-args>'   # call a tool
#
# Examples:
#   bash mcp-servers/ghl.sh KTU tools
#   bash mcp-servers/ghl.sh BTU contacts_get-contacts '{"query_limit":5}'
#   bash mcp-servers/ghl.sh KTU calendars_get-calendar-events \
#        '{"query_startTime":"2026-08-21T00:00:00Z","query_endTime":"2026-09-04T00:00:00Z"}'
#
# REST VERBS (not MCP tools — see below):
#   bash mcp-servers/ghl.sh KTU note-add <contactId> 'note text'
#   bash mcp-servers/ghl.sh KTU note-list <contactId>
#   bash mcp-servers/ghl.sh KTU note-delete <contactId> <noteId>
#   bash mcp-servers/ghl.sh KTU contact-by-phone '+19735551234'
#   bash mcp-servers/ghl.sh KTU rest GET /contacts/<id>/notes
#   bash mcp-servers/ghl.sh KTU rest POST /contacts/<id>/notes '{"body":"..."}'
#
# WHY REST AND NOT MCP FOR NOTES: the PIT MCP surface is 36 tools and NONE of
# them writes a note — the only note-shaped tool is
# `calendars_get-appointment-notes`, which is a read. Writing a note to a
# HighLevel contact is only possible through REST API v2. Verified live
# 2026-08-30 against the KTU PIT:
#   GET    /contacts/{id}/notes            -> {"notes":[...]}
#   POST   /contacts/{id}/notes            -> {"note":{"id":...}}
#   DELETE /contacts/{id}/notes/{noteId}   -> {"succeeded":true}
#   GET    /contacts/search/duplicate?locationId=..&number=..  -> {"contact":{"id":...}}
# The same PIT authenticates both surfaces, so no extra credential is needed.
#
# Requires env (set in the Cloud environment's secrets — see .env.example):
#   GHL_PIT_KTU   Private Integration Token for Kitchen Tune-Up
#   GHL_PIT_BTU   Private Integration Token for Bath Tune-Up
#
# Location IDs are pinned here to match bootstrap.sh (verified 2026-07-03 and
# re-verified 2026-08-21: KTU contacts carry source "Online/kitchentuneup.com",
# BTU contacts carry "Online/bathtune-up.com").
#
# Returns: the tool's JSON payload on stdout (the inner result, unwrapped from
# the MCP/SSE envelope). Non-zero exit + JSON {"error":...} on failure.
# =============================================================================
set -uo pipefail

BRAND="$(echo "${1:-}" | tr '[:lower:]' '[:upper:]')"
TOOL="${2:-}"
ARGS="${3:-{\}}"

case "$BRAND" in
  KTU) LOCATION_ID="nHLCxHPidnhV1NFzRtZZ"; TOKEN="${GHL_PIT_KTU:-}"; VAR="GHL_PIT_KTU" ;;
  BTU) LOCATION_ID="0uWA8M5BzHrrcJftuaDe"; TOKEN="${GHL_PIT_BTU:-}"; VAR="GHL_PIT_BTU" ;;
  *)   echo '{"error":"usage: ghl.sh <KTU|BTU> <tool|tools> [json-args]"}' >&2; exit 2 ;;
esac

if [ -z "$TOKEN" ]; then
  echo "{\"error\":\"$VAR not set in environment\"}" >&2
  exit 1
fi
if [ -z "$TOOL" ]; then
  echo '{"error":"no tool given; use `tools` to list available tool names"}' >&2
  exit 2
fi

# ---- REST verbs -------------------------------------------------------------
# These bypass the MCP proxy entirely and speak to REST API v2. Kept in this
# file so callers have ONE place to reach HighLevel with ONE credential, rather
# than a second helper that would drift out of sync with the location ids.
REST_BASE="https://services.leadconnectorhq.com"

ghl_rest() {  # ghl_rest <METHOD> <path> [json-body]
  local method="$1" path="$2" body="${3:-}"
  local args=(-sS --max-time 60 -X "$method" "$REST_BASE${path}"
              -H "Authorization: Bearer $TOKEN"
              -H "Version: 2021-07-28"
              -H "Accept: application/json")
  if [ -n "$body" ]; then
    args+=(-H "Content-Type: application/json" -d "$body")
  fi
  curl "${args[@]}" || { echo '{"error":"curl failed reaching leadconnectorhq REST"}' >&2; return 1; }
}

pretty() { python3 -c 'import json,sys
raw=sys.stdin.read()
try: print(json.dumps(json.loads(raw),indent=1))
except Exception: print(raw)'; }

case "$TOOL" in
  rest)
    METHOD="${3:-GET}"; RPATH="${4:-}"; RBODY="${5:-}"
    # `rest` shifts the arg positions: $3/$4/$5 rather than the usual $3 json.
    [ -n "$RPATH" ] || { echo '{"error":"usage: ghl.sh <KTU|BTU> rest <METHOD> <path> [json]"}' >&2; exit 2; }
    ghl_rest "$METHOD" "$RPATH" "$RBODY" | pretty; exit $?
    ;;
  note-list)
    CID="${3:-}"
    [ -n "$CID" ] || { echo '{"error":"usage: ghl.sh <KTU|BTU> note-list <contactId>"}' >&2; exit 2; }
    ghl_rest GET "/contacts/$CID/notes" | pretty; exit $?
    ;;
  note-add)
    CID="${3:-}"; TEXT="${4:-}"
    [ -n "$CID" ] && [ -n "$TEXT" ] || { echo '{"error":"usage: ghl.sh <KTU|BTU> note-add <contactId> <text>"}' >&2; exit 2; }
    # Build the JSON in python so quotes/newlines in the note body can never
    # break out of the payload — a note is free text typed by a human.
    BODY=$(TEXT="$TEXT" python3 -c 'import json,os;print(json.dumps({"body":os.environ["TEXT"]}))')
    ghl_rest POST "/contacts/$CID/notes" "$BODY" | pretty; exit $?
    ;;
  note-delete)
    CID="${3:-}"; NID="${4:-}"
    [ -n "$CID" ] && [ -n "$NID" ] || { echo '{"error":"usage: ghl.sh <KTU|BTU> note-delete <contactId> <noteId>"}' >&2; exit 2; }
    ghl_rest DELETE "/contacts/$CID/notes/$NID" | pretty; exit $?
    ;;
  contact-by-phone)
    PHONE="${3:-}"
    [ -n "$PHONE" ] || { echo '{"error":"usage: ghl.sh <KTU|BTU> contact-by-phone <+1234567890>"}' >&2; exit 2; }
    # search/duplicate is HighLevel's purpose-built "does this person already
    # exist" lookup and is the cheapest way from a phone number to a contact id.
    ENC=$(PHONE="$PHONE" python3 -c 'import os,urllib.parse;print(urllib.parse.quote(os.environ["PHONE"]))')
    ghl_rest GET "/contacts/search/duplicate?locationId=$LOCATION_ID&number=$ENC" | pretty; exit $?
    ;;
esac

if [ "$TOOL" = "tools" ]; then
  BODY='{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
else
  BODY=$(TOOL="$TOOL" ARGS="$ARGS" python3 -c '
import json, os, sys
try:
    args = json.loads(os.environ["ARGS"] or "{}")
except json.JSONDecodeError as e:
    print(json.dumps({"error": f"args is not valid JSON: {e}"}), file=sys.stderr); sys.exit(2)
print(json.dumps({"jsonrpc":"2.0","id":1,"method":"tools/call",
                  "params":{"name":os.environ["TOOL"],"arguments":args}}))') || exit 2
fi

RESP=$(curl -sS -X POST "https://services.leadconnectorhq.com/mcp/" \
  -H "Authorization: Bearer $TOKEN" \
  -H "locationId: $LOCATION_ID" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  --max-time 120 -d "$BODY") || {
    echo '{"error":"curl failed reaching services.leadconnectorhq.com"}' >&2; exit 1; }

# Unwrap: SSE ("data: {...}") -> JSON-RPC envelope -> MCP content -> inner JSON.
RESP="$RESP" python3 <<'PY'
import json, os, re, sys
raw = os.environ["RESP"]
m = re.search(r'^data: (\{.*)$', raw, re.M)
payload = m.group(1) if m else raw
try:
    env = json.loads(payload)
except json.JSONDecodeError:
    print(json.dumps({"error": "unparseable response", "raw": raw[:500]})); sys.exit(1)
if "error" in env:
    print(json.dumps({"error": env["error"]})); sys.exit(1)
res = env.get("result", env)
if isinstance(res, dict) and "tools" in res:
    print(json.dumps(sorted(t["name"] for t in res["tools"]), indent=1)); sys.exit(0)
content = (res or {}).get("content") or []
for blk in content:
    if blk.get("type") == "text":
        try:
            print(json.dumps(json.loads(blk["text"]), indent=1))
        except json.JSONDecodeError:
            print(blk["text"])
        sys.exit(0)
print(json.dumps(res, indent=1))
PY
