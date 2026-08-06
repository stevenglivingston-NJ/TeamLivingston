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
# it clones the repo (depth 1, **main** branch explicitly), then runs the MCP
# bootstrap. If a checkout already exists (persistent/snapshotted environment),
# it HARD-RESETS that checkout to origin/main before running bootstrap — so a
# stale on-disk clone can never serve outdated agent specs or settings (e.g. an
# agent .md still calling mcp__Supabase__execute_sql, or an old
# .claude/settings.json permission mode) to a scheduled agent run. The reset is
# forceful (discards any on-disk drift) precisely so nothing stale survives.
#
# RE-PASTE REQUIRED: the Cloud console's Setup-script field runs a COPY of this
# file. Editing this file does nothing until it is re-pasted into
# Cloud env → Setup script. A stale console copy is the #1 reason merged fixes
# never reach scheduled fires.
#
# IMPORTANT — pin to "main", never "the default branch": this repo's GitHub
# default-branch setting has drifted to a feature branch before (an admin-only
# GitHub Settings > Branches change, not something this script controls) —
# `git clone` with no --branch flag follows THAT pointer, not main. Pinning
# here means a repo-settings drift can no longer silently ship stale settings
# (e.g. an old permissions.defaultMode) to fresh scheduled-agent sessions.
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
MAIN_BRANCH="main"
CANDIDATES=(/home/user/TeamLivingston /workspace/TeamLivingston "$HOME/TeamLivingston")

find_repo() {
  for d in "${CANDIDATES[@]}"; do
    [ -f "$d/mcp-servers/bootstrap.sh" ] && { echo "$d"; return 0; }
  done
  return 1
}

REPO="$(find_repo)"

if [ -n "$REPO" ]; then
  # Existing checkout — fast-forward it to origin/main so a snapshotted/persistent
  # environment never runs bootstrap against a stale settings.json or agent spec.
  echo "▸ setup: existing checkout at $REPO — syncing to origin/$MAIN_BRANCH"
  (
    cd "$REPO" \
      && GIT_TERMINAL_PROMPT=0 timeout 60 git fetch --depth 1 origin "$MAIN_BRANCH" 2>&1 \
      && git checkout -B "$MAIN_BRANCH" "origin/$MAIN_BRANCH" 2>&1 \
      && git reset --hard "origin/$MAIN_BRANCH" 2>&1
  ) || echo "⚠ setup: sync to origin/$MAIN_BRANCH failed — continuing with checkout as-is (check network policy / git credentials)"
fi

# Fallback: no checkout present (some scheduled fires skip source checkout) → clone it.
if [ -z "$REPO" ]; then
  echo "▸ setup: no repo checkout found — cloning $REPO_URL (branch: $MAIN_BRANCH)"
  GIT_TERMINAL_PROMPT=0 timeout 180 git clone --depth 1 --branch "$MAIN_BRANCH" "$REPO_URL" "$HOME/TeamLivingston" 2>&1 \
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
