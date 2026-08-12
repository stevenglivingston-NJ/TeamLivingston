# Prospect — Multifamily Kitchen Lead-Research System

Weekly B2B pipeline research for the **Multifamily Kitchen Repositioning
Partner** business line: premium, standardized kitchen upgrades for affluent
North Jersey multifamily owners, investors, developers, and property managers.

The agent spec (workflow, scoring model, ethics rules, report format) lives at
[`.claude/agents/prospect.md`](../.claude/agents/prospect.md).

## Contents

| File | Purpose |
|---|---|
| `target-market-map.md` | Geography (primary affluent corridor + secondary volume market), property tiers, signals, exclusions |
| `source-registry.md` | Per-municipality and cross-market research sources with status + scan cadence |
| `leads/master-lead-list.csv` | Deduplicated CRM-ready lead ledger — the single source of truth; prevents duplicate outreach |
| `reports/` | Weekly "North Jersey Multifamily Kitchen Opportunity Report" (one per week, dated the Monday) |

## Operating rules (summary)

- Runs **weekly, Monday morning**. Only surfaces leads with a clear reason to
  act now.
- **No invented facts.** Every material claim has a source URL + date; data is
  labeled verified / probable / inferred / not verified.
- Public and authorized sources only; no prohibited scraping; no improperly
  obtained personal contact data.
- Master list is deduplicated by address + owner entity; a lead contacted in
  the last 30 days is never re-recommended for outreach.
- Monthly: performance review (responses, meetings, bids, wins, margin) and
  recommended changes to geography, scoring weights, offers, and messaging.
