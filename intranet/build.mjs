#!/usr/bin/env node
// Wraps ktubtuintranet.html into worker.js — the Worker Cloudflare actually
// deploys. worker.js is a generated build artifact: never commit it, never
// hand-edit it. Source of truth is ktubtuintranet.html; edit that, then
// `npm run deploy` (which runs this build first).
import { readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const dir = fileURLToPath(new URL('.', import.meta.url));
const html = readFileSync(dir + 'ktubtuintranet.html', 'utf8');

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
