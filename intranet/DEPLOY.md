# Axyom Intranet (`ktubtuintranet` Cloudflare Worker)

`ktubtuintranet.html` is the full single-file app served at **https://dash.goaxyom.com**.
It was recovered from the live site on 2026-07-05 (the worker had no source in this
repo) and then improved — **treat this file as the source of truth going forward**
and deploy from here, so the live worker and the repo never drift again.

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

## How to deploy

From any session/machine with a Cloudflare API token for the account
(`CLOUDFLARE_API_TOKEN` / `CLOUDFLARE_ACCOUNT_ID`, see `mcp-servers/.env.example`):

```bash
# wrap the HTML in a minimal module worker
cd intranet
node -e "
const fs=require('fs');
const html=JSON.stringify(fs.readFileSync('ktubtuintranet.html','utf8'));
fs.writeFileSync('worker.js',
  'const HTML='+html+';export default{fetch(){return new Response(HTML,{headers:{\"content-type\":\"text/html;charset=utf-8\"}})}}');
"
npx wrangler deploy worker.js --name ktubtuintranet --compatibility-date 2026-01-01
```

Or paste the wrapped `worker.js` into the Cloudflare dashboard editor for the
`ktubtuintranet` worker. After deploying, hard-refresh https://dash.goaxyom.com
and confirm the Finance tab renders (owner login required).

**Before deploying, diff against live first** (`curl -s https://dash.goaxyom.com`)
in case someone shipped a change that isn't in the repo yet — merge, don't clobber.
