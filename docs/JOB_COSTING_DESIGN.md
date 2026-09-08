# Job Costing & Payment Control — KTU / BTU

**The control:** no vendor invoice gets paid until it carries **job + vendor + category + amount + the sold line it maps to**, checked against what that job sold for. An invoice that cannot be mapped is **HELD** on an exceptions queue with the reason. Approving an unmapped invoice is a deliberate, recorded override — never the default path.

**Schema authority:** `KTU JCA ProfitabilityTracker` — Forecasted vs Actual side by side; categories **Direct Materials / Contract Labor / Employee Labor / Sales Commission**; per-line Description, Category, Qty, Unit Cost, Forecasted Cost, Actual Cost, Amount Charged, Gross Margin; a separate **GO-BACKS / REWORKS / UNPLANNED** block; Revenue split into **Forecasted Sale** vs **Added Revenue POST SALE**.

> Assumption (stated inline, per instructions): the ProfitabilityTracker workbook itself was not present in this session's filesystem or in Drive (Drive holds the base HFC JCA `KTU.xlsx`/`BTU.xlsx` and the live per-customer `Job Cost Analysis sheet - KTU .xlsx`, both the older single-column-Actual layout). The structure named above is taken as the authority verbatim; the base JCA workbooks corroborate the categories and benchmark framing.

**HFC benchmarks (from that workbook — not substituted):**
Gross Profit **50–55%** · Total Labor **<15%** · Direct Materials **<30%** · Commission **<8%** · G&A **10–13%** · Marketing **8–10%** · Royalty **6.5%** · NAF **1%**.

**Cash timing (Power Hour model):** 50% at close · 40% by 60 days · 10% by 90 days.

---

## 0. Source audit — what each system is actually fit for

Every source below was probed live on 2026-09-01. "Accepted-as" states the one role the design gives it; roles it *cannot* fill are stated as rejections with the evidence.

| Source | Accepted as | Rejected as / caveat |
|---|---|---|
| **ServiceMinder** (KTU + BTU keys, live) | **Revenue truth + forecast spine.** `Invoice.ProposalId` populated on 100% of sampled invoices → the accepted proposal is the job anchor. Proposals carry full `ProposalLines` (Qty, UnitPrice, `UnitCost`), `ChangeOrders[]` (→ Added Revenue POST SALE), `AcceptedDate`; invoices carry `Payments[]` (→ actual cash vs the 50/40/10 curve). Volumes: 213 KTU / 49 BTU invoices since 2025-01-01. | **Rejected as actual-cost source.** The SM Margins panel (dated vendor postings) is **not exposed by any API** — verified three ways (no costs/margins download kind; `proposal/details` has no postings array; `get_invoice` has none). Also: `query_proposals` returns only currently-open proposals (ETL must go invoice→`get_proposal`); KTU `ProposalLines.UnitCost` is nearly always null; some BTU proposals are lump-sum with zeroed lines (can't sum lines blindly). |
| **JobTread** (org `22PB4XPxGZHK`, both brands in one org) | **BTU estimate-side detail** (real budget lines: costType Labor/Materials, costCode, costGroup, unitCost/unitPrice — e.g. "Shower Labor: Waterproofing" 250/750) **+ job/status metadata + schedule windows.** | **Rejected as actuals and as KTU forecast.** Zero vendorBills, zero vendorOrders, zero customerInvoices org-wide — there is *no actual-cost data in JobTread at all*. `job.projectedPrice`/`actualCost` are 0/null even on budgeted jobs; sold price for imported KTU jobs literally lives as a numeric suffix in the job *name*. No KTU job carries any Labor-type cost line. No hard key to SM (fuzzy name+address only). Building the control inside JobTread would mean first building the data that isn't there. |
| **QuickBooks Online** (Zapier; 4 connections / 3 realms, default = the Oracabessa/BTU-labeled connection whose *content* is the KTU/combined operating books) | **Financial truth for what was actually incurred — and a mapping input we didn't expect:** on the 100 most recent bills, **93% of bill lines (645/696) already carry `CustomerRef` with customer-job names** ("Emily Berkowitz", "Marianne Ferrera"…) — the bookkeeper is already doing job mapping inside QBO. Per-vendor COGS subaccounts exist (`Job Materials - COGS: Elias Woodwork / Hardware Resources / Northern Contours / Orozco Bros / MSI…`) and **`Install Labor (SubContractors)` (Id 315)**. Paid-status backflow via BillPayment (recent payments run through Bill.com clearing, Chase, Ramp, Flex, Brex). | **Rejected as the mapping/control surface.** No held/exception workflow, no confidence scoring, no non-accountant UI — and through Zapier the QBO **query/report API is unusable** (realm interpolation broken; trigger reads capped at last-100 and ignore `connection_id`). Reports/queries need the direct Intuit connector, which in this session exposes only lending tools. So QBO is a sync source and truth check, not the place the gate lives. Purchases/expenses are the weak spot (~15% CustomerRef). |
| **ktubtubilling@gmail.com** (Zapier Gmail only — the direct `mcp__Gmail__` connector is stevenglivingston@, *not* this inbox) | **The invoice front door, high volume.** Already feeding `payables` (51 rows live, `source='email:ktubtubilling'`) with vendor, invoice #, amount and free-text PO hints ("PO: Rivera", "PO: ARENBERGBTU"). Live 5-day sample: 48 Richelieu invoices, Hardware Resources "Invoices for FIR112", Tile Shop, Wolf past-due, Bertch, Home Depot ×14, Floor & Decor ×7. | Caveats: hints are surname fragments, not ids (parser proposes, never disposes); Elias correspondence actually runs through tlivingston@kitchentuneup.com with personal Gmail cc'd — the front door has a side door, caught by the weekly QBO sweep. |
| **Supabase intranet** (`tguwpswcneywvscxzyef`) | **The system of record for the control** (see §2). Already holds `payables`, `bank_transactions` (with `matched_payable_id`), `project_schedule` (SM contact + proposal ids + install windows), `commissions` (per-job commission accruals from SM), `pnl_periods`/`pnl_commonsize` (benchmark-aware), and `foreman_board` — which already joins **SM contact ↔ JobTread job ↔ contract total** for 48 active jobs. | The planned `job_costs` intranet_records section was never populated ("empty org-wide" per Foreman) — replaced here by real tables; `intranet_records`' write-then-prune pattern is **rejected for costing data** (transactional history must never be pruned). |
| **Melio** | **Execution endpoint only — and brand new:** the trial went live **2026-08-31**, with "Melio Inbox Sync" connected to ktubtubilling the same day; zero Melio BillPayments exist in QBO yet. The gate lives upstream: nothing is scheduled in Melio unless the intranet shows it releasable. Verification is downstream: QBO BillPayment sync + `bank_transactions`. | Rejected as a control point — no API/MCP in this stack (zero references in any repo), and we can't block inside it. **Setup risk to close now:** Melio's Inbox Sync will pull the same invoices into its own pay queue; with any auto-pay/approval rule turned on it becomes a *bypass* of this control. Keep Melio approvals manual and sourced from the Releasable list. |
| **Catalog CSVs** (`KTU_Catalog.csv`, `KTU_Cost_Group.csv`, `KTU_Parameters.csv`) | **Category/cost-code dictionary + expected-cost baseline** for KTU forecast lines (JobTread has no KTU catalog). Vendor→category rules seed from `Custom Field: Item: Supplier/Vendor/Subcontractor`. | Static file — refresh manually when the JobTread template changes. |
| **Gusto / ADP payroll** | Employee-labor dollar totals per period (for §7 allocation). | No per-job timesheets exist anywhere — allocation is evidence-based, not source-based (stated as such on every row). |

---

## 1. Scope — end-to-end flow, invoice arrival → payment release

**Actors:** *Parser* = scheduled agent step (Moola's morning run + an on-demand sweep). *Matcher* = deterministic SQL + trigram matching in Supabase. *Mapper* = **Sonya** (works the queue and updates job costing; decision 2026-09-01). *Approver* = Steven or Sonya, for both override paths. *Payer* = whoever operates Melio (today: Steven/Sonya).

| # | Step | Who/what | Failure mode & catch |
|---|---|---|---|
| 1 | Vendor emails invoice PDF → `ktubtubilling@gmail.com` | vendor | Invoice goes to the wrong inbox / arrives on paper. Catch: weekly QBO-bill sweep (step 8) finds bills with no matching payable → exception "arrived outside the front door". |
| 2 | Parser reads inbox, writes/updates `payables` row: vendor, invoice #, amount, dates, `po_hint` (raw PO/customer text), brand | Parser (already live for Elias et al.) | OCR/parse miss on amount or duplicate email → dedupe rule (same vendor+invoice # = update, same vendor+amount±$1+~date = duplicate-suspect exception). |
| 3 | Matcher proposes job + category (+ sold line where resolvable), writes `mapping_status='auto_mapped'` + confidence, or `held` + `held_reason` | Matcher | Wrong-job auto-map (two active jobs, same surname). Catch: auto-map is never releasable by itself — a human confirm (step 5) is always required before payment. |
| 4 | Unmappable/low-confidence invoices land on the **exceptions queue** (`jc_exceptions` view, rendered in the intranet Job Costing tab) with reason: `no matching job` / `ambiguous (N candidates)` / `over remaining forecast` / `duplicate suspect` / `job already complete (go-back?)` | system | Queue ignored → it's on the intranet home tab count + Moola's morning brief; anything held >7 days escalates to a Slack callout. |
| 5 | Mapper works the queue: confirm the proposed map, pick job+category+line manually, split across jobs, mark go-back/rework, or route to `overhead_non_job` (rent, insurance…) | Mapper | Mis-categorisation (labor vs materials). Catch: vendor→category defaults + the per-job JCA view makes a mis-bucketed line visible as a benchmark breach. |
| 6 | **Gate:** payable → `scheduled` (queued in Melio) or `paid` is **blocked by a DB trigger** unless `mapping_status ∈ (confirmed, override)` or category `overhead_non_job`. Override requires who + why and is written to `jc_override_log` permanently. | DB + Payer | The real-world hole: Melio doesn't ask Supabase. The procedural rule is *the Payer schedules only from the intranet "Releasable" list*; the backstop is step 9 — a Melio/bank payment with no releasable payable = a red "paid outside control" flag, so violations are caught within a day, not silently. |
| 7 | Mapped invoice writes `jc_actual_costs` row(s) (splits allowed; splits must sum to the payable — `jc_split_mismatch` view enforces) against the job's forecast lines | system | — |
| 8 | Weekly: QBO Bills sync → any QBO bill with no payable = retro exception ("arrived outside the front door"), and **each bill line's `CustomerRef` (present on 93% of lines) is harvested as a high-confidence mapping proposal** — the bookkeeper's existing QBO job-tagging feeds the matcher instead of being re-derived. Gusto lump payments hitting `Install Labor (SubContractors)` → the weekly labor-allocation queue (§7) | Parser | Crew paid without job naming → allocation queue forces it weekly (§7); QBO Purchases (~15% CustomerRef) are the weak sweep — flagged as unmapped spend, not silently skipped. |
| 9 | Payment verification: QBO BillPayment + `bank_transactions.matched_payable_id` mark payables `paid`; the JCA card's cash line compares collections (SM `Payments[]`) against the 50/40/10 Power Hour curve | Moola run | Bank debit with no payable → "paid outside control" exception. |
| 10 | Job close: status → `complete` requires zero held invoices for that job; the JCA card freezes as the final per-job P&L (§5) | Mapper | Late invoices after close arrive as **go-back candidates** (step 4 reason), keeping post-completion cost isolated instead of silently degrading a closed margin. |

---

## 2. Where it lives — recommendation

**Recommendation: the existing intranet + Supabase. Not Google Sheets. Build one, not both.**

Why, judged against the control itself:

1. **The control is a state machine with a gate.** HELD → mapped → confirmed → released → paid, with overrides that must be *recorded*. Postgres enforces this in a trigger (`jc_payment_gate`) and an append-only `jc_override_log`. A spreadsheet cannot refuse a row edit; "held" in Sheets is a cell color someone can ignore, and an override leaves no trace.
2. **The join spine already exists there.** `foreman_board` already carries `sm_contact_id` + `jobtread_job_id` + `contract_total` per active job; `payables` already ingests ktubtubilling; `bank_transactions` already matches payables; `commissions` already accrues per-job commission from SM. Sheets would re-derive all of it by hand.
3. **The per-job workbook is the failure being replaced.** The live `Job Cost Analysis sheet - KTU .xlsx` (48 customer tabs) is exactly "Sheets per job rolling up" — and it coexists with 56 jobs at $0 labor. Same inputs, same hands, same outcome.
4. **Agents maintain it daily.** Moola/Foreman routines already write these tables every morning; freshness is watchdogged. Sheets have no watchdog.

**Cost of rejecting Sheets (stated honestly):** the team loses the familiar grid for ad-hoc noodling, and HFC coaching submissions expect the JCA workbook shape. Mitigations shipped with the design: the intranet JCA card renders the ProfitabilityTracker layout 1:1, and a per-job **"Export JCA (CSV/XLSX)"** produces the HFC-shaped workbook on demand — the spreadsheet becomes an *output*, never the system of record.

---

## 3. Schema

New Postgres tables (migration `supabase/migrations/20260901_job_costing.sql` on this branch). `intranet_records` sections are deliberately **not** used — costing is transactional and must never be write-then-pruned.

```
jc_jobs               1 row per sold job. Anchor: (brand, sm_proposal_id) unique.
                      Carries sm_contact_id, jobtread_job_id, contract_total
                      (= Forecasted Sale), added_revenue_post_sale (= signed COs),
                      service_type, status, commission_pct.
jc_forecast_lines     the SOLD side. description, category (direct_materials|
                      contract_labor|employee_labor|sales_commission|other), qty,
                      unit_cost, forecasted_cost, amount_charged, cost_code,
                      vendor_hint, is_change_order, source (sm_proposal|
                      sm_change_order|jobtread|catalog|manual) + source_line_id.
payables (+columns)   the inbound invoice. Adds: job_id, jc_category,
                      forecast_line_id, mapping_status (unmapped|auto_mapped|held|
                      confirmed|override), mapping_confidence, held_reason,
                      mapped_by/at, is_unplanned + unplanned_kind (go_back|rework|
                      unplanned), qbo_bill_id, po_hint.
jc_actual_costs       the ACTUAL side. job_id, category, vendor, amount,
                      payable_id (nullable), forecast_line_id (nullable),
                      is_unplanned/unplanned_kind, source (payable|qbo_bill|
                      labor_alloc|commission|manual). A payable may split into
                      several rows across jobs; jc_split_mismatch view enforces
                      sum(splits)=payable.
jc_labor_allocations  person, labor_kind (contract|employee), week_start, job_id
                      (nullable → bucket bench|shop|warranty), days, amount,
                      evidence, payable_id/source_ref. Trigger mirrors job rows
                      into jc_actual_costs.
jc_override_log       append-only: payable, amount, reason, approved_by, when.
Views: jc_exceptions (the queue), jc_job_pnl (per-category forecast vs actual),
       jc_job_summary (job rollup + HFC benchmark verdicts), jc_split_mismatch.
```

**Keys.** Job identity = ServiceMinder accepted proposal (`brand`,`sm_proposal_id`) — the only id that is populated on 100% of revenue records and that change orders hang off. JobTread joins into it by fuzzy `customer name + address` (there is no hard key; JT's 8-digit imported numbers were probed against SM and match nothing). A vendor invoice line joins to a sold line as `payables.forecast_line_id → jc_forecast_lines.id`, with `job_id + jc_category` as the mandatory coarse join.

**The join that will break most often — vendor invoice line → sold line.** Three reasons, all observed in live data:
1. The invoice names the job as a **free-text surname fragment** ("PO: Rivera", "PO: Louise-Remake") that must trigram-match a customer name — same-surname collisions and one invoice covering two jobs (Peyser reface + Peyser new-cabinets are separate tabs today) are routine.
2. The sold line it should map to **often doesn't exist as a costed line**: KTU proposal lines carry null `UnitCost`, some BTU proposals are lump-sum with zeroed lines, and KTU JobTread budgets are "Z. Selections" placeholders. You cannot FK onto a line that was never sold at line granularity.
3. Vendors invoice at **different granularity** than the sale (Elias invoices per shipment; the sale is "Refacing: per door all-in").

Design answer: the **hard gate is job + category** (always resolvable, always required); `forecast_line_id` is best-effort — auto-suggested where a category has exactly one costed forecast line, human-picked otherwise, and *allowed to stay null with the category-level check applied instead* (invoice amount vs remaining category forecast). Pretending line-level joins will always exist is how the control would rot in week two.

---

## 4. Auto-population — how far parsing gets on its own

**Parser (per email):** vendor (sender domain map), invoice #, amount, invoice/due dates, PO/customer hint, brand. This already works for the Elias-style flow (51 live payables prove it). Confidence on parse fields is not the issue; **identity is**.

**Matcher (per payable), in order:**
1. `po_hint` trigram match against `jc_jobs.customer_name` (active jobs first) — pg_trgm similarity.
2. QBO `CustomerRef` on the synced bill line (when the bill exists in QBO) — the bookkeeper's own job tag; treated as high confidence (≥0.9) but still requiring the same one-click confirm.
3. Vendor+amount match against open vendor orders/forecast lines (`vendor_hint`), e.g. an Elias invoice ≈ the Elias order confirmation amount for one job.
4. Single-candidate fallback: vendor sells only into one active job right now.
5. Category from vendor→category rules (Elias/HW Resources/MSI → direct_materials; Orozco Brothers/crew names → contract_labor; …), overrideable per line.

**Thresholds (default — flip per Steven's call in the decision batch):**
- similarity ≥ **0.85** and unique candidate → `auto_mapped` (job+category prefilled, one-click confirm).
- 0.5–0.85 or 2+ candidates → `held`, reason `ambiguous (N candidates)`, candidates listed on the queue row.
- < 0.5 → `held`, reason `no matching job`.
- Regardless of score: invoice > remaining category forecast → held with `over remaining forecast`; job status complete → held with `job complete — go-back?`; near-duplicate → held with `duplicate suspect`.

**A human always confirms:** payment release itself (auto_mapped is never releasable — confirm is the click), every override (with reason, logged), every split across jobs, every go-back/rework designation, and every labor allocation that isn't backed by a crew invoice naming the job.

---

## 5. Per-job P&L output (the JCA card)

Rendered per job in the intranet (and exportable as the HFC-shaped workbook), straight from `jc_job_pnl` / `jc_job_summary`:

```
REVENUE      Forecasted Sale $X · Added Revenue POST SALE $Y · Total $Z
COSTS        (per category: Direct Materials, Contract Labor, Employee Labor,
              Sales Commission)
             Forecasted $ | Actual $ | Actual % of revenue | Variance $ | HFC benchmark verdict
GO-BACKS / REWORKS / UNPLANNED   isolated block: rows + total $ + % of revenue
                                 (never blended into the category lines above)
GROSS MARGIN  forecast GM% vs actual GM% vs HFC 50–55% band
CASH          collected-to-date (SM Payments[]) vs the Power Hour curve:
              50% at close · 40% by day 60 · 10% by day 90 — ahead/behind flag
COVERAGE      % of contract value backed by real forecast costs, and count of
              held invoices — a GM% is never shown without its coverage
              (Foreman's validated rule: high GM% on 30% coverage is missing
              data, not health)
```

Benchmark verdicts use the HFC numbers verbatim (GP 50–55%, Labor <15%, DM <30%, Commission <8%); G&A 10–13% / Marketing 8–10% / Royalty 6.5% / NAF 1% are company-level lines and stay on the existing `pnl_commonsize` view, not per-job (they are not job costs — stated assumption).

---

## 6. Phased build

**Phase 1 — this week, on live jobs (shipped on this branch):**
- Migration above (tables, gate trigger, override log, views).
- Seed `jc_jobs` from `foreman_board` (48 active jobs: SM ids, JT ids, contract totals, service types) + `commissions` (per-job commission forecast lines).
- Seed forecast lines per job: SM accepted proposal lines via invoice→`get_proposal` (price side always; cost side where UnitCost exists), JobTread budget lines for BTU, catalog-anchored estimates for KTU where line costs are null (labeled `source='catalog'`).
- Retro-map the 51 existing payables from their `po_hint`s; everything unmatched lands on the queue day one.
- Intranet **Job Costing tab**: exceptions queue (with candidate picker + confirm/hold/override/split actions), releasable list (what the Payer may schedule in Melio), per-job JCA cards.
- Procedural rule goes live: **Melio scheduling happens only from the Releasable list.**

**Phase 2 — next 2 weeks:** QBO Bills weekly sync (crew bills included) with retro-exception for out-of-band bills; paid-status backflow (BillPayment + bank match → `paid`); weekly labor-allocation queue (§7); go-back workflow polish; Moola/Foreman routine steps updated to maintain it daily; held->7d Slack escalation.

**Phase 3:** 2025 backfill reconciliation (the $215,623 / $201,126 — §7) job by job; HFC workbook export; JobTread write-back of budgets/actuals *if* Steven wants JT to stop being estimate-only (optional — the control does not depend on it); BTU catalog gap-fill.

---

## 7. Closing the labor gap (the 56 × $0-labor jobs)

Verified this session: JobTread contains **zero** vendor bills and **no KTU Labor-type cost lines at all** (53 of 207 2025 jobs have labor > $0 — nearly all BTU; KTU budgeted-but-no-labor + item-less KTU imports cover the ~56). Meanwhile QuickBooks carries the real money (~$215,623 subcontractor install labor, ~$201,126 payroll, 2025). The gap exists because **labor is paid from QBO/Melio/payroll, which never asks "which job?"** — and JobTread only ever received estimates.

> Verification note (audited live): Miguel Bara (QBO vendor Id 450) and Jerson Godoy (Id 1187) exist as vendors but were only created in 2026 with zero bills — **the crew is actually paid through Gusto lump payments** (Gusto is the top purchase vendor; 7 of its 11 recent transactions hit `Install Labor (SubContractors)` Id 315). Oscar Yupa Herrera wasn't findable by exact-match vendor search (spelling variant likely). The $215,623 / $201,126 figures could not be re-verified through the Zapier pipe (no query/report API — realm interpolation broken); the accounts they live in exist and are active, and the verification query belongs to the direct Intuit connector's P&L (Phase 3 backfill step).

How the design closes it — money is trapped at the point of payment, not requested afterwards:
1. **Crew pay cannot leave the building unallocated.** The weekly Gusto contractor payment for Miguel Bara, Oscar Yupa Herrera, Jerson Godoy lands (via the QBO sweep of `Install Labor (SubContractors)` postings) on the **labor-allocation queue** — same posture as a held invoice: the week's amount must be split across the jobs they worked before the next cycle, or it sits red on the queue. Per decision #4, the split is made centrally from the JobTread daily worker-assignment calendar, corroborated by CompanyCam photo status.
2. **Fixed-crew allocation, not lump.** Each crew week splits in `jc_labor_allocations` across the jobs worked, by days-on-site, with evidence recorded (JobTread daily assignment > CompanyCam photo presence > install schedule > even split, flagged). Bench/shop/warranty weeks go to the non-job buckets — jobs stay honest *and* the fixed cost stays visible; nothing disappears into "overhead".
3. **W2 install labor** allocates the same way from payroll totals (category `employee_labor`), method recorded on every row. (Whether to allocate all W2 install labor or keep W2 in overhead for v1 is Steven's call — in the decision batch.)
4. **Backfill (Phase 3):** pull the 2025 `Install Labor (SubContractors)` and payroll activity from the direct Intuit P&L (verifying the $215,623 / $201,126 as the first act), then allocate across the 56 jobs by install-window overlap (`project_schedule`), labeled `evidence='allocated-by-window'` — an honest approximation that turns the lump into per-job labor, distinguishable from confirmed rows.

---

## 8. Decisions — asked as a batch 2026-09-01, answered by Steven

1. **Override authority: Steven or Sonya.** Only those two identities may set `mapping_status='override'`; the UI exposes the override action to their profiles only, and `jc_override_log` records who + why on every use. No dollar threshold.
2. **Auto-map threshold: ≥0.85 accepted.** Machine pre-fills job+category at strong PO-hint / QBO-CustomerRef confidence; a human one-click-confirm is still required before anything is releasable.
3. **W2 payroll: allocate to jobs from day one.** Weekly payroll totals split by install-day evidence into `employee_labor`, so the JCA Employee Labor column and the HFC Total-Labor <15% check are real.
4. **Crew allocation: central, driven by JobTread assignments.** Per Steven: use JobTread to see who's assigned to jobs (the daily worker-assignment calendar/tasks), with CompanyCam photo status corroborating what actually happened. So the evidence hierarchy for `jc_labor_allocations` is: **JobTread daily assignment > CompanyCam presence > install schedule > even split (flagged)** — no crew-invoice process change; the weekly Gusto lump still cannot leave the allocation queue unsplit.

## 9. Assumptions register

- ProfitabilityTracker structure taken from the brief verbatim (workbook not in session filesystem/Drive) — §top.
- Commission forecast = `jc_jobs.commission_pct × contract` (8% default, 12% self-gen per the SM `commissions` data); actual = the accrual rows already computed in the `commissions` section.
- Consultations are never modeled as cost or revenue lines (standing business rule).
- G&A/Marketing/Royalty/NAF benchmarks apply at company level (`pnl_commonsize`), not per job.
- Melio cannot be read or blocked programmatically; the gate is upstream (releasable list) with a downstream tripwire (bank/QBO payment with no releasable payable).
- `intranet_records` write-then-prune is unsuitable for costing; real tables used instead.
- KTU forecast cost lines built from the catalog CSVs are estimates and labeled as such; coverage % is always displayed next to GM%.

---

# Part 2 — decisions and build of 2026-09-01 (later the same day)

## 10. New decisions recorded

| # | Decision (Steven) | How it is implemented |
|---|---|---|
| 5 | **Sonya works the queue and updates job costing.** | She had an admin login but `payables` is RLS-gated to `has_finance_access()` and her flag is **false** — she could not have seen the queue at all. Rather than grant `finance_access` (which also opens owner-only Financial Reporting / Cash Flow, incl. personal financials), a new least-privilege capability `profiles.jc_access` + `has_jc_access()` opens job costing **and nothing else**. Sonya = true; the owner accounts inherit via `finance_access`. Ben and Takia are excluded, and the tab is hidden from them by the same capability so the UI and the RLS agree. |
| 6 | **Overrides must be creatable.** | Two override paths now exist, both recorded permanently in `jc_override_log` with who + why: `unmapped_override` (pay an invoice with no job mapping) and `margin_escalation` (release a payout on a job below the margin floor). Both are restricted to Steven and Sonya. |
| 7 | **Anything below 45% gross margin escalates before payout.** | `jc_job_gm(job)` = (revenue − projected cost) / revenue, where projected cost is the **worse** of forecast and actual-to-date, so a job cannot look healthy merely because costs have not landed. The payment gate blocks `scheduled`/`paid` on any job under 45% until a named approver releases it with a reason. `jc_refresh_escalations()` flags them ahead of time so the queue shows them before anyone tries to pay. |
| 8 | **Map items to the proposal and JobTread breakouts.** | `mcp-servers/jc-forecast-sync.py` — deterministic ETL (curl, no LLM in the financial path). Live result: **1,049 real sold lines across all 48 jobs, $880,446 of charged value**. |
| 9 | **Flag under/over-priced items and where to focus.** | `jc_item_variance` (same item across jobs → avg charged vs avg actual cost → verdict) and `jc_focus` (open jobs, worst margin first, with coverage). Both rendered on the Job Costing tab. |

## 11. What the ETL proved about our own data

**Sold lines exist; costs do not.** The 1,049 ServiceMinder proposal lines carry
**$880,446 of price** but only **$39,852 of cost** — KTU proposals ship with
`UnitCost` null, exactly as the source audit predicted. Consequences, stated
plainly because they shape how much the numbers can be trusted:

- **JobTread breakouts are empty for these jobs.** The ETL pulled cost items for
  all 48 active jobs and got **zero**. The "JobTread breakout" half of the
  mapping does not exist yet for live work; ServiceMinder is the only sold-line
  truth today. (The BTU catalog *does* hold real costed items — but not attached
  to these jobs' budgets.)
- **A sequencing mistake, corrected:** the first ETL run deleted the Foreman
  category estimates as "superseded" by the new proposal lines. They are not
  redundant — SM gives line *detail and price*, the estimate gives the only cost
  *baseline*. The $410,948 cost baseline was restored, and the ETL now only
  drops an estimate row where a genuinely **costed** line replaces it.
- **Therefore most margins are estimate-based today.** `jc_job_cost_coverage()`
  reports 0% on nearly every job, and the KTU estimate anchor (COGS at 30% of
  sell + labor + 8% commission) lands almost every KTU job at ~41%. So on day one
  the 45% floor would escalate nearly everything.
  **This is why every escalation states its basis** — "ESTIMATE-based, 0% cost
  coverage" vs "measured" — so an approver knows whether they are releasing
  against evidence or against an assumption. As mapped invoices land, coverage
  rises and the same gate starts biting on facts.
  *Open question for Steven (not blocking):* keep the hard block on
  estimate-based margins, or make estimate-based escalations advisory and hard-block
  only once coverage ≥ 25%? One line of SQL either way.

## 12. Labor: what Gusto, JobTread and CompanyCam can actually carry

Steven's instruction was to use **Gusto** for the labor dollars and pull
**CompanyCam** + **JobTread assignments** for the split. All three were audited
live. The honest position:

| Source | What it really holds | Verdict for allocation |
|---|---|---|
| **Gusto** | The connector in this stack exposes **time-off and Plaid banking only** — no payroll runs, no contractor payments, no compensation. No `GUSTO_*` credential exists in the environment either. | **Cannot supply dollars today.** Two ways in: (a) a Gusto API token → a `mcp-servers/gusto.sh` curl helper (the pattern `sm.sh`/`ghl.sh` already use), which would give **per-person** amounts; or (b) QBO, where Gusto already posts — 7 of its 11 recent transactions hit `Install Labor (SubContractors)` (acct 315). QBO gives the weekly **total**, not per person. |
| **JobTread assignments** | Tasks carry `assignedMemberships{user{name}}`, and all three crew exist as memberships (**Miguel** `22PT3Vk6pQva`, **Oscar Herrera** `22PV9W4Rvpx9`, **Jerson Godoy** `22PV9W9DvUGK`). But: `timeEntries` = **0 rows, ever**; no hourly rates on any membership; crew tasks are multi-week **"Project Window"** spans (5–47 days) with no times; ~50% of 2026 scheduled tasks have no assignee; Oscar and Jerson have **one task each, ever**. | **Coarse presence only** — "Miguel was on job X sometime in this window", and windows overlap, so a *day* cannot be attributed to one job. |
| **CompanyCam** | A genuinely good signal: photo `creator_id` + `project_id` + `captured_at`, geo-verified to ~10 m of the project with ~0 min upload lag. 1,018 photos across 36 projects in August. | **But the crew is missing from it.** Oscar and Jerson have **no CompanyCam seats at all**; "Miguel O" exists on Steven's BTU email address, unverified. One photographer covers a whole crew (only 4 of 80 project-days had 2+ shooters), and photo bursts (~0.1 h) cannot measure hours. |

**So the design allocates honestly rather than pretending to measure.** The
weekly crew total (from QBO/Gusto) is split across jobs by **evidenced job-days**
— CompanyCam activity per project per day, attributed by JobTread assignment
windows — and every row records its `evidence` grade. That is a defensible
proportional allocation, materially better than a lump, and it is labelled as an
allocation, never as measured labor.

**The one change that makes labor real:** JobTread time tracking is *already
switched on* (`showTime: true`, `costTrackingType: "costItem"`) and nobody has
ever clocked in. If the three 1099s clock in against a job, `timeEntry` yields
`user → job → minutes → cost` directly — the exact allocation primitive, no
inference at all. Second-best: CompanyCam seats for Oscar and Jerson, and the
"Miguel O" seat renamed and verified.

## 13. Feeding actual costs back into JobTread (plan)

Goal: as invoices are confirmed in the intranet, JobTread stops being
estimate-only and shows real actuals, so PMs see one truth.

**Verified against the live API** (grant key, `api.jobtread.com/pave`): the
mutations `createCostItem`, `updateCostItem` and `createDocument` all exist at
the query root. `createVendorBill` does **not** — a bill is a `createDocument`
with a vendor-bill type. Exact argument shapes still need one short spike against
JobTread's Pave docs before implementing; everything below is contingent on that.

**Recommended shape — write a vendor bill, not a budget edit.** JobTread derives
`job.actualCost` from vendorBill/vendorOrder documents plus time entries. Writing
documents keeps JobTread's own rollups correct; overwriting `costItem.unitCost`
would silently corrupt the *estimate* baseline we need for variance.

Flow, once per confirmed invoice (or nightly in batch):
1. Trigger: a payable reaches `mapping_status='confirmed'` and its job carries a
   `jobtread_job_id`.
2. Resolve or create the JobTread vendor (`createVendor` exists; match on name).
3. `createDocument` type vendorBill on that job — vendor, issue date, our
   invoice number, amount, and a line per `jc_actual_costs` row, mapped to the
   JobTread `costItem` where `forecast_line_id` resolves to one and to the job's
   catch-all cost code where it does not.
4. Store the returned document id on the payable (`jobtread_doc_id`, new column)
   so the sync is **idempotent** — never post the same invoice twice.
5. Reconcile nightly: any confirmed payable with no `jobtread_doc_id` is a failed
   push and goes on the exceptions queue, exactly like an unmapped invoice.

**Guardrails.** One-way (intranet → JobTread) for actuals; JobTread stays the
estimate source. Never write to a closed job. Dry-run mode first, on one job,
compared against the JobTread UI before enabling for all. And the write-back is
strictly a *mirror* — the payment gate remains in Supabase, because JobTread has
no held state to enforce it.

**Sequencing note:** this is only worth building once the queue is being worked
daily — pushing 0 actuals into JobTread achieves nothing. Phase 2, after the
QBO sync and the labor allocator.
