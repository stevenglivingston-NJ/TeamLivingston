# Jatalia / Earthwise → Cloud migration

Moves the standalone Jatalia dashboard pipeline into this repo + the Cloud
(CCR Routine) environment, rendering natively under the intranet's **Earthwise**
section. Branch: `jatalia-cloud-migration` (4 commits). Nothing runs in the Cloud
until this is merged to `main` (the Setup script hard-resets to `main`).

## What moved

| Area | Path | Notes |
|---|---|---|
| Deterministic sweep (Cellar's half) | `mcp-servers/jatalia/jatalia_sweep.py` | Runs the builders → writes `intranet_records` (brand `Earthwise`), write-then-prune by `scan_date`. Mirrors `lead-sweep.py`/Goldeneye. |
| Headless Shopify feed | `mcp-servers/jatalia/shopify_costs.py` | Admin API prices + unit costs; ACTIVE-over-DRAFT SKU collision fix. Replaces the session-only MCP/Coupler pull. |
| Ported builders | `mcp-servers/jatalia/{server,build_jatalia_data,build_ops_data,build_latency_data,check_exceptions}.py` | ShipStation client + billing/ops/scan-latency/exceptions. |
| Walmart Marketplace returns | `mcp-servers/jatalia/walmart_pull.py` | Optional sweep builder; feeds returns + shipping P&L. |
| Amazon Ads MCP | `mcp-servers/amazon-ads/server.py` | Harvest lane. |
| Walmart Ads MCP | `mcp-servers/walmart-ads/server.py` | Harvest lane. |
| SP-API keep-alive | `mcp-servers/amazon-sp/ping.py` | One successful call to reset the 60-day inactivity clock. |
| Intranet render | `intranet/ktubtuintranet.html` → `renderEarthOps()` | Earthwise **Orders & Fulfillment** tab renders the 4 sweep sections. |
| Agent spec | `.claude/agents/cellar.md` | Runs the sweep as step 0, narrates from the digest. |

Sweep sections written: `cellar_fulfillment`, `cellar_orders`, `cellar_exceptions`,
`cellar_billing`. Cellar still owns `cellar_briefing` + `exec_summary`.

## Cloud env → Environment variables

```
# Jatalia / Earthwise
SHIPSTATION_API_KEY=          # ShipStation V2
SHOPIFY_ADMIN_TOKEN=          # custom app, scopes read_products + read_inventory
SHOPIFY_SHOP_DOMAIN=earthwiseseed.myshopify.com
SUPABASE_URL=                 # https://tguwpswcneywvscxzyef.supabase.co
SUPABASE_SERVICE_ROLE_KEY=

# Amazon SP-API (direct ops — orders/inventory/FBA/finances/returns)
AMAZON_SP_CLIENT_ID=
AMAZON_SP_CLIENT_SECRET=
AMAZON_SP_REFRESH_TOKEN=

# Amazon Ads (Harvest) — US profile is 279048135141375 (NOT the MX 1035588453215307)
AMAZON_ADS_CLIENT_ID=
AMAZON_ADS_CLIENT_SECRET=
AMAZON_ADS_REFRESH_TOKEN=
AMAZON_ADS_PROFILE_ID=279048135141375
AMAZON_ADS_REGION=NA

# Walmart Marketplace (returns feed)
WMT_CLIENT_ID=
WMT_CLIENT_SECRET=
WMT_SELLER_ID=

# Walmart Ads (Harvest)
WMT_ADS_CLIENT_ID=
WMT_ADS_CLIENT_SECRET=
WMT_ADS_ADVERTISER_ID=
```

## Post-merge checklist

1. **Merge** `jatalia-cloud-migration` → `main`.
2. **Set the env vars above** in the Cloud environment.
3. **SP-API keep-alive (urgent — the 60-day deadline already lapsed):**
   `python3 mcp-servers/amazon-sp/ping.py` — expect `✅ SP-API call OK`. Re-run monthly (or add a small Routine).
4. **Sanity-check a Cloud session:** `claude mcp list` shows `amazon-ads`, `walmart-ads`, `amazon-sp`, `shipstation` registered (a server with missing creds is skipped, not blank).
5. **Run the sweep once** to populate the tab: `python3 mcp-servers/jatalia/jatalia_sweep.py` (add `--dry-run` to preview without writing).
6. **Deploy the intranet** (after the mandatory diff-against-live in `intranet/DEPLOY.md`): `cd intranet && npm run deploy`.
7. **Point the Cellar Routine** at `main`, model Sonnet.

## First-run validation (couldn't be tested locally)

- **Walmart returns parser** (`walmart_pull.py`) — built to Walmart's documented `/v3/returns` shape; confirm the flattening against a real payload.
- **Walmart Ads endpoints** (`walmart-ads/server.py`) — replicated the local code's `ADS_BASE` + paths 1:1; confirm `test_connection` returns campaigns.
- **SP-API returns / seller-health** — needs the SP-API **role** enabled on the LWA app + a re-minted refresh token (clears `AMAZON RETURNS pending`).

## Retire after cutover

- Local Mac cron for the Jatalia dashboard.
- `go.jataliamarketplace.com` standalone build (keep as a mirror during overlap, then retire).

## Docs to fix

- Global + repo CLAUDE.md list the Amazon Ads account as `1035588453215307` — that's the **MX** profile. The **US** Ads profile is `279048135141375`.
