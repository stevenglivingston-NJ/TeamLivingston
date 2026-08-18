# Intranet reconciliation — repo vs live (opened 2026-08-18)

> **⛔ DO NOT RUN `npm run deploy` UNTIL THIS IS RESOLVED.**
> Deploying `ktubtuintranet.html` as it stands today would **destroy roughly six
> weeks of live production features**. See "Why you must not deploy" below.

## What happened

`DEPLOY.md` says `ktubtuintranet.html` is the source of truth, recovered from live
on 2026-07-05. That was true on the day it was written. Since then **both copies
were edited independently** and never re-merged:

- **Live** (`dash.goaxyom.com`) kept being edited directly — almost certainly via
  the Cloudflare dashboard editor, which `DEPLOY.md` explicitly permits as an
  alternative to `wrangler`. It carries content dated through **2026-08-11**.
- **The repo copy** gained a month of work that was **never deployed**. Its
  newest embedded date is **2026-07-03**; last commit `973d508` (2026-08-06).

Neither is a superset of the other. This is a fork, not a lag.

## Measured divergence (2026-08-18)

| | Live (`dash.goaxyom.com`) | Repo (`ktubtuintranet.html`) |
|---|---|---|
| Size | 410,711 bytes | 457,069 bytes |
| JS functions | 220 | 251 |
| Functions unique to it | **86** | **120** |
| Newest embedded date | 2026-08-11 | 2026-07-03 |

### Only on LIVE — lost if the repo is deployed
Calendar system (`cal*`, `mkpCalendar`) · task drawer + kanban (`openTaskDrawer`,
`taskCardHTML`, `taskDragStart`, `taskDrop`, `saveTaskDrawer`, `postTaskComment`) ·
**PWA + web push** (`pwaInit`, `pushEnable`, `pushUrlB64ToU8`, `pwaShowInstallHint`) ·
mobile table handling (`mobileifyTables`, `startTableObserver`) · sidebar
(`openSidebar`/`closeSidebar`, `ensureScrim`) · appointment tabs (`buildApptTabs`,
`renderUpcoming`, `renderCompletedAppt`, `renderCancelAppt`) · `renderAP` / `renderAR` /
`renderLiabilities` / `renderCollections` · **`renderBenchmarks`** (the Moola benchmark
scorecard) · `renderProposals` · `renderLeadList` · `renderNeedsReply` ·
`renderTradeAlerts` · `renderVendorDir` · `renderPipeFunnel` · **Goldeneye callout state**
(`geAssign`, `geClose`, `geUpsertState`) · tech-stack rollups (`techMonthly`, `techSubSummary`)

Live-only tabs: `items`, `jobflow`, `trades`
Live-only mounts: `moola_ap_root`, `moola_ar_root`, `pipeline_kpis_root`,
`collections_root`, `liabilities_root`, `proposals_root`, `vendor_directory_root`,
`trade_alerts_root`, `unbooked_leads_root`, `inbox_needsreply_root`,
`perceptionist_followups_root`, `appt_upcoming_root`, `appt_completed_root`,
`appt_followups_root`, `mkt_high_touch_root`, `docs_marketing_root`

### Only in REPO — written but never shipped
Cash Flow command center (`cf*`, `renderMoolaCash`, `renderCashflow`) · **Paid tab**
(`renderPaid`) · **Organic tab** (`renderOrganic`) · **Library tab** (`renderLibrary`) ·
payables (`renderPayables`, `pay*`) · commissions (`renderCommissions`) · appointments
(`renderAppointments`) · call notes (`renderCallNotes`) · job costing (`renderJobCosting`) ·
project timeline (`renderProjectTimeline`, `pt*`) · resources (`renderResources`) ·
trades CRUD (`renderTrades`, `addTrade`) · directory (`addDirContact`, `dirExportCSV`) ·
**tab permissions** (`loadTabPermissions`, `renderTabPermissions`, `tabPermSave`) ·
settings (`openSettings`) · **sensitive-data toggle** (`setSensitiveVisible`,
`sensitiveHidden`) · `renderExecSummary` · `renderAgentPerf` · `renderHomeSnapshot` ·
`renderTechRecs`

Repo-only tabs: `appointments`, `cashflow`, `commissions`, `library`, `organic`, `resources`
Repo-only mounts: `cf_root`, `paid_root`, `organic_root`, `library_root`,
`payables_root`, `commissions_root`, `appointments_root`, `callnotes_root`,
`resources_root`, `snapshot_root`, `pt_root`

## Why you must not deploy

`npm run deploy` overwrites the worker wholesale — `build.mjs` inlines the HTML and
replaces the entire response body. There is no merge step. Deploying today would:

1. Remove the **benchmark scorecard**, which has **405 `moola_benchmarks` + 44
   `moola_exec_summary` rows**, written as recently as 2026-08-17.
2. Remove **PWA install + web push** — anyone who installed the intranet to a phone
   home screen loses notifications.
3. Remove the **calendar and task kanban**.
4. Remove **Goldeneye callout state** (`geUpsertState`) — assigned/closed callouts.

Conversely, live is missing renderers for sections agents write to *today*
(`paid_brief`, `organic_report`, `library_docs`, `system_health`, `moola_runway`,
`moola_balances`, `moola_cashledger`) — so that data is being written and never seen.
**That is why the Paid tab looked dead even when Paid was healthy.**

## Sections written by agents that NEITHER build renders

Populated or specified, but invisible on both:

| Section | Written by | Status |
|---|---|---|
| `moola_royalty` | Moola (merged #149) | no renderer anywhere |
| `moola_royalty_jobs` | Moola (merged #149) | no renderer anywhere |
| `moola_pl_recon` | Moola (PR #151) | no renderer anywhere |

## The plan

**Base = LIVE.** It is the newer build and the one people actually use; regressing
production is the only truly unacceptable outcome. Port the repo-only work onto it.

1. **Preserve live** — done. `ktubtuintranet.live-snapshot-2026-08-18.html` is the
   verified 410,711-byte capture. Until now, live existed *only* on Cloudflare;
   a single bad deploy would have been unrecoverable.
2. **Adopt live as the new base** for `ktubtuintranet.html`, in one commit that
   changes nothing functionally, so the diff that follows is reviewable.
3. **Port repo-only features onto that base**, one tab per commit — Cash Flow,
   Paid, Organic, Library, payables, commissions, appointments, call notes, job
   costing, project timeline, resources, tab permissions, sensitive toggle. Each is
   largely self-contained (a `render*` function plus a `*_root` mount plus a tab
   entry), which is what makes a staged port feasible.
4. **Add renderers for the three unrendered sections** above.
5. **Verify before deploying**: no duplicate function definitions, every `*_root`
   mount has a renderer, every renderer's mount exists, every `fetchRecords('x')`
   names a real section, and the file parses as JS.
6. **Deploy once, then re-fetch live and diff to zero.**

## Preventing a repeat

The root cause is that the Cloudflare dashboard editor can change production
without touching the repo. Either stop editing live directly (deploy only via
`npm run deploy`), or add a scheduled drift check that curls `dash.goaxyom.com`,
diffs it against `ktubtuintranet.html`, and raises a `system_health` row when they
differ. The second is more robust, because it does not depend on everyone
remembering the rule.
