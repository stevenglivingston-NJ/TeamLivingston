# Change log

Every change to a tool, flow, integration or deploy — **who / what / when / where**. Newest first.
Add an entry with every change; the **Tekki** agent mirrors this to the intranet Change Log
(Tech Stack tab). Format: `YYYY-MM-DD · who · WHERE (repo/system) · WHAT — detail [link]`.

## 2026-09-30
- **2026-09-30 · Claude Code (for Steven) · Supabase (job costing) · Every job now carries a cost, from actual invoices + the P&L** — `jc_cost_rules` + `jc_refresh_estimate_lines()` (pg_cron every 10 min): KTU doors at 52.5% of sell (Elias bills, 10 jobs), countertops $70/sq ft (MSI + ASAP bills), other lines calibrated to the 2026 YTD P&L (KTU COGS 48.3%); BTU topped up to its P&L 50.6%. No job shows 90%+ any more (was 46). Foreman category estimates moved to `jc_forecast_lines_superseded`. BTU margin escalations are advisory until real costs cover 25% of the job; KTU keeps the hard 45% block. [#232]
- **2026-09-30 · Claude Code (for Steven) · Supabase (job costing) · Forecast fixes: commission + line categories** — every job with a `commission_pct` now forecasts its commission (`jc_refresh_commission_lines()`, 22 jobs / $60.7K were missing it); category rules fixed in `jc-forecast-sync` (deployed v2) and the Python twin: "Decommission" was filed as sales commission, and `plumb`/`electric`/`carpent` never matched "Plumbing"/"Electrical". [#232]
- **2026-09-30 · Claude Code (for Steven) · Supabase (pg_cron) · Cron run-log retention** — purged `cron.job_run_details` (264K rows since July, queries timing out) to 7 days; new daily `cron-log-cleanup` job keeps it there. [#232]
- **2026-09-30 · Claude Code (for Steven) · TeamLivingston + Supabase · Scripted jobs moved from Claude routines to pg_cron** — appointments-sync, jc-forecast-sync, office-address-check (edge functions); morning_health_digest, ap_recon_digest, cancel_watch_run, sm_hl_recon_run (SQL + `http`). Matching Claude routines disabled. [#232]
- **2026-09-30 · Claude Code (for Steven) · Supabase (payables) · Emailed bills get real vendor names; non-bills kept out of AP** — `vendor_aliases` + `payables_normalize_email()` on insert; Melio notices → `payment_notice`, marketing/shipping → `not_a_bill`, forwarded copies → `duplicate`; `payables_reconciled` excludes them; Moola spec updated. [#232]
- **2026-09-30 · Claude Code (for Steven) · TeamLivingston · Require-CHANGELOG check + PR template** — CI nudge to keep this log current. [#pending]
- **2026-09-30 · Claude Code (for Steven) · TeamLivingston · Tekki owns the change log; Playbook "Tools & How-To" page** — Tekki mirrors each repo's CHANGELOG.md to the intranet and flags undocumented changes; new playbook page with flow diagram + how-tos, deployed to playbook.ktubtu.com. [#233]

<!-- Add new entries above this line, newest first. -->
