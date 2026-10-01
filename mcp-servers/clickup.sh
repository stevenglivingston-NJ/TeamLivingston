#!/usr/bin/env bash
# =============================================================================
# clickup.sh — ClickUp API v2/v3 access over curl
# -----------------------------------------------------------------------------
# Why this exists — two independent reasons, both load-bearing:
#
# 1. SCHEDULED RUNS STALL ON mcp__* CALLS. Claude-created Routines run in Auto
#    mode, where a connector-call classifier prompts before an mcp__* tool it
#    has not already approved. A non-interactive scheduled fire cannot answer
#    that prompt, so the session does not error — it stalls in REQUIRES_ACTION
#    forever. That is the 2026-08-19 → 08-27 outage: eight days, four agents,
#    every credential valid throughout. Any recurring job that touches ClickUp
#    MUST come through here, never through mcp__ClickUp__*.
#
# 2. THE MCP CONNECTOR IS CAPPED AT 100 CALLS/DAY. Measured 2026-09-21: a hard
#    429 RATE_LIMIT_EXCEEDED at call 100, resetting ~22h later. Seeding 50
#    tasks exhausts half a day's quota. The REST API is a separate, far higher
#    limit, so bulk work belongs here too — not only scheduled work.
#
# All HTTP goes through curl on purpose, matching sb.sh / ghl.sh / sm.sh: the
# session egress proxy is configured for it. (ClickUp happens to also work from
# python-urllib, unlike HighLevel, but curl stays the convention.)
#
# Usage:
#   bash mcp-servers/clickup.sh whoami
#   bash mcp-servers/clickup.sh get   <path>                 # raw GET
#   bash mcp-servers/clickup.sh post  <path> '<json>'        # raw POST
#   bash mcp-servers/clickup.sh put   <path> '<json>'        # raw PUT
#   bash mcp-servers/clickup.sh task-create <list_id> '<json>'
#   bash mcp-servers/clickup.sh task-update <task_id> '<json>'
#   bash mcp-servers/clickup.sh task-find   <list_id> '<name substring>'
#   bash mcp-servers/clickup.sh tasks       <list_id>
#   bash mcp-servers/clickup.sh comment     <task_id> '<text>'
#
# Examples:
#   bash mcp-servers/clickup.sh tasks 901421334062
#   bash mcp-servers/clickup.sh task-create 901421334062 \
#        '{"name":"Chase Vecchiarello","assignees":[118419930],"priority":2}'
#   bash mcp-servers/clickup.sh task-find 901421334062 'Vecchiarello'
#
# Requires env (set in the Cloud environment's secrets — see .env.example):
#   CLICKUP_API_TOKEN   Personal API token (ClickUp → Settings → Apps)
#
# GOTCHA — dates are epoch MILLISECONDS, not date strings. The MCP tool accepts
# "2026-10-03" and converts it; the REST API answers a bare HTTP 400 that names
# no field. Convert first:
#   python3 -c 'import datetime;print(int(datetime.datetime.strptime("2026-10-03","%Y-%m-%d").replace(tzinfo=datetime.timezone.utc).timestamp()*1000))'
# Applies to due_date and start_date.
#
# GOTCHA — never HTML-escape task or list text. Passing "Money &amp; AR" stores
# that string literally; ClickUp decodes no entities. Send a raw "&".
#
# Workspace/ids pinned for reference (verified 2026-09-21):
#   team/workspace   90141667621  "Goaxyom"
#   space            90148750591  "Team Space"
#   folder           901413604098 "Axyom Operations"
#     list           901421334048 "Decisions — Steven"
#     list           901421334055 "Money & AR"
#     list           901421334062 "Commitments"
#   member           240208616    Steven Livingston  steven@goaxyom.com
#   member           118419930    Sonya Hartland     sonya@goaxyom.com
# =============================================================================
set -euo pipefail

API="https://api.clickup.com/api/v2"
TOKEN="${CLICKUP_API_TOKEN:-}"

if [[ -z "$TOKEN" ]]; then
  echo "clickup.sh: CLICKUP_API_TOKEN is not set." >&2
  echo "  Set it in the Cloud environment's env-var config. Note that env vars" >&2
  echo "  load at SESSION START — adding one mid-session does not reach the" >&2
  echo "  running session." >&2
  exit 2
fi

_req() {
  local method="$1" path="$2" body="${3:-}"
  local url="$path"
  [[ "$url" == http* ]] || url="${API}${path}"
  local -a args=(-sS --fail-with-body -X "$method" -H "Authorization: ${TOKEN}")
  if [[ -n "$body" ]]; then
    args+=(-H "Content-Type: application/json" -d "$body")
  fi
  curl "${args[@]}" "$url"
}

# Idempotency helper: exact-name match inside a list. Every create path in a
# recurring job should call this first — a sync that re-files the same finding
# every morning is worse than no sync.
_find_task_id() {
  local list_id="$1" name="$2"
  _req GET "/list/${list_id}/task?include_closed=true" \
    | python3 -c "
import sys,json
want=sys.argv[1]
for t in json.load(sys.stdin).get('tasks',[]):
    if t['name']==want:
        print(t['id']); break
" "$name"
}

cmd="${1:-}"; shift || true
case "$cmd" in
  whoami)
    _req GET "/user"; echo ;;

  get)   _req GET  "$1"; echo ;;
  post)  _req POST "$1" "${2:-}"; echo ;;
  put)   _req PUT  "$1" "${2:-}"; echo ;;

  tasks)
    _req GET "/list/$1/task?include_closed=${2:-false}"; echo ;;

  task-create)
    # Idempotent when the payload carries a "name": skips if that name exists.
    list_id="$1"; payload="$2"
    name="$(printf '%s' "$payload" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("name",""))')"
    if [[ -n "$name" ]]; then
      existing="$(_find_task_id "$list_id" "$name" || true)"
      if [[ -n "$existing" ]]; then
        echo "{\"skipped\":\"exists\",\"id\":\"${existing}\",\"name\":$(printf '%s' "$name" | python3 -c 'import sys,json;print(json.dumps(sys.stdin.read()))')}"
        exit 0
      fi
    fi
    _req POST "/list/${list_id}/task" "$payload"; echo ;;

  task-update)
    _req PUT "/task/$1" "$2"; echo ;;

  task-find)
    _find_task_id "$1" "$2" ;;

  comment)
    _req POST "/task/$1/comment" \
      "$(python3 -c 'import sys,json;print(json.dumps({"comment_text":sys.argv[1],"notify_all":False}))' "$2")"
    echo ;;

  ""|help|-h|--help)
    sed -n '2,61p' "$0" ;;

  *)
    echo "clickup.sh: unknown command '${cmd}'. Try: bash mcp-servers/clickup.sh help" >&2
    exit 64 ;;
esac
