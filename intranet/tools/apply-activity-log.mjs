#!/usr/bin/env node
/**
 * apply-activity-log.mjs — additive patch: an "Activity Log" tab reporting
 * who has opened the Recovery Desk, when, and roughly how long they stayed.
 *
 * Reads public.recovery_desk_activity directly (RLS: insert-only for anon,
 * select restricted to is_admin()), the same "sb.from(...).select()" pattern
 * apply-recovery-dash.mjs uses for recovery_desk_config. Non-admins get the
 * same "ask the owner" empty state rather than an error, since RLS blocks
 * the read rather than the query failing.
 *
 * Written as a patch, not an edit, for the same fork reason as the other two
 * intranet patches (see RECONCILIATION.md): applies once, idempotently, to
 * either copy.
 *
 *   node tools/apply-activity-log.mjs <in.html> [out.html]
 */
import { readFileSync, writeFileSync } from 'node:fs';

const inFile = process.argv[2];
const outFile = process.argv[3] || inFile;
if (!inFile) { console.error('usage: apply-activity-log.mjs <in.html> [out.html]'); process.exit(1); }
let html = readFileSync(inFile, 'utf8');

if (html.includes('renderActivityLog')) {
  console.log('already patched — no change');
  writeFileSync(outFile, html);
  process.exit(0);
}

/* ---------- 1. nav item, next to Reports ---------- */
const NAV_ANCHOR = '<div class="nav-item" data-tab="reports">';
if (!html.includes(NAV_ANCHOR)) { console.error('anchor 1 (reports nav item) not found'); process.exit(1); }
const NAV = `<div class="nav-item" data-tab="activitylog"><span class="ico"><svg class="sv" viewBox="0 0 24 24">`
  + `<path d="M12 8v4l3 3"/><circle cx="12" cy="12" r="9"/></svg></span>`
  + `<span class="lbl">Activity Log</span>`
  + `<span class="pin" onclick="event.stopPropagation();togglePin('activitylog','Activity Log')">Pin</span></div>\n        `;
html = html.replace(NAV_ANCHOR, () => NAV + NAV_ANCHOR);

/* ---------- 2. the panel ---------- */
const PANEL_ANCHOR = '    <section class="panel" id="reports">';
if (!html.includes(PANEL_ANCHOR)) { console.error('anchor 2 (reports panel) not found'); process.exit(1); }
const PANEL = `    <section class="panel" id="activitylog">
      <div class="page-head">
        <h1 class="page-title">Activity Log</h1>
        <p class="page-sub">Who has opened the Recovery Desk, when, and roughly how long they stayed. The desk
          has one shared passcode rather than per-user login, so "who" is the first name each person types into
          it once per browser — the same name already shown next to their edits there.</p>
      </div>
      <div id="activitylog_root" class="loading">Loading…</div>
    </section>

`;
html = html.replace(PANEL_ANCHOR, () => PANEL + PANEL_ANCHOR);

/* ---------- 3. behaviour ---------- */
const JS = String.raw`
/* ================================================================
   Activity Log — who has opened the Recovery Desk, when, how long
   ----------------------------------------------------------------
   Reads recovery_desk_activity directly (RLS: select is_admin()-only).
   Three event kinds land there: 'view' (page load), 'duration' (time on
   page, sent via sendBeacon so it lands even on a hard close), 'save'
   (a row was edited). This aggregates per person and renders a recent
   feed; it does not write anything.
   ================================================================ */
function alFmtMs(ms) {
  if (!ms || ms < 1000) return '<1m';
  const mins = Math.round(ms / 60000);
  if (mins < 60) return mins + 'm';
  const h = Math.floor(mins / 60), m = mins % 60;
  return h + 'h' + (m ? ' ' + m + 'm' : '');
}
function alFmtWhen(iso) {
  const d = new Date(iso);
  const now = new Date();
  const sameDay = d.toDateString() === now.toDateString();
  return sameDay
    ? d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
    : d.toLocaleDateString([], { month: 'short', day: 'numeric' }) + ' ' +
      d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
}

async function renderActivityLog() {
  const box = document.getElementById('activitylog_root'); if (!box) return;
  const admin = (typeof CURRENT_ROLE !== 'undefined' && CURRENT_ROLE === 'admin');
  const since = new Date(Date.now() - 30 * 86400000).toISOString();
  const { data: rows, error } = await sb.from('recovery_desk_activity')
    .select('who,event,row_id,duration_ms,at').gte('at', since)
    .order('at', { ascending: false }).limit(2000);

  if (error) {
    // Non-admins are blocked by RLS; that is expected, not a fault.
    box.innerHTML = '<div class="card"><div class="empty">' +
      (admin ? 'Could not load activity: ' + esc(error.message)
             : 'The activity log is owner-only.') +
      '</div></div>';
    return;
  }

  if (!rows || !rows.length) {
    box.innerHTML = '<div class="card"><div class="empty">No desk activity in the last 30 days yet.</div></div>';
    return;
  }

  /* ---- per-person summary ---- */
  const people = new Map();
  for (const r of rows) {
    const who = (r.who || '').trim() || '(unnamed)';
    if (!people.has(who)) people.set(who, { views: 0, saves: 0, ms: 0, first: r.at, last: r.at });
    const p = people.get(who);
    if (r.event === 'view') p.views++;
    if (r.event === 'save') p.saves++;
    if (r.event === 'duration') p.ms += (r.duration_ms || 0);
    if (r.at < p.first) p.first = r.at;
    if (r.at > p.last) p.last = r.at;
  }
  const summary = [...people.entries()].sort((a, b) => b[1].last.localeCompare(a[1].last));

  const summaryRows = summary.map(([who, p]) => {
    const recentMs = Date.now() - new Date(p.last).getTime();
    const active = recentMs < 15 * 60000;
    return '<tr>' +
      '<td><span class="who"><span class="dot" style="background:' + (active ? 'var(--brass,#cf7a40)' : 'var(--s-prog,#5b7)') + '"></span>' + esc(who) + '</span></td>' +
      '<td>' + esc(alFmtWhen(p.last)) + (active ? ' <span class="nm-chip own" style="margin-left:6px">active now</span>' : '') + '</td>' +
      '<td>' + esc(alFmtWhen(p.first)) + '</td>' +
      '<td class="num">' + p.views + '</td>' +
      '<td class="num">' + p.saves + '</td>' +
      '<td class="num">' + esc(alFmtMs(p.ms)) + '</td>' +
    '</tr>';
  }).join('');

  const feedRows = rows.slice(0, 80).map(r => {
    const label = r.event === 'view' ? 'opened the desk'
      : r.event === 'save' ? 'saved a row' + (r.row_id ? ' (' + esc(r.row_id) + ')' : '')
      : 'was on the desk for ' + alFmtMs(r.duration_ms);
    return '<tr><td>' + esc(alFmtWhen(r.at)) + '</td><td>' + esc((r.who || '').trim() || '(unnamed)') +
      '</td><td>' + label + '</td></tr>';
  }).join('');

  box.innerHTML =
    '<div class="card" style="margin-bottom:14px">' +
      '<h2 class="sec-title">Last 30 days, by person</h2>' +
      '<div style="overflow-x:auto"><table class="tbl"><thead><tr>' +
        '<th>Who</th><th>Last seen</th><th>First seen</th><th class="num">Views</th>' +
        '<th class="num">Saves</th><th class="num">Time on page</th>' +
      '</tr></thead><tbody>' + summaryRows + '</tbody></table></div>' +
    '</div>' +
    '<div class="card">' +
      '<h2 class="sec-title">Recent activity</h2>' +
      '<div style="overflow-x:auto"><table class="tbl"><thead><tr><th>When</th><th>Who</th><th>What</th></tr></thead>' +
        '<tbody>' + feedRows + '</tbody></table></div>' +
      '<div class="note" style="margin-top:10px;opacity:.8">"Who" is a first name typed into the desk once per ' +
        'browser, not a login — treat it as a strong hint, not an audit-grade identity. Time on page is measured ' +
        'per visible tab span, so a browser left open in the background does not inflate it.</div>' +
    '</div>';
}
`;

const ANCHOR3 = 'function go(tab,push=true){';
if (!html.includes(ANCHOR3)) { console.error('anchor 3 (go) not found'); process.exit(1); }
html = html.replace(ANCHOR3, () => JS + '\n' + ANCHOR3);

/* ---------- 4. route it ---------- */
const ANCHOR4 = `  if(tab==='techstack'){ renderTechStack(); }`;
if (!html.includes(ANCHOR4)) { console.error('anchor 4 (go routing) not found'); process.exit(1); }
html = html.replace(ANCHOR4, () => `  if(tab==='activitylog'){ renderActivityLog(); }\n` + ANCHOR4);

/* ---------- 5. tab title ---------- */
const T = 'const TAB_TITLES';
if (html.includes(T)) {
  html = html.replace(/const TAB_TITLES\s*=\s*\{/, () => 'const TAB_TITLES={activitylog:"Activity Log",');
}

writeFileSync(outFile, html);
console.log(`patched ${inFile} -> ${outFile} (${html.length} bytes)`);
