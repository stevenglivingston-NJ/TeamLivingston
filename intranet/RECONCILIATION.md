# Intranet reconciliation — repo vs live (opened 2026-08-18)

> **Status 2026-08-18: port complete — one source of truth, ready to deploy.**
> `ktubtuintranet.html` is now **live + every repo-only feature merged in**:
> 267 functions (all 220 from live, plus 47 ported), 35 sections rendered, no
> dangling references, scripts parse, `build.mjs` builds. `tools/verify.mjs`
> asserts that no baseline function was lost; `tools/drift-check.mjs` reports
> **nothing that exists only on live**, which is the proof nothing was destroyed.
> Deploying now *adds* the missing tabs without removing anything.
>
> _(Earlier status, kept for the record:)_
> **base adopted — deploying is SAFE (a no-op).**
> `ktubtuintranet.html` is now a byte-for-byte copy of the live worker, so a
> deploy ships live's own content back to live. The danger described below is
> what *would* have happened before this change, and is kept as the record of
> why the base was reset.
>
> **Still outstanding:** the repo-only tabs are not yet ported. They are preserved
> in `ktubtuintranet.repo-snapshot-2026-08-18.html` — see "The plan", steps 3-6.

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

1. **Preserve live** — ✅ done. Live existed *only* on Cloudflare; a single bad
   deploy would have been unrecoverable.
2. **Adopt live as the new base** — ✅ done. `ktubtuintranet.html` is now
   byte-identical to the live worker (412,567 bytes; `node build.mjs` verified to
   build from it). Deploying is a no-op, which is the safest possible resting
   state while the port proceeds. The undeployed repo work is preserved as
   `ktubtuintranet.repo-snapshot-2026-08-18.html`, the source to port from.
3. **Port repo-only features onto that base** — ✅ done. 47 functions, 7 panels
   (Cash Flow, Library, Commissions, Resources, Paid & Organic, Appointments,
   Project Timeline) plus the cash-flow-by-vendor card, each with its nav entry,
   `TAB_TITLES` entry and `go()` dispatch.
   These sections render again, having been written-but-invisible on live:
   `moola_runway`, `moola_balances`, `moola_ar`, `moola_ap`, `moola_cashledger`,
   `moola_cashflow`, `paid_brief`, `organic_report`, `library_docs`, `job_costs`.
4. **Add renderers for `moola_royalty`, `moola_royalty_jobs`, `moola_pl_recon`** —
   ⏳ outstanding. These are new UI, not a port; nothing to copy from either build.
5. **Verify before deploying** — ✅ automated as `tools/verify.mjs`, run after every
   port step. It fails the build if any of the 220 baseline functions disappears,
   on duplicate definitions, on a dangling reference to snapshot-only code, or on a
   parse error. It caught two real breakages during this port: `switchPO`,
   `apptSetBucket`, `apptClearSlicer` and `addResource` reachable only from markup
   `onclick=` handlers, and `refreshCostDetail`/`openCostDetail` likewise — every
   one of which would have thrown at runtime while looking fine statically.
6. **Deploy once, then re-fetch live and diff to zero** — ⏳ the remaining step.
   `node tools/drift-check.mjs` currently lists the 47 ported functions as
   "only in repo" (correct — not deployed yet) and **nothing as "only on live"**,
   which is the evidence the port removed nothing. After deploying it should print
   `✅ in sync`.

### Known gaps, deliberately not forced

- **`system_health` is still not rendered.** Live's `renderDash` (586 bytes) and the
  snapshot's (5,249 bytes) are genuinely different functions; only the snapshot's
  reads `system_health`, and it targets Home markup live may not have. Swapping it
  would risk the most-visited page for one status row, so it needs a hand-merge with
  visual checking rather than a mechanical port.
- **The Finance company selector (`finCompany`) was not ported** — it lives in the
  snapshot's Finance panel, which live has its own version of. `finCompany()` is
  null-safe (`return e ? e.value : ''`), so with no selector the finance cards simply
  show every brand unfiltered. Correct behaviour, one lost convenience.
- **Project Timeline has no nav entry** by design (it never had one — it opens from
  a project). `openProjectTimeline()` is ported, but live's `renderProjects` does not
  link to it yet, so the panel is currently unreachable from the UI.

## Preventing a repeat — `tools/drift-check.mjs`

The root cause is that the Cloudflare dashboard editor can change production
without touching the repo, and DEPLOY.md's "diff against live first" rule relied
on someone remembering it. That is now mechanical:

```bash
node tools/drift-check.mjs             # report only; exit 1 on drift
node tools/drift-check.mjs --publish   # also write a system_health row
```

It separates the two failure directions, because they need opposite responses:
**only on live** means someone edited production and it will be *destroyed* by the
next deploy — commit it first; **only in repo** means work is written but not
shipped. Run it from Tekki's daily sweep so drift surfaces within a day instead of
six weeks.

## Tooling added

| File | Purpose |
|---|---|
| `tools/verify.mjs` | Structural safety gate — run after every edit, before every deploy |
| `tools/drift-check.mjs` | Repo ↔ live comparison, with `--publish` to `system_health` |
| `.baseline-live.html` | The 2026-08-18 live baseline `verify.mjs` checks against |

## 2026-08-30 — the two copies have forked again, in both directions

`ktubtuintranet.html` and the live worker are no longer the same file, and
neither is a superset of the other:

| | panels the other lacks |
|---|---|
| **live only** | `channelperf` `leadsrevival` `network` `paidorganic` `pipeproposals` `piperecovery` `processes` `techhealth` `tradesched` |
| **repo only** | `cashflow` `commissions` `jobflow` `library` `organic` `projtimeline` `prospect` `prospecting` `resources` `roles` |

So `npm run deploy` from this repo would drop nine tabs that people are using
today. **Do not run it until this is reconciled.**

The Reports-tab work of 2026-08-30 was therefore shipped as an *additive patch*
rather than an edit — `tools/apply-report-scheduler.mjs` applies cleanly to
either copy, is idempotent, and removes no lines. It was applied to both: to
`ktubtuintranet.html` here, and to a copy of live which is what was actually
deployed (so production kept all nine of its own tabs and gained the feature).

Use the same shape for anything else that has to ship before the forks are
merged: write it as a patch under `tools/`, apply it to both, deploy from live.

Reconciling properly is a decision for Steven, not a side effect of a feature —
it means choosing, tab by tab, which of two divergent implementations wins.
