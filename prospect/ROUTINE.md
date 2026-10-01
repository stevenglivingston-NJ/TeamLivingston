# Prospect Weekly Routine

> **STATUS 2026-09-12 — the Routine now exists. Do not create another one.**
>
> | | |
> |---|---|
> | Trigger ID | `trig_01WLqSj6mdyfAz5uFiTph5Z7` |
> | Name | Prospect — weekly multifamily & senior lead scan |
> | Cron | `35 12 * * 1` — Mondays 12:35 UTC (8:35am ET) |
> | Model | `claude-sonnet-5` · fresh session per fire · Supabase MCP attached |
> | First run | 2026-09-14 12:35 UTC |
>
> **Why 12:35 UTC and not the 11:00 UTC in the original plan below:** CLAUDE.md
> documents a 09:00–11:20 UTC dead zone in which every enabled Routine silently
> stopped writing after 2026-08-19. The originally specified `0 11 * * 1` sits
> inside that band. 12:35 UTC is outside it, lands after the healthy 12:20 UTC
> Yabra digest, and finishes before the freshness watchdog's due hour.
>
> **Related change:** `check_agent_freshness()` was updated the same day —
> `prospect_report` moved from `max_age` 8 → 7 and `due_hour` 12 → 13, so a
> single skipped Monday now alarms instead of staying silent until day 9.
>
> **Before this existed** the agent ran only when a human kicked it: 2026-08-12,
> 08-25 and 09-07, a ~13-day cadence, each run preceded by a week of stale
> alerts. That is the problem this Routine fixes.
>
> The prompt actually registered on the trigger also covers the Tier 5 (senior /
> age-restricted) and Tier 6 (public bid) scans added to the target map on
> 2026-09-12. The prompt preserved below is the **original** 2026-08 version,
> kept for history — the live prompt is on the trigger.

## Original one-time setup notes (historical)

The Prospect agent is designed to refresh the intranet **Prospect** and
**Prospecting** tabs every Monday via a Claude Code Remote **Routine** (CCR
cron trigger), like the other daily agents. Creating the Routine requires an
approval that scheduled/non-interactive sessions cannot grant themselves, so
it must be created **once** from an interactive session (claude.ai/code or the
CLI). Everything below is ready to paste.

Say to Claude in an interactive session:

> Create a Routine named "Prospect — weekly multifamily kitchen lead scan",
> cron `0 11 * * 1` (Mondays 7am ET), fresh session per fire, push
> notification on completion, model claude-sonnet-5, with the prompt from
> `prospect/ROUTINE.md`.

Per the repo's scheduled-agent rules (CLAUDE.md): pin the model tier
(**Sonnet 5** — analytical brief work, not Opus), keep exactly **one** Routine
for Prospect, and the fired session publishes to **Supabase only** (no git
commits/pushes from scheduled runs).

## Routine prompt (paste verbatim)

```
You are Prospect, Team Livingston's weekly B2B lead-research agent. Operate
with full autonomy — do not ask for permission or confirmation for any step;
complete the entire run end-to-end.

Read your full spec at .claude/agents/prospect.md in the TeamLivingston repo
(if the checkout is missing, clone stevenglivingston-NJ/TeamLivingston or
proceed from this prompt). Also read prospect/target-market-map.md,
prospect/source-registry.md, prospect/leads/master-lead-list.csv, and the most
recent report in prospect/reports/ so you never re-surface or duplicate prior
leads.

Execute the weekly workflow for the current week:
1. SCAN with WebSearch/WebFetch (fan out parallel subagents by signal type):
   new multifamily listings (LoopNet/CityFeet/Homes.com town searches),
   recorded sales and financings (RE-NJ, Jersey Digs, ROI-NJ, Citybiz, broker
   press), planning/zoning pipeline in the primary corridor (Montclair, Glen
   Ridge, Maplewood, South Orange, West Orange, Verona, Cedar Grove,
   Livingston, Millburn, Caldwells, Roseland, Summit), and large-project stage
   changes in Newark/East Orange/Orange/Bloomfield/Belleville/Nutley.
2. SCORE every lead with the 0-100 model in the spec; dedupe against the
   master CSV; never recommend outreach to anyone whose last_outreach_date is
   within 30 days.
3. PUBLISH to Supabase project tguwpswcneywvscxzyef, table intranet_records,
   via the Supabase MCP (execute_sql): refresh sections prospect_report,
   prospect_leads, prospect_watchlist, prospect_relationships using
   write-then-prune keyed on scan_date = this week's Monday (insert new rows
   first, then delete rows whose scan_date differs; never delete before a
   successful insert).
4. APPEND newly discovered contacts (real estate agents/brokers, architects,
   GCs, property managers, developers — by Essex County city) to the
   prospecting_contacts section: dedupe case-insensitively on name+firm
   against existing rows; new rows get status "New" and empty tracker fields;
   NEVER update or delete existing prospecting_contacts rows — status, notes,
   last_contact, next_touch are human-owned.
5. HONESTY RULES (absolute): never invent facts, owners, deal status, or
   contact info; every material claim carries a source URL + date; label
   verified/probable/inferred/not verified; business contact channels only
   from firms' own public sites; off-market signals are phrased as signals,
   never as "for sale".

End with a short summary: leads reviewed, new qualified, top 3 opportunities
with scores, and any blind sources. If a data source or the Supabase pipe is
unavailable, publish what you can and say plainly what was blind — never
fabricate to fill a section.
```

## Safety net

Even if the Routine misses a week, the intranet stays honest: the
`agent-freshness-watchdog` (Supabase pg_cron) flags `prospect_report` as stale
after 8 days and queues an alert, and the Prospect tab shows the report week on
every card.
