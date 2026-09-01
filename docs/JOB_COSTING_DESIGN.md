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

**Actors:** *Parser* = scheduled agent step (Moola's morning run + an on-demand sweep). *Matcher* = deterministic SQL + trigram matching in Supabase. *Mapper* = whoever works the queue (Mayra day-to-day, Steven for overrides). *Payer* = whoever operates Melio (today: Steven/Mayra).

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
1. **Crew pay cannot leave the building unallocated.** The weekly Gusto contractor payment for Miguel Bara, Oscar Yupa Herrera, Jerson Godoy lands (via the QBO sweep of `Install Labor (SubContractors)` postings) on the **labor-allocation queue** — same posture as a held invoice: the week's amount must be split across the jobs they worked before the next cycle, or it sits red on the queue. If the crew moves to submitting weekly invoices naming jobs (decision #4), those invoices flow through the ordinary payables gate instead — cleaner still.
2. **Fixed-crew allocation, not lump.** Each crew week splits in `jc_labor_allocations` across the jobs worked, by days-on-site, with evidence recorded (crew invoice naming jobs > install schedule > CompanyCam photo presence > even split, flagged). Bench/shop/warranty weeks go to the non-job buckets — jobs stay honest *and* the fixed cost stays visible; nothing disappears into "overhead".
3. **W2 install labor** allocates the same way from payroll totals (category `employee_labor`), method recorded on every row. (Whether to allocate all W2 install labor or keep W2 in overhead for v1 is Steven's call — in the decision batch.)
4. **Backfill (Phase 3):** pull the 2025 `Install Labor (SubContractors)` and payroll activity from the direct Intuit P&L (verifying the $215,623 / $201,126 as the first act), then allocate across the 56 jobs by install-window overlap (`project_schedule`), labeled `evidence='allocated-by-window'` — an honest approximation that turns the lump into per-job labor, distinguishable from confirmed rows.

---

## 8. Decisions for Steven (asked once, as a batch)

1. **Override authority** — who may release an unmapped invoice, and is there a $ threshold below which Mayra can, above which only Steven?
2. **Auto-map threshold** — accept the ≥0.85 auto-map + one-click confirm default, or start with everything human-mapped?
3. **W2 payroll scope** — allocate all install-tech W2 payroll to jobs (full JCA Employee Labor), or v1 = 1099 + materials + commission only?
4. **Crew process** — require Miguel/Oscar/Jerson to submit weekly invoices naming jobs (process change, cleanest evidence), or allocate centrally from schedule/photos?

## 9. Assumptions register

- ProfitabilityTracker structure taken from the brief verbatim (workbook not in session filesystem/Drive) — §top.
- Commission forecast = `jc_jobs.commission_pct × contract` (8% default, 12% self-gen per the SM `commissions` data); actual = the accrual rows already computed in the `commissions` section.
- Consultations are never modeled as cost or revenue lines (standing business rule).
- G&A/Marketing/Royalty/NAF benchmarks apply at company level (`pnl_commonsize`), not per job.
- Melio cannot be read or blocked programmatically; the gate is upstream (releasable list) with a downstream tripwire (bank/QBO payment with no releasable payable).
- `intranet_records` write-then-prune is unsuitable for costing; real tables used instead.
- KTU forecast cost lines built from the catalog CSVs are estimates and labeled as such; coverage % is always displayed next to GM%.
