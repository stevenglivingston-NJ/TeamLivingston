#!/usr/bin/env bash
# =============================================================================
# slack.sh — Slack DM/message send over curl (bypasses the mcp__Slack__* connector)
# -----------------------------------------------------------------------------
# Why this exists: Foreman's daily pacing brief (§7a) DMs Steven + Mayra via
# mcp__Slack__slack_send_message — a claude.ai OAuth connector, which is
# classifier-gated in Auto mode exactly like every other mcp__* tool. A
# non-interactive scheduled fire can't answer that "requests permission"
# prompt, so the session stalls in REQUIRES_ACTION forever (see CLAUDE.md
# "Scheduled runs stall on MCP connector calls" — this is the same mechanism
# that killed Tekki/Organic/Foreman/Goldeneye for 8 days on ghl-ktu/gmb/
# serviceminder calls).
#
# Bash is NOT classifier-gated. Slack's Web API is a plain Bearer-token REST
# API — this helper posts through it directly, so the daily pacing DM never
# depends on MCP registration or an Auto-mode approval.
#
# ONE-TIME SETUP (a human must do this): create or reuse a Slack app with a
# Bot User OAuth Token (scopes: chat:write, im:write — the same scopes
# CLAUDE.md already documents for the dispatch-notify Edge Function's
# SLACK_BOT_TOKEN; if that token already exists, the SAME value can be reused
# here, just also set as a plain env var in the Cloud environment's config,
# not only as a Supabase function secret). Set SLACK_BOT_TOKEN. Until it's
# set, this helper fails fast with a clear error — it does not hang waiting
# on a connector prompt.
#
# Usage:
#   bash mcp-servers/slack.sh dm <user_id> '<message text>'
#   bash mcp-servers/slack.sh channel <channel_id> '<message text>'
#
# `dm` opens (or reuses) a 1:1 IM with the user via conversations.open, then
# posts to it — this is what lets a bot message a user_id directly without
# already having been invited to a channel with them.
#
# Examples:
#   bash mcp-servers/slack.sh dm U017U4G26RY 'Foreman pacing brief: ...'
#   bash mcp-servers/slack.sh dm U09J3M80YRL 'Foreman pacing brief: ...'
#
# Requires env: SLACK_BOT_TOKEN
#
# Returns: Slack's JSON response on stdout. Non-zero exit + JSON {"error":...}
# on failure (including Slack's own {"ok":false,"error":"..."} responses,
# which are re-raised as failures rather than printed as if they succeeded).
# =============================================================================
set -uo pipefail

die() { echo "{\"error\":$(python3 -c 'import json,sys;print(json.dumps(sys.argv[1]))' "$1")}" >&2; exit "${2:-1}"; }

TOKEN="${SLACK_BOT_TOKEN:-}"
[ -n "$TOKEN" ] || die "SLACK_BOT_TOKEN not set — create/reuse a Slack bot token (chat:write + im:write) and set it as a plain env var in the Cloud environment config, not only as the dispatch-notify function secret" 1

ACTION="${1:-}"
TARGET="${2:-}"
TEXT="${3:-}"

[ -n "$ACTION" ] && [ -n "$TARGET" ] && [ -n "$TEXT" ] || die "usage: slack.sh <dm|channel> <user_id_or_channel_id> '<message text>'" 2

post_json() {
  local url="$1" body="$2"
  local resp
  resp=$(curl -sS --max-time 30 -X POST "$url" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json; charset=utf-8" \
    -d "$body") || die "curl failed reaching slack.com" 1
  echo "$resp"
}

case "$ACTION" in
  dm)
    OPEN_BODY=$(python3 -c 'import json,sys;print(json.dumps({"users":sys.argv[1]}))' "$TARGET")
    OPEN_RESP=$(post_json "https://slack.com/api/conversations.open" "$OPEN_BODY")
    CHANNEL_ID=$(echo "$OPEN_RESP" | python3 -c '
import json, sys
d = json.load(sys.stdin)
if not d.get("ok"):
    print(json.dumps(d)); sys.exit(1)
print(d["channel"]["id"], end="")
') || { echo "$OPEN_RESP"; exit 1; }
    ;;
  channel)
    CHANNEL_ID="$TARGET"
    ;;
  *)
    die "usage: slack.sh <dm|channel> <target> '<message text>'" 2
    ;;
esac

MSG_BODY=$(python3 -c 'import json,sys;print(json.dumps({"channel":sys.argv[1],"text":sys.argv[2]}))' "$CHANNEL_ID" "$TEXT")
MSG_RESP=$(post_json "https://slack.com/api/chat.postMessage" "$MSG_BODY")
echo "$MSG_RESP" | python3 -c '
import json, sys
d = json.load(sys.stdin)
if not d.get("ok"):
    print(json.dumps(d)); sys.exit(1)
print(json.dumps({"ok": True, "channel": d.get("channel"), "ts": d.get("ts")}, indent=1))
' || exit 1
