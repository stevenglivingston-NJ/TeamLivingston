# ClickUp Build-Out — execution prompt

**What this is:** the prompt for a single end-to-end run that audits ClickUp's real
capabilities, ingests every open commitment Steven has across every entity, derives a
workspace structure **from that data**, recommends the cheapest sufficient ClickUp plan,
builds the workspace, seeds it, and wires it to the existing stack.

**Why it reads the way it does:** the structure is *not* specified here. Every earlier
attempt at this started from somebody's idea of the right hierarchy — entity-first,
function-first, agent-first — and then bent the data to fit it. This run does the reverse:
ingest first, cluster the real corpus, and let the containers fall out of it. Where this
document does constrain the build, it constrains *how to decide*, not *what to decide*.

**Run it in an interactive session.** It calls `mcp__*` tools, which stall forever in a
scheduled Routine (see §6).

---

## The one invariant

Everything else in this document is derivable. This is not.

**One fact, one system of record.** For any fact the workspace displays, exactly one system
owns it, and that is the system you would go to in order to *correct* it. ClickUp displays
facts it does not own by linking to them, never by copying them.

Apply the test per fact, not per system:

- *"This job's install window slipped"* → corrected in ServiceMinder/JobTread → ClickUp
  links.
- *"Paid CPL is up 40% week over week"* → corrected by fixing the campaign; the number is
  computed by an agent into Supabase → ClickUp links.
- *"Steven owes Karen a decision on the Annunziato scope by Friday"* → corrected nowhere
  else; **no other system holds it** → **ClickUp owns it.**

That third case is what ClickUp is for: commitments, decisions, and delegated work — the
things that currently live in Steven's head, his Slack DMs, and his inbox. Everything
already owned elsewhere is a link.

**The failure mode this prevents:** a ClickUp view that restates an intranet tab. Two
surfaces showing the same number, diverging, neither trusted. If you build a Dashboard that
duplicates `dash.goaxyom.com`, you have broken the invariant — delete it.

---

## Phase 0 — Ground truth

No design decisions in this phase. Only evidence.

### 0.1 Read the existing build

- `CLAUDE.md` — the full stack map, the account IDs, the known traps
- `.claude/agents/*.md` — all agent specs: what each owns, cadence, output section
- `intranet/ktubtuintranet.html` — every tab and section key
- `docs/JOB_COSTING_DESIGN.md`, `docs/JOB_COSTING_RUNBOOK.md` — the one documented
  human workflow already written down; it is a model for how these get specified
- `mcp-servers/` — every server and every curl helper
- `bash mcp-servers/sb.sh "select table_name from information_schema.tables where table_schema='public' order by 1"`

**Output 0.1:** what already exists, and for each thing, whether it is a *record*, an
*analysis*, or a *commitment* (per the invariant).

### 0.2 ClickUp account state

Run, in order, and record raw output:

1. `clickup_get_workspace_hierarchy` — **the workspace may not be empty.** Every Space,
   Folder, List, and Doc that already exists, with item counts and last-activity dates.
2. `clickup_get_workspace_members` — every member and guest, their seat type, their ID.
   Identify the Chief of Staff's member ID explicitly.
3. `clickup_get_schema` — how entities relate on this account.
4. `clickup_get_operators` — which extended operations are enabled. **Anything not
   returned here is unavailable**, regardless of what ClickUp's docs say.
5. `clickup_get_custom_fields` against a non-empty list — the real field-type vocabulary.

### 0.3 Capability matrix — verify, do not assume

Probe each capability below **on this account**. For each, record: *available? · evidence
(the call and its result) · plan tier that gates it · what the build would use it for.*

Custom fields (which types, how many per list) · Relationship / list-link fields ·
Rollup fields · Formula fields · Custom Task Types · Automations (and monthly quota) ·
Dashboards (and which card types) · Docs and Doc pages · Chat channels · Forms ·
Goals/Targets · Time tracking · Reminders · Dependencies · Tags · Task-in-multiple-lists ·
Email-in-to-task · Private Spaces · Per-Space permissions and guest scoping ·
API rate limit (requests/min on the current tier).

Where a probe is ambiguous, `WebFetch` ClickUp's current pricing and feature-comparison
pages and cite them — but **live probe outranks documentation** wherever they disagree.

**Output 0.3:** the capability matrix. Every design decision later in this run must cite a
row in it. A design that depends on an unverified feature is not a design.

---

## Phase 1 — Ingest

Pull everything. **Write nothing to ClickUp in this phase.** Normalize every item to:

```
{ title, body, source, source_url, source_id, raw_owner, raw_due,
  raw_status, entity_guess, item_kind, confidence, first_seen, last_activity }
```

`item_kind` ∈ `commitment` (someone owes someone something) · `decision` (a choice awaiting
a decider) · `reference` (a document or fact) · `record_pointer` (lives in another system) ·
`noise`.

### 1.1 monday.com export — required

`mcp__Google_Drive__search_files` for the monday export (CLAUDE.md: monday is being retired,
boards/docs exported to Drive, mapped by the Librarian). Search `monday`, `monday.com`,
board-name fragments, `.csv`/`.xlsx` exports. Download and parse **every** board.

Per board record: name · columns · item count · owners · statuses · date of last item
activity. Then classify:

- **MIGRATE** — live work, activity within 90 days, items that are commitments or decisions
- **ARCHIVE** — real history, no recent activity → export to Drive, link from ClickUp, do
  not import
- **DEAD** — abandoned, empty, or superseded → name it and drop it

State the counts. Carrying dead boards across is the most common way a migration produces a
workspace nobody opens.

### 1.2 Slack

`mcp__Slack__slack_search_public_and_private`, `slack_read_channel`, `slack_read_thread`.
Prioritize DMs with the Chief of Staff, then Mayra, Karen, Miguel, Craig, Robert, then
channels Steven posts in. Extract: commitments made or received, open asks with no
resolution, decisions taken (for the decisions record), and questions directed at Steven
that have no reply. Capture permalinks. **Do not ingest message bodies wholesale** — extract
the item, link to the thread.

### 1.3 Email

`mcp__Gmail__search_threads` across `stevenglivingston@gmail.com` and, via the Zapier Gmail
path, `ktubloomfieldnj@gmail.com` and `ktubtubilling@gmail.com` where reachable. Target:
threads where Steven is the last-awaited reply · explicit commitments he made · starred or
flagged threads · vendor/client/recruiter threads awaiting action. Link to threads; do not
copy bodies.

### 1.4 Calendar

`mcp__Google_Calendar__list_events` — recurring meetings (candidates for recurring agendas)
and upcoming commitments that imply prep work.

### 1.5 Apple Reminders / Notes — state the limit, do not fake it

**There is no Apple connector in this environment and no path from a Cloud session to the
device.** Do not report this source as scanned.

1. Search Drive and the repo for an existing export and ingest it if found.
2. If none: file a task in the unsynced-sources list with the exact export procedure
   (Reminders → select list → Share/Export; Notes → Export as PDF/file) and the exact Drive
   folder to drop it in, plus the command to re-run this ingest step.
3. Name it in the final report under "not scanned, and why."

### 1.6 Live systems — open items only, never history

Use the **curl helpers**, not the MCP tools, wherever a helper exists — they are the tested
path through the session egress proxy:

```
bash mcp-servers/sm.sh  KTU|BTU <endpoint> '<json>'   # ServiceMinder
bash mcp-servers/ghl.sh KTU|BTU <tool> '<json>'       # HighLevel
bash mcp-servers/sb.sh  '<SQL>'                       # Supabase
bash mcp-servers/gmb.sh KTU|BTU info                  # Google Business Profile
bash mcp-servers/companycam.sh /v2/projects 'per_page=100'
```

Pull: SM open appointments / open proposals / unpaid invoices · JobTread active jobs
(`mcp__JobTread__query`) · HighLevel open opportunities and unanswered conversations ·
CompanyCam active projects · Shopify/ShipStation/Amazon/Walmart open Earthwise orders and
reorder flags · Supabase: today's open RAG callouts from every agent section.

**Never conclude a pipe is dead from a missing MCP tool.** CLAUDE.md is explicit: "no MCP
tools registered" ≠ "the token is dead." Try the helper first. An empty result next to a
failed connection is **unverified, not clean** — record it as a degradation.

### 1.7 Normalize, dedupe, resolve

The same commitment routinely appears in Slack, email, and a monday board. Dedupe on a
composite key (normalized title + counterparty + date window), keeping the richest record
and retaining **all** source URLs on the survivor.

Resolve people: build the person index from the corpus — every counterparty appearing in
any item — and for each, probe HighLevel / ServiceMinder / JobTread / CompanyCam for a
matching record, storing the IDs found.

**Output 1:** the staged corpus, with pre- and post-dedupe counts, a per-source item count,
and a degradations list.

---

## Phase 2 — Derive the structure

**Do not import a hierarchy from anywhere, including this document.** Derive it.

### 2.1 Cluster

Cluster the Phase 1 corpus on the dimensions actually present in it. Candidate axes —
test each, report which ones the data supports:

entity · counterparty · workflow stage · time horizon · who does the work ·
permission audience · item_kind

Report cluster sizes. A proposed axis that produces one dominant cluster and a tail of
singletons is a bad axis — say so and use the next one.

### 2.2 Container rules

Structure follows from these rules, applied to the clusters. Show your work per container.

| Container | Exists only when |
|---|---|
| **Space** | It is a distinct **permission audience** — a different answer to "who can see this?" Not a topic. If two candidate Spaces have identical membership, they are one Space. |
| **Folder** | A cluster is large enough to need its own views and its Lists genuinely share a lifecycle. |
| **List** | Its items share **one workflow** — the same statuses, start to finish. Two candidate lists with identical statuses and the same owner are one list. |
| **Custom field / tag** | The thing is an **attribute** of an item, not a home for it. Entity, priority, stage, and source are almost always attributes. |

Two hard constraints:
- **No container for fewer than 10 live items** unless it is a permission boundary.
- **Every List must have a named human owner.** A list nobody owns is a list nobody works.

### 2.3 Statuses

Derive from observed workflow in the corpus, not from ClickUp defaults. Where a documented
standard already exists — the Sales→PM Handover Standard V2 gates, Track A (reface, 5–7 wks)
vs Track B (custom, 9–12 wks), the Production Gate, the job-costing exceptions queue — use
it verbatim and cite it. Do not invent a parallel vocabulary for a process that already has
one.

### 2.4 Cross-system link fields

Every item that points at another system carries the ID that resolves it there. From the
Phase 1.7 resolution, the candidate set is: `SM Contact ID` · `SM Proposal ID` ·
`HL Contact ID` · `HL Opportunity ID` · `JobTread Job ID` · `CompanyCam Project ID` ·
`QBO Customer ID` · `Intranet Section` · `Source URL`.

**Include a field only if Phase 1.7 actually resolved IDs for it.** An always-empty field
is worse than a missing one.

### 2.5 People

Membership rule, not a target count: a person belongs in ClickUp if **(a)** there is a
two-way interaction with them in the corpus, **or (b)** they are attached to a live job,
open deal, active vendor relationship, or open decision. Everyone else stays in HighLevel
and is reached by link.

Report the resulting count. If it exceeds ~500, re-read the invariant — you are rebuilding
the CRM.

### 2.6 Permissions

Derive from the Space-as-audience rule. Two boundaries are non-negotiable and must survive
into ClickUp:

- Anything mirroring the intranet's `docs_finance` (RLS `is_admin()`-locked) stays
  owner-only.
- Steven's personal/career material, if the corpus contains any, is owner-only.

State, per Space, exactly who can see it and why.

**Output 2:** the derived architecture, every container justified by a cluster and a rule,
every field justified by a capability-matrix row and a resolved ID, plus an explicit list of
**what you chose not to build and why**. The rejections matter as much as the design.

---

## Phase 3 — Plan tier

The plan is an **output of the architecture**, not an input to it.

1. From Output 2, list every ClickUp capability the architecture requires.
2. From the Phase 0.3 matrix, mark which of those are gated and at what tier.
3. Compute usage drivers: seat count (members + the CoS + guests) · list count ·
   custom fields per list · automations/month · API calls/day for the Phase 6 sync
   (check this against the tier's rate limit).
4. `WebFetch` ClickUp's current pricing page for live per-seat pricing and limits.
5. Recommend **the cheapest tier that supports the architecture**, with annual cost at the
   real seat count.
6. Then state, separately: what the **next tier up** would add, and whether any of it is
   worth the delta *for this architecture specifically*. Do not recommend a tier for
   features the design does not use.
7. If a required capability is gated above the recommended tier, present the tradeoff
   plainly: the feature, its cost, and the degraded design that works without it.

**Checkpoint:** if the recommended tier is above the current plan, stop and surface the
recommendation before building anything that depends on the upgrade. Build everything that
does not depend on it, and mark the rest as pending.

---

## Phase 4 — Build

Build order: Spaces → Folders → Lists → statuses → custom fields → views → Docs →
relationships → automations → dashboards.

Rules:

1. **Idempotent.** Search before every create. State the idempotency key per object type.
   Re-running this must not duplicate anything.
2. **Verify by readback.** A 200 from a create call is not verification. Re-read with
   `clickup_get_workspace_hierarchy` / `clickup_get_list` / `clickup_filter_tasks`.
3. **Rate limits.** Batch and pace to the Phase 3 limit. Back off on 429.
4. **Partial failures are reported as partial**, naming the exact boundary of what landed.
   Never report a partial build as complete.
5. **Extend, never duplicate.** Anything Phase 0.2 found already existing gets extended.

---

## Phase 5 — Seed

Seed from the Phase 1 corpus. Real items only — no placeholders, no examples.

- Every seeded item carries its `Source URL` and a one-line provenance note.
- Items resolved in 1.7 carry their cross-system IDs.
- `item_kind = noise` is not seeded; report how much was dropped.
- Docs: write the workflows that exist but are undocumented. At minimum the Chief of Staff
  operating manual (what she opens, in what order, what she decides vs escalates) and the
  escalation ladder. Cite `docs/JOB_COSTING_RUNBOOK.md` as the format — task-level, not
  aspirational.

---

## Phase 6 — Bridge

### 6.1 The scheduling trap — read before building any recurring job

Per `CLAUDE.md`: scheduled Routines run in Auto mode, where an unapproved `mcp__*` connector
call cannot be answered and the session **stalls in `REQUIRES_ACTION` indefinitely**, with
no error logged. This caused an eight-day silent outage across four agents with every
credential valid throughout.

**No recurring automation may call `mcp__ClickUp__*`.**

Build `mcp-servers/clickup.sh` — curl against the ClickUp v2 API, `CLICKUP_API_TOKEN` from
the environment, following `ghl.sh` / `sm.sh` exactly (curl transport is deliberate:
python-urllib gets 403 from the session egress proxy and returns zero rows silently).
Cover: create task · update task · find task · list tasks · set custom field · add comment.
Add the var to `mcp-servers/.env.example`; document the helper in `CLAUDE.md`.

### 6.2 The agent → ClickUp bridge

Define and implement:

- Which agents emit findings that require a human, at what severity threshold, with what
  **dedupe key** so a standing finding does not re-file daily.
- The Supabase → ClickUp sync (`sb.sh` + `clickup.sh`), idempotent, with `--dry-run`.
- Any write-back, extending Ax's existing intranet→JobTread/ServiceMinder sync pattern
  rather than building a parallel one.

### 6.3 Hand off the Routine, do not create it

Test the sync interactively. Then hand Steven the exact Routine config: cron in **UTC**,
avoiding the 09:00–11:20 UTC dead zone documented in `CLAUDE.md`; model tier pinned
(**Sonnet 5** analytical, **Haiku 4.5** mechanical — never the Opus default); environment
pointed at `main`; and the prompt text. One Routine per job, no duplicates.

---

## Phase 7 — Report

1. **Built** — every object, with links.
2. **Seeded** — counts by source, dedupe delta, noise dropped.
3. **Capability matrix** — feature · available · evidence · used for · gap.
4. **Plan recommendation** — tier, annual cost at real seat count, what the next tier adds
   and whether it is worth it.
5. **Structure rationale** — why these containers and not others; the rejected alternatives.
6. **Not scanned, and why** — Apple Reminders explicitly, plus every degradation.
7. **Steven's queue** — Routine creation, Reminders export, seat/permission changes,
   credentials to mint.
8. **CoS day one** — what she opens first, and in what order.

---

## Guardrails

- **Never fabricate a scan.** Unreachable is reported as unreachable. Empty beside a failed
  connection is unverified, not clean.
- **Never bulk-import a CRM.** The §2.5 membership rule decides, and the count falls out.
- **Never duplicate a system of record.** Link to the fact; do not copy it.
- **Never let a recurring job call an `mcp__*` tool.** Use `clickup.sh`.
- **Pin a model tier** on anything scheduled.
- **Scheduled ops agents write to Supabase, never to the repo** — no commits, no PRs from a
  fired session.
- **Preserve provenance** on every seeded item.
- **Report partial as partial**, with the exact boundary.

## Done

Steven opens ClickUp and sees every open commitment he holds, across every entity, each
traceable to its source and delegable to his Chief of Staff in one action — and nothing in
it restates what the intranet already tells him.
