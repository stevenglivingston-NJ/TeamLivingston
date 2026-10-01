#!/usr/bin/env node
// Wraps ktubtuintranet.html into worker.js — the Worker Cloudflare actually
// deploys. worker.js is a generated build artifact: never commit it, never
// hand-edit it. Source of truth is ktubtuintranet.html; edit that, then
// `npm run deploy` (which runs this build first).
import { readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const dir = fileURLToPath(new URL('.', import.meta.url));
const html = readFileSync(dir + 'ktubtuintranet.html', 'utf8');

/* The worker `ktubtuintranet` has TWO deploy paths: the KTUBTU-Intranet
   repo's Cloudflare Git integration (fires on every push — the primary), and
   this manual build. On 2026-08-31 this file was six days stale and one
   `npm run deploy` away from rolling production back over a day of shipped
   finance work. Whichever path runs last wins and neither knows about the
   other, so the manual path now refuses to build from a copy that
   contradicts the repo checkout when one is present to compare against.
   No repo checkout found = warn and continue (emergency use), because a
   guard that blocks the only working path in an outage is worse than none. */
const repoCopy = process.env.INTRANET_REPO_HTML || '/home/user/KTUBTU-Intranet/index.html';
try {
  const repoHtml = readFileSync(repoCopy, 'utf8');
  if (repoHtml !== html && !process.argv.includes('--force')) {
    console.error(`ABORT: ktubtuintranet.html differs from ${repoCopy} (${html.length} vs ${repoHtml.length} bytes).`);
    console.error('The repo is the source of truth and its Git integration deploys this same worker on every push.');
    console.error('Sync first (cp <repo>/index.html ktubtuintranet.html) or re-run with --force to knowingly override.');
    process.exit(1);
  }
} catch (e) {
  if (e.code === 'ENOENT') console.warn(`note: no repo checkout at ${repoCopy} to verify against — deploying local copy as-is.`);
  else throw e;
}

const worker = `const HTML=${JSON.stringify(html)};
export default {
  fetch() {
    return new Response(HTML, {
      headers: {
        'content-type': 'text/html;charset=utf-8',
        'cache-control': 'public, max-age=0, must-revalidate',
      },
    });
  },
};
`;

writeFileSync(dir + 'worker.js', worker);
console.log(`Built worker.js (${worker.length} bytes, from ${html.length}-byte HTML)`);
