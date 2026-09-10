-- Job costing: backfill finished jobs + bill→job matcher v2 (2026-09-10)
--
-- WHY. The monthly report showed no job costing because vendor bills never reached jc_actual_costs:
--   1. Bills name customers whose jobs were already finished and paid off, and those jobs were never
--      in jc_jobs, so there was nothing to match them to. (18 jobs, $583,577 of paid invoices.)
--   2. v1 skipped every bill with status 'paid'. 25 of the 69 bills are paid.
--   3. v1 compared the whole PO note to the whole household name; "Mycka. Just past due." and
--      "Doug and Rosanne Drechsel" never clear 0.85 that way.
-- Dry run against live data on 2026-09-10, before applying: 21 bills auto-map on a surname,
-- 9 get a named suggestion, 9 stay unmatched, 0 of the 18 jobs already existed.
--
-- WHAT DOES NOT CHANGE. Auto-matches still need a person to confirm them in the Exceptions queue;
-- only confirmed/override bills become actual costs (jc_sync_actual_from_payable, unchanged).
-- Re-mapping a paid bill leaves its status alone, so jc_payment_gate never fires on it, and
-- jc_refresh_escalations still ignores paid bills.

-- ── 0. Helpers (already live from migration jc_matcher_v2_helpers; repeated so the repo is complete)
create or replace function public.jc_clean_hint(p text) returns text[]
language sql immutable set search_path = public, extensions as $$
  select coalesce(array_agg(t), '{}') from unnest(regexp_split_to_array(
    trim(regexp_replace(regexp_replace(regexp_replace(lower(coalesce(p,'')),
      '[^a-z ]', ' ', 'g'),
      '\m(just|past|due|net|remake|bookcase|rollouts?|slides?|satin|white|touch|up|three|wall|cabinets|hinges|add|on|kitchen|face|uppers|riva|r|ro|grigio|alabaster|btu|ktu|molding|samples|ben|yabra)\M', ' ', 'g'),
      '\s+', ' ', 'g')), ' ')) t
  where length(t) >= 3
$$;

-- Surname(s) of an SM household name: last word of every multi-word "and"/"&" part, plus the final
-- part. "Courtney Fleurantin and Raquel Garnett" → {fleurantin, garnett}; "Tom and Patrice
-- Minichello" → {minichello} — "Tom" alone is never a surname.
create or replace function public.jc_surnames(p text) returns text[]
language plpgsql immutable set search_path = public, extensions as $$
declare parts text[]; w text[]; out text[] := '{}'; i int;
begin
  parts := regexp_split_to_array(trim(regexp_replace(coalesce(p,''), '\s+', ' ', 'g')), '\s+(and|&)\s+', 'i');
  for i in 1 .. coalesce(array_length(parts,1),0) loop
    w := regexp_split_to_array(trim(parts[i]), '\s+');
    if array_length(w,1) >= 2 or i = array_length(parts,1) then
      out := out || lower(w[array_length(w,1)]);
    end if;
  end loop;
  return out;
end $$;

-- ── 1. Finished, paid-off jobs (one per SM contact; a later smaller proposal is an add-on)
-- Rule: paid ≥ $5k, no open invoice, not already tracked, and last paid in 2026 OR named on a bill.
insert into public.jc_jobs (brand, customer_name, address, status, sm_proposal_id, sm_contact_id,
                            contract_total, added_revenue_post_sale, contract_signed, completed_on, notes)
select v.brand, v.name, v.addr, 'complete', v.prop, v.contact, v.total, v.added, v.first_d::date, v.last_d::date,
  'Backfilled 2026-09-10 as a finished, paid-off job so its vendor bills have somewhere to land. '
  || 'contract_total, contract_signed and completed_on are PROXIES from paid ServiceMinder invoices (first '
  || v.first_d || ', last ' || v.last_d || '), not the signed proposal. Included because: ' || v.why || '.'
from (values
  ('BTU','Margaret Segal','4201 Harcourt Rd, Clifton',57475125,11347699,42033.72,0,'2025-12-24','2025-12-24','named on a bill: segal'),
  ('BTU','Barbara Gordon','181 longhill Road unit L3, Little Falls',77171182,13439864,10300.00,0,'2026-02-10','2026-02-10','paid in 2026'),
  ('KTU','Rochelle Coles Defranco','12 Homewood Way, Montclair',51504955,11268511,68106.49,0,'2025-10-09','2025-10-09','named on a bill: defranco'),
  ('KTU','MJ and Brian Day','9 Marquette Road, Montclair',49250834,10549261,59802.85,7124.68,'2025-09-12','2026-02-20','named on a bill: day; add-on proposal 78288640 folded into added_revenue_post_sale'),
  ('KTU','Myrna and Lenny Comerchero','26 Witte Pl, West Orange',81263513,13074469,54648.50,0,'2026-03-05','2026-07-06','paid in 2026'),
  ('KTU','Caitlin and Ted Bohlman','35 Tuscan Rd, Maplewood',77143334,13385474,52219.25,0,'2026-02-07','2026-02-07','paid in 2026'),
  ('KTU','Veronica and Roman Miklaszewski','100 Buckingham Rd, Montclair',78297290,13289649,44311.13,0,'2026-02-20','2026-02-20','named on a bill: miklasewski'),
  ('KTU','Courtney Fleurantin and Raquel Garnett','14 Ward Place, Montclair',57761197,11681546,40996.56,0,'2025-11-13','2025-11-13','named on a bill: fleurantin'),
  ('KTU','Marianne and Bill Sweeney','565 Ridgewood Ave, Glen Ridge',71383309,12561850,36780.27,0,'2026-01-06','2026-01-06','named on a bill: sweeney'),
  ('KTU','Mary Rex and Steve Black','7 Glenridge Pkwy, Montclair',71973785,13038161,27198.38,0,'2026-02-02','2026-02-02','named on a bill: rex'),
  ('KTU','Wesley and Amy Spence','19 Stonehouse Rd, Bloomfield',75057875,13068919,26875.78,0,'2026-01-23','2026-01-23','named on a bill: spence'),
  ('KTU','Stephen & Ankita Coccaro','139 Garrabrant Ave, Bloomfield',48829446,11020755,24792.86,0,'2025-09-02','2026-02-17','paid in 2026'),
  ('KTU','Justin Townsend and Elena Araoz','244 Christopher St, Montclair',71647400,12996335,23696.77,0,'2026-01-09','2026-01-09','named on a bill: townsend'),
  ('KTU','Sam and Laura Rastogi','8 Skyline Dr, North Caldwell',76763809,13077393,18698.78,0,'2026-03-09','2026-03-09','paid in 2026'),
  ('KTU','Tom and Patrice Minichello','10 Smith Manor Blvd, West Orange',81828689,14134574,17557.13,0,'2026-03-12','2026-03-12','paid in 2026'),
  ('KTU','Jennifer Ley','7 Ernst Avenue, Bloomfield',67011013,12242525,12330.81,0,'2025-12-12','2025-12-12','named on a bill: ley'),
  ('KTU','Renee Lenzy','134 Marion Dr, West Orange',77154518,13377810,10608.07,0,'2026-02-12','2026-02-12','paid in 2026'),
  ('KTU','Helen Petriello','81 Liberty Street, Bloomfield',80928669,13682540,5495.16,0,'2026-03-11','2026-03-11','paid in 2026')
) v(brand, name, addr, prop, contact, total, added, first_d, last_d, why)
where not exists (select 1 from public.jc_jobs j where j.sm_contact_id = v.contact);

-- ── 2. Best job per open bill, scored three ways. Pure read; the matcher and any preview share it.
--   s_sur   best trigram similarity of a note token to one of the job's SURNAMES
--   s_any   same against every name word (catches first-name notes: "LOUISE", "PATRICE")
--   anagram same letters, different order ("Dreschel" for Drechsel) — no fuzzystrmatch here
--   sur2    second-best surname similarity across ALL jobs, both brands: the ambiguity test
create or replace function public.jc_match_best()
returns table (payable_id uuid, job_id uuid, job_name text, job_brand text, same_brand boolean,
               s_sur real, s_any real, anagram boolean, score real, sur1 real, sur2 real)
language sql stable set search_path = public, extensions as $$
  with pt as (
    select p.id, p.brand, public.jc_clean_hint(p.po_hint) toks
    from payables p
    where p.po_hint is not null
      and (p.mapping_status = 'unmapped' or (p.mapping_status = 'held' and coalesce(p.mapped_by,'auto') = 'auto'))
  ), s as (
    select pt.id, j.id jid, j.customer_name, j.brand jbrand,
      (pt.brand is null or j.brand = pt.brand) same_brand,
      coalesce((select max(similarity(t, sn)) from unnest(pt.toks) t, unnest(public.jc_surnames(j.customer_name)) sn), 0) s_sur,
      coalesce((select max(similarity(t, w)) from unnest(pt.toks) t,
                unnest(regexp_split_to_array(lower(j.customer_name), '[^a-z]+')) w where length(w) >= 3), 0) s_any,
      exists (select 1 from unnest(pt.toks) t, unnest(public.jc_surnames(j.customer_name)) sn
              where length(t) >= 5 and t <> sn
                and (select string_agg(c, '' order by c) from regexp_split_to_table(t, '') c)
                  = (select string_agg(c, '' order by c) from regexp_split_to_table(sn, '') c)) anagram
    from pt cross join jc_jobs j
    where cardinality(pt.toks) > 0
  ), sc as (
    select *, greatest(s_sur, s_any, case when anagram then 0.8 else 0 end)::real score from s
  ), r as (
    select *,
      row_number() over (partition by id order by score desc, s_sur desc, same_brand desc) rn,
      max(s_sur) over (partition by id) m1,
      nth_value(s_sur, 2) over (partition by id order by s_sur desc
                                rows between unbounded preceding and unbounded following) m2
    from sc where score >= 0.5
  )
  select id, jid, customer_name, jbrand, same_brand, s_sur, s_any, anagram, score, m1, coalesce(m2, 0)::real
  from r where rn = 1
$$;
revoke execute on function public.jc_match_best() from public, anon;

-- ── 3. Matcher v2. Same contract as v1 (returns jsonb, called by jc_nightly hourly via pg_cron).
create or replace function public.jc_run_matcher()
returns jsonb language plpgsql security definer set search_path to 'public', 'extensions' as $$
declare v_changed int; v_nohint int;
begin
  update payables set po_hint = trim(substring(notes from 'PO:\s*([^,;(]+)'))
  where po_hint is null and notes ~ 'PO:';

  -- Paid bills are included now: a finished job's costs are exactly the paid ones.
  -- AUTO only on a unique, same-brand SURNAME match. Everything else is held with the likely job
  -- NAMED in held_reason — job_id stays null on held bills so escalations and the gate are unaffected.
  with elig as (
    select p.id, p.po_hint from payables p
    where p.po_hint is not null
      and (p.mapping_status = 'unmapped' or (p.mapping_status = 'held' and coalesce(p.mapped_by,'auto') = 'auto'))
  ), d as (
    select e.id, e.po_hint, b.*,
      (b.job_id is not null and b.same_brand and b.s_sur >= 0.85 and b.s_sur = b.sur1
       and b.sur1 - b.sur2 >= 0.15) is_auto
    from elig e left join public.jc_match_best() b on b.payable_id = e.id
  ), n as (
    select d.id,
      case when d.is_auto then d.job_id end new_job,
      case when d.is_auto then 'auto_mapped' else 'held' end new_status,
      case when d.job_id is not null then round(d.score::numeric, 2) end new_conf,
      case when d.is_auto then null
           when d.job_id is null then 'no matching job for "' || d.po_hint || '"'
           else 'suggested: ' || d.job_name || ' — ' ||
             case when not d.same_brand then 'that job is ' || d.job_brand || '; the bill is filed under the other brand'
                  when d.s_sur >= 0.85 then 'more than one job has this surname'
                  when d.anagram then 'letters transposed in "' || d.po_hint || '"'
                  when d.s_any >= 0.85 then 'first-name match on "' || d.po_hint || '"'
                  else 'close spelling (' || round(d.score::numeric * 100) || '%) of "' || d.po_hint || '"' end
             || '. Confirm in the Exceptions queue.' end new_reason
    from d
  )
  update payables p set job_id = n.new_job, mapping_status = n.new_status, mapping_confidence = n.new_conf,
    held_reason = n.new_reason, mapped_by = 'auto', mapped_at = now()
  from n
  where n.id = p.id
    and (p.job_id, p.mapping_status, p.held_reason) is distinct from (n.new_job, n.new_status, n.new_reason);
  get diagnostics v_changed = row_count;

  update payables set mapping_status = 'held', held_reason = 'no PO/customer hint on the invoice',
    mapped_by = 'auto', mapped_at = now()
  where mapping_status = 'unmapped' and po_hint is null;
  get diagnostics v_nohint = row_count;

  -- Categories now apply to paid bills too; a mapped bill without one can never become an actual cost.
  update payables set jc_category = 'direct_materials'
  where jc_category is null
    and vendor ~* 'elias|hardware resources|richelieu|msi|m\.?s\.? international|wolf|bertch|northern contours|cabinotch|tile shop|floor & decor|home depot|ideal cabinetry|mti|touch of class|masterbrand|classic rock|rf fager';
  update payables set jc_category = 'contract_labor'
  where jc_category is null and vendor ~* 'orozco|bara|yupa|godoy|checo';
  update payables set jc_category = 'overhead_non_job', mapping_status = 'confirmed',
    mapped_by = 'auto', mapped_at = now(), held_reason = null
  where mapping_status in ('unmapped','held') and vendor ~* 'HFC|Home Franchise';

  return jsonb_build_object(
    'changed', v_changed, 'held_no_hint', v_nohint,
    'awaiting_confirm', (select count(*) from payables where mapping_status = 'auto_mapped'),
    'held_with_suggestion', (select count(*) from payables where mapping_status = 'held' and held_reason like 'suggested:%'),
    'held_no_match', (select count(*) from payables where mapping_status = 'held' and held_reason not like 'suggested:%'),
    'matcher', 'v2');
end $$;
