# Team Livingston - Claude Code Environment

## Overview

This environment manages operations for two business groups:
- **KTUBTU** — Kitchen Tune-Up (KTU) and Bath Tune-Up (BTU) franchise locations in Bloomfield, NJ
- **Jatalia** — Jatalia / Earthwise brand operations

## MCP Servers

### KTUBTU Servers

| Server | Type | Tools | Auth |
|--------|------|-------|------|
| google-ads | stdio (Python) | Campaigns, keywords, search terms, geo performance, LSA | OAuth2 (Desktop client) |
| gmb | stdio (Python) | Reviews, metrics, search keywords, location info, hours | OAuth2 (shared with google-ads) |
| closebot | stdio (Python) | Bots, messages, actions, bookings, billing | API key (X-CB-KEY header) |
| companycam | stdio (Python) | Projects, photos, documents, notes, labels, users | Bearer token |
| serviceminder | stdio (Python) | Contacts, appointments, invoices, payments, proposals, downloads | Per-location API keys (KTU + BTU) |
| clarity | HTTP MCP (bootstrap) | Clarity Data-Export: landing-page experience, traffic-by-channel (KTU+BTU) | Static bearer (`CLARITY_MCP_AUTH_TOKEN`) — Render-hosted `ktubtu-mcp-clarity` |
| clarity-ktu-export / clarity-btu-export | stdio (npm, optional) | Microsoft Clarity npm server — alternative to the Render `clarity` above | `CLARITY_KTU_TOKEN` / `CLARITY_BTU_TOKEN` |
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
├── serviceminder/        server.py  # 28 tools (multi-location: KTU + BTU)
├── google-ads/           server.py  # 11 tools (KTU 2579406186, BTU 4477036900)
├── gmb/                  server.py  # 12 tools
├── closebot/             server.py  # 15 tools
├── companycam/           server.py  # 12 tools
├── shipstation/          server.py  # 17 tools (V2 API, Bearer auth)
├── amazon-sp/            server.py  # 15 tools (SP-API, LWA OAuth2)
└── cloudflare/           server.py  # 14 tools (Zones, DNS, Pages, Workers, R2, KV)

HTTP-transport servers (registered by bootstrap.sh, no local code):
  ghl-ktu / ghl-btu   → LeadConnector hosted MCP, PIT-scoped per location
  clarity             → Render-hosted ktubtu-mcp-clarity (Data-Export, static bearer)
```

> **Tekki owns this.** The `tekki` agent (`.claude/agents/tekki.md`) re-audits the
> stack daily — maintains the Tech Stack registry + SOWs, live-probes every
> connection, keeps these tables honest, and publishes a scored health board. If
> this doc drifts from reality, that's a Tekki finding.

## Setup Script (runs on new session)

Point the Cloud environment's **Setup script** at the MCP bootstrap so every
fresh session (including the scheduled agent runs — Goldeneye, Moola, Paid)
re-registers the custom stdio MCP servers, not just this repo's clone:

```bash
bash "$(git -C /home/user/TeamLivingston rev-parse --show-toplevel)/mcp-servers/bootstrap.sh"
```

`bootstrap.sh` installs Python deps and registers every custom stdio server
(closebot, companycam, serviceminder, google-ads, gmb, shipstation, amazon-sp,
cloudflare, clarity-*) reading API keys from **environment variables** — see
`mcp-servers/.env.example` for the full list. Set those vars in the Cloud
environment's env-var config (they are secrets; never commit real values). A
server whose keys are missing is skipped, never registered blank. The claude.ai
connectors (Gmail, HighLevel, QuickBooks, Bank Connection, Shopify,
monday, Slack, Zapier, Facebook) load from the account automatically and need
no bootstrap.

### HighLevel access — two paths, and the KTU gotcha

HighLevel is reachable **two different ways**, and they are NOT interchangeable —
this is the #1 cause of "HighLevel connection broken" and of Goldeneye/Paid
coming back blind on KTU:

1. **The claude.ai `Highlevel` connector (OAuth)** — loads from the account, no
   bootstrap. But it is **locked to a single sub-account: Bath Tune-Up**
   (`isAgencySubAccount: false`). It cannot switch locations, so it covers **BTU
   only**. There is no location parameter that makes it reach KTU.
2. **The per-location PIT servers `ghl-ktu` / `ghl-btu`** (LeadConnector hosted
   HTTP MCP, registered by `bootstrap.sh`) — each scoped to one location by a
   Private Integration Token in an env var:
   - `ghl-ktu` → KTU location `nHLCxHPidnhV1NFzRtZZ`, token `GHL_PIT_KTU`
   - `ghl-btu` → BTU location `0uWA8M5BzHrrcJftuaDe`, token `GHL_PIT_BTU`

**KTU HighLevel only works via `ghl-ktu`.** If `GHL_PIT_KTU` isn't set in the
environment's env-var config, `bootstrap.sh` skips that server, the intranet /
Tekki health check flags the KTU HighLevel pipe as broken, and any agent that
reads KTU conversations (Goldeneye, Paid, Foreman) silently misses all KTU
SMS/email/calls. BTU can still *look* fine because the OAuth connector covers it —
masking the fact that KTU is dark.

**Fix = wire the two env vars** (values are the location PITs; set them in the
Cloud environment's env-var/secrets config, never in the repo). To sanity-check a
PIT without registering anything, curl it directly — a valid token returns 200
with the location name:
`curl -H "Authorization: Bearer $GHL_PIT_KTU" -H "Version: 2021-07-28" https://services.leadconnectorhq.com/locations/nHLCxHPidnhV1NFzRtZZ`
A 401 there means the token itself is revoked/expired → regenerate the location's
Private Integration Token in HighLevel and update the env var. A 200 there while
the pipe still shows broken means it's purely the env-var wiring.

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

## Connection ownership (pipe → consumer agent)

Which agent depends on which pipe — so a broken connection maps straight to the
brief it degrades. Tekkie audits all of these daily.

| Pipe / source | Primary consumer agent(s) | What breaks if it's down |
|---|---|---|
| ServiceMinder (`SM_KEY_KTU/BTU`) | Moola, Foreman, Paid | Revenue/invoice/appointment truth; ROI tie-back |
| HighLevel `ghl-ktu` / `ghl-btu` | Goldeneye, Paid, Foreman | Customer conversations, lead attribution, HL→SM sync audit |
| Google Ads + LSA / Meta Ads | Paid | Spend sweep, CPL/CAC/ROAS |
| Clarity (`clarity`, Render) | Paid | Landing-page-experience check |
| QuickBooks / Ramp / Bank_Connection | Moola | P&L, AR/AP, cash flow, card spend |
| CompanyCam / JobTread | Foreman | Field progress, estimates, PM status |
| Shopify / ShipStation / Amazon SP | Cellar (fulfillment), Harvest (demand) | Orders, inventory, FBA, ad ROAS |
| Supabase intranet (`tguwpswcneywvscxzyef`) | ALL agents (publish target) | No agent can post its brief to the intranet |
| Cloudflare Workers/Pages | (infra) | Dashboard + intranet hosting |

## Environment Requirements

- Python 3.x with pip
- Network policy: **Trusted** (required for closebot, companycam, serviceminder, shipstation APIs)
- Google OAuth2 Desktop client for google-ads and gmb servers

## Location Reference

| Code | Business | Address |
|------|----------|---------|
| KTU | Kitchen Tune-Up | 1285 Broad St, Suite 2, Bloomfield NJ 07003 |
| BTU | Bath Tune-Up | 1285 Broad Street, Unit 2, Bloomfield NJ 07003 |

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
