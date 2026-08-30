/* ============================================================
   KTU Recovery Desk
   Shared work list. PEOPLE is the static roster shipped with the
   page; everything a person types lives in `db` under recovery/<id>
   so Ben and Sonya see each other's work as it happens. The page
   must be useful with no db at all (link opened outside the viewer),
   so it renders from PEOPLE first and layers saved work on top.
   ============================================================ */

const ASSIGNEES = ['Unassigned', 'Ben', 'Sonya', 'Steven'];

/* Ordered as the work actually moves. `terminal` closes a row out of
   the open count; `cold` means no further action without a reason. */
const STATUSES = [
  { v: 'todo',      label: 'Not started',            tone: 'new'  },
  { v: 'noanswer',  label: 'Called — no answer',     tone: 'prog' },
  { v: 'voicemail', label: 'Left a voicemail',       tone: 'prog' },
  { v: 'written',   label: 'Texted or emailed',      tone: 'prog' },
  { v: 'reached',   label: 'Spoke with them',        tone: 'prog' },
  { v: 'booked',    label: 'Consultation booked',    tone: 'win', terminal: true },
  { v: 'requoted',  label: 'Quote revised or re-sent',tone: 'win' },
  { v: 'won',       label: 'Sold',                   tone: 'win', terminal: true },
  { v: 'later',     label: 'Call back later',        tone: 'prog' },
  { v: 'no',        label: 'Not interested',         tone: 'cold', terminal: true },
  { v: 'badnum',    label: 'Bad number / wrong contact', tone: 'cold', terminal: true },
  { v: 'dnc',       label: 'Do not contact',         tone: 'crit', terminal: true },
];
const METHODS = ['—', 'Phone', 'Voicemail', 'Text', 'Email', 'In person', 'Other'];

const LANE_TONE = {
  'Our error — apologise and rebook':          'crit',
  'Came back, then the quote lapsed':          'crit',
  'Quote expired':                             'prog',
  'Asked us to call back':                     'win',
  'Requote a smaller scope':                   'prog',
  'Worth one call':                            'new',
  'Already rebooked':                          'new',
  'Do not call — documented disqualification': 'cold',
};
const toneVar = t => `var(--s-${t || 'new'})`;
const statusOf = v => STATUSES.find(s => s.v === v) || STATUSES[0];

const state = { tab: 'week', assignee: 'all', status: 'all', lane: 'all', q: '', open: new Set() };
let work = {};          // id -> saved fields
let me = null;

const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const money = n => '$' + Math.round(n || 0).toLocaleString('en-US');
const today = () => new Date().toISOString().slice(0, 10);

function rowOf(p) { return { assignee: 'Unassigned', status: 'todo', next: '', last: '', method: '—', notes: '', ...(work[p.id] || {}) }; }
function isOpen(p) { const s = statusOf(rowOf(p).status); return !s.terminal; }

/* ---------- which rows a tab shows ---------- */
const TABS = [
  { v: 'week',  label: 'This week',      test: p => p.week },
  { v: 'mine',  label: 'Mine',           test: p => ['Ben', 'Sonya', 'Steven'].includes(rowOf(p).assignee) },
  { v: 'money', label: 'Expired quotes', test: p => p.value > 0 },
  { v: 'all',   label: 'Everyone',       test: () => true },
  { v: 'done',  label: 'Closed',         test: p => statusOf(rowOf(p).status).terminal },
];

function visible() {
  const tab = TABS.find(t => t.v === state.tab);
  const q = state.q.trim().toLowerCase();
  return PEOPLE.filter(p => {
    if (!tab.test(p)) return false;
    if (state.tab !== 'done' && state.tab !== 'all' && statusOf(rowOf(p).status).terminal) return false;
    if (state.assignee !== 'all' && rowOf(p).assignee !== state.assignee) return false;
    if (state.status !== 'all' && rowOf(p).status !== state.status) return false;
    if (state.lane !== 'all' && p.lane !== state.lane) return false;
    if (q && !(`${p.name} ${p.city} ${p.phone} ${p.email}`.toLowerCase().includes(q))) return false;
    return true;
  });
}

/* ---------- summary ---------- */
function renderStats() {
  const wk = PEOPLE.filter(p => p.week);
  const openWk = wk.filter(isOpen);
  const doneWk = wk.length - openWk.length;
  const atStake = wk.reduce((a, p) => a + (p.value || 0), 0);
  const recovered = PEOPLE.filter(p => ['won', 'booked', 'requoted'].includes(rowOf(p).status))
    .reduce((a, p) => a + (p.value || 0), 0);
  const booked = PEOPLE.filter(p => ['booked', 'won'].includes(rowOf(p).status)).length;
  const pct = wk.length ? Math.round(doneWk / wk.length * 100) : 0;

  document.getElementById('stats').innerHTML = `
    <div class="stat"><div class="k">This week</div><div class="v">${openWk.length}</div>
      <div class="n">${doneWk} of ${wk.length} worked</div><div class="bar"><i style="width:${pct}%"></i></div></div>
    <div class="stat accent"><div class="k">Quoted value at stake</div><div class="v">${money(atStake)}</div>
      <div class="n">expired quotes in this week's list</div></div>
    <div class="stat"><div class="k">Back in play</div><div class="v" style="color:var(--s-win)">${money(recovered)}</div>
      <div class="n">booked, requoted or sold</div></div>
    <div class="stat"><div class="k">Consultations booked</div><div class="v">${booked}</div>
      <div class="n">from this list</div></div>
    <div class="stat"><div class="k">Whole list</div><div class="v">${PEOPLE.length}</div>
      <div class="n">${money(PEOPLE.reduce((a, p) => a + (p.value || 0), 0))} across 2026</div></div>`;
}

function renderTabs() {
  document.getElementById('tabs').innerHTML = TABS.map(t => {
    const n = PEOPLE.filter(p => t.test(p) && (t.v === 'done' || t.v === 'all' ? true : isOpen(p))).length;
    return `<button class="tab" role="tab" aria-selected="${state.tab === t.v}" data-tab="${t.v}">
      ${esc(t.label)}<span class="ct">${n}</span></button>`;
  }).join('');
}

function renderFilters() {
  const grp = (host, items, key) => {
    document.getElementById(host).innerHTML = items.map(([val, label, count]) =>
      `<button class="fbtn" aria-pressed="${state[key] === val}" data-f="${key}" data-v="${esc(val)}">
        <span>${esc(label)}</span><span class="c">${count}</span></button>`).join('');
  };
  const pool = PEOPLE.filter(p => TABS.find(t => t.v === state.tab).test(p));
  grp('fAssignee', [['all', 'Anyone', pool.length],
    ...ASSIGNEES.map(a => [a, a, pool.filter(p => rowOf(p).assignee === a).length])], 'assignee');
  grp('fStatus', [['all', 'Any status', pool.length],
    ...STATUSES.filter(s => pool.some(p => rowOf(p).status === s.v))
      .map(s => [s.v, s.label, pool.filter(p => rowOf(p).status === s.v).length])], 'status');
  const lanes = [...new Set(pool.map(p => p.lane))].sort();
  grp('fLane', [['all', 'Every reason', pool.length],
    ...lanes.map(l => [l, l, pool.filter(p => p.lane === l).length])], 'lane');
}

/* ---------- one person ---------- */
function rowHTML(p) {
  const w = rowOf(p);
  const st = statusOf(w.status);
  const tone = LANE_TONE[p.lane] || 'new';
  const opened = state.open.has(p.id);
  const tel = String(p.phone || '').replace(/[^\d+]/g, '');
  const hasNotes = p.consult_note || p.sm_notes || p.hl_notes || p.hl_convo;

  return `<article class="row ${st.terminal ? 'done' : ''}" style="--lane:${toneVar(tone)}" data-id="${p.id}">
    <div class="rtop">
      <div>
        <div class="nm">${esc(p.name)}</div>
        <div class="meta">
          ${p.phone ? `<a href="tel:${esc(tel)}" class="mono">${esc(p.phone)}</a>` : ''}
          ${p.email ? `<a href="mailto:${esc(p.email)}">${esc(p.email)}</a>` : ''}
          <span>${esc([p.addr, p.city].filter(Boolean).join(', '))}</span>
        </div>
        <div class="chips">
          <span class="chip" style="color:${toneVar(tone)}">${esc(p.lane)}</span>
          <span class="chip" style="color:${toneVar(st.tone)}">${esc(st.label)}</span>
          ${w.assignee !== 'Unassigned' ? `<span class="chip" style="color:var(--brass)">${esc(w.assignee)}</span>` : ''}
          ${p.quote_services ? `<span class="chip" style="color:var(--muted)">${esc(p.quote_services)}</span>` : ''}
          ${p.quote_sent && !p.quote_viewed ? `<span class="chip" style="color:var(--s-crit)">Quote never opened</span>` : ''}
          ${p.quote_viewed ? `<span class="chip" style="color:var(--muted)">Opened ${esc(p.quote_viewed)}</span>` : ''}
        </div>
        <p class="why">${esc(p.why)}</p>
      </div>
      <div>
        ${p.value ? `<div class="amt">${money(p.value)}<small>quoted ${esc(p.quote_latest)}</small></div>`
                  : `<div class="amt" style="color:var(--muted);font-size:14px">no quote<small>consult stage</small></div>`}
      </div>
    </div>

    <div class="edit">
      <div class="f"><label for="a-${p.id}">Assigned to</label>
        <select id="a-${p.id}" data-k="assignee">${ASSIGNEES.map(a =>
          `<option ${w.assignee === a ? 'selected' : ''}>${a}</option>`).join('')}</select></div>
      <div class="f"><label for="s-${p.id}">Status</label>
        <select id="s-${p.id}" data-k="status">${STATUSES.map(s =>
          `<option value="${s.v}" ${w.status === s.v ? 'selected' : ''}>${esc(s.label)}</option>`).join('')}</select></div>
      <div class="f"><label for="d-${p.id}">Last contact</label>
        <input id="d-${p.id}" type="date" data-k="last" value="${esc(w.last)}"></div>
      <div class="f"><label for="m-${p.id}">How</label>
        <select id="m-${p.id}" data-k="method">${METHODS.map(m =>
          `<option ${w.method === m ? 'selected' : ''}>${m}</option>`).join('')}</select></div>
      <div class="f wide"><label for="n-${p.id}">Next step</label>
        <input id="n-${p.id}" data-k="next" value="${esc(w.next)}"
          placeholder="e.g. Re-quote at the new Aline pricing and call Thursday"></div>
      <div class="f wide"><label for="t-${p.id}">Notes from the call</label>
        <textarea id="t-${p.id}" data-k="notes" placeholder="What they said, what they want, what we agreed">${esc(w.notes)}</textarea></div>
      <div class="foot">
        ${hasNotes ? `<button class="linkbtn" data-toggle="${p.id}">${opened ? 'Hide' : 'Show'} what we already know</button>` : '<span></span>'}
        <span class="saved" id="sv-${p.id}"></span>
      </div>
    </div>
    ${opened && hasNotes ? `<div class="drawer">
      ${p.consult_date ? `<div><h4>Cancelled consultation</h4><p>${esc(p.consult_date)} — ${esc(p.consult_reason)}</p></div>` : ''}
      ${p.consult_note ? `<div><h4>Appointment note</h4><p>${esc(p.consult_note)}</p></div>` : ''}
      ${p.sm_notes ? `<div><h4>ServiceMinder contact notes</h4><p>${esc(p.sm_notes)}</p></div>` : ''}
      ${p.hl_notes ? `<div><h4>HighLevel notes</h4><p>${esc(p.hl_notes)}</p></div>` : ''}
      ${p.hl_convo ? `<div><h4>Recent conversation</h4><p>${esc(p.hl_convo)}</p></div>` : ''}
      ${p.value ? `<div><h4>The quote</h4><p>${money(p.value)} for ${esc(p.quote_services || 'work quoted')}, dated ${esc(p.quote_latest)}${p.quote_count > 1 ? ` (${p.quote_count} quotes)` : ''}.${p.quote_sent ? ` Sent ${esc(p.quote_sent)}.` : ' No record of it being sent.'}${p.quote_viewed ? ` They opened it ${esc(p.quote_viewed)}.` : (p.quote_sent ? ' No record of them ever opening it.' : '')}</p></div>` : ''}
      ${p.channel ? `<div><h4>Came from</h4><p>${esc([p.channel, p.campaign].filter(Boolean).join(' · '))}</p></div>` : ''}
    </div>` : ''}
  </article>`;
}

function renderList() {
  const rows = visible();
  document.getElementById('list').innerHTML = rows.length
    ? rows.map(rowHTML).join('')
    : `<div class="empty"><strong>Nothing here.</strong><br>Try a different tab or clear the filters.</div>`;
}

function render() { renderStats(); renderTabs(); renderFilters(); renderList(); }

/* ---------- saving ----------
   The page holds no database credential of any kind. Every read and write
   goes back to the server that served the page, which talks to the database
   itself. Live-ness is a 6-second poll rather than a socket: two people on a
   call list do not need sub-second updates, and a poll cannot silently die
   the way a dropped websocket can. */
const timers = {};
let pollTimer = null;

function flash(id, msg, ok) {
  const el = document.getElementById('sv-' + id);
  if (!el) return;
  el.className = 'saved' + (ok ? ' ok' : '');
  el.textContent = msg;
  if (ok) setTimeout(() => { if (el.textContent === msg) el.textContent = ''; }, 2200);
}

async function api(path, opts) {
  const r = await fetch('/follow-up/api/' + path, {
    ...opts,
    headers: { 'content-type': 'application/json', ...((opts || {}).headers || {}) },
  });
  if (r.status === 401) { location.reload(); throw new Error('signed out'); }
  if (!r.ok) throw new Error((await r.text()).slice(0, 200));
  return r.json();
}

function edit(id, key, value) {
  work[id] = { ...rowOf({ id }), ...work[id], [key]: value };
  // Recording an outcome without a date is the commonest slip on a call list.
  if (key === 'status' && value !== 'todo' && !work[id].last) work[id].last = today();
  renderStats(); renderTabs(); renderFilters();
  flash(id, 'Saving…', false);
  clearTimeout(timers[id]);
  timers[id] = setTimeout(async () => {
    try {
      await api('state', { method: 'POST', body: JSON.stringify({ id, ...work[id], by: me || '' }) });
      flash(id, 'Saved for everyone', true);
    } catch (e) {
      flash(id, 'Could not save — check your connection and try again', false);
    }
  }, 600);
}

function setLive(ok) {
  const el = document.getElementById('livechip');
  if (!el) return;
  el.innerHTML = ok
    ? '<span class="dot" style="background:var(--s-win)"></span>Shared with the team'
    : '<span class="dot" style="background:var(--s-crit)"></span>Offline — changes are not saving';
}

async function pull() {
  try {
    const rows = await api('state');
    // Never yank text out from under someone who is mid-sentence.
    const busyRow = document.activeElement && document.activeElement.closest
      ? document.activeElement.closest('.row') : null;
    const next = {};
    rows.forEach(r => {
      next[r.id] = {
        assignee: r.assignee || 'Unassigned', status: r.status || 'todo',
        next: r.next_step || '', last: r.last_contact || '',
        method: r.method || '—', notes: r.notes || '', by: r.updated_by || '',
      };
    });
    if (busyRow && work[busyRow.dataset.id]) next[busyRow.dataset.id] = work[busyRow.dataset.id];
    work = next;
    setLive(true);
    if (busyRow) { renderStats(); renderTabs(); renderFilters(); } else { render(); }
  } catch (e) {
    setLive(false);
  }
}

/* ---------- events ---------- */
document.addEventListener('change', e => {
  const f = e.target.closest('[data-k]');
  if (f) {
    const id = f.closest('.row').dataset.id;
    edit(id, f.dataset.k, f.value);
    if (f.dataset.k === 'status' || f.dataset.k === 'assignee') renderList();
  }
});
document.addEventListener('input', e => {
  const f = e.target.closest('[data-k]');
  if (f && (f.tagName === 'TEXTAREA' || f.type === 'text' || f.tagName === 'INPUT' && !f.type.match(/date|select/)))
    edit(f.closest('.row').dataset.id, f.dataset.k, f.value);
});
document.addEventListener('click', e => {
  const t = e.target.closest('[data-tab]');
  if (t) { state.tab = t.dataset.tab; state.assignee = state.status = state.lane = 'all'; render(); return; }
  const f = e.target.closest('[data-f]');
  if (f) { state[f.dataset.f] = state[f.dataset.f] === f.dataset.v ? 'all' : f.dataset.v; render(); return; }
  const d = e.target.closest('[data-toggle]');
  if (d) { const id = d.dataset.toggle; state.open.has(id) ? state.open.delete(id) : state.open.add(id); renderList(); }
});
document.getElementById('q').addEventListener('input', e => { state.q = e.target.value; renderList(); });

/* ---------- who is working ---------- */
function renderPeers() {
  const who = new Map();
  if (me) who.set(me, true);
  Object.values(work).forEach(w => { if (w && w.by && w.by !== me) who.set(w.by, false); });
  document.getElementById('peers').innerHTML = [...who.entries()].map(([name, self]) =>
    `<span class="who"><span class="dot" style="background:${self ? 'var(--brass)' : 'var(--s-prog)'}"></span>${esc(name)}${self ? ' (you)' : ''}</span>`
  ).join('');
}

async function boot() {
  try { me = (localStorage.getItem('ktu-desk-name') || '').trim(); } catch (_) { me = ''; }
  if (!me) {
    const guess = prompt('Your first name, so the team can see who worked each row:', '');
    me = (guess || '').trim().slice(0, 24);
    if (me) { try { localStorage.setItem('ktu-desk-name', me); } catch (_) {} }
  }
  render();
  renderPeers();
  await pull();
  renderPeers();
  // Poll only while the tab is actually being looked at.
  pollTimer = setInterval(() => {
    if (document.visibilityState === 'visible') pull().then(renderPeers);
  }, 6000);
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') pull().then(renderPeers);
  });
}
boot();
