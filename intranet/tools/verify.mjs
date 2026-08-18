#!/usr/bin/env node
// verify.mjs — structural safety check for ktubtuintranet.html.
//
// The reconciliation ports repo-only tabs onto the LIVE build. The one
// unacceptable outcome is silently dropping something live already had, so this
// asserts the invariant directly: every function the live baseline defined must
// still be defined. It also catches the ways a hand-port typically breaks a
// single-file app — duplicate definitions shadowing each other, a renderer with
// no mount, a mount nothing renders into, and syntax errors.
//
//   node tools/verify.mjs [candidate.html] [baseline.html]
// Defaults: ktubtuintranet.html against the committed live baseline.
// Exits non-zero on any FAIL.
import { readFileSync, writeFileSync, unlinkSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const dir = fileURLToPath(new URL('.', import.meta.url));
const cand = process.argv[2] || dir + '../ktubtuintranet.html';
const base = process.argv[3] || dir + '../.baseline-live.html';

const read = p => readFileSync(p, 'utf8');
const fnDefs = t => [...t.matchAll(/(?:^|[^.\w])(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(/g)].map(m => m[1]);
const mounts = t => new Set([...t.matchAll(/id=["']([\w-]+)["']/g)].map(m => m[1]));
const mountRefs = t => new Set([...t.matchAll(/getElementById\(\s*["']([\w-]+)["']\s*\)/g)].map(m => m[1]));
const sections = t => new Set([...t.matchAll(/fetchRecords\(\s*["']([\w]+)["']/g)].map(m => m[1]));

const C = read(cand);
let B = null;
try { B = read(base); } catch { /* baseline optional on first run */ }

const fails = [], warns = [], notes = [];

// 1. Nothing the live baseline defined may disappear.
if (B) {
  const bs = new Set(fnDefs(B)), cs = new Set(fnDefs(C));
  const lost = [...bs].filter(f => !cs.has(f));
  if (lost.length) fails.push(`REGRESSION — ${lost.length} baseline function(s) missing: ${lost.join(', ')}`);
  else notes.push(`all ${bs.size} baseline functions still defined`);
  const added = [...cs].filter(f => !bs.has(f));
  if (added.length) notes.push(`added ${added.length} function(s): ${added.slice(0, 12).join(', ')}${added.length > 12 ? ` …+${added.length - 12}` : ''}`);
  const bSec = sections(B), cSec = sections(C);
  const lostSec = [...bSec].filter(s => !cSec.has(s));
  if (lostSec.length) fails.push(`REGRESSION — baseline section(s) no longer read: ${lostSec.join(', ')}`);
} else warns.push('no baseline file — regression check skipped');

// 2. A duplicated definition silently shadows the earlier one.
const counts = {};
for (const f of fnDefs(C)) counts[f] = (counts[f] || 0) + 1;
const dupes = Object.entries(counts).filter(([, n]) => n > 1);
if (dupes.length) fails.push(`duplicate function definitions: ${dupes.map(([f, n]) => `${f}×${n}`).join(', ')}`);

// 3. Every element the JS reaches for must exist in the markup.
const have = mounts(C);
const missing = [...mountRefs(C)].filter(id => !have.has(id));
if (missing.length) warns.push(`getElementById targets absent from markup (${missing.length}): ${missing.slice(0, 15).join(', ')}${missing.length > 15 ? ' …' : ''}`);

// 4. Tab nav entries and tab panels must correspond.
const navTabs = new Set([...C.matchAll(/data-tab=["']([\w-]+)["']/g)].map(m => m[1]));
const panels  = new Set([...C.matchAll(/id=["']tab-([\w-]+)["']/g)].map(m => m[1]));
if (panels.size) {
  const noPanel = [...navTabs].filter(t => !panels.has(t));
  const noNav   = [...panels].filter(t => !navTabs.has(t));
  if (noPanel.length) warns.push(`tab links with no panel: ${noPanel.join(', ')}`);
  if (noNav.length)   warns.push(`panels with no tab link: ${noNav.join(', ')}`);
}

// 5. The inline scripts must actually parse.
const scripts = [...C.matchAll(/<script\b(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/gi)].map(m => m[1]);
let checked = 0;
scripts.forEach((src, i) => {
  if (!src.trim()) return;
  const tmp = `${dir}.chk${i}.mjs`;
  try { writeFileSync(tmp, src); execFileSync(process.execPath, ['--check', tmp], { stdio: 'pipe' }); checked++; }
  catch (e) { fails.push(`script #${i + 1} does not parse: ${String(e.stderr || e).split('\n').find(l => l.includes('Error')) || e}`); }
  finally { try { unlinkSync(tmp); } catch {} }
});
notes.push(`${checked}/${scripts.length} inline script block(s) parse`);
notes.push(`${C.length.toLocaleString()} bytes, ${new Set(fnDefs(C)).size} functions, ${sections(C).size} sections read`);


// 6. Nothing may reference a function or constant that only exists in the snapshot.
//    A hand-port typically breaks here: markup onclick= handlers and go() dispatch
//    lines call helpers the closure analysis never saw, and the page throws at
//    runtime while every static check above still passes.
try {
  const snap = read(dir + '../ktubtuintranet.repo-snapshot-2026-08-18.html');
  const snapFns = new Set(fnDefs(snap));
  const candFns = new Set(fnDefs(C));
  const onlyInSnap = [...snapFns].filter(f => !candFns.has(f));
  const script = (C.match(/<script\b(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/i) || [, ''])[1];
  const called = new Set([
    ...[...script.matchAll(/(?<![\w.$])([A-Za-z_$][\w$]*)\s*\(/g)].map(m => m[1]),
    ...[...C.matchAll(/on\w+="([A-Za-z_$][\w$]*)\s*\(/g)].map(m => m[1]),
  ]);
  const undef = onlyInSnap.filter(f => called.has(f));
  if (undef.length) fails.push(`calls function(s) that exist only in the snapshot: ${undef.join(', ')}`);

  const snapConsts = [...snap.matchAll(/^[ \t]*(?:const|let|var)\s+([A-Z][A-Z0-9_]{2,})\s*=/gm)].map(m => m[1]);
  const undefC = [...new Set(snapConsts)].filter(v =>
    !new RegExp(`(?:const|let|var)\\s+${v}\\b`).test(C) && new RegExp(`(?<![\\w.$])${v}(?![\\w$])`).test(script));
  if (undefC.length) fails.push(`references constant(s) that exist only in the snapshot: ${undefC.join(', ')}`);
  if (!undef.length && !undefC.length) notes.push('no dangling references to snapshot-only code');
} catch { warns.push('snapshot not found — dangling-reference check skipped'); }

const out = (t, a) => a.forEach(m => console.log(`  ${t} ${m}`));
console.log(`\nverify: ${cand.split('/').pop()}`);
out('•', notes); out('⚠', warns); out('✗', fails);
console.log(fails.length ? `\nFAIL — ${fails.length} blocking issue(s)\n` : `\nPASS${warns.length ? ` (${warns.length} warning(s))` : ''}\n`);
process.exit(fails.length ? 1 : 0);
