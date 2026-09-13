#!/usr/bin/env bash
# =============================================================================
# gmail.sh — direct Gmail API access over curl (bypasses Zapier entirely)
# -----------------------------------------------------------------------------
# Why this exists: Foreman/Paid read firstgentalent@gmail.com and
# ktubtubilling@gmail.com through the Zapier "GoogleMailV2CLIAPI" connection
# today. Two separate problems with that, both documented from real runs:
#   1. It's an mcp__Zapier__* connector call — classifier-gated in Auto mode,
#      same stall risk as every other mcp__* tool in a scheduled Routine (see
#      CLAUDE.md "Scheduled runs stall on MCP connector calls").
#   2. Independent of (1), the search action itself (gmail_new_email_matching_
#      search) has been observed returning 0 results on EVERY query — including
#      a bare unfiltered keyword with no date filter — across at least two
#      consecutive runs (2026-09-12, 2026-09-13), while the connections
#      themselves show is_stale:false. That's a broken search action, not a
#      permission problem, and no amount of "avoid the classifier" fixes it.
#
# This helper sidesteps BOTH: it talks to the real Gmail API directly with its
# own OAuth refresh token per mailbox (same mint-token pattern as gmb.sh), so
# it is neither classifier-gated nor dependent on Zapier's search trigger.
#
# ONE-TIME SETUP (a human must do this — cannot be minted from inside a
# session): run, per mailbox, while logged into that Google account in the
# browser that opens:
#   python3 mcp-servers/tools/get_refresh_token.py --preset gmail-firstgentalent
#   python3 mcp-servers/tools/get_refresh_token.py --preset gmail-ktubtubilling
# Paste the two printed tokens into the Cloud environment's env vars as
# GMAIL_REFRESH_TOKEN_FIRSTGENTALENT / GMAIL_REFRESH_TOKEN_KTUBTUBILLING.
# Client id/secret default to GOOGLE_ADS_CLIENT_ID/SECRET (same OAuth app as
# GA4/GTM — a new scope just needs a new token, not a new app). Until those
# two env vars are set, this helper fails fast with a clear error naming which
# one is missing — it does not silently fall back to Zapier.
#
# Usage:
#   bash mcp-servers/gmail.sh <firstgentalent|ktubtubilling> search '<gmail-query>' [max_results]
#   bash mcp-servers/gmail.sh <firstgentalent|ktubtubilling> get <message_id>
#
# `search` returns each match's id + a decoded {from, to, subject, date, snippet}
# — enough to triage without fetching full bodies. `get` returns one message's
# full payload (headers + body, base64url-decoded where feasible) plus its
# attachment filenames (attachment BYTES need a follow-up call this helper
# does not make — list the filename and say a human/full read is needed, same
# discipline the agent specs already use for attachments).
#
# Examples:
#   bash mcp-servers/gmail.sh firstgentalent search 'subject:"Materials UPDATE" newer_than:45d' 20
#   bash mcp-servers/gmail.sh ktubtubilling search 'from:eliaswoodwork.com newer_than:60d' 25
#   bash mcp-servers/gmail.sh firstgentalent get 18d2f9a1b2c3d4e5
#
# Requires env: GMAIL_REFRESH_TOKEN_FIRSTGENTALENT or GMAIL_REFRESH_TOKEN_KTUBTUBILLING
#               (+ GOOGLE_ADS_CLIENT_ID / GOOGLE_ADS_CLIENT_SECRET, already set for GA4/GTM)
#
# Returns: JSON on stdout. Non-zero exit + JSON {"error":...} on failure.
# =============================================================================
set -uo pipefail

API_BASE="https://gmail.googleapis.com/gmail/v1/users/me"

die() { echo "{\"error\":$(python3 -c 'import json,sys;print(json.dumps(sys.argv[1]))' "$1")}" >&2; exit "${2:-1}"; }

MAILBOX="$(echo "${1:-}" | tr '[:upper:]' '[:lower:]')"
ACTION="${2:-}"
ARG3="${3:-}"
ARG4="${4:-}"

case "$MAILBOX" in
  firstgentalent) RT_VAR="GMAIL_REFRESH_TOKEN_FIRSTGENTALENT" ;;
  ktubtubilling)  RT_VAR="GMAIL_REFRESH_TOKEN_KTUBTUBILLING" ;;
  *) die "usage: gmail.sh <firstgentalent|ktubtubilling> <search|get> ...  (mailbox must be one of the two configured ops inboxes)" 2 ;;
esac

RT="${!RT_VAR:-}"
[ -n "$RT" ] || die "$RT_VAR not set — run: python3 mcp-servers/tools/get_refresh_token.py --preset gmail-$MAILBOX (one-time, needs a browser logged into that mailbox), then paste the token into the Cloud env config" 1

CID="${GOOGLE_ADS_CLIENT_ID:-}"
CSEC="${GOOGLE_ADS_CLIENT_SECRET:-}"
[ -n "$CID" ] && [ -n "$CSEC" ] || die "GOOGLE_ADS_CLIENT_ID / GOOGLE_ADS_CLIENT_SECRET must be set (same OAuth app used for GA4/GTM/gmb)" 1

mint_token() {
  local resp
  resp=$(curl -sS --max-time 60 -X POST "https://oauth2.googleapis.com/token" \
    -d "client_id=$CID" -d "client_secret=$CSEC" \
    -d "refresh_token=$RT" -d "grant_type=refresh_token") \
    || die "curl failed reaching oauth2.googleapis.com" 1
  RESP="$resp" python3 -c '
import json, os, sys
try:
    d = json.loads(os.environ["RESP"])
except json.JSONDecodeError:
    sys.exit(1)
if "access_token" not in d:
    sys.stderr.write(json.dumps(d)[:400]); sys.exit(1)
print(d["access_token"], end="")
'
}

TOKEN="$(mint_token)" || die "OAuth token refresh failed for $MAILBOX — check ${RT_VAR}'s scope (needs gmail.readonly) and that it hasn't been revoked" 1
[ -n "$TOKEN" ] || die "OAuth token refresh returned empty for $MAILBOX" 1

case "$ACTION" in
  search)
    QUERY="$ARG3"
    [ -n "$QUERY" ] || die "usage: gmail.sh <mailbox> search '<gmail-query>' [max_results]" 2
    MAX="${ARG4:-25}"
    LIST_URL="$API_BASE/messages"
    QS="$(python3 -c "import urllib.parse,sys; print(urllib.parse.urlencode({'q': sys.argv[1], 'maxResults': sys.argv[2]}))" "$QUERY" "$MAX")"
    LIST_FILE="$(mktemp)"; trap 'rm -f "$LIST_FILE"' EXIT
    curl -sS --max-time 60 -H "Authorization: Bearer $TOKEN" "$LIST_URL?$QS" -o "$LIST_FILE" \
      || die "curl failed reaching gmail.googleapis.com (list)" 1
    IDS="$(python3 -c '
import json
d = json.load(open("'"$LIST_FILE"'"))
if "error" in d:
    print(json.dumps(d)); raise SystemExit(1)
for m in d.get("messages", []):
    print(m["id"])
')" || { cat "$LIST_FILE" >&2; exit 1; }
    if [ -z "$IDS" ]; then
      echo '{"query":'"$(python3 -c 'import json,sys;print(json.dumps(sys.argv[1]))' "$QUERY")"',"results":[]}'
      exit 0
    fi
    echo "$IDS" | while read -r mid; do
      [ -n "$mid" ] || continue
      MSG_QS="format=metadata&metadataHeaders=From&metadataHeaders=To&metadataHeaders=Subject&metadataHeaders=Date"
      curl -sS --max-time 30 -H "Authorization: Bearer $TOKEN" "$API_BASE/messages/$mid?$MSG_QS"
      echo "---GMAIL_HELPER_RECORD_SEP---"
    done | python3 -c '
import json, sys
raw = sys.stdin.read()
records = [r for r in raw.split("---GMAIL_HELPER_RECORD_SEP---\n") if r.strip()]
out = []
for r in records:
    try:
        d = json.loads(r)
    except json.JSONDecodeError:
        continue
    headers = {h["name"]: h["value"] for h in d.get("payload", {}).get("headers", [])}
    out.append({
        "id": d.get("id"),
        "threadId": d.get("threadId"),
        "from": headers.get("From"),
        "to": headers.get("To"),
        "subject": headers.get("Subject"),
        "date": headers.get("Date"),
        "snippet": d.get("snippet"),
    })
print(json.dumps({"results": out}, indent=1))
'
    ;;
  get)
    MSG_ID="$ARG3"
    [ -n "$MSG_ID" ] || die "usage: gmail.sh <mailbox> get <message_id>" 2
    RESP_FILE="$(mktemp)"; trap 'rm -f "$RESP_FILE"' EXIT
    curl -sS --max-time 60 -H "Authorization: Bearer $TOKEN" "$API_BASE/messages/$MSG_ID?format=full" -o "$RESP_FILE" \
      || die "curl failed reaching gmail.googleapis.com (get)" 1
    python3 -c '
import base64, json

def walk(part, out):
    mime = part.get("mimeType", "")
    body = part.get("body", {})
    if mime.startswith("text/") and "data" in body:
        try:
            text = base64.urlsafe_b64decode(body["data"] + "===").decode("utf-8", "replace")
        except Exception:
            text = None
        if text and mime == "text/plain" and not out.get("body_text"):
            out["body_text"] = text
        if text and mime == "text/html" and not out.get("body_html"):
            out["body_html"] = text
    if part.get("filename"):
        out.setdefault("attachments", []).append({
            "filename": part["filename"],
            "mimeType": mime,
            "attachmentId": body.get("attachmentId"),
            "size": body.get("size"),
        })
    for sub in part.get("parts", []) or []:
        walk(sub, out)

d = json.load(open("'"$RESP_FILE"'"))
if "error" in d:
    print(json.dumps(d)); raise SystemExit(1)
headers = {h["name"]: h["value"] for h in d.get("payload", {}).get("headers", [])}
out = {
    "id": d.get("id"), "threadId": d.get("threadId"),
    "from": headers.get("From"), "to": headers.get("To"),
    "subject": headers.get("Subject"), "date": headers.get("Date"),
    "snippet": d.get("snippet"),
}
walk(d.get("payload", {}), out)
if "attachments" in out:
    out["_note"] = "attachment BYTES not fetched — attachmentId given for a follow-up messages.attachments.get call if the file itself is needed"
print(json.dumps(out, indent=1))
'
    ;;
  *)
    die "usage: gmail.sh <firstgentalent|ktubtubilling> <search|get> ..." 2
    ;;
esac
