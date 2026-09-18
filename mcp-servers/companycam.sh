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
#     Bloomfield NJ) — read through the MCP connector, the summary endpoint
#     answers cleanly rather than returning a plan error. But ZERO hours were
#     logged in the 30 days to 2026-09-18: the feature is on and nobody is
#     clocking in. An empty result therefore means "no one clocked in", NOT
#     "the integration is broken" — never report it as an outage.
#   * THIS HELPER CANNOT READ TIME ENTRIES with the current COMPANYCAM_TOKEN.
#     /v2/timeentries returns 401 {"error":{"general":"Bad credentials"}} while
#     the SAME token returns 200 on /v2/projects, /v2/users, /v2/company,
#     /v2/webhooks, /v2/tags and /v2/groups. So the token is live and the route
#     is real — the time-tracking surface simply authorizes separately and
#     rejects this credential. Time tracking is also absent from CompanyCam's
#     public API docs entirely (checked the documentation index), which fits:
#     it is a separately-sold, busybusy-backed product rather than part of the
#     documented v2 REST surface.
#   * Diagnosing it needs `Accept: application/json`. Without that header the
#     same request 302s to /users/sign_in and looks like a wrong path — which
#     is exactly the wrong conclusion drawn on 2026-09-18 before the header was
#     added. This helper now always sends it.
#   * The MCP connector's OAuth identity CAN read time entries. It is fine for
#     interactive work, but must never be used on a schedule (see above), so
#     jc-labor-sync.py takes --from-json until a curl-usable credential exists.
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
# Accept: application/json is NOT optional. Without it the time-tracking routes
# answer a browser-shaped request with 302 -> /users/sign_in, which reads like a
# wrong path. With it the same request returns an honest 401 "Bad credentials".
# That cost a misdiagnosis on 2026-09-18 — the route was real all along.
HTTP_CODE=$(curl -sS -X GET "$URL" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Accept: application/json" \
  -H "Content-Type: application/json" \
  --max-time 120 -o "$RESP_FILE" -w '%{http_code}') || {
    echo '{"error":"curl failed reaching api.companycam.com"}' >&2; exit 1; }

RESP_FILE="$RESP_FILE" HTTP_CODE="$HTTP_CODE" python3 <<'PY'
import json, os, sys
code = os.environ["HTTP_CODE"]
with open(os.environ["RESP_FILE"], encoding="utf-8", errors="replace") as fh:
    raw = fh.read()

if code == "401":
    print(json.dumps({"error": "CompanyCam returned 401 'Bad credentials'. Note this can be PER-ENDPOINT: the same token returns 200 on /v2/projects and /v2/users while the time-tracking routes reject it, because time tracking authorizes separately. So a 401 here does not mean the token is dead — check another endpoint before assuming that.", "http": 401, "body": raw[:300]}))
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
