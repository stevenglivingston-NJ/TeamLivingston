#!/usr/bin/env node
// drift-check.mjs — is the deployed worker still what this repo says it is?
//
// The repo and the live worker forked once already (2026-07-05 → 2026-08-18)
// because the Cloudflare dashboard can edit production without touching git,
// and the "diff against live before deploying" rule in DEPLOY.md depended on
// someone remembering it. This makes the check mechanical instead.
//
//   node tools/drift-check.mjs            # report only
//   node tools/drift-check.mjs --publish  # also write a system_health row
//
// Exit 0 = in sync, 1 = drift, 2 = could not reach live.
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';

const dir = fileURLToPath(new URL('.', import.meta.url));
const URL_LIVE = 'https://dash.goaxyom.com';
const repo = readFileSync(dir + '../ktubtuintranet.html', 'utf8');

let live;
try {
  live = execFileSync('curl', ['-sS', '-L', '--max-time', '45', URL_LIVE], { encoding: 'utf8', maxBuffer: 32 * 1024 * 1024 });
} catch (e) {
  console.error(`drift-check: could not fetch ${URL_LIVE} — ${e.message}`);
  process.exit(2);
}

const fns = t => new Set([...t.matchAll(/(?:^|[^.\w])(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(/g)].map(m => m[1]));
const R = fns(repo), L = fns(live);
const onlyLive = [...L].filter(f => !R.has(f));   // shipped straight to prod, never committed
const onlyRepo = [...R].filter(f => !L.has(f));   // committed, never deployed
const inSync = repo.length === live.length && onlyLive.length === 0 && onlyRepo.length === 0;

console.log(`\ndrift-check ${new Date().toISOString().slice(0, 10)}`);
console.log(`  repo ${repo.length.toLocaleString()} bytes / ${R.size} fns`);
console.log(`  live ${live.length.toLocaleString()} bytes / ${L.size} fns`);
if (inSync) { console.log('  ✅ in sync\n'); process.exit(0); }
if (onlyLive.length) console.log(`  ⚠ ONLY ON LIVE (edited in prod, not committed — commit before deploying or it is lost): ${onlyLive.join(', ')}`);
if (onlyRepo.length) console.log(`  ⚠ ONLY IN REPO (committed, not deployed): ${onlyRepo.join(', ')}`);
if (!onlyLive.length && !onlyRepo.length) console.log('  ⚠ same functions, different bytes — markup/CSS/copy differs');

if (process.argv.includes('--publish')) {
  const sql = `insert into intranet_records (section, brand, sort_order, fields) values ('system_health','Both',50,
    '${JSON.stringify({
      title: 'Intranet repo/live drift',
      status: onlyLive.length ? 'urgent' : 'warn',
      detail: `repo ${repo.length}B/${R.size}fns vs live ${live.length}B/${L.size}fns` +
              (onlyLive.length ? ` · only-live: ${onlyLive.slice(0, 8).join(', ')}` : '') +
              (onlyRepo.length ? ` · only-repo: ${onlyRepo.slice(0, 8).join(', ')}` : ''),
      scan_date: new Date().toISOString().slice(0, 10),
    }).replace(/'/g, "''")}'::jsonb)`;
  try { execFileSync('bash', [dir + '../../mcp-servers/sb.sh', sql], { stdio: 'inherit' }); }
  catch { console.error('  (could not publish system_health row)'); }
}
console.log('');
process.exit(1);
