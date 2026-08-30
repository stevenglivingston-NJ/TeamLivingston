#!/usr/bin/env node
/**
 * apply-report-scheduler.mjs — additive patch: Reports tab gains the
 * Cancellation Watch board and the schedule manager for every report.
 *
 * Written as a patch rather than an edit because ktubtuintranet.html and the
 * live worker have forked in both directions (see RECONCILIATION.md), so this
 * has to apply cleanly to either copy. It only inserts; it never rewrites
 * anything that is already there, and it is idempotent — running it twice is a
 * no-op.
 *
 *   node tools/apply-report-scheduler.mjs <in.html> [out.html]
 */
import { readFileSync, writeFileSync } from 'node:fs';

const inFile = process.argv[2];
const outFile = process.argv[3] || inFile;
if (!inFile) { console.error('usage: apply-report-scheduler.mjs <in.html> [out.html]'); process.exit(1); }
let html = readFileSync(inFile, 'utf8');

if (html.includes('renderReportsTab')) {
  console.log('already patched — no change');
  writeFileSync(outFile, html);
  process.exit(0);
}

/* ---------- 1. Reports panel markup ------------------------------------- */
const OLD_PANEL = `      <div class="card"><div id="reports_root" class="loading">Loading…</div></div>
    </section>`;
if (!html.includes(OLD_PANEL)) { console.error('anchor 1 (reports panel) not found'); process.exit(1); }

const NEW_PANEL = `      <div id="cancelwatch_root"></div>
      <div id="repsched_root"></div>
      <h2 class="sec-title" style="margin-top:26px">Dashboards</h2>
      <div class="card"><div id="reports_root" class="loading">Loading…</div></div>
    </section>`;
html = html.replace(OLD_PANEL, () => NEW_PANEL);

/* ---------- 2. Behaviour ------------------------------------------------ */
const JS = String.raw`
/* ================================================================
   Reports tab — Cancellation Watch + report scheduling
   ----------------------------------------------------------------
   Two boards, both fed from Supabase:

   Cancellation Watch  intranet_records/cancel_watch, written by
                       mcp-servers/cancellation-watch.py. Shows the rate
                       against the agreed 24% allowed ceiling, the reason
                       mix, and every cancellation outside the allowed set.

   Report schedules    report_schedules — one row per report: how often it
                       goes out, at what hour, and to whom. Owner-editable
                       here; public.enqueue_due_reports() (hourly pg_cron)
                       does the sending, so a change made here takes effect
                       on the next tick with no deploy.

   Snapshot age is shown deliberately. The generator and the mailer fail
   independently, so a stale snapshot has to be visible rather than quietly
   re-sent as if it were this week's numbers.
   ================================================================ */
const RS_FREQ = { daily:'Every day', weekly:'Weekly', monthly:'Monthly', off:'Paused' };
const RS_DOW  = ['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'];
let RS_EDITING = null;

function rsHour(h){ const n=Number(h)||0; const ap=n<12?'am':'pm'; const t=n%12||12; return t+ap; }
function rsWhen(s){
  if(s.frequency==='off'||!s.enabled) return 'Paused';
  const at=' at '+rsHour(s.hour_local)+' ET';
  if(s.frequency==='daily')   return 'Every day'+at;
  if(s.frequency==='weekly')  return 'Every '+(RS_DOW[s.day_of_week]||'Monday')+at;
  if(s.frequency==='monthly') return 'Day '+(s.day_of_month||1)+' of the month'+at;
  return RS_FREQ[s.frequency]||s.frequency;
}
function rsAge(iso){
  if(!iso) return {txt:'never generated', cls:'urgent'};
  const days=Math.floor((Date.now()-new Date(iso).getTime())/86400000);
  if(days<=1) return {txt:days===0?'generated today':'generated yesterday', cls:'ok'};
  if(days<=8) return {txt:'generated '+days+' days ago', cls:'ok'};
  return {txt:'stale — generated '+days+' days ago', cls:'urgent'};
}

async function renderCancelWatch(){
  const box=document.getElementById('cancelwatch_root'); if(!box) return;
  box.innerHTML='<div class="card"><div class="loading">Loading cancellation watch…</div></div>';
  const [{data:rows,error}, {data:snaps}] = await Promise.all([
    sb.from('intranet_records').select('fields,sort_order').eq('section','cancel_watch').order('sort_order'),
    sb.from('report_snapshots').select('report_key,generated_at,metrics').eq('report_key','cancel_watch')
  ]);
  if(error){ box.innerHTML='<div class="card"><div class="empty">Could not load: '+esc(error.message)+'</div></div>'; return; }
  if(!rows||!rows.length){
    box.innerHTML='<div class="card"><h2 class="sec-title">Consultation Cancellation Watch</h2>'+
      '<div class="empty">No scan has run yet. It publishes on the first scheduled run.</div></div>';
    return;
  }
  const head=(rows.find(r=>r.fields.kind==='headline')||{}).fields||{};
  const reasons=rows.filter(r=>r.fields.kind==='reason').map(r=>r.fields);
  const breaches=rows.filter(r=>r.fields.kind==='breach').map(r=>r.fields);
  const m=(snaps&&snaps[0]&&snaps[0].metrics)||{};
  const age=rsAge(snaps&&snaps[0]&&snaps[0].generated_at);
  const ok=head.severity==='ok';
  const pc=v=>v==null?'—':Math.round(v*100)+'%';

  const kpi=(label,value,tone)=>'<div class="kpi" style="padding:12px 14px"><div class="label">'+esc(label)+
    '</div><div class="value" style="font-size:22px'+(tone?';color:'+tone:'')+'">'+esc(String(value))+'</div></div>';

  box.innerHTML='<div class="card">'+
    '<h2 class="sec-title">Consultation Cancellation Watch'+
      '<span class="chip '+(ok?'ok':'urgent')+'" style="margin-left:10px">'+(ok?'Within ceiling':'Over ceiling')+'</span>'+
      '<span class="chip '+age.cls+'" style="margin-left:6px">'+esc(age.txt)+'</span></h2>'+
    '<p class="page-sub" style="margin:2px 0 14px">'+esc(head.window||'')+
      ' · allowed reasons are client-requested, out of territory, non-cabinet scope, or repair only.</p>'+
    '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;margin-bottom:14px">'+
      kpi('Booked', m.booked??'—')+
      kpi('Attended', m.attended??'—')+
      kpi('Cancelled', (m.cancelled??'—')+' ('+pc(m.cancel_rate)+')')+
      kpi('Allowed reasons', (m.allowed??'—')+' ('+pc(m.allowed_rate_of_booked)+')', ok?'#4ade80':'')+
      kpi('Ceiling', pc(m.ceiling)+' = '+(m.ceiling_count??'—'))+
      (m.over_ceiling ? kpi('Replacement cost','$'+Number(m.spend_impact||0).toLocaleString(),'#fb923c') : '')+
    '</div>'+
    '<div style="font-weight:600;margin-bottom:6px">'+esc(head.title||'')+'</div>'+
    '<div class="note" style="margin-bottom:16px">'+esc(head.detail||'')+'</div>'+
    (reasons.length?'<table class="tbl"><thead><tr><th>Reason</th><th style="width:80px">Count</th>'+
      '<th style="width:200px">Against the ceiling?</th></tr></thead><tbody>'+
      reasons.map(f=>'<tr><td>'+esc(f.reason)+'</td><td>'+esc(String(f.count))+'</td>'+
        '<td><span class="chip '+(f.severity==='ok'?'ok':'warn')+'">'+esc(f.allowed)+'</span></td></tr>').join('')+
      '</tbody></table>':'')+
    (breaches.length?'<h3 style="margin:18px 0 8px;font-size:14px">Cancellations counting against the ceiling ('+breaches.length+')</h3>'+
      '<table class="tbl"><thead><tr><th>Customer</th><th>Town</th><th>Date</th><th>Reason</th><th>What we know</th></tr></thead><tbody>'+
      breaches.map(f=>'<tr><td>'+esc(f.customer||'(no name)')+'<br><small>'+esc(f.phone||'')+'</small></td>'+
        '<td>'+esc(f.city||'')+'</td><td>'+esc(f.when||'')+'</td><td>'+esc(f.reason||'')+'</td>'+
        '<td><small>'+esc((f.note||f.full_note||'').slice(0,240))+'</small></td></tr>').join('')+
      '</tbody></table>':'')+
    '<div class="note" style="margin-top:14px;opacity:.75">Reasons are read from the cancel-reason picklist and the '+
      'contact note log. The free-text note typed on the appointment itself is not readable by any API — only by the '+
      'manual UI export — so a reason written only there shows here as “no reason captured”. Setting a real '+
      'cancel reason on the appointment (not “Other”) classifies it automatically.</div>'+
  '</div>';
}

async function renderReportSchedules(){
  const box=document.getElementById('repsched_root'); if(!box) return;
  const admin=(typeof CURRENT_ROLE!=='undefined' && CURRENT_ROLE==='admin');
  if(!admin){ box.innerHTML=''; return; }
  box.innerHTML='<div class="card" style="margin-top:20px"><div class="loading">Loading report schedules…</div></div>';
  const since=new Date(Date.now()-7*86400000).toISOString();
  const [{data:rows,error},{data:snaps},{data:recent}]=await Promise.all([
    sb.from('report_schedules').select('*').order('name'),
    sb.from('report_snapshots').select('report_key,generated_at'),
    sb.from('notify_queue').select('recipient_email,sent_at,result').gte('created_at',since).limit(300)
  ]);
  if(error){ box.innerHTML='<div class="card" style="margin-top:20px"><div class="empty">Could not load schedules: '+esc(error.message)+'</div></div>'; return; }
  const snapBy=Object.fromEntries((snaps||[]).map(s=>[s.report_key,s.generated_at]));

  const body=(rows||[]).map(s=>{
    if(RS_EDITING===s.key){
      const dow=RS_DOW.map((d,i)=>'<option value="'+i+'"'+(i===s.day_of_week?' selected':'')+'>'+d+'</option>').join('');
      const hrs=Array.from({length:24},(_,h)=>'<option value="'+h+'"'+(h===s.hour_local?' selected':'')+'>'+rsHour(h)+' ET</option>').join('');
      const fq=Object.entries(RS_FREQ).map(([k,v])=>'<option value="'+k+'"'+(k===s.frequency?' selected':'')+'>'+v+'</option>').join('');
      return '<tr><td colspan="5"><div class="edit-form" style="display:grid;gap:8px">'+
        '<div style="font-weight:600">'+esc(s.name)+'</div>'+
        '<div style="display:flex;gap:8px;flex-wrap:wrap">'+
          '<label>Frequency<br><select id="rs_freq_'+s.key+'">'+fq+'</select></label>'+
          '<label>Day<br><select id="rs_dow_'+s.key+'">'+dow+'</select></label>'+
          '<label>Day of month<br><input id="rs_dom_'+s.key+'" type="number" min="1" max="28" value="'+(s.day_of_month||1)+'" style="width:90px"></label>'+
          '<label>Send at<br><select id="rs_hour_'+s.key+'">'+hrs+'</select></label>'+
          '<label>Active<br><select id="rs_on_'+s.key+'"><option value="1"'+(s.enabled?' selected':'')+'>Yes</option><option value="0"'+(!s.enabled?' selected':'')+'>No</option></select></label>'+
        '</div>'+
        '<label>Recipients — one email per line<br><textarea id="rs_to_'+s.key+'" rows="4" style="width:100%">'+esc((s.recipients||[]).join('\n'))+'</textarea></label>'+
        '<div class="rowbtns"><button class="btn sm" onclick="saveReportSchedule('+JSON.stringify(s.key)+')">Save</button>'+
        '<button class="btn sm ghost" onclick="RS_EDITING=null;renderReportSchedules()">Cancel</button></div>'+
      '</div></td></tr>';
    }
    const age=rsAge(snapBy[s.key]);
    const to=(s.recipients||[]);
    return '<tr>'+
      '<td><b>'+esc(s.name)+'</b><br><small>'+esc(s.description||'')+'</small></td>'+
      '<td>'+esc(rsWhen(s))+'</td>'+
      '<td>'+(to.length?to.map(e=>'<div><small>'+esc(e)+'</small></div>').join(''):'<small class="empty">nobody — will not send</small>')+'</td>'+
      '<td><span class="chip '+age.cls+'">'+esc(age.txt)+'</span>'+
        (s.last_sent_at?'<br><small>last sent '+esc(new Date(s.last_sent_at).toLocaleDateString())+'</small>':'')+
        (s.last_result?'<br><small style="opacity:.7">'+esc(s.last_result)+'</small>':'')+'</td>'+
      '<td class="rowbtns">'+
        '<button class="btn sm ghost" onclick="RS_EDITING='+JSON.stringify(s.key)+';renderReportSchedules()">Edit</button>'+
        '<button class="btn sm ghost" onclick="sendReportNow('+JSON.stringify(s.key)+')">Send now</button>'+
      '</td></tr>';
  }).join('');

  /* Delivery health. A queue row is marked "sent" when ANY channel delivers,
     so an email that 401s while Slack succeeds looks like a success. Reports
     are email-only, so that failure mode has to be surfaced here or a report
     silently never arrives while the queue claims it did. */
  const emailFails=(recent||[]).filter(r=>((r.result&&r.result.partial_failures)||[])
    .some(f=>String(f).toLowerCase().startsWith('email')));
  const emailOk=(recent||[]).filter(r=>r.recipient_email &&
    String((r.result&&r.result.via)||'').includes('email'));
  const health = emailFails.length
    ? '<div class="note" style="margin:0 0 12px;padding:10px 12px;border-left:3px solid #f87171">'+
      '<b>Email delivery is failing.</b> '+emailFails.length+' message(s) in the last 7 days could not be '+
      'emailed — most recently: <code>'+esc(String(emailFails[0].result.partial_failures[0]).slice(0,150))+
      '</code>. Queue rows still read “sent” because Slack delivered, so this does not show up as an error '+
      'anywhere else. Reports go out by email only, so they will not arrive until this is fixed.</div>'
    : (emailOk.length
       ? '<div class="note" style="margin:0 0 12px;opacity:.75">Email delivery healthy — '+emailOk.length+
         ' message(s) sent in the last 7 days.</div>'
       : '<div class="note" style="margin:0 0 12px;opacity:.75">No email has been sent in the last 7 days, '+
         'so the email path is currently unverified.</div>');

  box.innerHTML='<div class="card" style="margin-top:20px">'+
    '<h2 class="sec-title">Report schedules</h2>'+
    '<p class="page-sub" style="margin:2px 0 12px">Who gets each report and how often. Changes take effect on the next '+
      'hourly dispatch — no deploy needed. A report with no recipients, or set to Paused, is not sent. '+
      'Numbers are never re-sent from a stale snapshot: if the generator has not run in over a week the dispatcher '+
      'skips that report and says so here.</p>'+health+
    '<table class="tbl"><thead><tr><th style="width:28%">Report</th><th style="width:16%">Schedule</th>'+
      '<th style="width:22%">Recipients</th><th style="width:20%">Data freshness</th><th style="width:14%"></th>'+
      '</tr></thead><tbody>'+(body||'<tr><td colspan="5" class="empty">No reports registered yet.</td></tr>')+
    '</tbody></table></div>';
}

async function saveReportSchedule(key){
  const v=id=>{const e=document.getElementById(id+key);return e?e.value:null;};
  const to=(v('rs_to_')||'').split(/[\n,;]+/).map(s=>s.trim()).filter(Boolean);
  const bad=to.filter(e=>!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(e));
  if(bad.length){ alert('These do not look like email addresses:\n'+bad.join('\n')); return; }
  const patch={
    frequency:v('rs_freq_'), day_of_week:Number(v('rs_dow_')), day_of_month:Number(v('rs_dom_')),
    hour_local:Number(v('rs_hour_')), enabled:v('rs_on_')==='1', recipients:to
  };
  const {error}=await sb.from('report_schedules').update(patch).eq('key',key);
  if(error){ alert('Could not save: '+error.message); return; }
  RS_EDITING=null; renderReportSchedules();
}

/* Queue the report immediately, outside its schedule. Reads the snapshot the
   dispatcher would read, so "Send now" can never mail something the generator
   has not actually produced. */
async function sendReportNow(key){
  const {data:s}=await sb.from('report_schedules').select('*').eq('key',key).maybeSingle();
  const {data:snap}=await sb.from('report_snapshots').select('*').eq('report_key',key).maybeSingle();
  if(!s) return;
  const to=(s.recipients||[]);
  if(!to.length){ alert('No recipients set on this report yet.'); return; }
  if(!snap){ alert('This report has never been generated, so there is nothing to send yet.'); return; }
  if(!confirm('Send "'+s.name+'" now to '+to.length+' recipient(s)?\n\n'+to.join('\n')+
              '\n\nData generated: '+new Date(snap.generated_at).toLocaleString())) return;
  const stamp='manual:'+key+':'+Date.now();
  const rows=to.map(e=>({kind:'report', recipient_email:e, subject:snap.subject, body:snap.body, source:stamp+':'+e}));
  const {error}=await sb.from('notify_queue').insert(rows);
  if(error){ alert('Could not queue: '+error.message); return; }
  alert('Queued for '+to.length+' recipient(s). Delivery runs within a minute.');
  renderReportSchedules();
}

function renderReportsTab(){ renderCancelWatch(); renderReportSchedules(); renderSection('reports'); }
`;

const ANCHOR2 = 'function go(tab,push=true){';
if (!html.includes(ANCHOR2)) { console.error('anchor 2 (go) not found'); process.exit(1); }
html = html.replace(ANCHOR2, () => JS + '\n' + ANCHOR2);

/* ---------- 3. Route the tab ------------------------------------------- */
const ANCHOR3 = `  if(tab==='techstack'){ renderTechStack(); }`;
if (!html.includes(ANCHOR3)) { console.error('anchor 3 (go routing) not found'); process.exit(1); }
html = html.replace(ANCHOR3, () => `  if(tab==='reports'){ renderReportsTab(); }\n` + ANCHOR3);

writeFileSync(outFile, html);
console.log(`patched ${inFile} -> ${outFile} (${html.length} bytes)`);
