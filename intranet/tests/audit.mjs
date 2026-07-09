/*
 * Playwright audit harness for the Axyom intranet (intranet/index.html).
 * Stubs the Supabase UMD client (file:// blocks the CDN anyway) and injects
 * realistic fake data so every Home card / feed / table renders for styling,
 * screenshots, and overflow checks. No real network calls are made.
 *
 * Usage: node intranet/tests/audit.mjs <prefix>   (prefix = "before" | "after")
 */
import { chromium } from '/opt/node22/lib/node_modules/playwright/index.mjs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const INDEX = path.resolve(__dirname, '..', 'index.html');
const SHOTS = path.resolve(__dirname, '..', 'screenshots');
const PREFIX = process.argv[2] || 'audit';

const STUB = `
(() => {
  const NOW = Date.now();
  const iso = (mins) => new Date(NOW - mins * 60000).toISOString();
  const today = new Date().toISOString().slice(0, 10);
  let idc = 1; const rid = () => 'r' + (idc++);
  const rec = (section, fields, brand) => ({ id: rid(), section, brand: brand || null, sort_order: idc, fields, updated_at: iso(idc * 47) });

  const DATA = {
    profiles: [{ id: 'u1', email: 'stevenglivingston@gmail.com', display_name: 'Steven', role: 'admin' }],
    contacts: [
      { id: 'c1', name: 'Maria Alvarez', company: 'Alvarez Home', phone: '(973) 555-0142', email: 'maria@example.com', type: 'Customer', brand: 'KTU', created_at: iso(30) },
      { id: 'c2', name: 'Dan Whitfield', company: 'Whitfield Res.', phone: '(862) 555-0177', email: 'dan.w@example.com', type: 'Lead', brand: 'BTU', created_at: iso(200) },
      { id: 'c3', name: 'Elias Woodworks', company: 'Elias Cabinet Co', phone: '(201) 555-0111', email: 'orders@elias.example', type: 'Vendor', brand: 'Both', created_at: iso(400) },
      { id: 'c4', name: 'Rocco Marino', company: 'Marino Install', phone: '(973) 555-0193', email: 'rocco@example.com', type: 'Subcontractor', brand: 'KTU', created_at: iso(900) },
      { id: 'c5', name: 'Janet Kim', company: 'Kim Residence', phone: '(908) 555-0128', email: 'janet.kim@example.com', type: 'Customer', brand: 'BTU', created_at: iso(1400) },
      { id: 'c6', name: 'Miguel Santos', company: 'Santos Tile', phone: '(551) 555-0164', email: 'miguel@example.com', type: 'Subcontractor', brand: 'BTU', created_at: iso(2000) },
    ],
    items: [
      { id: 'i1', name: 'Shaker door — maple', code: 'CAB-101', cost: 84, price: 178, brand: 'KTU', created_at: iso(60) },
      { id: 'i2', name: 'Soft-close hinge set', code: 'HW-220', cost: 12, price: 34, brand: 'Both', created_at: iso(300) },
      { id: 'i3', name: 'Quartz vanity top 36"', code: 'BTU-310', cost: 260, price: 540, brand: 'BTU', created_at: iso(700) },
      { id: 'i4', name: '1-day wood restoration', code: 'SVC-010', cost: 350, price: 1250, brand: 'KTU', created_at: iso(1100) },
      { id: 'i5', name: 'Frameless glass door', code: 'BTU-402', cost: 410, price: 890, brand: 'BTU', created_at: iso(1600) },
    ],
    jobs: [
      { id: 'j1', name: 'Alvarez — kitchen reface', brand: 'KTU', cost: 9800, price: 21400, status: 'In Progress', created_at: iso(100) },
      { id: 'j2', name: 'Kim — hall bath remodel', brand: 'BTU', cost: 7200, price: 15800, status: 'Approved', created_at: iso(500) },
      { id: 'j3', name: 'Whitfield — tune-up', brand: 'KTU', cost: 1400, price: 4200, status: 'Estimate', created_at: iso(1200) },
      { id: 'j4', name: 'Patel — master bath', brand: 'BTU', cost: 11900, price: 26500, status: 'Complete', created_at: iso(2400) },
    ],
    team_tasks: [
      { id: 't1', title: 'Order Alvarez countertop', detail: 'Confirm edge profile with Maria first', assignee: 'Takia', brand: 'KTU', due_date: today, status: 'open', created_by_name: 'Steven', created_at: iso(90) },
      { id: 't2', title: 'Call back Whitfield lead', detail: null, assignee: 'Sonya', brand: 'KTU', due_date: null, status: 'in_progress', created_by_name: 'Steven', created_at: iso(400) },
      { id: 't3', title: 'Send Kim final invoice', detail: null, assignee: 'Takia', brand: 'BTU', due_date: null, status: 'done', created_by_name: 'Takia', created_at: iso(2000), completed_at: iso(100) },
    ],
    intranet_records: [],
    action_queue: [], notify_queue: [],
  };

  const R = DATA.intranet_records;
  R.push(
    rec('goldeneye_callouts', { severity: 'urgent', title: 'Janet Kim asked about start date 2 days ago — no reply', detail: 'SMS thread in HighLevel BTU. She asked Tuesday whether demo starts Monday; nobody has answered.', source: 'HighLevel · BTU', scan_date: today }),
    rec('goldeneye_callouts', { severity: 'warn', title: 'New Google review (3★) needs a response', detail: 'KTU Bloomfield profile — reviewer mentions scheduling confusion. Respond within 24h to keep response rate.', source: 'Google Business Profile', scan_date: today }),
    rec('goldeneye_callouts', { severity: 'info', title: 'Perceptionist logged 2 after-hours calls', detail: 'Both booked consultations for next week. No action needed — verifying they landed in ServiceMinder.', source: 'Perceptionist', scan_date: today }),
    rec('moola_briefing', { severity: 'urgent', kind: 'pay', title: 'HFC royalty auto-debit hits Friday — $4,180', detail: 'Chase operating balance covers it, but Ramp payment lands the same day. Consider moving $5k from Bluevine.', source: 'Chase · HFC', scan_date: today }),
    rec('moola_briefing', { severity: 'info', kind: 'save', title: 'Ramp duplicate SaaS: two Canva seats', detail: 'Second seat unused 60 days — cancel to save $30/mo.', source: 'Ramp', scan_date: today }),
    rec('client_status', { client: 'Maria Alvarez', service: 'Kitchen reface — maple shaker', brand: 'KTU', stage: 'In production', contract_total: 21400, paid: 19260, outstanding: 2140, last_payment: '2026-06-28', jobtread_number: 'JT-1042', flags: '', scan_date: today }, 'KTU'),
    rec('client_status', { client: 'Janet Kim', service: 'Hall bath remodel', brand: 'BTU', stage: 'Sold', contract_total: 15800, paid: 7900, outstanding: 7900, last_payment: '2026-06-15', jobtread_number: 'JT-1051', flags: 'awaiting start date', scan_date: today }, 'BTU'),
    rec('client_status', { client: 'Dan Whitfield', service: '1-day tune-up', brand: 'KTU', stage: 'Proposal', contract_total: 4200, paid: 0, outstanding: 4200, last_payment: '', jobtread_number: '', flags: '', scan_date: today }, 'KTU'),
    rec('client_status', { client: 'Anil Patel', service: 'Master bath — full', brand: 'BTU', stage: 'Complete', contract_total: 26500, paid: 26500, outstanding: 0, last_payment: '2026-07-01', jobtread_number: 'JT-1038', flags: '', scan_date: today }, 'BTU'),
    rec('team', { name: 'Steven Livingston', role: 'Owner — Sales & Marketing', business: 'Both', reports_to: '', tenure: '6 yrs', strengths: 'Sales, marketing, systems', note: 'Owner lane. Final call on pricing and spend.', employment: 'Owner' }),
    rec('team', { name: 'Takia', role: 'Operations Lead', business: 'Both', reports_to: 'Steven Livingston', tenure: '4 yrs', strengths: 'Scheduling, vendors, AP', note: 'Runs the ops lane day-to-day.', employment: 'W2' }),
    rec('team', { name: 'Sonya', role: 'Inside Sales', business: 'KTU', reports_to: 'Steven Livingston', tenure: '2 yrs', strengths: 'Follow-ups, revival queue', note: 'Owns the revival list top-down.', employment: 'W2' }),
    rec('team', { name: 'Rocco Marino', role: 'Lead Installer', business: 'KTU', reports_to: 'Takia', tenure: '3 yrs', strengths: 'Reface, wood restoration', note: 'Crew of 2 with Nicco.', employment: '1099' }),
    rec('team', { name: 'Miguel Santos', role: 'Bath Crew Lead', business: 'BTU', reports_to: 'Takia', tenure: '2 yrs', strengths: 'Tile, glass, plumbing coordination', note: 'BTU installs.', employment: '1099' }),
    rec('vendors', { vendor: 'Elias Cabinet Co', category: 'Cabinet doors & boxes', relationship: '6-year account — priority queue', ordering: 'Email PO to orders@; confirm in 24h', lead: '3–4 weeks', notes: 'Best pricing tier. Order through existing rep.' }),
    rec('vendors', { vendor: 'NJ Countertop Supply', category: 'Quartz / granite tops', relationship: 'Net-30 account', ordering: 'Portal + template drawing', lead: '10 days from template', notes: 'Ask for Marco.' }),
    rec('vendors', { vendor: 'ProSource Wayne', category: 'Tile & flooring', relationship: 'Member pricing', ordering: 'Showroom pickup or job-site delivery', lead: 'Stock: 2 days', notes: 'BTU tile default.' }),
    rec('trades', { name: 'A+ Electric (Lou)', service: 'Electrical — permits & finish', contact: 'Lou · (973) 555-0155 · lou@apluselec.example' }),
    rec('trades', { name: 'Santos Tile', service: 'Tile setting', contact: 'Miguel · (551) 555-0164' }),
    rec('reports', { name: 'KTU CMO Dashboard', url: 'https://ktu-cmo.example.com', description: 'Spend, CPL, ROAS by channel — refreshed daily.' }),
    rec('reports', { name: 'Jatalia Ops Dashboard', url: 'https://jataliamarketplace.com', description: 'Amazon + Walmart + Shopify + ShipStation consolidated view.' }),
    rec('docs_dashboards', { title: 'KTU CMO dashboard', url: 'https://ktu-cmo.example.com', desc: 'Marketing performance' }),
    rec('docs_dashboards', { title: 'Jatalia ops', url: 'https://jataliamarketplace.com', desc: 'Earthwise daily driver' }),
    rec('daily_ops', { text: 'Check HighLevel inbox — reply to every lead within 15 min' }),
    rec('daily_ops', { text: 'Review ServiceMinder appointments for tomorrow' }),
    rec('ordering_reps', { vendor: 'Elias Cabinet Co', contact: 'Ben Yabra · ben@elias.example', pricing: 'Tier 1 franchise', terms: 'Net 30' }),
    rec('team_dates', { name: 'Takia', birthday: '1988-07-19', anniversary: '2022-03-01' }, 'Both'),
    rec('team_dates', { name: 'Sonya', birthday: '1994-11-02', anniversary: '2024-05-15' }, 'Both'),
    rec('btu_ordering', { job: 'Kim — hall bath', jobtread_number: 'JT-1051', sold_total: 15800, item: 'Vanity + quartz top 36"', category: 'Vanity', tier: 'Series 2', qty: 1, unit: 'ea', unit_cost: 640, extended_cost: 640, customer_price: 1380, budget_note: 'White shaker, chrome pulls', status: 'to order', invoice_match: 'matched', scan_date: today }, 'BTU'),
    rec('btu_ordering', { job: 'Kim — hall bath', jobtread_number: 'JT-1051', sold_total: 15800, item: 'Frameless glass door', category: 'Shower', tier: 'Clear 3/8"', qty: 1, unit: 'ea', unit_cost: 410, extended_cost: 410, customer_price: 890, budget_note: 'Measure after tile', status: 'ordered 2026-07-01', invoice_match: 'matched', scan_date: today }, 'BTU'),
    rec('pipeline_briefing', { severity: 'warn', title: 'Booking ratio dipped to 58% this week', detail: 'Speed-to-lead on Meta forms is the drag — median first response 3h 40m.', source: 'HighLevel + ServiceMinder', scan_date: today }),
    rec('pipeline_funnel', { stage: 'Leads', period: 'Last 30d', value: '86', rate: '—', note: 'All sources' }),
    rec('pipeline_funnel', { stage: 'Consults booked', period: 'Last 30d', value: '50', rate: '58%', note: 'Booking ratio' }),
    rec('pipeline_sources', { source: 'Organic / GMB', leads: '52', appts: '34', sales: '11', close_rate: '32%', note: 'Protect at all costs' }),
    rec('pipeline_sources', { source: 'Google Ads', leads: '21', appts: '11', sales: '3', close_rate: '27%', note: '' }),
    rec('mkt_plan_items', { title: 'July4 town banner — Bloomfield', channel: 'Print', owner: 'Sonya', brand: 'KTU', start: '2026-07-01', end: '2026-07-31', month: '2026-07', budget: 1200, actual: 950, status: 'live', notes: 'Broad St banner + Patch feature' }, 'KTU'),
    // ---- Tekky (Tech Stack · Live tab) — shapes copied from the live rows ----
    rec('tekky_stack', { scan_date: today, generated_at: new Date(NOW).toISOString(), run: 'initial inventory (Tekky first run)', domains: {
      mcp_stdio: [
        { name: 'ghl-ktu', kind: 'http-mcp', status: 'UP', reason: 'PIT set; tools live this session', auth: { env_vars: [{ name: 'GHL_PIT_KTU', state: 'SET' }] }, notes: 'LeadConnector hosted MCP, Kitchen Tune-Up' },
        { name: 'closebot', kind: 'stdio', status: 'DOWN', reason: 'env keys missing; not registered this environment', auth: { env_vars: [{ name: 'CLOSEBOT_API_KEY', state: 'MISSING' }] }, notes: '15 tools; KTU/BTU booking bots' },
        { name: 'serviceminder', kind: 'stdio', status: 'DOWN', reason: 'env keys missing; connector covers reads', auth: { env_vars: [{ name: 'SM_KEY_KTU', state: 'MISSING' }, { name: 'SM_KEY_BTU', state: 'MISSING' }] }, notes: '28 tools; multi-location KTU+BTU' },
      ],
      connectors: [
        { name: 'Gmail', kind: 'connector', status: 'UP', reason: 'tools present in session', notes: '' },
        { name: 'Slack', kind: 'connector', status: 'UP', reason: 'tools present in session', notes: '' },
        { name: 'Shopify', kind: 'connector', status: 'DEGRADED', reason: 'documented in CLAUDE.md but not attached to this session — Jatalia DTC lens blind', notes: 'reattach in claude.ai connectors' },
      ],
      cloudflare: { probe: 'workers_list via Cloudflare Developer Platform connector', zones: ['goaxyom.com', 'jataliamarketplace.com'], account: { id: '2cdff9b17750f72247f2704875696ed5', name: 'Firstgenerationusallc' }, workers: [
        { name: 'ktubtuintranet', status: 'UP', reason: 'deployed; serves dash.goaxyom.com (HTTP 200)', notes: 'assets-only; custom domain dash.goaxyom.com' },
        { name: 'axyom-chat', status: 'DEGRADED', reason: 'in development, NOT deployed — /api/chat returns 404', notes: 'route dash.goaxyom.com/api/chat*' },
        { name: 'ktu-cmo-dashboard-auth', status: 'REMOVED', reason: 'absent from live workers_list; decommissioned', notes: 'still listed in CLAUDE.md — drift' },
      ] },
      supabase: { project: 'tguwpswcneywvscxzyef', status: 'UP', reason: 'MCP queries OK; REST 401 = auth enforced as designed', notes: 'profiles: 4 intranet users; RLS enabled on all public tables', intranet_records_sections: 61, tables: [
        { name: 'contacts', rows: 56, rls: true }, { name: 'intranet_records', rows: 435, rls: true }, { name: 'profiles', rows: 4, rls: true },
      ] },
      intranet: [
        { name: 'Axyom intranet (dash.goaxyom.com)', status: 'UP', reason: 'HTTP 200', notes: 'SPA at intranet/index.html served by ktubtuintranet worker' },
        { name: 'Jatalia ops dashboard (jataliamarketplace.com)', status: 'UP', reason: 'HTTP 200', notes: '' },
      ],
      agents: [
        { name: 'tekky', status: 'UP', reason: 'first run today', purpose: 'IT dept: stack inventory, change log, health monitor', outputs: ['tekky_stack', 'tekky_changes', 'tekky_status', 'tekky_briefing'] },
        { name: 'moola', status: 'DEGRADED', reason: 'moola_briefing stale >48h for a daily agent', purpose: 'daily CFO briefing', outputs: ['moola_briefing', 'earth_moola'] },
        { name: 'harvest', status: 'UNKNOWN', reason: 'specced but never published', purpose: 'Earthwise demand & growth', outputs: ['harvest_briefing', 'harvest_ads'] },
      ],
      saas: [
        { name: 'HighLevel CRM', status: 'UP', access: 'ghl-ktu/ghl-btu MCP + Highlevel connector' },
        { name: 'CloseBot', status: 'UNKNOWN', access: 'stdio only (CLOSEBOT_API_KEY)', reason: 'no access path this session' },
      ],
      repo: { path: '/home/user/TeamLivingston', dirs: { 'intranet/': 'index.html SPA + tests/audit.mjs', 'mcp-servers/': '8 stdio servers + bootstrap.sh + .env.example' } },
    } }, 'Both'),
    rec('tekky_status', { component: 'stdio MCP: closebot/serviceminder', domain: 'mcp_stdio', status: 'DOWN', reason: 'required env keys MISSING in this environment', checked_at: iso(5), scan_date: today }, 'Both'),
    rec('tekky_status', { component: 'Moola daily briefing', domain: 'agents', status: 'DEGRADED', reason: 'moola_briefing stale >48h for a daily agent', checked_at: iso(5), scan_date: today }, 'Both'),
    rec('tekky_status', { component: 'axyom-chat worker', domain: 'cloudflare', status: 'DEGRADED', reason: 'built but not deployed; /api/chat returns 404', checked_at: iso(5), scan_date: today }, 'Both'),
    rec('tekky_status', { component: 'ghl-ktu / ghl-btu MCP', domain: 'mcp_stdio', status: 'UP', reason: 'PITs SET; both HighLevel servers live', checked_at: iso(5), scan_date: today }, 'Both'),
    rec('tekky_status', { component: 'Supabase tguwpswcneywvscxzyef', domain: 'supabase', status: 'UP', reason: '7 tables, RLS on', checked_at: iso(5), scan_date: today }, 'Both'),
    rec('tekky_status', { component: 'Harvest / Cellar agents', domain: 'agents', status: 'UNKNOWN', reason: 'specced but never published', checked_at: iso(5), scan_date: today }, 'Both'),
    rec('tekky_briefing', { severity: 'urgent', title: 'Moola + Goldeneye briefings stale >48h', detail: 'Both daily agents last published 2 days ago — check the scheduled sessions ran and their Supabase writes succeeded.', source: 'Supabase intranet_records max(created_at)', scan_date: today }, 'Both'),
    rec('tekky_briefing', { severity: 'warn', title: '10 of 12 stdio MCP servers unregistered — env keys MISSING', detail: 'Only GHL_PIT_KTU/GHL_PIT_BTU are SET. Set the missing keys in the Cloud env-var config so bootstrap.sh registers the servers.', source: 'printenv names vs mcp-servers/.env.example', scan_date: today }, 'Both'),
    rec('tekky_briefing', { severity: 'info', title: 'Stack baseline recorded: 83 components tracked', detail: 'Full map in tekky_stack; all future runs diff against this baseline.', source: 'Tekky initial inventory', scan_date: today }, 'Both'),
    rec('tekky_changes', { ts: iso(10), kind: 'added', component: 'entire stack', domain: 'all', detail: 'Initial inventory — baseline recorded. 83 components across all domains.', evidence: 'Tekky first run', scan_date: today }, 'Both'),
    rec('tekky_changes', { ts: iso(3), kind: 'modified', component: 'axyom-chat worker', domain: 'cloudflare', detail: 'Route added: dash.goaxyom.com/api/chat*', evidence: 'wrangler.toml', scan_date: today }, 'Both'),
  );

  const clone = (x) => JSON.parse(JSON.stringify(x));

  function makeBuilder(table) {
    const st = { filters: [], single: false, limit: null, order: null, op: 'select' };
    const b = {};
    const chain = (fn) => (...a) => { fn(...a); return b; };
    b.select = chain(() => { if (st.op === 'select') st.op = 'select'; });
    b.eq = chain((k, v) => st.filters.push([k, v]));
    b.order = chain((k, o) => { st.order = [k, o && o.ascending]; });
    b.limit = chain((n) => { st.limit = n; });
    b.single = chain(() => { st.single = true; });
    b.insert = chain((row) => { st.op = 'insert'; st.rows = Array.isArray(row) ? row : [row]; });
    b.update = chain((patch) => { st.op = 'update'; st.patch = patch; });
    b.delete = chain(() => { st.op = 'delete'; });
    b.then = (res, rej) => Promise.resolve().then(() => {
      let rows = (DATA[table] || []).slice();
      for (const [k, v] of st.filters) rows = rows.filter(r => r[k] === v);
      if (st.op === 'insert') { st.rows.forEach(r => (DATA[table] = DATA[table] || []).push({ id: 'n' + Math.random().toString(36).slice(2), created_at: new Date().toISOString(), ...r })); return { data: st.rows, error: null }; }
      if (st.op === 'update') { rows.forEach(r => Object.assign(r, st.patch)); return { data: rows, error: null }; }
      if (st.op === 'delete') { DATA[table] = (DATA[table] || []).filter(r => !rows.includes(r)); return { data: null, error: null }; }
      if (st.order) { const [k, asc] = st.order; rows.sort((a, b2) => (a[k] > b2[k] ? 1 : -1) * (asc === false ? -1 : 1)); }
      if (st.limit != null) rows = rows.slice(0, st.limit);
      if (st.single) return { data: clone(rows[0] || null), error: rows[0] ? null : { message: 'no rows' } };
      return { data: clone(rows), error: null };
    }).then(res, rej);
    return b;
  }

  const session = { access_token: 'fake-token', user: { id: 'u1', email: 'stevenglivingston@gmail.com' } };
  const fake = {
    auth: {
      getSession: async () => ({ data: { session } }),
      getUser: async () => ({ data: { user: session.user } }),
      signInWithPassword: async () => ({ data: { session }, error: null }),
      signOut: async () => ({ error: null }),
      onAuthStateChange: (cb) => { setTimeout(() => cb('SIGNED_IN', session), 0); return { data: { subscription: { unsubscribe() {} } } }; },
    },
    from: (t) => makeBuilder(t),
    channel: () => { const c = { on: () => c, subscribe: () => c }; return c; },
  };
  window.supabase = { createClient: () => fake };
})();
`;

async function newPage(browser, { width, height, mobile }) {
  const ctx = await browser.newContext({
    viewport: { width, height },
    deviceScaleFactor: 2,
    isMobile: !!mobile,
    hasTouch: !!mobile,
    userAgent: mobile
      ? 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1'
      : undefined,
  });
  await ctx.route(/googleapis|gstatic|jsdelivr|supabase\.co/, r => r.abort());
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', e => errors.push('pageerror: ' + e.message));
  page.on('console', m => {
    if (m.type() === 'error' && !/Failed to load resource|net::ERR/.test(m.text())) errors.push('console: ' + m.text());
  });
  await page.addInitScript(STUB);
  return { ctx, page, errors };
}

const run = async () => {
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium', headless: true });
  const results = { errors: [], overflow: [], tabbar: null };

  // ---- Mobile 390x844 ----
  const { ctx, page, errors } = await newPage(browser, { width: 390, height: 844, mobile: true });
  await page.goto('file://' + INDEX);
  await page.waitForSelector('#app', { state: 'visible', timeout: 10000 });
  await page.waitForTimeout(900);
  await page.screenshot({ path: `${SHOTS}/${PREFIX}-mobile-home.png` });
  await page.screenshot({ path: `${SHOTS}/${PREFIX}-mobile-home-full.png`, fullPage: true });

  // drawer open
  const menuBtn = await page.$('.mobile-menu, .tabbar-item[data-tab="__more"]');
  if (menuBtn) {
    await menuBtn.click();
    await page.waitForTimeout(400);
    await page.screenshot({ path: `${SHOTS}/${PREFIX}-mobile-drawer.png` });
    await page.evaluate(() => document.querySelector('.sidebar')?.classList.remove('open'));
    await page.waitForTimeout(300);
  }

  // clients (data tab)
  await page.evaluate(() => go('clients'));
  await page.waitForTimeout(700);
  await page.screenshot({ path: `${SHOTS}/${PREFIX}-mobile-clients.png` });

  // all tabs: switch + overflow check
  const tabs = await page.evaluate(() => Object.keys(TAB_TITLES));
  for (const t of tabs) {
    await page.evaluate(tb => go(tb), t);
    await page.waitForTimeout(250);
    const m = await page.evaluate(() => ({
      active: document.querySelector('.panel.active')?.id,
      sw: document.documentElement.scrollWidth,
      iw: window.innerWidth,
      bw: document.body.scrollWidth,
    }));
    if (m.active !== t) results.errors.push(`tab ${t}: panel not activated (got ${m.active})`);
    if (m.sw > m.iw + 1 || m.bw > m.iw + 1) results.overflow.push(`${t}: scrollWidth=${m.sw}/${m.bw} innerWidth=${m.iw}`);
  }
  // bottom bar coverage check (after redesign)
  results.tabbar = await page.evaluate(() => {
    const bar = document.querySelector('.tabbar');
    if (!bar) return null;
    const r = bar.getBoundingClientRect();
    const content = document.querySelector('.content');
    const cs = getComputedStyle(content);
    return { visible: r.height > 0, top: r.top, padBottom: cs.paddingBottom, items: bar.querySelectorAll('.tabbar-item').length };
  });
  await page.evaluate(() => go('home'));
  await page.waitForTimeout(400);

  // scrolled home (KPIs + feed)
  await page.evaluate(() => document.querySelector('.grid')?.scrollIntoView({ block: 'start' }));
  await page.waitForTimeout(300);
  await page.screenshot({ path: `${SHOTS}/${PREFIX}-mobile-home-kpis.png` });

  // role gating: tab bar must follow the role/workspace
  results.roleGating = await page.evaluate(async () => {
    const read = () => [...document.querySelectorAll('.tabbar-item')].map(b => b.dataset.tab);
    const out = {};
    applyRole('homeservices'); await new Promise(r => setTimeout(r, 150)); out.homeservices = read();
    applyRole('ecommerce'); await new Promise(r => setTimeout(r, 150));
    out.ecommerce = read();
    out.ecomHsHidden = [...document.querySelectorAll('.nav-group[data-scope="hs"]')].every(g => g.style.display === 'none');
    applyRole('admin'); await new Promise(r => setTimeout(r, 150)); out.admin = read();
    return out;
  });

  // ---- Tech Stack · Live (Tekky) tab: header tally, callouts, stack map,
  //      Earthwise grouping for Shopify, env-key chips, changelog ----
  await page.evaluate(() => go('tech'));
  await page.waitForTimeout(700);
  results.tech = await page.evaluate(() => {
    const txt = el => (el ? el.textContent.trim() : null);
    const shopify = [...document.querySelectorAll('#tech .tek-comp-name')].find(n => /shopify/i.test(n.textContent));
    return {
      active: document.querySelector('.panel.active')?.id,
      tally: txt(document.querySelector('#tek_head .tek-tally')),
      pills: document.querySelectorAll('#tek_head .tek-pill').length,
      scanline: txt(document.querySelector('#tek_head .tek-scanline')),
      callouts: document.querySelectorAll('#tek_briefing .ge-row').length,
      urgent: document.querySelectorAll('#tek_briefing .ge-row.urgent').length,
      groups: document.querySelectorAll('#tek_stack .tek-group').length,
      badges: document.querySelectorAll('#tek_stack .tek-badge').length,
      chipsSet: document.querySelectorAll('#tek_stack .tek-chip.set').length,
      chipsMissing: document.querySelectorAll('#tek_stack .tek-chip.missing').length,
      chipValueLeak: [...document.querySelectorAll('#tek_stack .tek-chip')].some(c => /=|secret|token[^s]/i.test(c.textContent)),
      shopifyGroup: shopify ? txt(shopify.closest('.tek-group')?.querySelector('summary')) : null,
      changelog: document.querySelectorAll('#tek_changes .tek-tl-item').length,
      skeletons: document.querySelectorAll('#tech .loading').length,
    };
  });
  const T = results.tech;
  if (T.active !== 'tech') results.errors.push('tech: panel not activated');
  if (T.pills !== 4 || !/2 up/.test(T.tally || '') || !/1 down/.test(T.tally || '')) results.errors.push('tech: health tally wrong (' + T.tally + ')');
  if (!/Tekky scanned/.test(T.scanline || '')) results.errors.push('tech: scan line missing');
  if (T.callouts !== 3 || T.urgent !== 1) results.errors.push(`tech: briefing callouts wrong (${T.callouts}/${T.urgent} urgent)`);
  if (T.groups < 8) results.errors.push('tech: expected >=8 stack-map groups, got ' + T.groups);
  if (T.badges < 12) results.errors.push('tech: too few health badges (' + T.badges + ')');
  if (!T.chipsSet || !T.chipsMissing) results.errors.push(`tech: env-key chips missing (set=${T.chipsSet} missing=${T.chipsMissing})`);
  if (T.chipValueLeak) results.errors.push('tech: env chip appears to render a value');
  if (!/Earthwise \/ Jatalia/.test(T.shopifyGroup || '')) results.errors.push('tech: Shopify not grouped under Earthwise / Jatalia (in: ' + T.shopifyGroup + ')');
  if (T.changelog !== 2) results.errors.push('tech: changelog should show 2 entries, got ' + T.changelog);
  if (T.skeletons) results.errors.push('tech: loading skeletons left behind');
  // Capture-only tweaks: hide the (closed) fixed-position chat panel, and lift
  // the mobile overflow-x trap that makes <body> its own scroll container —
  // fullPage stitching scrolls the window, so the body-scroller would paint
  // everything below the first viewport blank.
  await page.evaluate(() => {
    document.getElementById('axChat').style.visibility = 'hidden';
    document.documentElement.style.overflow = 'visible';
    document.body.style.overflow = 'visible';
  });
  await page.screenshot({ path: `${SHOTS}/tech-tab-mobile.png`, fullPage: true });
  await page.evaluate(() => {
    document.getElementById('axChat').style.visibility = '';
    document.documentElement.style.overflow = '';
    document.body.style.overflow = '';
  });

  // ---- Ask Ax chat (mobile): open, streamed reply against a mocked SSE
  //      response, tool chip, persistence, close ----
  await page.evaluate(() => go('home'));
  await page.waitForTimeout(300);
  await page.evaluate(() => {
    window.fetch = async (url, opts) => {
      if (!String(url).includes('/api/chat')) throw new Error('unexpected fetch: ' + url);
      window.__CHAT_REQ__ = JSON.parse(opts.body);
      const enc = new TextEncoder();
      const frames = [
        'event: tool\ndata: {"name":"get_system_status","status":"start"}\n\n',
        'event: tool\ndata: {"name":"get_system_status","status":"done"}\n\n',
        'event: text\ndata: {"text":"All systems are "}\n\n',
        'event: text\ndata: {"text":"**healthy** right now."}\n\n',
        'event: done\ndata: {"stop_reason":"end_turn"}\n\n',
      ];
      const stream = new ReadableStream({
        async start(c) {
          for (const f of frames) { c.enqueue(enc.encode(f)); await new Promise(r => setTimeout(r, 25)); }
          c.close();
        },
      });
      return new Response(stream, { status: 200, headers: { 'Content-Type': 'text/event-stream' } });
    };
  });
  await page.evaluate(() => document.getElementById('axFab').click());
  await page.waitForTimeout(400);
  const chatState = await page.evaluate(() => ({
    open: document.getElementById('axChat').classList.contains('open'),
    chips: document.querySelectorAll('#axChatLog .ax-chip').length,
  }));
  if (!chatState.open) results.errors.push('chat: panel did not open on mobile');
  if (chatState.chips < 3) results.errors.push('chat: starter chips missing on empty state');
  await page.evaluate(() => { document.getElementById('axChatText').value = 'How are things?'; chatSend(); });
  await page.waitForTimeout(1200);
  results.chat = await page.evaluate(() => ({
    user: document.querySelector('#axChatLog .ax-msg.user')?.textContent || null,
    tool: document.querySelector('#axChatLog .ax-tool')?.textContent || null,
    toolDone: document.querySelector('#axChatLog .ax-tool.done') != null,
    reply: document.querySelector('#axChatLog .ax-msg.ax')?.innerHTML || '',
    persisted: (JSON.parse(sessionStorage.getItem('axyom_chat_v1') || '{}').msgs || []).length,
    reqToken: window.__CHAT_REQ__?.token,
    reqLastRole: window.__CHAT_REQ__?.messages?.at(-1)?.role,
  }));
  if (results.chat.user !== 'How are things?') results.errors.push('chat: user bubble missing');
  if (!/system status/i.test(results.chat.tool || '') || !results.chat.toolDone) results.errors.push('chat: tool chip missing or never resolved');
  if (!results.chat.reply.includes('<b>healthy</b>')) results.errors.push('chat: streamed reply not rendered (got: ' + results.chat.reply + ')');
  if (results.chat.persisted !== 2) results.errors.push('chat: sessionStorage should hold 2 messages, got ' + results.chat.persisted);
  if (results.chat.reqToken !== 'fake-token') results.errors.push('chat: request did not carry the Supabase access token');
  if (results.chat.reqLastRole !== 'user') results.errors.push('chat: last message in payload must be user');
  await page.screenshot({ path: `${SHOTS}/chat-mobile.png` });
  await page.evaluate(() => closeChat());
  await page.waitForTimeout(300);
  const chatClosed = await page.evaluate(() =>
    !document.getElementById('axChat').classList.contains('open') &&
    !document.getElementById('axFab').classList.contains('hide'));
  if (!chatClosed) results.errors.push('chat: panel did not close / FAB did not return');
  results.errors.push(...errors);
  await ctx.close();

  // ---- Ask Ax degraded state: /api/chat 404s (route not deployed) ----
  const g = await newPage(browser, { width: 390, height: 844, mobile: true });
  await g.page.goto('file://' + INDEX);
  await g.page.waitForSelector('#app', { state: 'visible', timeout: 10000 });
  await g.page.waitForTimeout(700);
  await g.page.evaluate(() => {
    window.fetch = async () => new Response('<html><body>intranet</body></html>', {
      status: 404, headers: { 'Content-Type': 'text/html' },
    });
  });
  await g.page.evaluate(() => { document.getElementById('axFab').click(); });
  await g.page.waitForTimeout(300);
  await g.page.evaluate(() => chatSend('hello?'));
  await g.page.waitForTimeout(600);
  const degraded = await g.page.evaluate(() => ({
    sys: document.querySelector('#axChatLog .ax-msg.sys')?.textContent || null,
    fabVisible: getComputedStyle(document.getElementById('axFab')).display !== 'none',
    orphanBubbles: document.querySelectorAll('#axChatLog .ax-msg.ax').length,
  }));
  if (!/being connected/i.test(degraded.sys || '')) results.errors.push('chat degraded: friendly offline message missing (got: ' + degraded.sys + ')');
  if (degraded.orphanBubbles !== 0) results.errors.push('chat degraded: empty assistant bubble left behind');
  results.errors.push(...g.errors);
  await g.ctx.close();

  // ---- Desktop 1280x800 ----
  const d = await newPage(browser, { width: 1280, height: 800, mobile: false });
  await d.page.goto('file://' + INDEX);
  await d.page.waitForSelector('#app', { state: 'visible', timeout: 10000 });
  await d.page.waitForTimeout(900);
  await d.page.screenshot({ path: `${SHOTS}/${PREFIX}-desktop-home.png` });
  await d.page.evaluate(() => go('integrations'));
  await d.page.waitForTimeout(500);
  const dm = await d.page.evaluate(() => ({ sw: document.documentElement.scrollWidth, iw: window.innerWidth }));
  if (dm.sw > dm.iw + 1) results.overflow.push(`desktop integrations: ${dm.sw}>${dm.iw}`);
  await d.page.evaluate(() => go('tech'));
  await d.page.waitForTimeout(600);
  const dt = await d.page.evaluate(() => ({
    sw: document.documentElement.scrollWidth, iw: window.innerWidth,
    badges: document.querySelectorAll('#tek_stack .tek-badge').length,
    changelog: document.querySelectorAll('#tek_changes .tek-tl-item').length,
  }));
  if (dt.sw > dt.iw + 1) results.overflow.push(`desktop tech: ${dt.sw}>${dt.iw}`);
  if (dt.badges < 12 || dt.changelog !== 2) results.errors.push('tech desktop: render incomplete ' + JSON.stringify(dt));
  // Chat opens/closes as a side panel on desktop
  await d.page.evaluate(() => document.getElementById('axFab').click());
  await d.page.waitForTimeout(350);
  const dChat = await d.page.evaluate(() => {
    const r = document.getElementById('axChat').getBoundingClientRect();
    return {
      open: document.getElementById('axChat').classList.contains('open'),
      inViewport: r.right <= window.innerWidth + 1 && r.bottom <= window.innerHeight + 1 && r.width > 300,
    };
  });
  if (!dChat.open || !dChat.inViewport) results.errors.push('chat: desktop panel missing/misplaced ' + JSON.stringify(dChat));
  await d.page.screenshot({ path: `${SHOTS}/${PREFIX}-desktop-chat.png` });
  await d.page.evaluate(() => closeChat());
  await d.page.waitForTimeout(300);
  const dClosed = await d.page.evaluate(() => !document.getElementById('axChat').classList.contains('open'));
  if (!dClosed) results.errors.push('chat: desktop panel did not close');
  results.errors.push(...d.errors);
  await d.ctx.close();

  // ---- Login shell (no session) ----
  const l = await newPage(browser, { width: 390, height: 844, mobile: true });
  await l.page.addInitScript(`window.__NO_SESSION__ = true;`);
  // override stub session: re-add init script that nulls getSession
  await l.page.addInitScript(`
    const orig = window.supabase;
    window.supabase = { createClient: (...a) => { const c = orig.createClient(...a);
      c.auth.getSession = async () => ({ data: { session: null } });
      c.auth.onAuthStateChange = (cb) => ({ data: { subscription: { unsubscribe(){} } } });
      return c; } };
  `);
  await l.page.goto('file://' + INDEX);
  await l.page.waitForTimeout(700);
  const loginVisible = await l.page.evaluate(() => {
    const el = document.getElementById('login');
    return el && getComputedStyle(el).display !== 'none' && document.getElementById('app').style.display !== 'block';
  });
  if (!loginVisible) results.errors.push('login shell did not render without a session');
  await l.page.screenshot({ path: `${SHOTS}/${PREFIX}-mobile-login.png` });
  results.errors.push(...l.errors);
  await l.ctx.close();

  await browser.close();
  console.log(JSON.stringify(results, null, 2));
  if (results.errors.length || results.overflow.length) process.exitCode = 1;
};

run().catch(e => { console.error(e); process.exit(1); });
