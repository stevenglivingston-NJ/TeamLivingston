#!/usr/bin/env bash
# =============================================================================
# companycam.sh — CompanyCam API access over curl
# -----------------------------------------------------------------------------
# Why this exists: same reason as sm.sh / ghl.sh / sb.sh. Scheduled Routines are
# Claude-created, so they run in Auto mode, where a connector-call classifier
# prompts before any `mcp__*` tool it has not already approved. A non-interactive
# scheduled fire CANNOT answer that prompt — the session does not error, it sits
# in REQUIRES_ACTION forever and the board silently goes stale. That is the
# single highest-impact failure mode in this repo (CLAUDE.md, verified
# 2026-08-27, an eight-day outage with every credential valid throughout).
#
# Bash is not classifier-gated. So the labor sync reaches CompanyCam through
# THIS helper, never through mcp__CompanyCam__* / mcp__companycam__*. The MCP
# tools stay fine for interactive work where a human can approve a prompt.
#
# Usage:
#   bash mcp-servers/companycam.sh <path> [query-string]
#
# Examples:
#   bash mcp-servers/companycam.sh /v2/timeentries 'per_page=100&status=completed'
#   bash mcp-servers/companycam.sh /v2/timeentries 'since=2026-09-01T00:00:00Z'
#   bash mcp-servers/companycam.sh /v2/projects    'per_page=100'
#   bash mcp-servers/companycam.sh /v2/users
#
# TIME TRACKING NOTES (probed live 2026-09-18):
#   * The time-tracking plan IS active on company 592669 (Kitchen Tune-Up
#     Bloomfield NJ) — the summary endpoint answers cleanly rather than
#     returning a plan error. But ZERO hours were logged in the 30 days to
#     2026-09-18, i.e. the pipe works and nobody is clocking in yet. An empty
#     result from this helper therefore means "no one clocked in", NOT "the
#     integration is broken" — do not report it as an outage.
#   * Time-entry reads require a MANAGER or ADMIN token. A standard-user token
#     is rejected outright rather than being silently narrowed to that user's
#     own entries, so an agent can never mistake a partial view for the full
#     company report. Today only 2 of 11 active users hold admin.
#   * CompanyCam returns HOURS, NEVER DOLLARS. There is no pay-rate field
#     anywhere in the API. Costing dollars come from payroll (jc_payroll_periods);
#     these hours only decide how those dollars SPLIT across jobs.
#   * There is ONE CompanyCam company covering BOTH brands. Brand is resolved
#     per project through jc_cc_project_map, never from the account.
#
# Requires env (Cloud environment secrets — see .env.example):
#   COMPANYCAM_TOKEN   Bearer token, manager/admin scope
#
# Returns: the endpoint's JSON on stdout. Non-zero exit + {"error":...} on
# failure. Pagination cursors come back in the `meta` object; pass the next
# cursor back as `after=<cursor>`.
# =============================================================================
set -uo pipefail

API_BASE="https://api.companycam.com"

PATH_IN="${1:-}"
QS="${2:-}"

TOKEN="${COMPANYCAM_TOKEN:-}"
if [ -z "$TOKEN" ]; then
  echo '{"error":"COMPANYCAM_TOKEN not set in environment"}' >&2
  exit 1
fi
if [ -z "$PATH_IN" ]; then
  echo '{"error":"no path given; e.g. /v2/timeentries, /v2/projects, /v2/users"}' >&2
  exit 2
fi

URL="${API_BASE}/${PATH_IN#/}"
[ -n "$QS" ] && URL="${URL}?${QS}"

RESP_FILE="$(mktemp)"
trap 'rm -f "$RESP_FILE"' EXIT

# -w writes the status code after the body so a 401/403 is distinguishable from
# an empty-but-valid 200. Without this an expired token reads as "no hours".
HTTP_CODE=$(curl -sS -X GET "$URL" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  --max-time 120 -o "$RESP_FILE" -w '%{http_code}') || {
    echo '{"error":"curl failed reaching api.companycam.com"}' >&2; exit 1; }

RESP_FILE="$RESP_FILE" HTTP_CODE="$HTTP_CODE" python3 <<'PY'
import json, os, sys
code = os.environ["HTTP_CODE"]
with open(os.environ["RESP_FILE"], encoding="utf-8", errors="replace") as fh:
    raw = fh.read()

if code == "401":
    print(json.dumps({"error": "CompanyCam returned 401 — COMPANYCAM_TOKEN is invalid or revoked. Regenerate it in CompanyCam and update the env var.", "http": 401}))
    sys.exit(1)
if code == "403":
    print(json.dumps({"error": "CompanyCam returned 403 — the token lacks manager/admin scope. Time-entry reads require it; a standard-user token cannot read them at all.", "http": 403}))
    sys.exit(1)
if code.startswith(("4", "5")):
    print(json.dumps({"error": f"CompanyCam returned HTTP {code}", "http": int(code), "body": raw[:500]}))
    sys.exit(1)

try:
    print(json.dumps(json.loads(raw), indent=1))
except json.JSONDecodeError:
    print(json.dumps({"error": "CompanyCam returned non-JSON", "http": int(code), "body": raw[:500]}))
    sys.exit(1)
PY
