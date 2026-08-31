# Axyom Intranet (`ktubtuintranet` Cloudflare Worker)

> ## 🔴 `npm run deploy` does NOT match what's live (found 2026-08-31)
> The live Worker serves the intranet HTML as a **Workers Asset**
> (`env.ASSETS.fetch(request)`), and `worker.js` also runs a small `/api/ghl`
> proxy (GHL contact search, bearer-auth'd against Supabase) in front of it.
> This repo's `build.mjs` instead produces a single-file worker with the HTML
> inlined and **no GHL proxy at all** — `npm run deploy` as written would
> regress the proxy and likely break asset serving, because `wrangler.jsonc`
> here had no `assets` stanza either. Both are now fixed:
> - `wrangler.jsonc` gained an `assets` block (`directory: ./public`,
>   `binding: ASSETS`, SPA fallback) matching what's live.
> - `worker.js` is **gitignored** (as before) but must be the GHL-proxy
>   script, not build.mjs's output, until build.mjs is rewritten to produce
>   it. Fetch the live one with the Cloudflare MCP's `workers_get_worker_code`
>   (`scriptName: "ktubtuintranet"`) if you don't have a copy — it changes
>   rarely, only when the GHL proxy itself changes.
> - Correct deploy, until `npm run deploy` is fixed to do this automatically:
>   `mkdir -p public && cp ktubtuintranet.html public/index.html && npx wrangler deploy`,
>   then verify with `node tools/drift-check.mjs` and a manual curl of
>   `/api/ghl/health` (expect `401 {"error":"unauthorized"}`, not `404`/`500`
>   — a wrong response there means the proxy didn't deploy).
>
> This was discovered adding the Activity Log tab, not caused by it — the
> drift predates this session. `npm run deploy`/`build.mjs` should be fixed
> to generate the correct worker.js so this stops being a manual step; that
> wasn't done here to keep this change to what was asked.

> ## ⚠️ Reconciliation in progress (2026-08-18)
> `ktubtuintranet.html` has been **reset to match the live worker byte-for-byte**,
> so **deploying is now safe — it is a no-op against production.**
>
> A month of repo-side work is NOT yet in this file. It is preserved in
> `ktubtuintranet.repo-snapshot-2026-08-18.html` and is being ported back in
> tab by tab. Read **[RECONCILIATION.md](RECONCILIATION.md)** before editing.
>
> Until the port completes, deploying ships live's own content back to live —
> harmless, but it does not yet restore the Cash Flow, Paid, Organic or Library
> tabs.

`ktubtuintranet.html` is the full single-file app served at **https://dash.goaxyom.com**.
It was recovered from live on 2026-07-05, then the two copies forked (see
RECONCILIATION.md). As of 2026-08-18 this file is a **verbatim copy of the live
worker** again, which makes it a truthful base to build on — **treat it as the
source of truth and deploy only from here**, so the two never drift again.

The worker is a static HTML server: no server-side routes, all data flows
browser → Supabase (`tguwpswcneywvscxzyef`) via supabase-js with the public
anon key. Auth is Supabase email+password with RLS; role comes from `profiles`.

## Changes in this copy vs live (fetched 2026-07-05)

Finance tab, `renderMoola()`:
1. **Severity-priority sort** — urgent → warn → info, then `sort_order` (matches Goldeneye/Pipeline behavior; a misordered insert can no longer bury an urgent row).
2. **Brand chips on rows** — entity-specific rows (KTU/BTU/Earthwise) now show a `brandTag` chip, so items are distinguishable in the "Axyom (all)" workspace. The existing global workspace switcher pills already filter Finance by brand.
3. **Stale-briefing banner** — if the latest `scan_date` is older than today (after 8am ET) or older than yesterday, a ⏰ warn row says the scheduled run may have failed. This makes a silent Moola failure (like 2026-07-04's) visible on the dashboard instead of showing yesterday's data as if it were fresh.
4. **Icon map knows all kinds** — added `liability` 🏦, `risk` 🎯, `question` ❓, `status` 📊, `paid-challenge` ⚖️.
5. Fixed the outdated "RLS lands later" security note (RLS is live).

## Structure

```
intranet/
├── ktubtuintranet.html   # SOURCE OF TRUTH — edit this, nothing else
├── wrangler.jsonc        # Worker config: name, custom domain, workers_dev=false
├── build.mjs             # wraps the HTML into worker.js (generated, gitignored)
├── package.json          # npm run build / npm run deploy
├── DEPLOY.md             # this file
└── worker.js             # BUILD ARTIFACT — gitignored, never commit, never hand-edit
```

`wrangler.jsonc` pins two things worth knowing:
- **`workers_dev: false` / `preview_urls: false`** — the intranet is internal
  (Supabase-authed), so it should only be reachable at the custom domain, not
  also at a public `*.workers.dev` URL. A pre-wrangler manual deploy had left
  the preview subdomain enabled; deploying via this config turns it off.
- **`routes: [{ pattern: "dash.goaxyom.com", custom_domain: true }]`** — the
  Custom Domain binding is declared in config, so every deploy keeps it bound
  instead of relying on a one-time manual dashboard step.

## How to deploy

From any session/machine with a Cloudflare API token for the account
(`CLOUDFLARE_API_TOKEN` / `CLOUDFLARE_ACCOUNT_ID`, see `mcp-servers/.env.example`):

```bash
cd intranet
npm install      # first time only — installs wrangler
npm run deploy   # builds worker.js from ktubtuintranet.html, then wrangler deploy
```

`npm run deploy` = `npm run build && wrangler deploy`. Run `npm run build` alone
if you just want to regenerate `worker.js` (e.g. to hand-paste into the
Cloudflare dashboard editor instead of using wrangler).

After deploying, hard-refresh https://dash.goaxyom.com and confirm it renders
(owner login required).

**Before deploying, diff against live first** (`curl -s https://dash.goaxyom.com`)
in case someone shipped a change that isn't in the repo yet — merge, don't clobber.

This instruction was not followed between 2026-07-05 and 2026-08-18, and the two
copies forked; see RECONCILIATION.md. Treat the diff-against-live step as
mandatory, not advisory — and prefer automating it (a scheduled curl + diff that
writes a `system_health` row on mismatch) over relying on memory, since the
Cloudflare dashboard editor can change production without touching this repo.

## ⚠️ 2026-08-30 — `npm run deploy` is UNSAFE right now

The repo file and live have forked in both directions (nine live-only tabs,
ten repo-only tabs — see RECONCILIATION.md). Deploying from
`ktubtuintranet.html` today would remove nine tabs from production.

Until that is reconciled, ship additively:

```bash
curl -s https://dash.goaxyom.com > /tmp/live.html
node tools/apply-report-scheduler.mjs /tmp/live.html /tmp/live.patched.html   # or your own patch
node -e "…build worker.js from /tmp/live.patched.html…"
npx wrangler deploy
```

and apply the same patch to `ktubtuintranet.html` so the repo keeps up.
