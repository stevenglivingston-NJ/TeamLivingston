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
| clarity-ktu | connector (npm) | Dashboard analytics, session recordings | Microsoft Clarity |
| clarity-btu | connector (npm) | Dashboard analytics, session recordings | Microsoft Clarity |
| ktu-highlevel | connector (HTTP) | HighLevel CRM for KTU | JWT Bearer token |
| btu-highlevel | connector (HTTP) | HighLevel CRM for BTU | JWT Bearer token |
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
| Truthifi | connector | Financial analytics (requires OAuth authorization) |
| GoDaddy | connector | Domain management |
| Semrush | connector | SEO analytics |
| Ahrefs | connector | SEO analytics |
| Ramp | connector | Expense management |
| Gusto | connector | Payroll/HR |
| Clay | connector | Data enrichment |
| Zapier | connector | App integrations |
| Coupler.io | connector | Data pipelines |

## Custom MCP Server Locations

All Python stdio servers live under `/root/code/`:

```
/root/code/
├── closebot-mcp/
│   ├── server.py        # 15 tools
│   └── requirements.txt
├── companycam-mcp/
│   ├── server.py        # 12 tools
│   └── requirements.txt
├── google-ads-mcp/
│   ├── server.py        # 11 tools (KTU acct 2579406186, BTU acct 4477036900)
│   └── requirements.txt
├── gmb-mcp/
│   ├── server.py        # 12 tools
│   └── requirements.txt
├── serviceminder-mcp/
│   ├── server.py        # 28 tools (multi-location: KTU + BTU)
│   └── requirements.txt
├── shipstation-mcp/
│   ├── server.py        # 17 tools (V2 API, Bearer auth)
│   └── requirements.txt
└── amazon-sp-mcp/
    ├── server.py        # 15 tools (SP-API, LWA OAuth2)
    └── requirements.txt
```

## Setup Script (runs on new session)

```bash
pip install mcp[cli] httpx google-ads google-auth
```

## Environment Requirements

- Python 3.x with pip
- Network policy: **Trusted** (required for closebot, companycam, serviceminder, shipstation APIs)
- Google OAuth2 Desktop client for google-ads and gmb servers

## Location Reference

| Code | Business | Address |
|------|----------|---------|
| KTU | Kitchen Tune-Up | 1285 Broad St, Suite 2, Bloomfield NJ 07003 |
| BTU | Bath Tune-Up | 1285 Broad Street, Unit 2, Bloomfield NJ 07003 |
