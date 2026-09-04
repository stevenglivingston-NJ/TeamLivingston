# Team Livingston - Claude Code Environment

## Overview

This environment manages operations for two business groups:
- **KTUBTU** — Kitchen Tune-Up (KTU) and Bath Tune-Up (BTU) franchise locations in Bloomfield, NJ
- **Jatalia** — Jatalia / Earthwise brand operations

## MCP Servers

### KTUBTU Servers

| Server | Type | Tools | Auth |
|--------|------|-------|------|
| google-ads | stdio (Python) | Campaigns, keywords, search terms, geo performance, LSA, **change history** (`query_change_history` — who changed what, 30-day retention) | OAuth2 (Desktop client) |
| gmb | stdio (Python) | Reviews, metrics, search keywords, location info, hours | OAuth2 (shared with google-ads) |
| google-analytics | stdio (Python) | GA4 Data API direct — channel/landing-page performance, generate_lead events | ✅ LIVE (2026-08-21). Own `GA4_REFRESH_TOKEN` (scope `.../auth/analytics`; the google-ads token 403s here). Properties: KTU 453600017, BTU 487870392. **Filter by `hostName`** — the two properties are cross-contaminated |
| gtm | stdio (Python) | Tag Manager API v2 — tags, triggers, variables, stage container versions (KTU GTM-KLT6WSH4, BTU GTM-PK4HC6SR) | Own `GTM_REFRESH_TOKEN` (scopes `tagmanager.readonly` + `edit.containers` + `edit.containerversions`, NO publish — humans publish in the GTM UI; current token lacks `edit.containerversions`, so `create_container_version` 403s until re-minted). Client id/secret fall back to `GOOGLE_ADS_CLIENT_ID/SECRET` |
| closebot | stdio (Python) | Bots, messages, actions, bookings, billing | API key (X-CB-KEY header) |
| companycam | stdio (Python) | Projects, photos, documents, notes, labels, users | Bearer token |
| serviceminder | stdio (Python) | Contacts, appointments, invoices, payments, proposals, downloads | Per-location API keys (KTU + BTU) |
| clarity-live | stdio (Python) | Direct live-insights endpoint (`/api/v1/project-live-insights`) for KTU+BTU — `get_live_insights`, `get_ktu_live_insights`, `get_btu_live_insights`, `test_connection` | `CLARITY_KTU_TOKEN` / `CLARITY_BTU_TOKEN` |
| clarity | HTTP MCP (bootstrap) | Clarity Data-Export: landing-page experience, traffic-by-channel (KTU+BTU) | Static bearer (`CLARITY_MCP_AUTH_TOKEN`) — Render-hosted `ktubtu-mcp-clarity` |
| clarity-ktu-export / clarity-btu-export | stdio (npm, optional) | Microsoft Clarity npm server — dashboard, recordings, docs tools per project | `CLARITY_KTU_TOKEN` / `CLARITY_BTU_TOKEN` |
| ghl-ktu | HTTP MCP (bootstrap) | HighLevel CRM for KTU (location nHLCxHPidnhV1NFzRtZZ) | PIT (`GHL_PIT_KTU` env var) |
| ghl-btu | HTTP MCP (bootstrap) | HighLevel CRM for BTU (location 0uWA8M5BzHrrcJftuaDe) | PIT (`GHL_PIT_BTU` env var) |
| jobtread | connector | Project management, estimates, invoices | Bearer token |
| Facebook Ads | connector | Campaigns, ad sets, ads, catalogs, IG boosting, experiments | OAuth |
| Google Calendar | connector | Events, calendars, scheduling | OAuth |
| Google Drive | connector | Files, permissions, search, content | OAuth |
| Gmail | connector | Email threads, drafts, labels, search | OAuth |
| Slack | connector | Channels, messages, users, search | OAuth |

### Jatalia Servers

| Server | Type | Tools | Auth |
|--------|------|-------|------|
| shipstation | stdio (Python) | Orders, shipments, rates, products, stores, carriers, fulfillments | V2 API key (Bearer) |
| amazon-sp | stdio (Python) | Orders, inventory, catalog, listings, reports, finances, FBA inbound | LWA OAuth2 (SP-API) |
| Shopify | connector | Products, orders, collections, inventory, customers, analytics | OAuth |
| amazon-ads | *(planned)* | Sponsored Products/Brands/Display campaigns, keywords, reports | LWA OAuth2 (Ads API) |
| walmart-marketplace | *(planned)* | Orders, items, inventory, prices, reports | Walmart API |
| walmart-ads | *(planned)* | Sponsored Products campaigns, keywords, reports | Walmart Connect API |

### Shared / Cross-Group

| Server | Type | Tools |
|--------|------|-------|
| cloudflare | stdio (Python) | Zones, DNS records, Pages projects/deployments, Workers, R2, KV, analytics |
| Cloudflare Developer Platform | connector | D1 databases, Workers, KV namespaces, R2 buckets, Hyperdrive |
| Bank Connection | connector | Financial analytics — cash, transactions, balances, findings (`mcp__Bank_Connection__*`) |
| GoDaddy | connector | Domain management |
| Semrush | connector | SEO analytics |
| Ahrefs | connector | SEO analytics |
| Ramp | connector | Expense management |
| Gusto | connector | Payroll/HR |
| Clay | connector | Data enrichment |
| Zapier | connector | App integrations |
| Coupler.io | connector | Data pipelines |

## Custom MCP Server Locations

All custom servers live in this repo under `mcp-servers/` and are registered on
each fresh session by `mcp-servers/bootstrap.sh` (see below). The `ghl-*` and
Render-hosted `clarity` servers are HTTP transports (no local `server.py`); the
rest are Python stdio:

```
mcp-servers/
├── bootstrap.sh          # registers every server below from env-vars
├── .env.example          # the full env-var list (names only, no secrets)
├── serviceminder/        server.py  # 29 tools (multi-location: KTU + BTU)
├── google-ads/           server.py  # 12 tools (KTU 2579406186, BTU 4477036900)
├── gmb/                  server.py  # 12 tools
├── closebot/             server.py  # 15 tools
├── companycam/           server.py  # 12 tools
├── shipstation/          server.py  # 17 tools (V2 API, Bearer auth)
├── amazon-sp/            server.py  # 15 tools (SP-API, LWA OAuth2)
├── cloudflare/           server.py  # 14 tools (Zones, DNS, Pages, Workers, R2, KV)
├── clarity/              server.py  # 4 tools — direct live-insights (KTU+BTU, Bearer)
└── gtm/                  server.py  # 12 tools — Tag Manager v2, stage-only (no publish scope)

HTTP-transport servers (registered by bootstrap.sh, no local code):
  ghl-ktu / ghl-btu   → LeadConnector hosted MCP, PIT-scoped per location
  clarity             → Render-hosted ktubtu-mcp-clarity (Data-Export, static bearer)

Direct-access helpers (curl/CLI, NOT registered MCP servers — no bootstrap needed):
  sb.sh               → Supabase REST/RPC over curl
  ghl.sh              → HighLevel over curl, same endpoint as ghl-ktu / ghl-btu
  sm.sh               → ServiceMinder Open API over curl
  gmb.sh              → Google Business Profile over curl (mints its own OAuth token)
  lead-sweep.py       → daily ad-response / missed-lead / booking-integrity sweep
  tracking-audit.py   → daily tracking-health sweep (GTM/GA4/Ads/HL/Clarity/Meta
                        config drift — paused conv tags, wrong-brand containers,
                        foreign ids, unattributed leads); Paid runs it first,
                        Tekki verifies it ran (RAG JSON, curl transport)
```

**`lead-sweep.py` — the deterministic half of Goldeneye's morning run.** One pass
over HighLevel + ServiceMinder that emits a RAG-graded JSON document: positive ad
responses, unanswered customers, missed and abandoned calls broken out **by
tracking number**, leads never worked, complaints, campaign list damage, and
bookings that exist in HighLevel or in a Perceptionist note but **not in
ServiceMinder** (an appointment nobody is scheduled to attend). Goldeneye reads
the JSON and publishes it — it does not re-derive the analysis.

```
python3 mcp-servers/lead-sweep.py --days 2 --out /tmp/lead-sweep.json
```

It self-tests every pipe first and reports failures in `degradations`; an empty
bucket next to a degradation is **unverified, not clean**. All HTTP goes through
`curl` on purpose — python-urllib gets a 403 from the session egress proxy and
would silently return zero rows.

**`ghl.sh` — HighLevel without MCP registration.** `bootstrap.sh` runs from the
Cloud environment's setup script, so when that step doesn't run (or runs after
the session's tool list is built) there are no `mcp__ghl-*` tools and an agent
wrongly reports "HighLevel unavailable" even though both PITs are valid — that
is exactly what happened on the 2026-08-21 Foreman run. `mcp-servers/ghl.sh`
calls the same LeadConnector MCP endpoint over curl, reading `GHL_PIT_KTU` /
`GHL_PIT_BTU` from the environment, so it works with zero dependency on
registration. Prefer the `mcp__ghl-*` tools when they exist; fall back to this:

```
bash mcp-servers/ghl.sh KTU tools                              # list tool names
bash mcp-servers/ghl.sh BTU contacts_get-contacts '{"query_limit":5}'
```

An agent must NOT report the HighLevel pipe as unreachable until it has tried
`ghl.sh` — "no MCP tools registered" is not the same finding as "the token is
dead", and only the latter is a real outage.

## Scheduled runs stall on MCP connector calls — use the curl helpers (canonical; verified 2026-08-27)

**The single highest-impact failure mode in this repo.** Scheduled Routines are
Claude-created, so they run in **Auto mode**, where a connector-call classifier
prompts before an `mcp__*` tool it hasn't already approved. A non-interactive
scheduled fire **cannot answer that prompt**, so the session does not error — it
**stalls in `REQUIRES_ACTION` forever**, and the next day's fire stalls at the
identical call. Nothing is logged as a failure; the board just goes stale.

`.claude/settings.json` sets `permissions.defaultMode: bypassPermissions`, and
that **does** cover Bash in scheduled runs — which is why `sb.sh` works. It does
**not** override the account-level connector classifier that gates `mcp__*`
calls. Repo settings cannot fix this; only avoiding the gated call can.

Measured on the 2026-08-19 → 08-27 outage — eight consecutive days, every
credential valid the whole time:

| Routine | Stalled on | Section that went stale |
|---|---|---|
| Tekki | `mcp__ghl-ktu__locations_get-location` | `tekky_status` (8d) |
| Organic | `mcp__gmb__list_locations` | `organic_report` (8d) |
| Foreman | `mcp__serviceminder__query_invoices` | `foreman_briefing` (8d) |
| Goldeneye | (same class) | `goldeneye_callouts` |

Moola, Pipeline and Paid ran fine across the same window **because they reach
their data through `sb.sh`/curl rather than connector tools.** That asymmetry is
the whole diagnosis: it is never the prompt, the spec, or the credential.

**The rule generalizes beyond four systems: on a schedule, NEVER call a tool
from a custom project-registered MCP server (stdio or HTTP) — only claude.ai's
own native connectors (Gmail, Slack, Zapier, QuickBooks, Shopify…) tolerate an
unattended first call.** Re-confirmed live on 2026-09-04 — three more agents hit
the identical stall on three more custom servers that have no curl helper yet,
none of them in the original four:

| Routine | Stalled on | Notes |
|---|---|---|
| Goldeneye | `mcp__closebot__test_connection` | speculative health-check call, not even asked for in `goldeneye.md` |
| Tekki | `mcp__shipstation__list_carriers` | outside Tekki's own documented probe list (§3b) — the model reached for it anyway |
| Cellar | `mcp__shipstation__test_connection` | same server as Tekki's stall, different call |
| Organic | `mcp__google-analytics__get_channel_performance` | GA4's own MCP server has no curl fallback |

Two conclusions: (1) **ShipStation is now a two-time repeat offender** — worth a
`shipstation.sh` curl helper (V2 API, Bearer token, same shape as `sm.sh`) once
`SHIPSTATION_API_KEY` is set somewhere this can be tested; until then, agents must
not call it on a schedule at all. (2) an agent doesn't have to be *told* to call a
risky tool to hit this bug — Goldeneye and Tekki both reached for a connectivity
check nobody's spec asked for, so "only call what's documented" isn't a safe
enough guardrail on its own; each agent spec now says explicitly not to call
these tools on a scheduled fire (see `goldeneye.md` §4c, `cellar.md`, `organic.md`
GA4 section, `tekki.md` §3b).

**A stall can't be caught and skipped once made.** Earlier wording here said "if
one of these raises a permission prompt, record 🟡 and move on" — that's not
how it works. The approval prompt blocks the whole turn with no `tool_result`
ever coming back; there is no code path in the prompt that runs after a stalled
call. The only real guard is to never attempt the call in the first place on a
non-interactive fire — decide from the run's own context (scheduled vs.
interactive), not from what the last call returned.

```
bash mcp-servers/sb.sh  'SELECT …'                          # Supabase
bash mcp-servers/ghl.sh KTU contacts_get-contacts '{...}'   # HighLevel
bash mcp-servers/sm.sh  KTU invoice/query '{"Take":50}'     # ServiceMinder
bash mcp-servers/gmb.sh KTU info                            # Google Business Profile
```

Diagnosing a stale board: read the Routine's `last_run.status`. `ABANDONED` +
a session in `REQUIRES_ACTION` with a `pending_action` naming an `mcp__*` tool
is this bug, not an agent error — the fix is to move that one call to its curl
helper, or drop it if none exists yet. Do **not** rewrite the agent's analysis
logic; it never ran.

**A second, unrelated failure mode wears the same "stale board" symptom: the
account's 5-hour session/usage limit.** Checked live on 2026-09-04 — five
Routines (KTU LSA Recovery Watch, Tracking Health Sweep, Paid's
customer-acquisition brief, Agent Performance sync, Harvest) all show
`session_status: SESSION_STATUS_IDLE` with `status_bucket: FAILED`,
`post_turn_summary.status_detail: "You've hit your session limit"`, and
`rate_limit_info: {rateLimitType: "five_hour", status: "rejected"}` — **not**
`REQUIRES_ACTION`, and no `pending_action` at all. This is capacity exhaustion,
not a connector stall, and no code fix applies: the account ran out of its
5-hour usage window before these Routines got their turn, most likely because
heavy interactive (Opus-tier) usage on the same account consumed it first. Tell
these two apart by `status_bucket` before touching any agent's tool calls:
`BLOCKED` + `pending_action` is the connector stall above; `FAILED` +
`rate_limit_info.status: "rejected"` is capacity, fixed only by using less of
the shared window (lighter interactive model choice, or spreading Routine fire
times further apart so they don't all compete for the same 5-hour block).

> **Tekki owns this.** The `tekki` agent (`.claude/agents/tekki.md`) re-audits the
> stack daily — maintains the Tech Stack registry + SOWs, live-probes every
> connection, keeps these tables honest, and publishes a scored health board. If
> this doc drifts from reality, that's a Tekki finding.

## Setup Script (runs on new session)

The Cloud environment's **Setup script** must provision every fresh session —
including the scheduled agent fires (Goldeneye, Moola, Paid, Pipeline, …) —
with (1) a repo checkout and (2) the custom MCP servers.

**Canonical content: `mcp-servers/setup.sh`** (version-controlled). Paste that
file's contents into the Cloud env → Setup script; if console and repo drift,
the repo file wins — re-paste it.

Why the self-healing form: scheduled fires sometimes come up with **no repo
checkout at all**. The older path-robust loop found no `bootstrap.sh`, exited 0
silently, and the session ran blind (no MCP servers, no agent specs) — which
produced stale intranet boards that looked like agent failures. `setup.sh`
fixes this: if no checkout exists it clones the repo (`--depth 1`, default
branch, `GIT_TERMINAL_PROMPT=0`, 180s timeout), then runs the MCP bootstrap,
and prints a greppable `⚠ SETUP INCOMPLETE` marker if registration still
didn't happen. It always exits 0, so setup never false-fails the session.

Setup scripts can NOT enable the claude.ai connectors (Gmail, Drive, Slack,
JobTread, Bank Connection…) — those are account-level and must be enabled for
scheduled runs in the environment/connector settings.

`bootstrap.sh` installs Python deps and registers every custom stdio server
(closebot, companycam, serviceminder, google-ads, gmb, shipstation, amazon-sp,
cloudflare, clarity-*) reading API keys from **environment variables** — see
`mcp-servers/.env.example` for the full list. Set those vars in the Cloud
environment's env-var config (they are secrets; never commit real values). A
server whose keys are missing is skipped, never registered blank. The claude.ai
connectors (Gmail, HighLevel, QuickBooks, Bank Connection, Shopify,
Slack, Zapier, Facebook) load from the account automatically and need
no bootstrap. (monday.com is being retired — its boards/docs are exported to
Google Drive and mapped by the Librarian; don't depend on the monday connector.)

### HighLevel access — OAuth is now primary (2026-08-17), PIT is the fallback

**The claude.ai OAuth connector — listed as `High Level`** (not "Highlevel") is
now the primary path, and it is **verified agency-scoped**:

- Until 2026-08-17 it was locked to a single sub-account (Bath Tune-Up only,
  `isAgencySubAccount: false`) and was also toggled off in-chat — it contributed
  nothing to either brand.
- Steven upgraded it to an **agency-level connection** and enabled it in-chat.
  **Verified the same day**, end to end, not just "connector shows connected":
  - `mcp__High_Level__list_locations` returns **both** `nHLCxHPidnhV1NFzRtZZ`
    (Kitchen Tune-Up) and `0uWA8M5BzHrrcJftuaDe` (Bath Tune-Up) — the sub-account
    lock is gone.
  - `execute_operation` → `get-location` returned 200 with correct data for
    **both** locations: KTU (`nHLCxHPidnhV1NFzRtZZ`) and BTU
    (`0uWA8M5BzHrrcJftuaDe`).
  - `execute_operation` → `search-contacts-advanced` returned 200 for both,
    with **18,488 KTU contacts / 17,586 BTU contacts** — both counts matching
    exactly what the `ghl-ktu` / `ghl-btu` PIT servers independently returned
    earlier the same day. Two different auth paths, same numbers, both brands,
    from the live API — as solid a cross-check as this gets.
- **How it's used:** unlike the old per-location servers, this is one connector
  with generic `search_operations` / `describe_operation` / `execute_operation`
  tools covering the full GHL public API — pass `locationId` explicitly per call
  (KTU `nHLCxHPidnhV1NFzRtZZ` / BTU `0uWA8M5BzHrrcJftuaDe`) since the connection
  is multi-location. This also closes the earlier `calendars` gap in a general
  way: `search_operations` can find calendar/user/group list endpoints that the
  old per-location `ghl-ktu`/`ghl-btu` servers simply didn't expose as tools.
- **One thing still to confirm, not yet blocking:** connector enablement is
  account-level per the existing rule in this file ("Setup scripts can NOT
  enable the claude.ai connectors... must be enabled for scheduled runs in the
  environment/connector settings") — the same caveat that already applies to
  Gmail/Drive/Slack. Confirm `High Level` is enabled for **scheduled Routine**
  fires specifically (Goldeneye/Paid/Foreman), not just this interactive
  session, before fully retiring the PIT fallback below.

**The per-location PIT servers `ghl-ktu` / `ghl-btu`** (LeadConnector hosted HTTP
MCP, registered by `bootstrap.sh`) are now the **fallback**, kept wired for
resilience and for anything that still needs the older per-location tool shape:

- `ghl-ktu` → KTU location `nHLCxHPidnhV1NFzRtZZ`
- `ghl-btu` → BTU location `0uWA8M5BzHrrcJftuaDe`
- Token env vars: `GHL_PIT_KTU` / `GHL_PIT_BTU` (per-location), or
  `GHL_PIT_AGENCY` alone to cover both. **Currently unset** — Steven removed
  these intentionally once the OAuth connector was confirmed working, so
  `bootstrap.sh` skips both servers on a fresh session. Restore either if the
  OAuth connector's Routine-scheduling coverage doesn't check out.

A third path was explored and abandoned same-day: a self-serve OAuth MCP
endpoint at `services.leadconnectorhq.com/mcp/anthropic/v2` (server name
`leadconnector`), authenticated via `claude mcp login`. It requires a live
browser + localhost callback that can't complete in a headless Cloud session,
and even if authenticated it would have registered at **local, per-container
scope** — useless for ephemeral scheduled sessions. Removed once the connector
path (above) verified working instead. Not worth resurrecting unless the
connector path breaks.

**If the PIT servers are ever wired again** (env vars restored as fallback — see
above, this is not the current state): `bootstrap.sh` needs `GHL_PIT_KTU` +
`GHL_PIT_BTU`, or `GHL_PIT_AGENCY` alone, to register `ghl-ktu`/`ghl-btu` at
all. Missing either means that brand's PIT-server fallback silently doesn't
register — check whether the OAuth connector (now primary) is still covering
that brand before treating it as an incident. To sanity-check a token without
registering anything, curl it directly — a valid token returns 200 with the
location name:
`curl -H "Authorization: Bearer $GHL_PIT_KTU" -H "Version: 2021-07-28" https://services.leadconnectorhq.com/locations/nHLCxHPidnhV1NFzRtZZ`
A 401 there means the token itself is revoked/expired → regenerate the location's
Private Integration Token in HighLevel and update the env var. A 200 there while
the pipe still shows broken means it's purely the env-var wiring.

#### Verified tool surface (both `ghl-ktu` and `ghl-btu`, audited 2026-08-17)

Both servers expose the **same 36 tools across 9 families**, and both PITs
returned HTTP 200 on a live read of every family — the two locations are at
parity, so anything that works for one brand works for the other:

| Family | Tools | Live probe result |
|---|---|---|
| `contacts` | 8 | 🟢 KTU 18,488 · BTU 17,586 contacts |
| `conversations` | 3 | 🟢 KTU 11,056 · BTU 8,459 conversations |
| `opportunities` | 4 | 🟢 KTU 3,253 · BTU 1,583 open |
| `locations` | 2 | 🟢 name + custom fields resolve per brand |
| `payments` | 2 | 🟢 KTU 3 txns · BTU 0 (empty, not an error) |
| `emails` | 2 | 🟢 KTU 7 · BTU 13 templates |
| `social-media-posting` | 6 | 🟢 KTU 10 · BTU 4 accounts |
| `blogs` | 7 | 🟢 200, no blog sites configured on either |
| `calendars` | 2 | 🟢 KTU 57 events (old ID) · 🟢 BTU 155 events (corrected ID) |

#### Consultation calendar IDs — RESOLVED via the OAuth connector's `get-calendars`

The old per-location `ghl-ktu`/`ghl-btu` servers had no list-calendars tool, so
`calendars_get-calendar-events` (422 without a `calendarId`) needed IDs recorded
by hand, and there was no way to tell an empty result from a wrong ID. **The
`High Level` OAuth connector's generic operations close this gap** —
`search_operations` finds `get-calendars` (list, per location) and
`get-calendar-events` (by ID), covering what the old surface couldn't.

| Brand | Consultation calendar ID | Name | isActive | Status |
|---|---|---|---|---|
| KTU | `IezEuyUywqr1OL7tjHEk` | Consultation Calendar | ✅ true | ✅ verified — 57 events (60-day window, 2026-07-18→08-29) |
| BTU | ~~`15oJxXW4lJZpbYyk6Zca`~~ | ~~Free In-Home consultation~~ | ❌ **false** | ⚠️ retired — this was the source of the earlier "empty" mystery |
| BTU | **`k6bokOz0oIicKYu93zhW`** | **Consultation Calendar** | ✅ true | ✅ **verified — 155 events for 2026** (88 confirmed, 67 cancelled) |

**The mystery is solved, not just worked around.** The BTU ID Steven originally
gave (`15oJxXW4lJZpbYyk6Zca`) is real and correctly scoped to BTU — it's just a
**retired legacy calendar** (`isActive: false`, type `round_robin`, named "Free
In-Home consultation"). KTU has the exact same fossil sitting alongside its
working calendar (`MScsc3B7AFkpkwMTQ4Zk`, same name, also `isActive: false`) —
so this looks like a naming migration both brands went through, where an old
"Free In-Home consultation" calendar was replaced by a `service_booking`-type
"Consultation Calendar" and the old one was never deleted, just deactivated.
**Lesson for future calendar IDs supplied by Steven or pulled from the GHL UI:
cross-check `isActive` via `get-calendars` before trusting an ID that returns
empty** — don't assume the endpoint or the ID is broken.

Appointment truth still belongs to ServiceMinder; use the GHL calendar as a
cross-check, not as the system of record.

## Scheduling & notification delivery (how the automation actually runs)

Two independent schedulers — do not confuse them:

- **Daily/hourly agents (Goldeneye, Moola, Foreman, Paid, Organic, Tekki, Ax)** run
  as **Claude Code Remote Routines** (CCR cron triggers), *not* Supabase cron. Each
  firing spins up a fresh non-interactive Claude session that reads the agent's
  `.claude/agents/*.md` and writes to Supabase. If a Routine's session can't
  authenticate its connectors, it fires but writes nothing (silent failure).
- **Notification delivery + freshness** run in **Supabase pg_cron** (enabled 2026-07-06;
  `pg_cron` + `pg_net`):
  - `dispatch-notify` (every minute) → the `dispatch-notify` Edge Function drains
    `notify_queue` (Slack DM via bot token / webhook, email via Resend). It is
    **dormant until `SLACK_BOT_TOKEN` is set** as a function secret; until then Ax's
    hourly run is the primary dispatcher. Auth is a shared secret in `public.app_config`.
  - `agent-freshness-watchdog` (hourly) → `check_agent_freshness()` writes stale agents
    to the `system_health` section and queues one alert per stale section per day.

To activate real-time delivery, set function secrets on the `dispatch-notify` function:
`SLACK_BOT_TOKEN` (scopes `chat:write`, `users:read.email`, `im:write`), optional
`SLACK_ALERTS_CHANNEL`, and `RESEND_API_KEY` + `NOTIFY_FROM_EMAIL` for email.

### The 09:00–11:20 UTC dead zone (observed 2026-08-22)

Every **enabled** Routine scheduled between 09:00 and 11:20 UTC silently stopped
writing after 2026-08-19, while every Routine outside that band stayed current.
Four for four against six for six, with identical environment, no persistent
session binding, and no config difference between the two groups:

| Fires (UTC) | Routine | Last wrote |
|---|---|---|
| 06:00 | Cellar | ✅ current |
| 07:00 | Goldeneye | ✅ current |
| 08:00 | Moola | ✅ current |
| **09:00** | **Tekki** | ❌ stuck at 2026-08-19 |
| **10:00** | **Organic** | ❌ stuck at 2026-08-19 |
| **11:00** | **Paid** | ❌ stuck at 2026-08-19 |
| **11:18** | **Pipeline** | ❌ stuck at 2026-08-19 |
| 12:00 | Foreman | ✅ current |
| 13:00 | Ax | ✅ current |
| 14:00 | Harvest | ✅ current |

**Recommended mitigation — must be done by Steven, an agent cannot do it.** Move
these four out of the band to slots that demonstrably work, e.g. Tekki 15:00,
Organic 16:00, Paid 17:00, Pipeline 17:30. `update_trigger` refuses here: these
Routines were created via `http_api`, and an agent may only update Routines it
created itself (`update_trigger: this routine was created via "http_api"`). So
the reschedule has to happen in the Routines UI.

**This is a mitigation, not a root cause** — the mechanism is unconfirmed, and it
could equally be a capacity/quota window on the CCR side. If the moved Routines
start writing again, the band is real; if they still fail at the new times, the
cause is agent-specific and the schedule was a red herring. Re-check
`max(fields->>'scan_date')` per section before concluding either way.

Note the band is a *correlation across ten Routines*, not a proven mechanism.
Before spending long on it, rule out the cheap explanation: open one failed run's
session transcript and read the actual error. A connector that fails to
authenticate produces exactly this signature — the Routine fires, the agent runs,
and it writes nothing.

**Why this is hard to notice:** these agents write with *write-then-prune by
`scan_date`*, so a failed run leaves the last good day's rows in place. The tab
renders fine and simply shows stale data — there is no error state on screen.
`last_run` is also empty on every Routine here (they are persistent-session
bound), so the scheduler's own history cannot be used to spot it. The only
reliable check is the per-section `scan_date` query above.

## Scheduled agent runs — model tiers & no-repo-writes policy

Two rules keep the daily fleet cheap and stop the duplicate-PR loop. Agent specs
use `model: inherit`, so the model is set on the **CCR Routine**, not the spec.

**1. Pin a model tier per Routine — never leave it on the env default (Opus 5).**
Daily ops agents do read → gather → write-brief work; none needs Opus.
- **Haiku 4.5** (`claude-haiku-4-5`) — mechanical / high-frequency: Ax (hourly
  dispatcher), the ServiceMinder→intranet syncs (Agent Performance, Appointment
  Follow-ups), the office-address check (12×/day).
- **Sonnet 5** (`claude-sonnet-5`) — the daily analytical briefs: Goldeneye,
  Foreman, Paid, Moola, Organic, Pipeline, Cellar, Harvest, Tekki.
- **Opus** — none of the recurring runs; reserve for one-off deep work.
An unpinned Routine silently rides the env default (Opus 5) and burns tokens —
new Routines MUST set a model. Keep **one** Routine per agent (no duplicate daily
runs — e.g. a single Paid, single Tekki, single Moola).

**2. Scheduled ops agents write to Supabase, never to the repo.** Goldeneye,
Moola, Foreman, Paid, Organic, Pipeline, Tekki, Ax, Cellar, Harvest, Librarian
publish via `sb.sh` / Supabase only — they must NOT `git commit`, `git push`, or
open a pull request. The duplicate-PR loop (dozens of "Add sb.sh" drafts, ~24/day)
came from fired sessions landing on stale `claude/*` branches, re-adding the
missing `sb.sh`, and auto-PRing it. `setup.sh` now hard-resets each run to
`origin/main` (so `sb.sh` is already present and there is nothing to commit), and
its `SETUP_SCRIPT_VERSION` echo lets you confirm the Cloud-console Setup-script
copy isn't stale. Point each Routine's environment at `main`, not a fresh
`claude/*` branch.

## Connection ownership (pipe → consumer agent)

Which agent depends on which pipe — so a broken connection maps straight to the
brief it degrades. Tekkie audits all of these daily.

| Pipe / source | Primary consumer agent(s) | What breaks if it's down |
|---|---|---|
| ServiceMinder (`SM_KEY_KTU/BTU`) | Moola, Foreman, Paid | Revenue/invoice/appointment truth; ROI tie-back |
| HighLevel `ghl-ktu` / `ghl-btu` | Goldeneye, Paid, Foreman | Customer conversations, lead attribution, HL→SM sync audit |
| Google Ads + LSA / Meta Ads | Paid | Spend sweep, CPL/CAC/ROAS |
| Clarity (`clarity-live` stdio, `clarity` Render, `clarity-*-export` npm) | Paid, Organic | Landing-page-experience check; live-insights direct feed |
| QuickBooks / Ramp / Bank_Connection | Moola | P&L, AR/AP, cash flow, card spend |
| CompanyCam / JobTread | Foreman | Field progress, estimates, PM status |
| Shopify / ShipStation / Amazon SP | Cellar (fulfillment), Harvest (demand) | Orders, inventory, FBA, ad ROAS |
| Supabase intranet (`tguwpswcneywvscxzyef`) | ALL agents (publish target) | No agent can post its brief to the intranet |
| Cloudflare Workers/Pages | (infra) | Dashboard + intranet hosting |

## Google Drive routing (two drives — do not cross them)

Two Google Drives are connected; agents may read either as needed, but they
serve different purposes and different audiences:

- **Business library — `ktubloomfieldnj@gmail.com`, the DIRECT `Google Drive`
  connector.** Numbered top-level folders (`01 Company & HR` … `07 Vendors &
  Products`, `KTU Resources`, `.Project Management`). This is the team library:
  it feeds the intranet **Library** (`library_docs`) and the per-section doc
  links. The Librarian maps its folders into the tabs.
  - Two of its folders are owner-sensitive: **`06 Finance`** (business books/
    reports) and **`01 Company & HR`** (comp/HR). Keep these out of the
    team-visible surfaces — route Finance to the owner-only `docs_finance`.
- **Owner personal drive — `stevenglivingston@gmail.com`, via the Zapier / KTU
  MCP route (NOT the direct connector).** Holds personal financials & legal
  (`05 Finance & Legal`, etc.). Link it ONLY into the owner-only Cash Flow /
  Finance sections (`docs_finance`, RLS admin-only). Never publish it to any
  team-visible tab.

Rule of thumb: **business/library docs → direct `ktubloomfield` connector;
anything personal or financial → owner-only sections**, sourced from the
personal drive via Zapier. Financial doc links live in `docs_finance`, which is
RLS-locked to `is_admin()`.

## ServiceMinder notes — where they actually live (canonical; verified 2026-08-25)

Every agent that reports a cancellation reason, a call summary, or "what the customer
said" reads this. **There are three separate places notes live, none of them reliably
populated, so check all three and merge.** Earlier specs asserted one source was "the
truth" and another was "always empty" — both claims were over-generalised from single
samples and were wrong. Report which source each note came from.

| # | Source | How to read it | Reality check |
|---|---|---|---|
| 1 | **Appointment free-text** | `find_appointment(location, appointment_id)` → `Notes`, `UpdateNote` | Where a rep's "family situation, must reschedule" lands. **Was null** on the live cancellation checked 2026-08-25. |
| 2 | **Contact notes** | `find_contact(location, id_search=<ContactId>)` → `Matches[0].Notes[]` — an **array** of `{Id, Title, Body}` | Titles seen live: `Perceptionist Call`, `Form`, hand-written. **Held the real content** on that same cancellation. Read every element; prefer the highest `Id`. |
| 3 | **Cancel-reason picklist** | `CancelReasonId` on the appointment | Populated on **8 of 57** cancelled KTU appointments over 7 weeks (~14%). Observed ids `3523`, `4279`. |

**Traps that produce false "no reason" reports:**
- `query_appointments` returns `CancelReasonId` at the **top level** of each appointment.
  `find_appointment` returns **`CancelReasonId: 0` at the top level** and the real value
  nested in **`Slots[].CancelReasonId`**. Read the Slot.
- `query_appointments` returns **`Contact: null`** unless you pass `include_contact=true`
  — so the contact's notes are never in a bulk pull. You must resolve the contact
  separately by `ContactId`.
- **`Status` is numeric**: `1` = scheduled, `3` = completed, `4` = cancelled.
- **There is no cancel-reason lookup endpoint.** Probed `cancelreasons`,
  `settings/cancelreasons`, `lookups/cancelreasons`, `appointmentcancelreasons` — all
  return HTTP 200 with an **empty body**, which is how this API signals "no such
  endpoint" (it does not 404). Get the id→label map from the cancellation **download**
  (which carries reason text) or the SM UI; until then pass the id through rather than
  inventing a label.
- Never conclude "no notes" from one source. `no_reason_logged` requires all three empty.

## Environment Requirements

- Python 3.x with pip
- Network policy: **Trusted** (required for closebot, companycam, serviceminder, shipstation APIs)
- Google OAuth2 Desktop client for google-ads and gmb servers

## Location Reference

| Code | Business | Address |
|------|----------|---------|
| KTU | Kitchen Tune-Up | 1285 Broad St, Suite 2, Bloomfield NJ 07003 |
| BTU | Bath Tune-Up | 1285 Broad Street, Unit 2, Bloomfield NJ 07003 |

## Active Builds

| Project | Path | Purpose |
|---------|------|---------|
| KTU Instant Tune-Up Funnel | **moved 2026-08-19 →** [`ktubtu-automations/tuneup-funnel/`](https://github.com/stevenglivingston-NJ/ktubtu-automations/tree/main/tuneup-funnel) | Instant-quote + booking funnel for `ktubloomfield.com/tuneup` (Cloudflare Workers + Pages, D1/KV/R2, ServiceMinder, HighLevel, Meta/GA4). Phases 1–5 complete, full git history preserved on the move. No longer in this repo. |

## Dashboards

| Group | Purpose | URL |
|-------|---------|-----|
| Shared | Axyom Intranet — agent briefings; Finance tab = Moola (owner-only). Source of truth `intranet/ktubtuintranet.html`, deploy per `intranet/DEPLOY.md` | https://dash.goaxyom.com |
| Jatalia | Ops dashboard | https://go.jataliamarketplace.com/ |

## Cloudflare Workers

| Name | Purpose |
|------|---------|
| ktubtuintranet | KTU/BTU internal intranet |
| ktu-cmo-dashboard-auth | KTU CMO dashboard auth layer |
| ktu-dashboard-auth | KTU dashboard auth layer |
| city-replacement | City replacement service |
