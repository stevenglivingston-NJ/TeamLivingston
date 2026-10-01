#!/usr/bin/env node
/**
 * apply-recovery-dash.mjs — additive patch: a "Recovery Dash" tab that links
 * out to the hosted recovery desks and lets the owner change a desk's passcode
 * without a deploy.
 *
 * The desks themselves stay where they are for now (separate Cloudflare
 * Workers); this is the front door into them from the intranet until the two
 * are merged. Rows come from `recovery_desk_config`, so adding the Bath Tune-Up
 * desk later is a database row plus its own Worker — no change here.
 *
 * Written as a patch, not an edit, for the same reason as the report-scheduler
 * one: ktubtuintranet.html and the live worker have forked in both directions
 * (see RECONCILIATION.md), so this has to apply cleanly to either copy. It only
 * inserts, never rewrites, and is idempotent.
 *
 *   node tools/apply-recovery-dash.mjs <in.html> [out.html]
 */
import { readFileSync, writeFileSync } from 'node:fs';

const inFile = process.argv[2];
const outFile = process.argv[3] || inFile;
if (!inFile) { console.error('usage: apply-recovery-dash.mjs <in.html> [out.html]'); process.exit(1); }
let html = readFileSync(inFile, 'utf8');

if (html.includes('renderRecoveryDash')) {
  console.log('already patched — no change');
  writeFileSync(outFile, html);
  process.exit(0);
}

/* ---------- 1. nav item, next to Reports ---------- */
const NAV_ANCHOR = '<div class="nav-item" data-tab="reports">';
if (!html.includes(NAV_ANCHOR)) { console.error('anchor 1 (reports nav item) not found'); process.exit(1); }
const NAV = `<div class="nav-item" data-tab="recoverydash"><span class="ico"><svg class="sv" viewBox="0 0 24 24">`
  + `<path d="M21 12a9 9 0 1 1-2.6-6.4"/><path d="M21 3v6h-6"/><path d="M12 8v4l3 2"/></svg></span>`
  + `<span class="lbl">Recovery Dash</span>`
  + `<span class="pin" onclick="event.stopPropagation();togglePin('recoverydash','Recovery Dash')">Pin</span></div>\n        `;
html = html.replace(NAV_ANCHOR, () => NAV + NAV_ANCHOR);

/* ---------- 2. the panel ---------- */
const PANEL_ANCHOR = '    <section class="panel" id="reports">';
if (!html.includes(PANEL_ANCHOR)) { console.error('anchor 2 (reports panel) not found'); process.exit(1); }
const PANEL = `    <section class="panel" id="recoverydash">
      <div class="page-head">
        <h1 class="page-title">Recovery Dash</h1>
        <p class="page-sub">The shared call lists — every cancelled consultation and expired quote, with owner,
          status, next step and notes. Hosted separately for now and linked from here; it will be folded into
          this intranet once the two are consolidated.</p>
      </div>
      <div id="recoverydash_root" class="loading">Loading…</div>
    </section>

`;
html = html.replace(PANEL_ANCHOR, () => PANEL + PANEL_ANCHOR);

/* ---------- 3. behaviour ---------- */
const JS = String.raw`
/* ================================================================
   Recovery Dash — links to the hosted desks + passcode rotation
   ----------------------------------------------------------------
   Rows come from recovery_desk_config, one per desk (ktu, btu). A desk
   with no url or enabled=false renders as "not built yet" rather than a
   dead link, so the Bath Tune-Up row can sit here before it exists.

   Passcodes are never stored or shown in plaintext. Setting one hashes
   it in the browser — SHA-256 over "salt:passcode" with a fresh random
   salt — and writes only the salt and hash. The Worker hashes what a
   visitor types and compares, so nothing here can reveal a current
   passcode; whoever sets it is the one who tells the team. Changing it
   also signs everyone out, because the desk signs its cookies with a key
   derived from the current hash.
   ================================================================ */
let RD_SETTING = null;

async function rdHash(salt, passcode) {
  const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(salt + ':' + passcode));
  return [...new Uint8Array(buf)].map(b => b.toString(16).padStart(2, '0')).join('');
}
function rdSalt() {
  return [...crypto.getRandomValues(new Uint8Array(16))].map(b => b.toString(16).padStart(2, '0')).join('');
}

async function renderRecoveryDash() {
  const box = document.getElementById('recoverydash_root'); if (!box) return;
  const admin = (typeof CURRENT_ROLE !== 'undefined' && CURRENT_ROLE === 'admin');
  const { data: rows, error } = await sb.from('recovery_desk_config').select('*').order('desk');

  if (error) {
    // Non-admins are blocked by RLS; that is expected, not a fault.
    box.innerHTML = '<div class="card"><div class="empty">' +
      (admin ? 'Could not load the desks: ' + esc(error.message)
             : 'The recovery desks are owner-managed. Ask Steven for the link and passcode.') +
      '</div></div>';
    return;
  }

  box.innerHTML = (rows || []).map(d => {
    const live = d.enabled && d.url;
    const set = !!d.passcode_hash;
    if (RD_SETTING === d.desk) {
      return '<div class="card" style="margin-bottom:14px">' +
        '<h2 class="sec-title">' + esc(d.label) + ' — set a new passcode</h2>' +
        '<p class="page-sub" style="margin:2px 0 12px">Everyone currently signed in will be signed out and will ' +
          'need the new passcode. It is stored one-way, so nobody — including this screen — can read it back. ' +
          'Write it down before you save.</p>' +
        '<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:flex-end">' +
          '<label style="flex:1;min-width:220px">New passcode<br>' +
            '<input id="rd_pc_' + d.desk + '" type="text" autocomplete="off" style="width:100%;padding:8px 10px;' +
            'border:1px solid var(--line,#d7dde3);border-radius:7px" placeholder="at least 10 characters"></label>' +
          '<button class="btn sm" onclick="saveDeskPasscode(' + JSON.stringify(d.desk) + ')">Save passcode</button>' +
          '<button class="btn sm ghost" onclick="RD_SETTING=null;renderRecoveryDash()">Cancel</button>' +
        '</div>' +
        '<div id="rd_msg_' + d.desk + '" class="note" style="margin-top:10px"></div>' +
      '</div>';
    }
    return '<div class="card" style="margin-bottom:14px">' +
      '<h2 class="sec-title">' + esc(d.label) +
        '<span class="chip ' + (live ? 'ok' : 'warn') + '" style="margin-left:10px">' +
        (live ? 'Live' : 'Not built yet') + '</span></h2>' +
      (live
        ? '<p class="page-sub" style="margin:2px 0 12px">' +
            '<a href="' + esc(d.url) + '" target="_blank" rel="noopener" ' +
            'style="color:var(--accent,#9c6122);font-weight:600;text-decoration:none">' + esc(d.url) + ' ↗</a></p>'
        : '<p class="page-sub" style="margin:2px 0 12px">No desk for this brand yet. When one is built, add its ' +
          'URL to this row and it appears here.</p>') +
      '<div class="note">' +
        (set ? 'Passcode is set. ' : '<b>No passcode set</b> — the desk will not open until one is. ') +
        (d.updated_at ? 'Last changed ' + esc(new Date(d.updated_at).toLocaleDateString()) +
           (d.updated_by ? ' by ' + esc(d.updated_by) : '') + '. ' : '') +
        'Shared with the team by hand; it is not shown here.</div>' +
      (admin
        ? '<div class="rowbtns" style="margin-top:10px">' +
            '<button class="btn sm ghost" onclick="RD_SETTING=' + JSON.stringify(d.desk) + ';renderRecoveryDash()">' +
            (set ? 'Change passcode' : 'Set a passcode') + '</button></div>'
        : '') +
    '</div>';
  }).join('') +
  '<div class="card"><div class="note" style="opacity:.8">These lists carry live customer names, addresses and ' +
    'phone numbers. Share the link and passcode inside the team only, and change the passcode when someone ' +
    'leaves.</div></div>';
}

async function saveDeskPasscode(desk) {
  const msg = document.getElementById('rd_msg_' + desk);
  const el = document.getElementById('rd_pc_' + desk);
  const pc = (el ? el.value : '').trim();
  const say = (t, bad) => { if (msg) { msg.innerHTML = t; msg.style.color = bad ? '#b3382f' : 'inherit'; } };
  if (pc.length < 10) { say('Use at least 10 characters — this is the only thing protecting customer data.', true); return; }
  say('Saving…');
  const salt = rdSalt();
  const hash = await rdHash(salt, pc);
  const who = (typeof CURRENT_PROFILE !== 'undefined' && CURRENT_PROFILE &&
               (CURRENT_PROFILE.display_name || CURRENT_PROFILE.email)) || 'owner';
  const { error } = await sb.from('recovery_desk_config')
    .update({ passcode_salt: salt, passcode_hash: hash, updated_by: who }).eq('desk', desk);
  if (error) { say('Could not save: ' + esc(error.message), true); return; }
  say('Saved. It takes up to a minute to take effect, and everyone signed in has been signed out. ' +
      'Send the team the new passcode now — it cannot be read back.');
  setTimeout(() => { RD_SETTING = null; renderRecoveryDash(); }, 6000);
}
`;

const ANCHOR3 = 'function go(tab,push=true){';
if (!html.includes(ANCHOR3)) { console.error('anchor 3 (go) not found'); process.exit(1); }
html = html.replace(ANCHOR3, () => JS + '\n' + ANCHOR3);

/* ---------- 4. route it ---------- */
const ANCHOR4 = `  if(tab==='techstack'){ renderTechStack(); }`;
if (!html.includes(ANCHOR4)) { console.error('anchor 4 (go routing) not found'); process.exit(1); }
html = html.replace(ANCHOR4, () => `  if(tab==='recoverydash'){ renderRecoveryDash(); }\n` + ANCHOR4);

/* ---------- 5. tab title ---------- */
const T = 'const TAB_TITLES';
if (html.includes(T)) {
  html = html.replace(/const TAB_TITLES\s*=\s*\{/, () => 'const TAB_TITLES={recoverydash:"Recovery Dash",');
}

writeFileSync(outFile, html);
console.log(`patched ${inFile} -> ${outFile} (${html.length} bytes)`);
