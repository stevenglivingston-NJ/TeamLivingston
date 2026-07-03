# CMO Command Center — Decommission Audit (2026-07-03)

Audit of the CMO dashboard (ops/team/content.ktubloomfield.com, Cloudflare Pages
project `ktu-cmo-dashboard` + `ktu-team-dashboard`, auth worker
`ktu-cmo-dashboard-auth`) before decommission. Goal: port anything valuable into
the Axyom intranet + agent suite, then shut CMO down.

**Coordination note:** the `claude/report-audit-agent-5oimse` session rebuilt the
agent suite in parallel (Foreman, rewritten Paid, Harvest/Cellar, Goldeneye scope
changes). This doc maps every CMO capability to its owner so the two sessions
don't duplicate. Items marked **PORTED HERE** landed in this branch; items marked
**HANDOFF** belong to the other session or a later intranet pass.

## Verdict

Safe to decommission — with two caveats:
1. **Data freshness**: only the ServiceMinder revenue/AR path still refreshes
   (7/02). QuickBooks P&L frozen at April (Windsor feed disconnected); most
   marketing intel is 6–12 weeks stale; the 7:04 AM refresh task
   (`ktu-btu-daily-dashboard-refresh`) stopped fully populating mid-June. We port
   **mechanisms, not numbers**.
2. **John's workflow**: content.ktubloomfield.com is the only surface serving the
   Content Creation briefs (captions/hashtags/edit treatments/CompanyCam readiness
   per project). Killing CMO kills that view unless replaced — see handoff #5.

## Coverage map — CMO capability → new owner

| CMO capability | Owner | Status |
|---|---|---|
| 40%-at-install inflow forecast (50/40/10 → dated draws) | Moola | **PORTED HERE** |
| Commission liability tracker (5g: trigger events, next-payroll payable) | Moola | **PORTED HERE** |
| Debt & leverage + balance sheet + restructure scenarios (5e/5f) | Moola monthly | **PORTED HERE** |
| Throughput-vs-burn breakeven + crew scenario | Moola monthly | **PORTED HERE** |
| Fleet & mileage anomalies (Motive/Ramp) | Moola monthly | **PORTED HERE** |
| Pre-install timelines, selections past due, Production Gate, CompanyCam gap | Foreman | Covered (other branch) |
| Materials-selection risk tiers / install-at-risk | Foreman | Covered (other branch) |
| HighLevel↔ServiceMinder sync-break monitor | Foreman | Covered (other branch) |
| Vendor invoices / unmatched-invoice queue (billing inbox) | Foreman + Moola job costing | Covered (other branch) |
| True-source attribution audit (HL vs SM vs platforms) | Paid | Covered (other branch) |
| Clarity landing-page/JS-error checks | Paid | Covered (other branch, partial — see handoff #2) |
| PPC diagnostics (impression share, auction insights, QS, dayparting) | Paid | Covered (other branch, §1/§6) |
| Closebot bot-health audit | Goldeneye | Covered (other branch) |
| Conversations triage / unread queue | Goldeneye | Covered (existing) |
| Daily spend/CPL/channel tables, ROAS/CAC | Paid | Covered (existing) |
| Cash position, AR/AP aging, anomalies, recurring outflows | Moola + Truthifi | Covered (existing) |
| Exec Recommendations / Munib Apr-2026 action plans | — | Skip (stale, point-in-time) |
| Query Center, Portals directory | Intranet Systems/Integrations tabs | Skip (covered; see handoff #4) |
| GHL BTU pipeline "won revenue" | — | Skip (known-unreliable, 903 $0-opps bug) |

## HANDOFF — remaining items (not done anywhere yet)

1. **Expired-proposal + cancellation recovery** — CMO tracked 47 expired proposals
   worth **$1.27M** with call sheets, plus a 35.1% appointment-cancellation rate
   (benchmark 10–15%) with reason tracking. Goldeneye watches stale deals (>7d)
   but not dormant-pipeline reactivation. → Add a weekly reactivation queue to
   Goldeneye (or Foreman).
2. **Tracking-integrity check** — CMO's #1 flagged priority was a **39.13%
   JS-error session rate** killing conversion tracking. Paid reads Clarity daily
   but should explicitly verify instrumentation (pixel/GTM firing, AnyTrack
   receiving) and treat a broken tracking layer as a must-action, since every
   spend verdict depends on it.
3. **Channel×Zip×Service combo optimizer + close-rate-by-zip** — top-10
   over-invest / bottom-10 kill combos from ServiceMinder outcomes joined to
   spend. Paid does geo spend; Territories tab does demographics; neither joins
   them to close rates. → Paid monthly section and/or Territories tab overlay.
4. **Portals account IDs** — port the account/property/location IDs (Google Ads
   accts, GA4 property, GMB locations, Meta act_ IDs, Clarity project IDs, HL
   location IDs, QBO entities) into the intranet Systems tab. **Do NOT port the
   login-hint lines** from the CMO Portals tab (credential hints — policy: never
   surface credentials on the intranet).
5. **John's Content Creation view** — replace before decommission: either a
   role-gated intranet section fed by a content-readiness scan (CompanyCam photo
   counts + drafted captions/hashtags per project) or a standalone generated
   page. Until this exists, keep content.ktubloomfield.com alive.
6. **Demand pockets / search landscape / seasonality** — zip-level opportunity
   scoring and keyword volume/difficulty tables. → Paid quarterly market review
   via Semrush/Ahrefs MCPs; Territories tab enrichment.
7. **Upcoming-campaigns calendar** — print-ad deadlines (Lifestyle, Worrall,
   Montclair Girl, Best Version Media) + scheduled social. → Marketing Plan tab.

## Decommission checklist (execute only after handoffs #4 and #5)

1. Archive the two HTML builds (already captured during audit) into the repo or
   Drive for reference.
2. Delete/disable the daily refresh task `ktu-btu-daily-dashboard-refresh`
   (already half-dead since mid-June).
3. Delete Cloudflare Pages projects `ktu-cmo-dashboard`, `ktu-team-dashboard`
   and the content.* deployment; remove DNS records for ops/team/content
   .ktubloomfield.com.
4. Delete workers `ktu-cmo-dashboard-auth` and `ktu-dashboard-auth` (their only
   job was gating these dashboards) and rotate/retire the basic-auth credentials
   embedded in them.
5. Update the intranet Tech Stack / Systems tabs: mark CMO dashboard retired,
   pointing at the intranet + agent briefs as the replacement.
