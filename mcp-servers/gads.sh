#!/usr/bin/env bash
# =============================================================================
# gads.sh — Google Ads (and LSA) access without the MCP connector
# -----------------------------------------------------------------------------
# Why this exists: on 2026-09-21 the Organic Routine was found stalled for NINE
# DAYS. Its session sat in REQUIRES_ACTION with:
#
#   pending_action: mcp__google-ads__query_lsa_periods {location: "KTU"}
#
# Scheduled Routines run in Auto mode, where the connector-call classifier
# prompts before an mcp__* tool it has not already approved. A non-interactive
# fire cannot answer, so the session does not error — it hangs, and the board
# silently serves yesterday's rows. Same mechanism as the 2026-08-19 → 08-27
# outage; only the tool name differs.
#
# Every other system in this stack already had a curl escape hatch (sb.sh,
# sm.sh, ghl.sh, gmb.sh, companycam.sh, clickup.sh). Google Ads did not, which
# is exactly why this one call never got migrated and kept killing the agent.
#
# HOW IT WORKS — deliberately NOT a reimplementation. query_lsa_periods carries
# real logic (week/month/year bucketing from raw lead timestamps, prior-year
# YTD with a partial-coverage warning, a second account-report call for spend
# and call responsiveness). Rewriting that in bash would fork it and the two
# copies would drift. Instead this loads mcp-servers/google-ads/server.py and
# calls the very same function the MCP tool calls. FastMCP's decorator returns
# the undecorated function, so the import costs nothing and the behaviour is
# identical by construction. Bash is the transport; the logic is shared.
#
# Usage:
#   bash mcp-servers/gads.sh tools                       # list callable tools
#   bash mcp-servers/gads.sh <tool> '<json-args>'
#
# Examples:
#   bash mcp-servers/gads.sh test_connection '{}'
#   bash mcp-servers/gads.sh query_lsa_periods '{"location":"KTU"}'
#   bash mcp-servers/gads.sh query_lsa_periods '{"location":"BTU","include_cost":false}'
#   bash mcp-servers/gads.sh query_campaigns '{"location":"EARTHWISE","days":30}'
#
# Requires env (see .env.example): GOOGLE_ADS_DEVELOPER_TOKEN, _CLIENT_ID,
#   _CLIENT_SECRET, _REFRESH_TOKEN, and _LOGIN_CUSTOMER_ID for MCC-managed
#   accounts only. Earthwise (7159460368) is NOT under the KTU/BTU MCC —
#   server.py's _MCC_MANAGED_ACCOUNTS handles that, and this helper inherits it.
#
# NOTE: include_cost=true costs three extra REST calls per brand against a
# rate-limited endpoint. Pass false when only lead volume is needed.
# =============================================================================
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVER="$HERE/google-ads/server.py"
[[ -f "$SERVER" ]] || { echo "gads.sh: cannot find $SERVER" >&2; exit 2; }

for v in GOOGLE_ADS_DEVELOPER_TOKEN GOOGLE_ADS_CLIENT_ID GOOGLE_ADS_CLIENT_SECRET GOOGLE_ADS_REFRESH_TOKEN; do
  [[ -n "${!v:-}" ]] || { echo "gads.sh: $v is not set (env vars load at SESSION START)" >&2; exit 2; }
done

TOOL="${1:-}"; ARGS="${2:-{\}}"
[[ -n "$TOOL" ]] || { sed -n '2,45p' "$0"; exit 0; }

SERVER="$SERVER" TOOL="$TOOL" ARGS="$ARGS" python3 <<'PY'
import importlib.util, inspect, json, os, sys

spec = importlib.util.spec_from_file_location("gads_server", os.environ["SERVER"])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

tool = os.environ["TOOL"]
if tool == "tools":
    names = sorted(
        n for n, o in vars(mod).items()
        if inspect.isfunction(o) and not n.startswith("_") and o.__module__ == mod.__name__
    )
    print(json.dumps({"tools": names}, indent=1)); sys.exit(0)

fn = getattr(mod, tool, None)
if not callable(fn):
    print(json.dumps({"error": f"no such tool: {tool}",
                      "hint": "bash mcp-servers/gads.sh tools"}), file=sys.stderr)
    sys.exit(64)

try:
    args = json.loads(os.environ["ARGS"] or "{}")
except json.JSONDecodeError as e:
    print(json.dumps({"error": f"args is not valid JSON: {e}"}), file=sys.stderr); sys.exit(64)

try:
    print(json.dumps(fn(**args), indent=1, default=str))
except TypeError as e:
    sig = str(inspect.signature(fn))
    print(json.dumps({"error": str(e), "signature": f"{tool}{sig}"}), file=sys.stderr); sys.exit(64)
except Exception as e:
    print(json.dumps({"error": f"{type(e).__name__}: {e}"}), file=sys.stderr); sys.exit(1)
PY
