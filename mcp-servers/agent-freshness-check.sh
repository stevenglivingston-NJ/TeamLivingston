#!/usr/bin/env bash
# =============================================================================
# agent-freshness-check.sh — did every daily agent actually publish today?
# -----------------------------------------------------------------------------
# Why this exists: a stalled agent is invisible. The boards write-then-prune by
# scan_date, so a session that hangs in REQUIRES_ACTION leaves yesterday's rows
# in place and the tab renders perfectly. There is no error state on screen.
#
# `check_agent_freshness()` already writes staleness into the system_health
# section — but NOTHING PUSHES IT. On 2026-09-21 Organic had been stale nine
# days and Foreman four; system_health knew, and also missed paid_brief being a
# day behind entirely. This script is the delivery leg: it reads the truth
# directly from each section's own scan_date rather than trusting the watchdog,
# and prints a verdict a human can act on.
#
# Pure Bash + curl through sb.sh ON PURPOSE. A scheduled Routine that calls an
# mcp__* tool stalls in REQUIRES_ACTION forever — a watchdog that can hang the
# same way as the thing it watches is worthless.
#
# Usage:  bash mcp-servers/agent-freshness-check.sh [YYYY-MM-DD]
# Exit:   always 0 (never false-fail a session); read the verdict line.
# =============================================================================
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TODAY="${1:-$(date -u +%F)}"

SQL="select section, max(fields->>'scan_date') as last_scan
     from intranet_records
     where section in ('goldeneye_callouts','moola_briefing','foreman_briefing','paid_brief',
                       'organic_report','pipeline_briefing','tekki_health','cellar_briefing',
                       'harvest_briefing')
     group by 1 order by 1"

OUT="$(bash "$HERE/sb.sh" "$SQL" 2>&1)" || true

TODAY="$TODAY" OUT="$OUT" python3 <<'PY'
import json, os, datetime, sys
today = datetime.date.fromisoformat(os.environ["TODAY"])
try:
    rows = json.loads(os.environ["OUT"])
    if not isinstance(rows, list): raise ValueError
except Exception:
    print("‼️  COULD NOT REACH SUPABASE — this is itself a failure, not a clean result.")
    print(os.environ["OUT"][:400]); raise SystemExit(0)

# due_hour_utc per agent, from the Routine cron schedules
DUE = {"cellar_briefing":6,"goldeneye_callouts":7,"moola_briefing":8,"tekki_health":9,
       "organic_report":10,"paid_brief":11,"pipeline_briefing":11,"foreman_briefing":12,
       "harvest_briefing":14}
WATCH = {"organic_report","foreman_briefing"}   # the two fixed on 2026-09-21

stale, fresh, missing = [], [], []
for r in rows:
    sec, last = r["section"], r.get("last_scan")
    if not last: missing.append(sec); continue
    late = (today - datetime.date.fromisoformat(last[:10])).days
    (fresh if late <= 0 else stale).append((sec, last, late))
for sec in DUE:
    if sec not in {r["section"] for r in rows}: missing.append(sec)

print(f"AGENT FRESHNESS — {today}\n" + "=" * 58)
for sec, last, late in sorted(stale, key=lambda x: -x[2]):
    mark = "🔴" if sec in WATCH else "🟠"
    print(f"{mark} STALE  {sec:<22} last={last[:10]}  {late}d late   (due {DUE.get(sec,'?')}:00 UTC)")
for sec in sorted(set(missing)):
    print(f"🔴 NO DATA {sec:<22} never published")
for sec, last, late in sorted(fresh):
    print(f"🟢 ok     {sec:<22} last={last[:10]}")

print("=" * 58)
watch_stale = [s for s, _, _ in stale if s in WATCH] + [s for s in missing if s in WATCH]
if not stale and not missing:
    print("VERDICT: ALL CURRENT. Nothing to do.")
elif watch_stale:
    print(f"VERDICT: FIX DID NOT HOLD — {', '.join(sorted(set(watch_stale)))} still stale.")
    print("  The 2026-09-21 helper migration did not resolve it. Read the stalled")
    print("  session's pending_action: if it names Bash it is the destructive-shell")
    print("  gate; if it names mcp__* a connector call was missed in the migration.")
else:
    print(f"VERDICT: FIX HELD for Organic + Foreman, but {len(stale)+len(missing)} other agent(s) are behind.")
PY
exit 0
