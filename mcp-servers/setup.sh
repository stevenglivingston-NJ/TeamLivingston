#!/bin/bash
# =============================================================================
# Team Livingston — Cloud environment SETUP SCRIPT (self-healing)
# -----------------------------------------------------------------------------
# This is the canonical content of the Cloud environment's "Setup script"
# (Cloud env → Setup script). Keep the console copy in sync with this file —
# if they drift, this file wins; re-paste it.
#
# Why it exists: scheduled/headless fires (the daily agent routines — Moola,
# Foreman, Pipeline, Tekki, …) sometimes come up WITHOUT a repo checkout. The
# old setup loop found no bootstrap.sh, exited 0 silently, and the session ran
# blind — no custom MCP servers, no agent specs → stale intranet boards that
# looked like agent failures. This version self-heals: if no checkout exists,
# it clones the repo (depth 1, default branch), then runs the MCP bootstrap.
#
# Always exits 0 so a hiccup never marks the session failed — but prints a
# greppable "⚠ SETUP INCOMPLETE" marker when registration didn't happen.
#
# What this does NOT cover (account-level, no script can set them):
#   - claude.ai connectors (Gmail, Drive, Slack, JobTread, Bank Connection…)
#     must be enabled for scheduled runs in the environment/connector settings.
#   - Env-var secrets (SM_KEY_*, GHL_PIT_*, …) — see mcp-servers/.env.example.
#     bootstrap.sh SKIPS any server whose keys are missing, never registers blank.
# =============================================================================
set -u

REPO_URL="https://github.com/stevenglivingston-NJ/TeamLivingston"
CANDIDATES=(/home/user/TeamLivingston /workspace/TeamLivingston "$HOME/TeamLivingston")

find_repo() {
  for d in "${CANDIDATES[@]}"; do
    [ -f "$d/mcp-servers/bootstrap.sh" ] && { echo "$d"; return 0; }
  done
  return 1
}

REPO="$(find_repo)"

# Fallback: no checkout present (some scheduled fires skip source checkout) → clone it.
if [ -z "$REPO" ]; then
  echo "▸ setup: no repo checkout found — cloning $REPO_URL"
  GIT_TERMINAL_PROMPT=0 timeout 180 git clone --depth 1 "$REPO_URL" "$HOME/TeamLivingston" 2>&1 \
    || echo "⚠ setup: clone failed (check git credentials / network policy)"
  REPO="$(find_repo)"
fi

if [ -n "$REPO" ]; then
  echo "▸ setup: running MCP bootstrap from $REPO"
  bash "$REPO/mcp-servers/bootstrap.sh"
else
  echo "⚠ SETUP INCOMPLETE: no bootstrap.sh and clone produced none — custom MCP servers NOT registered this session"
fi

exit 0
