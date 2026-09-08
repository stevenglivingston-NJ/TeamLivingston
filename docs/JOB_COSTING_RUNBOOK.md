# Job Costing — daily runbook (Sonya)

**Where:** https://dash.goaxyom.com → **Job Costing** (visible to Sonya and Steven only).
**The one rule:** payments are scheduled in Melio **only** from the *Releasable*
list on this page. If it isn't on that list, it doesn't get paid.

## 1. Work the exceptions queue (≈15 min/day)

Every inbound vendor invoice lands here until it is mapped to a job. Nothing on
this list can be paid — the database itself refuses.

| What you see | What it means | What to do |
|---|---|---|
| **auto-mapped @ 87%** | The matcher found the job from the invoice's PO/customer hint. | Check the job is right → **Confirm**. |
| **ambiguous (3 candidates for "Peyser")** | More than one job matches that name. | Pick the right job from the dropdown → **Confirm**. |
| **no PO/customer hint on the invoice** | The invoice never said which job it was for. | Find out (vendor, PO, or ask the PM), pick the job → **Confirm**. |
| **no matching job for "GORDON"** | We have no job by that name. | Either it's a job not yet in the system (add it in the Job board box), or it's not a job cost at all → set category **Overhead — not a job cost**. |
| **job complete — go-back?** | The job is finished and a new cost arrived. | Tick **Go-back?** before confirming, so it lands in the go-backs block instead of quietly eating the job's margin. |

Press **↻ Run matcher** first — it picks up anything new and re-checks margins.

## 2. Release for payment

The *Releasable* list is what's cleared. Two things can still stop a row:

- **⚠ margin escalation** — this job's projected gross margin is **below 45%**.
  Only you or Steven can release it, and it asks why. That reason is recorded
  permanently. Read the basis first: *"ESTIMATE-based, 0% cost coverage"* means
  the margin is a forecast assumption, not measured cost; *"measured"* means real
  invoices are behind it and it deserves a harder look.
- **Override** — an invoice being paid with no job mapping at all. Same rule:
  you or Steven, with a reason, recorded forever. Use it rarely; it's the escape
  hatch, not the workflow.

Then mark **Scheduled in Melio** when you queue it there, and **Mark paid** when
it clears.

## 3. Keep the job list honest

- **Focus** shows every open job worst-margin-first. Anything red is under the
  45% floor. **Cost coverage** tells you how much to trust it — 0% means no
  invoices have landed yet.
- **Pricing variance** fills in over time and flags items we're systematically
  under- or over-pricing across jobs. It stays empty until enough invoices are
  mapped — that's expected, not broken.
- **Job board** is the JCA per job: forecast vs actual by category, go-backs
  isolated, HFC benchmark chips (GP 50–55% · Labor <15% · Materials <30% ·
  Commission <8%). Click a row to see the cost lines behind it.

## 4. If something looks wrong

- A job missing → add it in the **Job board** box (name, brand, contract $).
- An invoice mapped to the wrong job → re-pick the job and Confirm again; the
  actual-cost line follows the mapping.
- The queue looks stale (no new invoices for days) → the billing-inbox feed has
  stopped; tell Steven. The gate only guards invoices that actually arrive.
