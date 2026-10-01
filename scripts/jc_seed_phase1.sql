-- Job Costing Phase 1 seed — run once (idempotent-ish: guarded by not-exists).
-- 1) jc_jobs from the latest foreman_board scan (SM contact + JT ids + contract totals).
insert into jc_jobs (brand, customer_name, address, service_type, status,
                     sm_contact_id, jobtread_job_id, jobtread_number,
                     contract_total, contract_signed, install_start, commission_pct, notes)
select
  fields->>'brand',
  trim(split_part(fields->>'project',' - ',1)),
  nullif(trim(substr(fields->>'project', position(' - ' in fields->>'project')+3)),''),
  fields->>'service_type',
  case when coalesce(fields->>'install_started','false')='true' then 'in_progress' else 'approved' end,
  nullif(fields->>'sm_contact_id','')::bigint,
  fields->>'jobtread_job_id',
  fields->>'jobtread_number',
  nullif(fields->>'contract_total','')::numeric,
  nullif(fields->>'contract_signed','')::date,
  nullif(fields->>'install_date','')::date,
  0.08,
  'Seeded from foreman_board '||(fields->>'scan_date')
from intranet_records fb
where section='foreman_board'
  and fields->>'scan_date' = (select max(fields->>'scan_date') from intranet_records where section='foreman_board')
  and position(' - ' in fields->>'project') > 0
  and not exists (select 1 from jc_jobs j where j.jobtread_job_id = fb.fields->>'jobtread_job_id'
                                            and j.jobtread_job_id is not null);

-- 2) sm_proposal_id from project_schedule via contact id (one per contact).
update jc_jobs j set sm_proposal_id = ps.proposal_id
from (select distinct on (contact_id) contact_id, proposal_id
      from project_schedule where proposal_id is not null order by contact_id, synced_at desc) ps
where ps.contact_id = j.sm_contact_id and j.sm_proposal_id is null;

-- 3) Forecast lines (category-level, labeled foreman_estimate) per job.
with fb as (
  select fields->>'jobtread_job_id' jt,
         nullif(fields->>'contract_total','')::numeric contract,
         nullif(fields->>'estimated_cost','')::numeric est_total,
         nullif(fields->>'est_labor_cost','')::numeric est_labor,
         nullif(fields->>'est_labor_hours','')::numeric est_hours
  from intranet_records
  where section='foreman_board'
    and fields->>'scan_date' = (select max(fields->>'scan_date') from intranet_records where section='foreman_board')
)
insert into jc_forecast_lines (job_id, description, category, qty, unit_cost, forecasted_cost, source)
select j.id, l.descr, l.cat, 1, l.amt, l.amt, 'foreman_estimate'
from jc_jobs j
join fb on fb.jt = j.jobtread_job_id
cross join lateral (values
  ('Direct materials (Foreman COGS estimate: catalog UnitCost + 30%-of-sell anchor)',
   'direct_materials',
   greatest(coalesce(fb.est_total,0) - coalesce(fb.est_labor,0) - round(coalesce(fb.contract,0)*j.commission_pct,2), 0)),
  ('Install labor estimate ('||coalesce(fb.est_hours::text,'?')||'h @ $100/hr per Foreman)',
   'contract_labor', coalesce(fb.est_labor,0)),
  ('Sales commission @ '||round(j.commission_pct*100)||'% of contract',
   'sales_commission', round(coalesce(fb.contract,0)*j.commission_pct,2))
) l(descr,cat,amt)
where l.amt > 0
  and not exists (select 1 from jc_forecast_lines f where f.job_id=j.id and f.source='foreman_estimate');

-- 4) po_hint from the notes the parser already writes ("PO: Rivera", "PO: Mycka Bookcase").
update payables set po_hint = trim(substring(notes from 'PO:\s*([^,;(]+)'))
where po_hint is null and notes ~ 'PO:';

-- 5) Retro-map unpaid payables: trigram match po_hint -> customer_name (brand-scoped).
with cand as (
  select p.id pid, j.id jid, j.customer_name,
         word_similarity(lower(p.po_hint), lower(j.customer_name)) sim
  from payables p
  join jc_jobs j on j.brand = p.brand
  where p.status <> 'paid' and p.mapping_status = 'unmapped' and p.po_hint is not null
    and word_similarity(lower(p.po_hint), lower(j.customer_name)) >= 0.5
), ranked as (
  select *, row_number() over (partition by pid order by sim desc) rn,
         count(*)  over (partition by pid) n,
         max(sim)  over (partition by pid) topsim,
         lead(sim) over (partition by pid order by sim desc) sim2
  from cand
)
update payables p set
  job_id = case when r.topsim >= 0.85 and (r.n = 1 or r.topsim - coalesce(r.sim2,0) >= 0.15) then r.jid end,
  mapping_status = case when r.topsim >= 0.85 and (r.n = 1 or r.topsim - coalesce(r.sim2,0) >= 0.15)
                        then 'auto_mapped' else 'held' end,
  mapping_confidence = round(r.topsim::numeric, 2),
  held_reason = case when r.topsim >= 0.85 and (r.n = 1 or r.topsim - coalesce(r.sim2,0) >= 0.15) then null
                     else 'ambiguous ('||r.n||' candidate jobs for "'||p.po_hint||'")' end,
  mapped_by = 'auto', mapped_at = now()
from ranked r
where r.pid = p.id and r.rn = 1;

-- 6) Whatever found no candidate at all -> held / no matching job.
update payables set mapping_status='held',
  held_reason = case when po_hint is null then 'no PO/customer hint on the invoice'
                     else 'no matching job for "'||po_hint||'"' end,
  mapped_by='auto', mapped_at=now()
where status <> 'paid' and mapping_status='unmapped';

-- 7) Category defaults by vendor (materials vendors vs labor).
update payables set jc_category = 'direct_materials'
where jc_category is null and status <> 'paid'
  and (vendor ~* 'elias|hardware resources|richelieu|msi|m\.?s\.? international|wolf|bertch|northern contours|cabinotch|tile shop|floor & decor|home depot|ideal cabinetry|mti|touch of class|masterbrand');
update payables set jc_category = 'contract_labor'
where jc_category is null and status <> 'paid'
  and (vendor ~* 'orozco|bara|yupa|godoy|checo');

-- 8) Known non-job overhead (franchise fees etc.) — releasable without a job map.
update payables set jc_category='overhead_non_job', mapping_status='confirmed',
  mapped_by='auto', mapped_at=now(), held_reason=null
where status<>'paid' and vendor ~* 'HFC|Home Franchise';
