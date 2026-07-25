---
name: job-pacing
description: >-
  Pull a single KTU/BTU job across every system and produce a crew/PM-facing
  pacing tracker with an Ahead / On Target / At Risk / Behind Target status call.
  Trigger this ANY time Steven names a project and says "pacing" — e.g.
  "Murchison pacing", "how are we pacing on the Annunziato job", "Schnaufer job
  pacing", "pacing on 66 Lenox" — even if he doesn't spell out the steps. Merges
  ServiceMinder scope + change orders, JobTread schedule + budget, the KTU Google
  Drive design packet & selections, and CompanyCam field photos into one dated
  progress board against the target completion date. Use whenever the ask is "how
  are we doing / how are we pacing / are we on track" on a specific bath or kitchen
  remodel job.
model: inherit
---

# Job Pacing Tracker (KTU / BTU)

When Steven says **"<project name> pacing"** (or any "how are we pacing on X"
phrasing), he wants one thing: a clear read on whether a specific remodel job is
going to hit its target completion date, grounded in every system that holds a
piece of the truth. No single system has the whole picture — the money and scope
live in ServiceMinder, the schedule and budget in JobTread, the design intent in
Google Drive, and the *actual field progress* only in CompanyCam photos. Your job
is to stitch them together and make an honest call.

The deliverable is a **one-page tracker artifact** (crew + PM facing) ending with
a four-state status verdict. Steven shares this with the field crew and the PM, so
it must be accurate, specific to the real finish selections, and skimmable.

## The target date

Steven usually says the target completion date in his message ("target complete
Aug 4"). If he doesn't, pull it from the JobTread schedule (`taskSummary.endDate`)
and say that's where it came from. The whole verdict is measured against this date.

## Step 1 — Find the job in every system (names vary, search widely)

Customer names are spelled inconsistently across systems (e.g. **Murchison** in
ServiceMinder vs **Murchinson** in CompanyCam/Drive). Addresses vary too ("Lenox"
vs "Lennox", "Ter" vs "Terrace"). So search by **name variants AND address
fragment**, and don't give up after one spelling.

Run these in parallel:

- **ServiceMinder** — `find_contact` in **both** `KTU` and `BTU` locations, by
  `name_search` and by `address_search`. The job is whichever location returns a
  match. The contact result includes `OpenInvoices` and `OpenProposals` — note
  those IDs. Record the `LocationID` and `Id` (contact id).
- **CompanyCam** — `search_projects` by name and by street fragment. Grab the
  `project_id` and `photo_count` of the real match (ignore ZZ TEST / zero-photo
  stubs). The project may also list a JobTread integration and a "Job N" number.
- **JobTread** — get org id once: `{"currentGrant":{"organization":{"id":{}}}}`.
  KTU/BTU share one org ("Kitchen Tune-Up Bloomfield"). Then find the job (see
  Step 3 for the query quirks) — it is often named **"Job N"** by number, not by
  customer name.

## Step 2 — ServiceMinder: scope, change orders, schedule

- `get_invoice` on the customer's remodel invoice → this is the **authoritative
  scope of work**. The parent line carries the price; the child lines (rate $0)
  are the itemized work: demo, decommission, shower pan/valve, waterproofing,
  drywall, niche, wetwall/tile, flooring, vanity/top, faucet, linen, mirror,
  toilet, fan, paint, general conditions, dumpster, project fee.
- `query_appointments` (contact_id) → consult vs production appointments and who's
  assigned. Often only the consult is booked here; production lives in JobTread.
- Check `OpenProposals`. Any recent one is likely a **change order** — pull it with
  `get_proposal`. `ChangeOrderForProposalId` links it to the original. Report new
  scope (added electrical, extra fixtures) since it affects the schedule. If
  Steven says to ignore financials/sign-offs, still capture the *scope* a change
  order adds — just drop the dollars and approval status.

## Step 3 — JobTread: schedule + budget (mind the query quirks)

The Pave JSON API has two traps that will waste your time if you forget them:

1. **The `like` operator silently returns nothing.** Only exact match works:
   `"where": [["name"], "=", "Job 80"]`. Since jobs are usually named "Job N",
   get the number from the CompanyCam project, or list recent jobs
   (`sortBy` createdAt desc) and eyeball it, or match on `location.address`.
2. **`projectedPrice` / `projectedCost` often come back `null`** even when a budget
   exists. Get the budget by summing cost items instead:
   ```
   {"job":{"$":{"id":"<id>"},
     "b":{"_":"costItems","totalPrice":{"_":"sum","$":"price"},
          "totalCost":{"_":"sum","$":"cost"},"count":{}}}}
   ```
   `price − cost` is projected gross profit (drop if Steven says ignore financials).

Pull `taskSummary` (`startDate`, `endDate`, `completed`, `unstarted`, `progress`)
and the `tasks` nodes. **Reality check:** the schedule is frequently a single
lumped task marked "unstarted" with no progress updates. When it is, say so —
it means JobTread is NOT a live pacing signal and CompanyCam photos are the only
real one. Also flag if `taskSummary.endDate` runs **past** the target date.

## Step 4 — KTU Google Drive: the design plan & selections

The exact finish products the crew installs live in the job's Drive folder, not in
the generic ServiceMinder line items. `search_files` uses a **structured query**,
not free text:

```
title contains 'Lenox' or fullText contains 'Murchison'
```

Find the job folder (e.g. "Murchinson (66 Lenox Ter...)"). Inside are subfolders
like **Layout & Presentation** (design packet, e.g. "M. <Name> Presentation.pdf")
and **Specs & Materials** ("Selections … Job N ….pdf" plus individual spec sheets).
Read them with `read_file_content` (it handles PDFs). The **Selections** doc is the
finish schedule — capture the real specs (brand/model/finish) for shower walls
(e.g. Sentrel panel + finish), base, shower system, glass door, niche, floor LVT,
cabinets (brand + color + door style), countertop, faucet, toilet, mirror, light,
paint color. Watch **Specs & Materials for recently added files** — a spec added
mid-build (e.g. a shower seat) is new scope the crew needs to know about.

Reconcile against ServiceMinder: if the SM line says "36″ vanity" but Selections
says a 30″ Elias in Nautical Blue, **trust the Drive selection** (it's what was
ordered) and flag the discrepancy for confirmation.

## Step 5 — CompanyCam: actual field progress (the ground truth)

- `get_project_photos` returns a large payload. **Analyze it in a subagent** so it
  stays out of your context. Ask the subagent to parse the file (each element is
  `{type,text}` where `text` is one photo's JSON), then return: a **day-by-day
  timeline** (date, photo count, creators), the **first and last captured_at**
  dates, and any tags. Note: this endpoint has **no tags** and captions are
  usually null, so cadence + imagery are the signal, not metadata.
- **Download the most recent day's photos and actually look at them.** Extract the
  latest `captured_at` photos' `uris` (prefer `web`/`original`), download to the
  scratchpad, and `Read` them. This is how you determine the *actual build stage*
  (demo done? framing? rough-in? board up? pan set? tile/panels? fixtures?).
  A helper is bundled: `scripts/companycam_photos.py` — see below.
- Translate the imagery into phase status: Demo → Framing/blocking → Rough plumbing
  → Rough electrical → Wall board/waterproofing → Shower base → Shower panels/door
  → Floor → Vanity/cabinets/top → Toilet/fixtures/trim → Paint → Base/trim → Punch.
- **Flag multi-day gaps** in the photo cadence — if there are working days with no
  photos, ask whether they were down days (it erodes the finish buffer).

## Step 6 — Make the status call (be honest — this goes to the PM)

Classify the job into exactly one of four states, measured against the target date:

- **Ahead of Target** — finish sequence will clearly land before the target with
  buffer to spare.
- **On Target** — trending to finish on the target date; normal risk.
- **At Risk** — *can* still hit the target but has no buffer, or the schedule of
  record already lands past it, or material readiness is unconfirmed. Any slip
  pushes it late. (This is the right call more often than optimism suggests.)
- **Behind Target** — the remaining work cannot realistically fit before the
  target at the current pace; completion will be after the date.

Give a one-line rationale and a "to pull to <better state>" fix line. Anchor it in
facts: working days elapsed vs remaining, phase reached, whether JobTread's own end
date is past the target, material-on-site status, and any photo gaps. Self-
performed trades (KTU/BTU crew does its own plumbing/electrical/tile/paint) is a
point in favor — no subcontractor handoffs to stall the finish run — mention it
when true. A panel shower (Sentrel/wetwall, no tile cure) is also a schedule saver.

## Step 7 — Build the tracker artifact

Use the bundled template `assets/tracker-template.html` as the design system —
copy it and fill in the real data so every job's tracker looks consistent. Publish
with the `Artifact` tool (favicon 🛁 for baths / 🍳 for kitchens). The board must
contain, top to bottom:

1. **Header** — job name/number, address, business (KTU/BTU), and the record IDs
   from each system (SM invoice, JobTread job, Drive packet/selections numbers).
2. **PM Status Call** — the four-state scale with the current state highlighted,
   plus the rationale and fix line. This is the headline; it comes first.
3. **Summary tiles** — build window (with JobTread end date if it differs from
   target), days elapsed, days remaining, and a notable scope fact (shower type).
4. **Progress bar** — rough % with a "status as of <last photo date>" label.
5. **Scope by phase** — grouped rows (Structural/Rough-in, Shower, Flooring,
   Cabinetry, Fixtures/Finishes). Every row shows the **real finish spec** from the
   Drive selections and a status pill: Done / In progress / Not started (plus
   intermediate notes like "Set", "Framed", "Rough in", "Backing in").
6. **Remaining sequence** — numbered steps from where they are to the target date,
   with dates.
7. **Watch items** — the scheduling risks (material staging, photo gaps, stale
   JobTread schedule). If Steven said ignore financials/sign-offs, keep these
   purely about scope and schedule.
8. **Footer** — the source systems and the "status as of" date.

Keep it factual and skimmable. When Steven asks to change the status call or add a
field, it's a one-line edit — republish the same file path to keep the URL.

## Quick reference — the data you're pulling

| System | What it holds | Key tools |
|--------|---------------|-----------|
| ServiceMinder | Scope of work, change orders, appointments | `find_contact`, `get_invoice`, `get_proposal`, `query_appointments` |
| JobTread | Production schedule, budget | `query` (org id → job by "Job N" → `taskSummary`, `costItems` sum) |
| Google Drive (KTU) | Design packet, finish selections/specs | `search_files` (structured query), `read_file_content` |
| CompanyCam | Actual field progress (photos) | `search_projects`, `get_project_photos` (analyze in subagent + download recent) |
