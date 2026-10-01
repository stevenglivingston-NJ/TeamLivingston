import "jsr:@supabase/functions-js/edge-runtime.d.ts";

/**
 * appointments-sync — daily refresh of public.appointments (intranet Appointments
 * tab + Home snapshot) from ServiceMinder, both brands. Driven by pg_cron
 * (net.http_post + x-cron-secret from dispatch_config), same mechanism as
 * sm-agent-sync. Deliberately NOT a Claude Code Routine: a scheduled Claude
 * session runs in Auto mode and can be stopped by a permission prompt nobody is
 * present to answer. This runs server-side with no session at all.
 *
 * Port of TeamLivingston mcp-servers/appointments-sync.py (2026-09-28 audit):
 *  - appointments/query today-120d .. today+120d, IncludeContact, paged
 *  - drops test/internal rows
 *  - upserts on appointment_id (never writes human next_action / next_action_by)
 *  - rpc appointments_refresh_derived(): proposal_* from `proposals`, notes from
 *    `appt_followups`, re-bucket every row against today ET
 */

const SUPA = Deno.env.get("SUPABASE_URL")!;
const SRK = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
const SM_BASE = "https://serviceminder.io/api";
const svc = {
  "Content-Type": "application/json",
  apikey: SRK,
  authorization: `Bearer ${SRK}`,
  "Content-Profile": "public",
  "Accept-Profile": "public",
};

const SM_KEYS: Record<string, string> = { KTU: "", BTU: "" };
async function loadSmKeys() {
  SM_KEYS.KTU = Deno.env.get("SM_KEY_KTU") ?? "";
  SM_KEYS.BTU = Deno.env.get("SM_KEY_BTU") ?? "";
  if (SM_KEYS.KTU && SM_KEYS.BTU) return;
  const r = await fetch(`${SUPA}/rest/v1/app_secrets?select=key,value&key=in.(SM_KEY_KTU,SM_KEY_BTU)`, { headers: svc });
  if (!r.ok) return;
  for (const row of (await r.json()) as { key: string; value: string }[]) {
    if (row.key === "SM_KEY_KTU" && !SM_KEYS.KTU) SM_KEYS.KTU = row.value;
    if (row.key === "SM_KEY_BTU" && !SM_KEYS.BTU) SM_KEYS.BTU = row.value;
  }
}

async function smCall(brand: string, endpoint: string, body: Record<string, unknown>) {
  const r = await fetch(`${SM_BASE}/${endpoint}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...body, ApiKey: SM_KEYS[brand] }),
  });
  const text = await r.text();
  if (!text) throw new Error(`${brand} ${endpoint}: empty body, status ${r.status}`);
  return JSON.parse(text);
}

const TEST_NAME = /\btest\b|testfallback|holding time slot|steven livingston/i;
const INTERNAL_EMAIL = /@(kitchentuneup|bathtune-up|bathtuneup)\.com$/i;
const isTest = (c: any) => TEST_NAME.test(c?.Name ?? "") || INTERNAL_EMAIL.test(c?.Email ?? "");

// Offset (minutes) of America/New_York from UTC at a given instant.
function etOffsetMin(d: Date): number {
  const p = Object.fromEntries(new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York", hour12: false, year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit",
  }).formatToParts(d).map((x) => [x.type, x.value]));
  const asUtc = Date.UTC(+p.year, +p.month - 1, +p.day, +p.hour % 24, +p.minute, +p.second);
  return (asUtc - d.getTime()) / 60000;
}
// "12/17/2026 12:00:00 PM" in Eastern time -> ISO UTC
function parseEt(s?: string): string | null {
  const m = /^(\d{1,2})\/(\d{1,2})\/(\d{4}) (\d{1,2}):(\d{2}):(\d{2}) (AM|PM)$/i.exec((s ?? "").trim());
  if (!m) return null;
  let h = +m[4] % 12; if (m[7].toUpperCase() === "PM") h += 12;
  const guess = Date.UTC(+m[3], +m[1] - 1, +m[2], h, +m[5], +m[6]);
  let t = guess - etOffsetMin(new Date(guess)) * 60000;
  t = guess - etOffsetMin(new Date(t)) * 60000; // settle across DST edges
  return new Date(t).toISOString();
}
const fmt = (d: Date) => `${String(d.getUTCMonth() + 1).padStart(2, "0")}/${String(d.getUTCDate()).padStart(2, "0")}/${d.getUTCFullYear()}`;
const STATUS: Record<number, string> = { 0: "scheduled", 1: "scheduled", 2: "scheduled", 3: "completed", 4: "cancelled" };

Deno.serve(async (req) => {
  const presented = req.headers.get("x-cron-secret") || "";
  const cfg = await fetch(`${SUPA}/rest/v1/dispatch_config?key=eq.cron_secret&select=value`, { headers: svc });
  const want = cfg.ok ? (await cfg.json())?.[0]?.value : null;
  if (!want || presented !== want) return new Response(JSON.stringify({ error: "unauthorized" }), { status: 401 });

  const days = Number(new URL(req.url).searchParams.get("days") ?? 120);
  await loadSmKeys();
  const now = new Date();
  const from = fmt(new Date(now.getTime() - days * 864e5));
  const thru = fmt(new Date(now.getTime() + days * 864e5));
  const today = new Date(now.getTime() + etOffsetMin(now) * 60000).toISOString().slice(0, 10);
  const result: Record<string, unknown> = {};
  let ok = true;

  for (const brand of ["KTU", "BTU"]) {
    if (!SM_KEYS[brand]) { result[brand] = { error: "no SM key configured" }; ok = false; continue; }
    try {
      const raw: any[] = [];
      for (let skip = 0; ; skip += 500) {
        const d = await smCall(brand, "appointments/query", { FromDate: from, ThroughDate: thru, IncludeContact: true, Skip: skip, Take: 500 });
        if (d?.ResultCode && d.ResultCode !== 0) throw new Error(`appointments/query: ${d.Message}`);
        const batch = d?.Appointments ?? [];
        raw.push(...batch);
        if (batch.length < 500) break;
      }
      const kept = raw.filter((r) => r?.AppointmentId && !isTest(r.Contact)).map((r) => ({ r, at: parseEt(r.DateTime) })).filter((x) => x.at);
      const laterLive = new Map<number, string>();
      for (const { r, at } of kept) {
        if ((STATUS[r.Status] ?? "scheduled") !== "cancelled") {
          const prev = laterLive.get(r.ContactId);
          if (!prev || at! > prev) laterLive.set(r.ContactId, at!);
        }
      }
      const rows = kept.map(({ r, at }) => {
        const c = r.Contact ?? {};
        const status = STATUS[r.Status] ?? "scheduled";
        const later = laterLive.get(r.ContactId);
        return {
          appointment_id: r.AppointmentId, brand, contact_id: r.ContactId ?? null,
          customer_name: c.Name ?? null, customer_phone: c.Phone || null, customer_email: c.Email || null,
          address: [c.Address1, c.City, c.State, c.Zip].filter(Boolean).join(", ") || null,
          service: r.ServiceName ?? null, service_agent: r.ServiceAgentName ?? null, appt_at: at,
          status, cancel_segment: status === "cancelled" ? (later && later > at! ? "follow_up" : "unknown") : null,
          proposal_id: r.ProposalId || null, scan_date: today,
          source: "serviceminder (appointments-sync edge fn)", updated_at: new Date().toISOString(),
        };
      });
      for (let i = 0; i < rows.length; i += 200) {
        const up = await fetch(`${SUPA}/rest/v1/appointments?on_conflict=appointment_id`, {
          method: "POST", headers: { ...svc, Prefer: "resolution=merge-duplicates,return=minimal" },
          body: JSON.stringify(rows.slice(i, i + 200)),
        });
        if (!up.ok) throw new Error(`upsert ${up.status}: ${(await up.text()).slice(0, 300)}`);
      }
      result[brand] = { pulled: raw.length, upserted: rows.length };
      if (!rows.length) ok = false;
    } catch (e) {
      result[brand] = { error: String((e as Error)?.message ?? e).slice(0, 300) };
      ok = false;
    }
  }

  const rpc = await fetch(`${SUPA}/rest/v1/rpc/appointments_refresh_derived`, { method: "POST", headers: svc, body: "{}" });
  result.derived = rpc.ok ? await rpc.json() : { error: `${rpc.status} ${(await rpc.text()).slice(0, 200)}` };
  if (!rpc.ok) ok = false;

  return new Response(JSON.stringify({ ok, ran_at: now.toISOString(), result }), {
    status: ok ? 200 : 500, headers: { "Content-Type": "application/json" },
  });
});
