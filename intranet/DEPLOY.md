# Axyom Intranet (`ktubtuintranet` Cloudflare Worker)

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
