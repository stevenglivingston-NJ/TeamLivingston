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

Safe to decommission. CMO was the laptop-dependent predecessor of the cloud
intranet + agent suite; the audit's only question was "does it have anything we
don't." Owner rulings (7/03):
- **John's Content Creation view is NOT needed** — decommission without replacing
  it. Content-readiness signals (CompanyCam coverage) live with Foreman.
- **Port nothing obsolete.** Karen Naithe has departed — her BTU commission
  config is legacy only. Munib Apr-2026 action plans, Windsor-fed panels, and
  point-in-time recommendations are dead weight, not ports.
- **Data freshness**: only the ServiceMinder revenue/AR path still refreshed
  (7/02). QuickBooks P&L frozen at April (Windsor feed disconnected); most
  marketing intel was 6–12 weeks stale; the 7:04 AM refresh task
  (`ktu-btu-daily-dashboard-refresh`) stopped fully populating mid-June. We
  ported **mechanisms, not numbers**.

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
| Cash position, AR/AP aging, anomalies, recurring outflows | Moola + Bank Connection | Covered (existing) |
| Exec Recommendations / Munib Apr-2026 action plans | — | Skip (stale, point-in-time) |
| Query Center, Portals directory | Intranet Systems/Integrations tabs | Skip (covered; see handoff #4) |
| GHL BTU pipeline "won revenue" | — | Skip (known-unreliable, 903 $0-opps bug) |

## Formerly-handoff items — ALL INCORPORATED 2026-07-03 (owner directive)

All remaining gaps were folded into the agents that feed the existing intranet
reporting (no intranet code changes):

1. **Expired-proposal + cancellation recovery** ($1.27M/47 proposals; 35.1%
   cancellation rate vs 10–15% band) → **Goldeneye §5b**, Monday weekly queue,
   surfaces as `goldeneye_callouts` rows on the intranet home page.
2. **Tracking-integrity check** (39% JS-error rate finding) → **Paid §2**, every
   run; broken instrumentation leads 🚨 MUST ACTION.
3. **Channel×Town×Service combo optimizer + close-rate-by-town** → **Paid §7b**,
   monthly, feeds §8 reallocation verdicts.
4. **Demand pockets / search landscape / seasonality** → **Paid §7c**, quarterly
   via Semrush/Ahrefs.
5. **Upcoming-campaigns calendar** (print deadlines + starts, next 14 days) →
   **Paid brief 📅 section**, daily.
6. **Paid now writes `paid_brief` rows** to `intranet_records` (crash-safe
   write-then-prune) so its verdicts are in the reporting layer and Moola can
   pressure-test them, as Moola's spec already expects.

## Account IDs salvaged from the CMO Portals tab (ported to intranet Tech Stack)

The only durable data in the Portals tab. Login-hint lines were NOT ported
(policy: never surface credentials on the intranet).

| System | Brand | ID |
|---|---|---|
| Google Ads | KTU | 2579406186 |
| Google Ads | BTU | 4477036900 |
| Meta Ads | KTU | act_512807913902919 |
| Meta Ads | BTU | act_1226816105474707 |
| GA4 property | shared (KTU site) | 453600017 |
| Clarity project | KTU | 2708513173760009 |
| Clarity project | BTU | 2789761772911940 |
| HighLevel location | KTU | nHLCxHPidnhV1NFzRtZZ |
| HighLevel location | BTU | 0uWA8M5BzHrrcJftuaDe |

## Decommission execution (2026-07-03)

1. ✅ Archive the two HTML builds → `docs/archive/` (gzipped) in this repo.
2. Delete/disable the daily refresh task `ktu-btu-daily-dashboard-refresh`
   (already half-dead since mid-June).
3. Delete Cloudflare Pages projects `ktu-cmo-dashboard`, `ktu-team-dashboard`
   and the content.* deployment; remove DNS records for ops/team/content
   .ktubloomfield.com.
4. Delete workers `ktu-cmo-dashboard-auth` and `ktu-dashboard-auth` (their only
   job was gating these dashboards); their embedded basic-auth credentials die
   with them.
5. Update the intranet Tech Stack / Systems tabs: mark CMO dashboard retired,
   pointing at the intranet + agent briefs as the replacement.
