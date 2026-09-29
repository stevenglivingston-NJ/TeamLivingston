// jc-forecast-sync — builds the SOLD side of job costing, on a schedule, with
// no workstation and no model in the path.
//
// A port of mcp-servers/jc-forecast-sync.py. That script stays as the manual /
// backfill tool (it can target one job and do a dry run); THIS is the scheduled
// path. Keep the categorisation rules below in step with the Python if either
// side changes — they are the one piece of shared logic.
//
// Modes (pg_cron picks; see 20260910b_jc_forecast_sync_schedule.sql):
//   {"mode":"index"}             page ServiceMinder invoices -> contact/proposal cache
//   {"mode":"jobs","batch":10}   refresh the N stalest jobs' forecast lines
//
// Sources:
//   ServiceMinder accepted proposals -> source='sm_proposal'  (what we SOLD)
//   JobTread job cost items          -> source='jobtread'     (the BREAKOUT)

const SUPA = Deno.env.get("SUPABASE_URL")!;
const SRK = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
const SM_BASE = "https://serviceminder.io/api";

// Vendor credentials: a real Edge Function secret wins if one is set; otherwise
// fall back to `dispatch_config`, which is RLS-enabled with ZERO policies, so
// only the service role can read it (the same store the HighLevel PIT uses).
// The fallback exists so this function needs no dashboard step to run.
let JT_KEY = "";
const SM_KEYS: Record<string, string> = { KTU: "", BTU: "" };

async function loadKeys(): Promise<void> {
  JT_KEY = Deno.env.get("JOBTREAD_GRANT_KEY") ?? "";
  SM_KEYS.KTU = Deno.env.get("SM_KEY_KTU") ?? "";
  SM_KEYS.BTU = Deno.env.get("SM_KEY_BTU") ?? "";
  if (JT_KEY && SM_KEYS.KTU && SM_KEYS.BTU) return;

  const rows = await sb(
    `select key, value from dispatch_config ` +
      `where key in ('jc_jobtread_grant_key','jc_sm_key_ktu','jc_sm_key_btu')`,
  );
  for (const r of Array.isArray(rows) ? rows : []) {
    if (r.key === "jc_jobtread_grant_key" && !JT_KEY) JT_KEY = r.value;
    if (r.key === "jc_sm_key_ktu" && !SM_KEYS.KTU) SM_KEYS.KTU = r.value;
    if (r.key === "jc_sm_key_btu" && !SM_KEYS.BTU) SM_KEYS.BTU = r.value;
  }
}

async function sb(sql: string): Promise<any> {
  const r = await fetch(`${SUPA}/rest/v1/rpc/exec_sql`, {
    method: "POST",
    headers: {
      apikey: SRK,
      Authorization: `Bearer ${SRK}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ query: sql }),
  });
  const text = await r.text();
  try {
    return JSON.parse(text);
  } catch {
    throw new Error(`supabase returned non-JSON: ${text.slice(0, 300)}`);
  }
}

// ServiceMinder takes the ApiKey INSIDE the json body (not a header), and
// signals "no such endpoint" with an empty 200 body rather than a 404.
async function sm(brand: string, endpoint: string, body: unknown): Promise<any | null> {
  const payload = { ...(body as object), ApiKey: SM_KEYS[brand] };
  const r = await fetch(`${SM_BASE}/${endpoint}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const text = await r.text();
  if (!text.trim()) return null;
  return JSON.parse(text);
}

async function jt(query: unknown): Promise<any> {
  const r = await fetch("https://api.jobtread.com/pave", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query: { $: { grantKey: JT_KEY }, ...(query as object) } }),
  });
  return JSON.parse(await r.text());
}

/** Quote a value for inline SQL. */
function q(v: unknown): string {
  if (v === null || v === undefined || v === "") return "null";
  if (typeof v === "number") return String(v);
  return "'" + String(v).replaceAll("'", "''") + "'";
}

function num(v: unknown): number | null {
  const n = typeof v === "number" ? v : parseFloat(String(v));
  return Number.isFinite(n) ? n : null;
}

// --- category mapping -------------------------------------------------------
// JCA categories: direct_materials | contract_labor | employee_labor |
//                 sales_commission | other
const LABOR_RX =
  /\b(labor|labour|install(ation)?|shop|demo|deliver|freight|handling|carpent|plumb|electric|tile setter|painting labor)\b/i;
const COMMISSION_RX = /commission/i;
const FEE_RX = /\b(fee|permit|dumpster|general conditions|overhead|contingency)\b/i;

const JT_COSTTYPE_MAP: Record<string, string> = {
  "labor": "contract_labor",
  "materials": "direct_materials",
  "fixture": "direct_materials",
  "installation materials": "direct_materials",
  "labor & materials (inclusive)": "direct_materials",
  "other": "other",
  "fee": "other",
  "selection": "other",
};

function categorize(text: string, costType?: string | null, isInternal = false): string {
  if (costType) {
    const m = JT_COSTTYPE_MAP[costType.trim().toLowerCase()];
    if (m) return m;
  }
  const t = text || "";
  if (COMMISSION_RX.test(t)) return "sales_commission";
  if (LABOR_RX.test(t)) return isInternal ? "employee_labor" : "contract_labor";
  if (FEE_RX.test(t)) return "other";
  return "direct_materials";
}

type Line = {
  description: string;
  category: string;
  qty: number;
  unit_cost: number | null;
  forecasted_cost: number | null;
  amount_charged: number | null;
  cost_code?: string | null;
  source_line_id: string;
};

function linesFromProposal(prop: any): Line[] {
  const out: Line[] = [];
  for (const ln of prop?.ProposalLines ?? []) {
    const part = ln?.Part ?? {};
    const desc = String(ln?.LineDescription ?? part?.Name ?? part?.Description ?? "").trim();
    if (!desc) continue;
    const qty = num(ln?.Quantity) ?? 0;
    const ucost = num(ln?.UnitCost) ?? num(part?.UnitCost);
    const charged = num(ln?.ExtendedTotal);
    const internal = Boolean(ln?.IsInternal);
    out.push({
      description: desc.slice(0, 400),
      category: categorize(desc, null, internal),
      qty: qty || 1,
      unit_cost: ucost,
      forecasted_cost: ucost !== null && qty ? qty * ucost : null,
      amount_charged: internal ? null : charged,
      source_line_id: String(ln?.Id ?? ""),
    });
  }
  return out;
}

function linesFromJt(items: any[]): Line[] {
  const out: Line[] = [];
  for (const it of items) {
    const name = String(it?.name ?? it?.description ?? "").trim();
    if (!name) continue;
    // JobTread treats a NULL quantity as 1 in its own cost/price rollups
    // (vendor-confirmed 2026-09-10: unit cost 100 / unit price 130 with no
    // quantity rolls up as cost 100 and price 130). The fallback must use the
    // same effective quantity -- multiplying by a literal 0 recorded cost 0
    // against the FULL price, flattering gross margin and making the 45% gate
    // less likely to escalate a job that deserves it.
    // NULL and an explicit 0 are NOT the same thing here: null means 1, while a
    // deliberate 0 zeroes both cost and price. `qty || 1` conflated them, so an
    // item zeroed on purpose still carried a full unit of cost.
    const rawQty = num(it?.quantity);
    const effQty = rawQty === null ? 1 : rawQty;
    const ucost = num(it?.unitCost);
    const cost = num(it?.cost);
    out.push({
      description: name.slice(0, 400),
      category: categorize(name, it?.costType?.name),
      qty: effQty,
      unit_cost: ucost,
      forecasted_cost: cost !== null ? cost : (ucost !== null ? effQty * ucost : null),
      amount_charged: num(it?.price),
      cost_code: it?.costCode?.name ?? null,
      source_line_id: String(it?.id ?? ""),
    });
  }
  return out;
}

async function insertLines(jobId: string, source: string, lines: Line[]): Promise<number> {
  if (!lines.length) return 0;
  const vals = lines.map((l) =>
    `(${q(jobId)},${q(l.description)},${q(l.category)},${q(l.qty)},${q(l.unit_cost)},` +
    `${q(l.forecasted_cost)},${q(l.amount_charged)},${q(l.cost_code ?? null)},${q(source)},${q(l.source_line_id)})`
  );
  await sb(
    `delete from jc_forecast_lines where job_id=${q(jobId)} and source=${q(source)};\n` +
      `insert into jc_forecast_lines (job_id,description,category,qty,unit_cost,` +
      `forecasted_cost,amount_charged,cost_code,source,source_line_id) values\n${vals.join(",\n")};`,
  );
  return vals.length;
}

// --- mode: index ------------------------------------------------------------
// Invoices carry ProposalId on ~100% of rows; proposals themselves are only
// queryable while OPEN, so accepted proposals are discovered invoice-first.
async function runIndex(): Promise<Record<string, number>> {
  const counts: Record<string, number> = {};
  for (const brand of ["KTU", "BTU"]) {
    if (!SM_KEYS[brand]) continue;
    const pairs = new Set<string>();
    let skip = 0;
    const take = 200;
    while (true) {
      const res = await sm(brand, "invoice/query", { FromDate: "2025-01-01", Skip: skip, Take: take });
      const invs = res?.Invoices ?? [];
      for (const inv of invs) {
        if (inv?.ContactId && inv?.ProposalId) {
          pairs.add(`${Number(inv.ContactId)}:${Number(inv.ProposalId)}`);
        }
      }
      if (invs.length < take) break;
      skip += take;
      if (skip > 20000) break; // hard stop; the window is 2025-01-01 onward
    }
    if (pairs.size) {
      const vals = [...pairs].map((p) => {
        const [c, pid] = p.split(":");
        return `(${q(brand)},${c},${pid})`;
      });
      // Chunked so one statement never gets unwieldy.
      for (let i = 0; i < vals.length; i += 500) {
        await sb(
          `insert into jc_sm_proposal_index (brand, sm_contact_id, proposal_id) values ` +
            vals.slice(i, i + 500).join(",") +
            ` on conflict (brand, sm_contact_id, proposal_id) do update set seen_at = now();`,
        );
      }
    }
    counts[brand] = pairs.size;
  }
  return counts;
}

// --- mode: jobs -------------------------------------------------------------
async function runJobs(batch: number) {
  const jobs = await sb(
    `select id, brand, customer_name, sm_contact_id, sm_proposal_id, jobtread_job_id ` +
      `from jc_jobs order by forecast_synced_at asc nulls first limit ${batch}`,
  );
  if (!Array.isArray(jobs)) throw new Error(`jc_jobs read failed: ${JSON.stringify(jobs).slice(0, 200)}`);

  let smTotal = 0, jtTotal = 0;
  const errors: string[] = [];

  for (const j of jobs) {
    // --- ServiceMinder sold lines
    let smLines: Line[] = [];
    let chosen: number | null = null;
    if (j.sm_contact_id) {
      const idx = await sb(
        `select proposal_id from jc_sm_proposal_index where brand=${q(j.brand)} ` +
          `and sm_contact_id=${Number(j.sm_contact_id)} order by proposal_id`,
      );
      for (const row of Array.isArray(idx) ? idx : []) {
        try {
          const prop = await sm(j.brand, "proposal/details", { Id: Number(row.proposal_id) });
          if (!prop) continue;
          const got = linesFromProposal(prop);
          if (got.length) {
            smLines = smLines.concat(got);
            chosen = chosen ?? Number(row.proposal_id);
          }
        } catch (e) {
          errors.push(`SM ${j.customer_name}: ${String(e).slice(0, 120)}`);
        }
      }
    }
    if (smLines.length) {
      smTotal += await insertLines(j.id, "sm_proposal", smLines);
      if (chosen && !j.sm_proposal_id) {
        await sb(`update jc_jobs set sm_proposal_id=${chosen} where id=${q(j.id)}`);
      }
    }

    // --- JobTread breakout
    if (j.jobtread_job_id) {
      try {
        const res = await jt({
          job: {
            $: { id: j.jobtread_job_id },
            id: {}, name: {},
            costItems: {
              $: { size: 100 },
              nodes: {
                id: {}, name: {}, description: {}, quantity: {}, unitCost: {},
                unitPrice: {}, cost: {}, price: {},
                costType: { name: {} }, costCode: { name: {} }, costGroup: { name: {} },
              },
            },
          },
        });
        const items = res?.job?.costItems?.nodes ?? [];
        const jtLines = linesFromJt(items);
        if (jtLines.length) jtTotal += await insertLines(j.id, "jobtread", jtLines);
      } catch (e) {
        errors.push(`JT ${j.customer_name}: ${String(e).slice(0, 120)}`);
      }
    }

    await sb(`update jc_jobs set forecast_synced_at=now() where id=${q(j.id)}`);
  }

  // Placeholder category rows are superseded once real lines land. NOTE: SM
  // proposal lines carry PRICE but (on KTU) almost never UnitCost, so they do
  // NOT supersede the estimate rows -- the two are complementary. Only drop an
  // estimate row where real COSTED lines exist for that job.
  await sb(
    `delete from jc_forecast_lines f where f.source='foreman_estimate' ` +
      `and exists (select 1 from jc_forecast_lines r where r.job_id=f.job_id ` +
      `and r.source in ('sm_proposal','jobtread') and coalesce(r.forecasted_cost,0) > 0)`,
  );

  return { jobs_done: jobs.length, sm_lines: smTotal, jt_lines: jtTotal, errors };
}

Deno.serve(async (req) => {
  // Same shared-secret shape the other scheduled functions use.
  const secretRow = await sb(`select value from dispatch_config where key='cron_secret'`);
  const expected = Array.isArray(secretRow) ? secretRow[0]?.value : null;
  if (!expected || req.headers.get("x-cron-secret") !== expected) {
    return new Response(JSON.stringify({ error: "unauthorized" }), {
      status: 401,
      headers: { "Content-Type": "application/json" },
    });
  }

  let body: any = {};
  try {
    body = await req.json();
  } catch { /* empty body is fine */ }
  const mode = body?.mode === "index" ? "index" : "jobs";
  const batch = Math.min(Math.max(Number(body?.batch ?? 10), 1), 48);

  await loadKeys();
  if (!SM_KEYS.KTU && !SM_KEYS.BTU && !JT_KEY) {
    const msg = "no vendor credentials: set SM_KEY_KTU / SM_KEY_BTU / JOBTREAD_GRANT_KEY " +
      "as function secrets, or jc_sm_key_ktu / jc_sm_key_btu / jc_jobtread_grant_key in dispatch_config";
    await sb(`insert into jc_sync_runs (mode, ok, detail) values (${q(mode)}, false, ${q(JSON.stringify({ error: msg }))}::jsonb)`);
    return Response.json({ ok: false, mode, error: msg }, { status: 500 });
  }

  try {
    if (mode === "index") {
      const counts = await runIndex();
      await sb(
        `insert into jc_sync_runs (mode, ok, detail) values ('index', true, ${q(JSON.stringify(counts))}::jsonb)`,
      );
      return Response.json({ ok: true, mode, counts });
    }

    const r = await runJobs(batch);
    await sb(
      `insert into jc_sync_runs (mode, ok, jobs_done, sm_lines, jt_lines, detail) values ` +
        `('jobs', ${r.errors.length ? "false" : "true"}, ${r.jobs_done}, ${r.sm_lines}, ${r.jt_lines}, ` +
        `${q(JSON.stringify({ errors: r.errors }))}::jsonb)`,
    );
    return Response.json({ ok: true, mode, ...r });
  } catch (e) {
    const msg = String(e).slice(0, 500);
    await sb(
      `insert into jc_sync_runs (mode, ok, detail) values (${q(mode)}, false, ${q(JSON.stringify({ error: msg }))}::jsonb)`,
    );
    return Response.json({ ok: false, mode, error: msg }, { status: 500 });
  }
});
