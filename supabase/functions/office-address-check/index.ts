import "jsr:@supabase/functions-js/edge-runtime.d.ts";

/**
 * office-address-check — hourly scan for the "1285 Broad Street" bug: upcoming
 * ServiceMinder appointments whose contact address is the office, not the
 * customer's home. Driven by pg_cron (x-cron-secret from dispatch_config), same
 * as appointments-sync. Replaces the Claude routine "KTU/BTU — office-address
 * appointment check" (12 sessions a day, each able to stall on a permission
 * prompt or the account usage limit).
 *
 * Detect only — it never writes to ServiceMinder. The routine's write-back step
 * only ran when connectors were attached, which a scheduled run never has, so in
 * practice it was report-only too. For KTU the alert carries whatever HighLevel
 * holds for that phone number, so whoever fixes the record has the lead.
 *
 * Alerts once per (brand, contact, appointment time) via notify_queue
 * (dispatch-notify delivers to Slack + email); office_address_alerts remembers
 * what has already been sent, so a moved appointment alerts again.
 */

const SUPA = Deno.env.get("SUPABASE_URL")!;
const SRK = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
const SM_BASE = "https://serviceminder.io/api";
const HL_LOCATION_KTU = "nHLCxHPidnhV1NFzRtZZ";
const RECIPIENT = "slivingston@kitchentuneup.com";
const svc = {
  "Content-Type": "application/json",
  apikey: SRK,
  authorization: `Bearer ${SRK}`,
  "Content-Profile": "public",
  "Accept-Profile": "public",
};

const OFFICE = /1285\s*broad/i;
const TEST_NAMES = /^(test fallback 1|test integration|test 03|test test|test lead|ktu sales team|home show)$/i;
const STATUS: Record<number, string> = { 0: "Tentative", 1: "Scheduled", 2: "Scheduled", 3: "Completed", 4: "Cancelled" };

const secrets: Record<string, string> = {};
async function loadSecrets() {
  const r = await fetch(`${SUPA}/rest/v1/app_secrets?select=key,value&key=in.(SM_KEY_KTU,SM_KEY_BTU,HL_TOKEN_KTU)`, { headers: svc });
  if (r.ok) for (const row of (await r.json()) as { key: string; value: string }[]) secrets[row.key] = row.value;
  // HL_TOKEN_KTU is the live KTU token (app_secrets.GHL_PIT_KTU returned 401 on 2026-09-30).
  for (const k of ["SM_KEY_KTU", "SM_KEY_BTU", "HL_TOKEN_KTU"]) secrets[k] = Deno.env.get(k) ?? secrets[k] ?? "";
}

const fmt = (d: Date) => `${String(d.getUTCMonth() + 1).padStart(2, "0")}/${String(d.getUTCDate()).padStart(2, "0")}/${d.getUTCFullYear()}`;

async function smQuery(brand: string, from: string, thru: string): Promise<any[]> {
  const out: any[] = [];
  for (let skip = 0; ; skip += 500) {
    const r = await fetch(`${SM_BASE}/appointments/query`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ApiKey: secrets[`SM_KEY_${brand}`], FromDate: from, ThroughDate: thru, IncludeContact: true, Skip: skip, Take: 500 }),
    });
    const text = await r.text();
    if (!text) throw new Error(`${brand} appointments/query: empty body, status ${r.status}`);
    const d = JSON.parse(text);
    if (d?.ResultCode && d.ResultCode !== 0) throw new Error(`${brand} appointments/query: ${d.Message}`);
    const batch = d?.Appointments ?? [];
    out.push(...batch);
    if (batch.length < 500) return out;
  }
}

// What HighLevel (KTU location only) has for this phone. The real street often
// sits in `address1` when SM's copy was stomped to the office.
async function hlLookup(phone: string): Promise<string> {
  const digits = (phone || "").replace(/\D/g, "").slice(-10);
  if (digits.length !== 10 || !secrets.HL_TOKEN_KTU) return "no HighLevel lookup (no phone)";
  const r = await fetch(`https://services.leadconnectorhq.com/contacts/?locationId=${HL_LOCATION_KTU}&query=${digits}&limit=3`, {
    headers: { Authorization: `Bearer ${secrets.HL_TOKEN_KTU}`, Version: "2021-07-28" },
  });
  if (!r.ok) return `HighLevel lookup failed (${r.status})`;
  const cs = ((await r.json())?.contacts ?? []) as any[];
  if (!cs.length) return "not found in HighLevel";
  const c = cs[0];
  const addr = [c.address1, c.city, c.state, c.postalCode].filter(Boolean).join(", ");
  if (!c.address1 || OFFICE.test(c.address1)) return `HighLevel has no usable street${addr ? ` (only: ${addr})` : ""} — call the customer`;
  return `HighLevel address: ${addr}`;
}

Deno.serve(async (req) => {
  const cfg = await fetch(`${SUPA}/rest/v1/dispatch_config?key=eq.cron_secret&select=value`, { headers: svc });
  const want = cfg.ok ? (await cfg.json())?.[0]?.value : null;
  if (!want || req.headers.get("x-cron-secret") !== want) return new Response(JSON.stringify({ error: "unauthorized" }), { status: 401 });

  await loadSecrets();
  const now = new Date();
  const from = fmt(now), thru = fmt(new Date(now.getTime() + 365 * 864e5));
  const result: Record<string, unknown> = {};
  const fresh: { brand: string; contact_id: number; appt_at: string; line: string }[] = [];
  let ok = true;

  const seenRes = await fetch(`${SUPA}/rest/v1/office_address_alerts?select=brand,contact_id,appt_at`, { headers: svc });
  const seen = new Set(((seenRes.ok ? await seenRes.json() : []) as any[]).map((s) => `${s.brand}|${s.contact_id}|${s.appt_at}`));

  for (const brand of ["KTU", "BTU"]) {
    if (!secrets[`SM_KEY_${brand}`]) { result[brand] = { error: "no SM key" }; ok = false; continue; }
    try {
      const appts = await smQuery(brand, from, thru);
      const hits = appts.filter((a) => {
        const c = a?.Contact ?? {};
        return OFFICE.test(c.Address1 ?? "") && !TEST_NAMES.test((c.Name ?? "").trim()) && a.Status !== 4;
      });
      for (const a of hits) {
        const key = `${brand}|${a.ContactId}|${a.DateTime}`;
        if (seen.has(key)) continue;
        const c = a.Contact ?? {};
        const hl = brand === "KTU" ? await hlLookup(c.Phone) : "BTU — not recoverable from HighLevel (KTU location only); call the customer";
        fresh.push({
          brand, contact_id: a.ContactId, appt_at: a.DateTime,
          line: `• ${brand} ${c.Name} (SM contact ${a.ContactId}) — ${a.ServiceName ?? "appointment"} ${a.DateTime}, ${STATUS[a.Status] ?? a.Status}, phone ${c.Phone || "none"}. ${hl}.`,
        });
      }
      result[brand] = { upcoming: appts.length, office_address: hits.length };
    } catch (e) {
      result[brand] = { error: String((e as Error)?.message ?? e).slice(0, 300) };
      ok = false;
    }
  }

  if (fresh.length) {
    const body = `Upcoming appointments carrying the office address (1285 Broad St) instead of the customer's:\n\n` +
      fresh.map((f) => f.line).join("\n") +
      `\n\nFix in ServiceMinder (contacts/addupdate with IdSearch, or the contact screen). Each hit alerts once; it re-alerts if the appointment moves.`;
    const q = await fetch(`${SUPA}/rest/v1/notify_queue`, {
      method: "POST", headers: svc,
      body: JSON.stringify({ kind: "office_address", recipient_email: RECIPIENT, subject: `Office address on ${fresh.length} upcoming appointment(s)`, body, source: "office-address-check", status: "pending" }),
    });
    if (!q.ok) { ok = false; result.notify_error = `${q.status} ${(await q.text()).slice(0, 200)}`; }
    else {
      await fetch(`${SUPA}/rest/v1/office_address_alerts?on_conflict=brand,contact_id,appt_at`, {
        method: "POST", headers: { ...svc, Prefer: "resolution=ignore-duplicates,return=minimal" },
        body: JSON.stringify(fresh.map(({ brand, contact_id, appt_at }) => ({ brand, contact_id, appt_at }))),
      });
    }
  }
  result.new_alerts = fresh.length;

  return new Response(JSON.stringify({ ok, ran_at: now.toISOString(), result }), {
    status: ok ? 200 : 500, headers: { "Content-Type": "application/json" },
  });
});
