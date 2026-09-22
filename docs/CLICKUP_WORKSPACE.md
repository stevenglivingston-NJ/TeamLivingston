# ClickUp workspace — build record & operating notes

Built 2026-09-21. ClickUp is the **work layer**: commitments, decisions and the
Steven↔Sonya delegation loop. It is not a second intranet and not a second CRM.

## The invariant

One fact, one system of record — tested per fact by asking where you would go
to **correct** it.

| Fact | Corrected in | ClickUp |
|---|---|---|
| A job's install window | ServiceMinder / JobTread | links |
| Paid CPL, ACOS, organic rank | the campaign; computed into Supabase | links |
| An invoice's balance | ServiceMinder / QuickBooks | links |
| **A commitment or a pending decision** | **nowhere else — no system holds it** | **owns** |

A ClickUp view that restates an intranet tab is the failure mode this prevents.

**Explicitly out of scope, and why it matters:** vendor-invoice payment approval
stays in Supabase and on the intranet Job Costing tab, where nothing is payable
until it maps to a job. A parallel pay queue in ClickUp would be a bypass of a
deliberate control — the same risk already flagged for Melio's Inbox Sync.

## IDs (verified 2026-09-21)

| Object | ID |
|---|---|
| Workspace "Goaxyom" | `90141667621` |
| Space "Team Space" | `90148750591` |
| Folder "Axyom Operations" | `901413604098` |
| List "Decisions — Steven" | `901421334048` |
| List "Money & AR" | `901421334055` |
| List "Commitments" | `901421334062` |
| Steven Livingston | `240208616` · steven@goaxyom.com |
| Sonya Hartland | `118419930` · sonya@goaxyom.com |

## Why three lists and not nine

The structure was derived from the ingested corpus, not chosen up front.
Clustering 50 real open items:

- **`item_kind`** — 39 commitments / 11 decisions. Decisions are a genuinely
  distinct cluster with their own workflow, so they get their own list.
- **Owner** — Steven 28 / Sonya 19. Both touch everything → an *attribute*.
- **Entity** — mostly cross-entity or unlabelled → an *attribute*.
- **Permission audience** — exactly **two** (Steven+Sonya, and Steven alone)
  → two Spaces, not six.
- **Workflow** — Money/AR 12 · Systems 9 · Customer follow-up 8 · Hiring 6 ·
  Ops 6 · Marketing 5 · Vendor 4.

Rule applied: *no container for fewer than 10 live items unless it is a
permission boundary; every list has a named owner.* Only Decisions and
Commitments clear that bar outright. **Money & AR is a deliberate exception at
8–12 items** — kept because its workflow (chase → dispute → resolve) and its
owner (Sonya, end to end) both differ from Commitments. Stated here rather than
buried, because it is the one place the rule was overridden.

Everything below the floor — Hiring, Systems, Marketing, Vendor, Ops — is a
`Workstream` value, not a list.

## Connector limits found by live probe

**Scope: this table describes the MCP connector only.** The REST API is a
different surface and does more — see *Correction* below before concluding
anything here is impossible.

| Capability | Via MCP connector | Note |
|---|---|---|
| Create Folder / List / Task / Doc / Comment / Reminder | ✅ | |
| Create **Space** | ❌ | no such tool *(REST can — see Correction)* |
| Create **custom field** | ❌ | no such tool *(REST can)* |
| Create **view** | ❌ | no such tool *(REST can)* |
| Create **status** | ❌ | inherited from the Space *(REST cannot either — plan-gated)* |
| Unified API operators | ❌ none enabled | `get_operators` → "none" |
| **Call quota** | **100/day** | hard 429 at call 100; resets ~22h |

The REST API has none of these limits, which is why `mcp-servers/clickup.sh`
exists. Use the connector for interactive work; use the helper for bulk and for
anything recurring.

## Correction — most of this was NOT UI-only

An earlier pass concluded Spaces, custom fields, views and statuses could only be
created by hand. **That was true of the MCP connector's tool surface, not of the
REST API.** With `CLICKUP_API_TOKEN` the REST API creates all of them. Everything
below was then built programmatically:

| Thing | REST | Note |
|---|---|---|
| Private Space | ✅ | `POST` creates it **public**; privacy needs a follow-up `PUT {"private":true}`. Verified `private=true` after. |
| Custom fields | ✅ creatable | but see the usage cap below |
| Views | ✅ | `divide.collapsed` must be `null`, not `false`, or you get a bare 400 |
| Docs + pages | ✅ v3 | returns **201**, not 200 — a `!= 200` check silently skips every page |
| **Custom statuses** | ❌ | the API accepts the PUT and **silently drops** custom statuses, keeping only open/closed. `handback` is not creatable on this plan. |

### The plan answer, measured

`FIELD_033: Custom field usages exceeded for your plan` fired at **exactly 60
usages** — 15 tasks × 4 fields. Free ClickUp caps custom-field *usages*, not
field definitions. 67 tasks × 4 fields would need 268.

So the taxonomy rides on **tags**, which are uncapped: `ws:` workstream, `ent:`
entity, `wait:` who is blocking, and `unverified`. All 67 tasks carry them (200
tag applications, 0 untagged). The five field definitions are kept but their
usages were cleared, so the quota is free the day the plan is upgraded.

**What an upgrade actually buys here:** custom-field usage headroom, and custom
statuses — the `handback` step the delegation loop wants. Little else this design
uses. So it is worth upgrading for those two things or not at all.

## Built — final state, verified 2026-09-21

- **Space `90148750591` "Team Space"** → Folder `901413604098` "Axyom Operations"
  - Decisions — Steven `901421334048` — **14**
  - Money & AR `901421334055` — **13**
  - Commitments `901421334062` — **40**
  - **67 tasks, 0 untagged**
- **Views:** Waiting on Steven · Waiting on Sonya · Money & AR — all ·
  Unverified — verify before acting
- **Doc:** Chief of Staff — Operating Manual (4 pages: how the workspace works ·
  Sonya's day · standing meetings · field rules the crew already follows)
- **Space `90148784039` "Steven — Private"**, `private=true`, Sonya has no access
  - Career — 4 · Content & Personal — 2

## Known residue

An empty custom field named `__scope_probe` survives on the space. It has no
usages and no effect, but it resisted deletion through every endpoint tried
(`DELETE /space/{id}/field/{id}` → 404, `/list/{id}/field/{id}` → 404, v3 → 405).
Delete it in the UI.

## Cross-system ID fields — still not created, and why

`SM Contact ID`, `SM Proposal ID`, `HL Opportunity ID`, `JobTread Job ID` are
**still absent on purpose.** No ID-resolution pass has run, and an always-empty
field is worse than a missing one — doubly so now that field *usages* are the
scarce resource. The customer names are in the corpus (Thompson, Rubin, McGriff,
Vecchiarello, Simeone, Collins, Murchison, Barrett, Fleming, Lunny, Drechsel,
Gold, MacQuillken, Rutherford, Labagnara, Province, Rabbitt, Mycka); resolving
them against ServiceMinder is the next pass.

## Sources ingested, and not

**In:** the Steven↔Sonya Slack DM (2026-07-01 → 09-21) — 50 items, 46 open.
This channel is currently the de-facto task system.

**Excluded, with reason:**
- `#ktugroup` — field-crew logistics ("bring inside by EOD", deliveries, meeting
  reminders). Two standing rules extracted for SOPs: inspect all product on
  delivery within the 2-day return window; leftover tile/grout returns to the
  showroom.
- The **monday.com export** (Drive, 100+ boards, exported 2026-07-13) —
  classified ARCHIVE. It is a wiki, not a task tracker: board-per-vendor sprawl,
  five "Duplicate of monday Doc" files, "New Board" twice, "Delete", "Start from
  scratch", and a "To do list" board whose newest item is from April 2025. It
  stays in Drive where the Librarian maps it.

**Reached in later passes (see below):** Gmail, Google Calendar, ServiceMinder.
**Still not reached:** JobTread, HighLevel, CompanyCam, the ecommerce stack —
each has an owning agent, so only their human-decision exceptions would cross.

**Not reachable at all:** Apple Reminders / Notes — no connector exists and a
Cloud session has no path to the device. Export to Drive and re-run the ingest.

## Second ingest pass — Gmail (2026-09-21)

Added 10 tasks. Total seeded: **59** (13 Decisions · 10 Money & AR · 36 Commitments),
verified by readback through `clickup.sh`, not by create responses.

Two REST gotchas found and documented in `clickup.sh`: dates must be epoch
milliseconds (the API returns a bare 400 naming no field), and text must not be
HTML-escaped (ClickUp stores `&amp;` literally — it named a list "Money &amp; AR"
until corrected).

**Held back deliberately.** Gmail surfaced live career items — a Stokke GM/US
update from the Barker Owen search, and an unanswered question from Simply Apply
about broadening role targeting to Growth and Product Marketing. **Neither was
seeded**, because the only Space that exists is shared with Sonya and the
permission rule puts personal/career material owner-only. They land once the
private Space exists.

## Third pass — ServiceMinder + Calendar (2026-09-21)

Total seeded: **67** (14 Decisions · 13 Money & AR · 40 Commitments), verified by
readback.

**ServiceMinder AR — the largest finding of the build.** `$466,957` open across
both brands. Split by the 50/40/10 cash model (50% at close, 40% by 60 days,
10% by 90 days), since a balance inside 90 days can be legitimately on schedule:

- **Past 90 days: $257,961.82 across 14 invoices.** 13 of the 14 sit at almost
  exactly **50% paid** — deposit collected, closing balance never was. Track A
  runs 5–7 weeks and Track B 9–12, so these jobs are long finished. That is a
  closeout process gap, not fourteen coincidences.
- Within 90 days: $208,995.54, not counted as aged.

Three cross-checks corrected existing tasks:
- **Kim Thompson** — answered Sonya's open question. Invoice `I476148` shows
  $2,187.60 of $21,876.00, so **90% was collected**; only the closing 10% remains.
- **Vecchiarello** — aging corrected from "125+" to the actual **143 days**.
- **"Bill Rutherford and Karen L."** — Karen L. is **Karen Labagnara**. Between
  them they carry **$66,161.58** open (Rutherford $42,666.27 at 159d; Labagnara
  $23,495.31 at 75d), and Labagnara's balance is what is holding Elias order
  #2649281. What looked like a scheduling call is a collection call.

**API note:** `invoice/query` silently ignores `UnpaidOnly` and returns paid
invoices regardless. Filter client-side on `DatePaid is null and BalanceDue > 0`.
Pass `IncludeContact: true` or you get bare `ContactId` integers.

**Calendar.** Six standing meetings across two calendar systems, and **Weekly
Sales/Operations (Tue 11:00–12:00) collides with BTU Weekly (Tue 11:30–12:00)**
every week — Steven, Jessica and Mayra double-booked, Mayra marked *tentative*.

**Excluded by the invariant, deliberately:** HighLevel conversations (Goldeneye
owns them), JobTread jobs (Foreman), CompanyCam photos. Only aged AR and stale
proposals cross from the record systems.

**Still held for the private Space:** the Gmail career items, plus calendar-side
Executive Impact Institute and Larnell Vickers sessions, and the weekly LinkedIn
post schedule.

## Repo gotcha — setup.sh resets the checkout to origin/main

`mcp-servers/setup.sh` runs `git reset --hard origin/main` on session start, and
the SessionStart hook can fire again mid-session. Twice during this build it
moved the working tree off the feature branch without warning: once a commit
landed on `main` instead (moved by cherry-pick, `main` restored, never pushed),
and once `clickup.sh` vanished from disk while sitting safely on the remote.

Push early and re-check `git branch --show-current` after any long tool
sequence. The branch is the thing that gets lost, not the commits.

## Fourth pass — the working directory build (2026-09-22)

Steven's ask went further than the original build: ClickUp should be "our working
directory for finding any and everything," should surface every tool/platform,
should hold job descriptions and procedures for easy hiring, and should
consolidate what monday.com left behind. That is a real widening of scope from
the original invariant, reconciled below rather than silently overridden.

**Correction to "Sources ingested, and not," above.** The monday.com export is
not only Drive-side archive — it is *also* live in this workspace as its own
Space, **"Monday Import" (`90148799318`), ~140 lists**, imported at some point
before this session and never documented here. Both facts were independently
true; this was a documentation gap, not a contradiction. Findings:

- **50 of its lists are `Subitems of X` with zero tasks** — a structural
  artifact of every monday.com board that uses subitems, not real content.
  Verified live (including closed tasks) on a spot-check of three. Recommended
  for bulk deletion — zero information loss — but **not executed**: a bulk
  `DELETE /list/{id}` loop was correctly blocked by the session's own
  permission classifier as an external-system write needing a human's sign-off,
  and 50 deletions in a workspace Sonya also uses warranted that pause anyway.
  Full list + the real (non-empty) near-duplicates needing an actual look —
  three overlapping "Owned_Territories" lists, `SOPs & Procedures` vs
  `Standard operating Procedures`, `Rolodex` vs `Crucial Rolodex`, two
  `New Board`s, a `Delete` list and a `Start from scratch` list — are in the
  **"Monday Import & Marketing Calendar — Consolidation Findings"** Doc below.
  Nothing in that Space was deleted, merged, or reorganized this pass.
- The 2026-forward marketing material buried in it (`2026 Content Calendar -
  Confirmed ads`, 23 items; `2026 Budget Allocation`, 16 items) is more current
  than the intranet: `mkt_plan_items`/`mkt_vendor_map`/`mkt_budget_targets`
  were all last scanned **2026-07-05**, 11 weeks stale. Neither Monday list has
  due dates set, so it's real backlog, not yet a schedule — dating it is
  Sonya's/the Marketing Intern's call, not something to fabricate from outside.

**Four new Docs, all under Team Space (`90148750591`), same visibility/access
as the existing Chief of Staff Operating Manual:**

| Doc | ClickUp URL | Sourced from |
|---|---|---|
| Policies, Procedures & Handover Standards | `.../v/dc/2kydtc95-854` | Full Handover Standard V2 + Design Standards Technical Reference v1.0 (pulled live from `intranet_records.sow_authored`) + the approved-not-yet-signed V3 amendments |
| Roles & Job Descriptions — Current | `.../v/dc/2kydtc95-874` | The finalized seat JDs from the org-restructure Claude Doc: Design Sales Consultant (+ 3-tier sales comp, corrected to the actual $60K+5.5% Mauro offer), Sales & Showroom Coordinator, Director of Business Operations, Marketing & Events Intern, Senior Project Manager, Production Manager (full CareerPlug posting) |
| Tools & Platforms Directory | `.../v/dc/2kydtc95-894` | CLAUDE.md's MCP server tables, links-only — deliberately does not restate any live data, per the invariant below |
| Monday Import & Marketing Calendar — Consolidation Findings | `.../v/dc/2kydtc95-914` | Live probe of the Monday Import Space + the intranet freshness check above |

A throwaway `__test_doc` (`2kydtc95-834`) used to verify the v3 Docs API still
sits in the Space — **known residue**, same category as `__scope_probe`. The
v3 API has no doc-rename or doc-delete endpoint (`PATCH`/`DELETE` on
`/docs/{id}` both 405), so it could not be repurposed or removed
programmatically; delete it by hand in the UI.

**Reconciling the invariant.** "One fact, one system of record" still holds for
anything with a live owner elsewhere — the Tools directory links to systems
instead of mirroring their data, and none of the four Docs restate a number
that ServiceMinder, QuickBooks, or the intranet already owns. What changed is
recognizing that **job descriptions, the signed operating standards, and a
tools index had no live owner anywhere** before today — the monday.com JD
board and the old Handover Standard PDF were static files nobody was
maintaining. That is exactly the documented "In" criterion from
`CLICKUP_BUILDOUT_PROMPT.md` ("nothing else owns it today"), so ClickUp owning
these four things going forward is consistent with the invariant, not an
exception to it.

**The orphaned "Org Chart & Hiring Plan" list question — resolved.** The list
(`901421350250`, 12 seat tasks) now carries a description linking both the
Roles doc and the Policies doc, so the hiring tracker and the JD library are
one click apart instead of Steven having to know both exist separately.

**Intranet `docs_team` updated:** added links to the Google Drive copy of the
full restructure doc (`1IlEzqmzs...`) and all four new ClickUp Docs; corrected
the stale "Ben (KTU) 11% · Karen (BTU) 9%" commission-plan description to the
confirmed current structure.

## Fifth pass — Vendor Directory (2026-09-22)

Built at Steven's request after the Monday Import audit surfaced five
unreconciled vendor-contact lists sitting untouched in that Space. New List
**"Vendor Directory" (`901421384995`)**, Team Space → Axyom Operations,
**104 vendors/suppliers/subcontractors/professional-services contacts**.

**Sources merged, by seniority:**
1. Intranet `vendor_directory` (79 rows) — the base. Already deduped, already
   carried `group` (KTU/BTU/Ops/Realtors → mapped to Brand KTU/BTU/Both),
   contact name/email/phone/website/portal/username/password, Drive doc links.
2. Intranet `vendors` (16 rows) — narrative category + relationship $ volume +
   lead time + ordering process, matched by name to enrich Type and Notes.
3. Intranet `docs_vendors` (62 rows) — title/desc pairs, used only for Type
   hints on rows the other two sources didn't cover.
4. Raw Monday `Supplier/Vendors` (100 tasks) — fuzzy name-matched against the
   above to fill missing passwords/usernames/emails on existing rows, and
   contributed **12 genuinely new vendors** the intranet source had missed.
   ~40 rows were pure junk (category placeholders like "Countertops"/"Tubs"
   with no data, or personal notes like "Shirt printing") and were dropped.
5. Monday `Crucial Rolodex` (13) → type **Professional Services** (bank,
   insurance, legal, CPA contacts).
6. Monday `Rolodex` (13) → type **Subcontractor** (trade sub vetting sheet —
   license, insurance, crew size, accepting-new-jobs status folded into notes).

**Not done: fresh Gmail/Spark scraping per vendor.** Steven's ask named Spark
specifically; **Spark is not a connected server in this environment** — only
the `Gmail` connector is. Rather than run ~100 individual Gmail searches for
uncertain payoff, the build used `vendor_accounts` (Foreman's own Gmail-sourced
AR/order-status intelligence, scan_date 2026-09-14) for the handful of vendors
it already tracks live (Elias, MSI, Hardware Resources) and left everything
else on its Monday/intranet contact info. If a specific vendor's contact is
stale, that's a one-vendor Gmail lookup, not a re-run of the whole build.

**Classification.** `Type` (35 distinct values — Cabinetry, Countertops/Stone,
Plumbing Fixtures, Subcontractor, Professional Services, etc.) and `Brand`
(ktu/btu/both) are **tags**, not custom fields — the free-plan 60-usage cap
documented above would have blown past instantly at 104 vendors × up to 9
fields. Contact details (name/email/phone/website/portal/username/password/
notes/doc links) live in the task **description** instead, which doesn't count
against that cap. A `has-credentials` tag marks the 17 rows carrying a portal
password.

**Security flag, not resolved.** Those 17 rows carry vendor portal
login credentials copied forward from Monday, at Steven's explicit
instruction. This is not a new exposure in kind — the same passwords already
sit in the intranet's `vendor_directory` (Supabase) and in the Monday import —
but it is a **new surface**: ClickUp lists aren't secrets-grade storage (no
encryption-at-rest guarantee, no rotation tracking, and this workspace is
explicitly meant to be shared with and beyond Sonya). Flagged once, in the
list's own description and in the Tools & Platforms Directory Doc, with a
recommendation to migrate to a real password manager. Not blocking — Steven's
instruction was explicit and repeated.

**Coverage after merge:** 89/104 have a contact name, 58/104 a phone,
49/104 an email, 17/104 a portal password. The ~15 rows still short every
field are genuinely under-documented vendors (mostly one-line Monday category
placeholders that did carry *some* real signal, e.g. a bare website) — not a
tooling gap.

## Known gaps in the Drive tooling

`mcp__Google_Drive__search_files` **caps at 100 results and its pagination is
broken** — page 2 returns byte-identical results to page 1. The monday board
count is therefore a floor, not a total. Workaround: the Zapier Drive raw-API
path.
