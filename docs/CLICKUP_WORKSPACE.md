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

| Capability | Via MCP connector | Note |
|---|---|---|
| Create Folder / List / Task / Doc / Comment / Reminder | ✅ | |
| Create **Space** | ❌ | no such tool — must be done in the UI |
| Create **custom field** | ❌ | no such tool |
| Create **view** | ❌ | no such tool |
| Create **status** | ❌ | inherited from the Space |
| Unified API operators | ❌ none enabled | `get_operators` → "none" |
| **Call quota** | **100/day** | hard 429 at call 100; resets ~22h |

The REST API has none of these limits, which is why `mcp-servers/clickup.sh`
exists. Use the connector for interactive work; use the helper for bulk and for
anything recurring.

## Still to do by hand (UI only)

1. **Private Space** for personal/career — cannot be created via API.
2. **Custom fields** on all three lists: `Workstream` (Hiring · Systems & fixes ·
   Customer follow-up · Marketing & events · Vendor & procurement · Ops & admin ·
   Money & AR), `Entity` (KTU · BTU · KTU/BTU · Jatalia/Earthwise · Axyom),
   `Waiting on`, `Source URL`, `Status confidence`. Until these exist, every
   seeded task carries those values in its description footer.
3. **A `handback` status** on Commitments — the delegation loop needs
   *assigned → doing → handback → accepted*, and only to do/in progress/complete
   exist today.
4. **Views**: "Waiting on Steven", "Waiting on Sonya", "This week", "Aged >30d".

## Cross-system ID fields — deliberately NOT created

The design calls for `SM Contact ID`, `SM Proposal ID`, `HL Opportunity ID`,
`JobTread Job ID`. **None were created, because no ID resolution pass has run
yet** — and an always-empty field is worse than a missing one. The customer
names are in the corpus (Thompson, Rubin, McGriff, Vecchiarello, Simeone,
Collins, Murchison, Barrett, Fleming, Lunny, Drechsel, Gold, MacQuillken);
resolving them against ServiceMinder is a follow-up pass, and the fields get
created when it produces IDs.

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

**Not reached this session:** Gmail (both identities), Google Calendar,
ServiceMinder, JobTread, HighLevel, CompanyCam, the ecommerce stack. These are a
second ingest pass; `clickup.sh` is idempotent so re-running is safe.

**Not reachable at all:** Apple Reminders / Notes — no connector exists and a
Cloud session has no path to the device. Export to Drive and re-run the ingest.

## Known gaps in the Drive tooling

`mcp__Google_Drive__search_files` **caps at 100 results and its pagination is
broken** — page 2 returns byte-identical results to page 1. The monday board
count is therefore a floor, not a total. Workaround: the Zapier Drive raw-API
path.
