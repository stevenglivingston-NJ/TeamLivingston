#!/bin/bash
# =============================================================================
# SessionStart hook — re-register the custom stdio/HTTP MCP servers on every
# fresh Claude Code on the web session (including the scheduled agent runs:
# Goldeneye, Moola, Paid, Ax, Foreman, etc.).
#
# The remote container is ephemeral: /root/.claude.json (where `claude mcp`
# stores user-scope servers) is wiped when the container is reclaimed, so the
# direct MCP connections — clarity-ktu-export, clarity-btu-export, ghl-*,
# serviceminder, google-ads, gmb, companycam, cloudflare — must be
# re-registered at the start of each session. bootstrap.sh reads every API key
# from environment variables and is idempotent (remove-then-add per server).
#
# Runs synchronously so the MCP servers are registered BEFORE the agent loop
# starts (no race where an agent calls a Clarity tool before it exists).
# =============================================================================
set -uo pipefail

# Only run in Claude Code on the web (remote) sessions. Local machines can run
# mcp-servers/bootstrap.sh by hand if they need the direct connections.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

REPO="${CLAUDE_PROJECT_DIR:-$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel 2>/dev/null)}"
BOOTSTRAP="$REPO/mcp-servers/bootstrap.sh"
LOG="/tmp/mcp-bootstrap.log"

if [ -f "$BOOTSTRAP" ]; then
  bash "$BOOTSTRAP" >"$LOG" 2>&1 || true
  # Surface the one-line registration summary to the session context.
  grep '^▸ Registered' "$LOG" 2>/dev/null || echo "MCP bootstrap ran (see $LOG)"
else
  echo "MCP bootstrap not found at $BOOTSTRAP — skipping MCP registration."
fi

exit 0
