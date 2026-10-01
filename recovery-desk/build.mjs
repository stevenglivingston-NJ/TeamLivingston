#!/usr/bin/env node
/**
 * Builds dist/worker.js: the gate + API Worker with the full desk page inlined.
 *
 * The page is assembled from the same three parts as the published Artifact
 * (head, body, app) plus the roster JSON, so the hosted copy and the Artifact
 * never drift apart by hand-editing one of them.
 */
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const dir = fileURLToPath(new URL('.', import.meta.url));
const art = dir + '../../tmp-art/';   // overridden below when parts live elsewhere
const PARTS = process.env.DESK_PARTS || dir + 'parts/';

const head = readFileSync(PARTS + 'head.html', 'utf8');
const body = readFileSync(PARTS + 'body.html', 'utf8');
const app = readFileSync(dir + 'app.js', 'utf8');
const data = readFileSync(PARTS + 'tracker_min.json', 'utf8');

if (/<\/script/i.test(data)) throw new Error('roster JSON contains a script terminator');

const html = `<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow,noarchive">
${head}
</head><body>
${body}
<script>
const PEOPLE=${data};
</script>
<script>
${app}
</script>
</body></html>`;

// NOTE: the replacement MUST be a function. The page contains `'$' + ...`
// (money formatting), and a string replacement would read `$'` as "everything
// after the match" and splice the rest of the file into the literal.
const worker = readFileSync(dir + 'worker.js', 'utf8')
  .replace("const DESK = '<h1>Not built</h1>';", () => 'const DESK = ' + JSON.stringify(html) + ';');

if (worker.includes("<h1>Not built</h1>")) throw new Error('DESK placeholder was not replaced');

mkdirSync(dir + 'dist', { recursive: true });
writeFileSync(dir + 'dist/worker.js', worker);
console.log(`built dist/worker.js — ${worker.length} bytes (page ${html.length})`);
