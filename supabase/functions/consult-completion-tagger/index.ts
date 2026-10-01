// consult-completion-tagger v2 (2026-09-28): when a CONSULTATION is marked Completed in
// ServiceMinder, tag the matching HighLevel contact `appointment-completed` so a HighLevel workflow
// can text the "reply 1-5" survey, and log the ServiceMinder ids so consult-sms-reply can tie the
// client's text reply back to the right appointment.
//
// Why v2: v1 read HighLevel's calendars, waited 12h after the event, and stamped HighLevel's event
// id where the ServiceMinder appointment id belongs (consult-feedback rejects it). It never ran --
// HL_TOKEN_* were empty -- so consult_completion_log was still empty when this replaced it.
// ServiceMinder is the appointment system of record and "Completed" is the real signal.
//
// Runs every 15 min (pg_cron job consult-completion-tagger, x-cron-secret gate unchanged).
// consult_survey_config.tagger_mode:
//   off      -> do nothing
//   dry_run  -> (default) read ServiceMinder + HighLevel, report what WOULD be tagged, write nothing
//   live     -> tag + log
// so deploying this never texts a client until the owner has built the HighLevel workflows.
//
// Per completed consult (not yet logged): find the HighLevel contact by phone, then email
// (lookup only -- never creates a contact, which could fire new-lead workflows at a past client),
// clear last round's survey tags, stamp last_consult_* fields (best effort), then remove+add
// `appointment-completed` so the tag-added trigger fires even for a repeat client.
import { createClient } from "npm:@supabase/supabase-js@2";

const sb = createClient(Deno.env.get("SUPABASE_URL")!, Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!);

const HL_BASE = "https://services.leadconnectorhq.com";
const HL_VERSION = "2021-07-28";
const SM = "https://serviceminder.io/api";
const BRANDS = ["KTU", "BTU"] as const;
const LOOKBACK_DAYS = 3;            // appointments dated within this window are considered
const FRESH_HOURS = 36;             // ...and only ones that took place in the last 36h get texted
const MAX_ATTEMPTS = 3;
const SURVEY_TAGS_TO_CLEAR = ["consult-survey-sent", "consult-survey-done", "consult-promoter", "consult-neutral", "consult-detractor"];

type Secrets = Record<string, string>;

async function loadSecrets(): Promise<Secrets> {
  const [{ data: a }, { data: d }, { data: c }] = await Promise.all([
    sb.from("app_secrets").select("key,value"),
    sb.from("dispatch_config").select("key,value"),
    sb.from("consult_survey_config").select("key,value"),
  ]);
  return Object.fromEntries([...(d ?? []), ...(a ?? []), ...(c ?? [])].map((r) => [r.key, r.value]));
}

// HL_TOKEN_* (the documented slot) first, then the older GHL_PIT_* rows.
const hlToken = (s: Secrets, b: string) => s[`HL_TOKEN_${b}`] || s[`GHL_PIT_${b}`] || "";

async function sm(key: string, ep: string, body: Record<string, unknown>) {
  const r = await fetch(`${SM}/${ep}`, { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...body, ApiKey: key }) });
  const t = await r.text();
  if (!r.ok || !t) throw new Error(`ServiceMinder ${ep} ${r.status}${t ? "" : " (empty)"}`);
  return JSON.parse(t);
}

async function hl(token: string, path: string, opts: RequestInit = {}) {
  const r = await fetch(`${HL_BASE}${path}`, { ...opts,
    headers: { Authorization: `Bearer ${token}`, Version: HL_VERSION, "Content-Type": "application/json", Accept: "application/json", ...(opts.headers ?? {}) } });
  const t = await r.text();
  if (!r.ok) throw new Error(`HL ${opts.method ?? "GET"} ${path.split("?")[0]} -> ${r.status}: ${t.slice(0, 200)}`);
  try { return t ? JSON.parse(t) : null; } catch { return null; }
}

const digits = (s?: string | null) => String(s ?? "").replace(/\D/g, "");
const e164 = (s?: string | null) => { const d = digits(s); return d.length === 10 ? `+1${d}` : d.length === 11 && d[0] === "1" ? `+${d}` : ""; };
const isConsult = (a: Record<string, any>) =>
  [a.ServiceName, ...(a.Slots ?? []).map((x: Record<string, any>) => x.ServiceName)].some((n) => /consult/i.test(String(n ?? "")));
// SM DateTime is "12/3/2026 10:00:00 AM" (local, America/New_York). Date.parse reads it as UTC,
// which is at most 5h off -- fine for a 36h freshness window.
const apptTime = (a: Record<string, any>) => Date.parse(String(a.DateTime ?? a.Slots?.[0]?.DateTime ?? "")) || 0;

async function findHlContact(token: string, locationId: string, phone: string, email: string) {
  for (const q of [phone ? `number=${encodeURIComponent(phone)}` : "", email ? `email=${encodeURIComponent(email)}` : ""].filter(Boolean)) {
    const r = await hl(token, `/contacts/search/duplicate?locationId=${locationId}&${q}`);
    if (r?.contact?.id) return r.contact as { id: string; firstName?: string };
  }
  return null;
}

async function tagContact(token: string, contactId: string, fields: Record<string, string>) {
  const notes: string[] = [];
  try {
    await hl(token, `/contacts/${contactId}`, { method: "PUT",
      body: JSON.stringify({ customFields: Object.entries(fields).map(([key, field_value]) => ({ key, field_value })) }) });
  } catch (e) { notes.push(`custom fields not stamped: ${String(e).slice(0, 120)}`); }   // nice-to-have, never blocks the tag
  await hl(token, `/contacts/${contactId}/tags`, { method: "DELETE", body: JSON.stringify({ tags: [...SURVEY_TAGS_TO_CLEAR, "appointment-completed"] }) });
  await hl(token, `/contacts/${contactId}/tags`, { method: "POST", body: JSON.stringify({ tags: ["appointment-completed"] }) });
  return notes.join("; ");
}

async function runBrand(brand: string, s: Secrets, mode: string, freshHours: number) {
  const out: Record<string, unknown>[] = [];
  const smKey = s[`SM_KEY_${brand}`], token = hlToken(s, brand), locationId = s[`HL_LOCATION_${brand}`];
  if (!smKey) return [{ brand, skipped: "no SM key" }];
  if (!token || !locationId) return [{ brand, skipped: "no HighLevel token/location (set HL_TOKEN_" + brand + ")" }];

  const today = new Date(), from = new Date(today.getTime() - Math.max(LOOKBACK_DAYS * 86400_000, freshHours * 3600_000));
  const ymd = (d: Date) => d.toISOString().slice(0, 10);
  const q = await sm(smKey, "appointments/query", { Skip: 0, Take: 500, IncludeContact: false, Appointments: [],
    FromDate: ymd(from), ThroughDate: ymd(today) });
  const done = (q.Appointments ?? []).filter((a: Record<string, any>) =>
    Number(a.Status) === 3 && isConsult(a) && apptTime(a) > Date.now() - freshHours * 3600_000);

  for (const a of done) {
    const key = `sm:${brand}:${a.AppointmentId}`;
    const { data: prior } = await sb.from("consult_completion_log").select("action").eq("hl_event_id", key);
    if ((prior ?? []).some((r) => r.action !== "error")) continue;                    // already handled
    const errors = (prior ?? []).filter((r) => r.action === "error").length;
    if (errors >= MAX_ATTEMPTS) continue;

    const agent = String(a.ServiceAgentName ?? a.Slots?.[0]?.ServiceAgentName ?? "").trim() || null;
    const base = { hl_event_id: key, brand, sm_appt_id: Number(a.AppointmentId), sm_contact_id: Number(a.ContactId),
                   agent_name: agent, start_time: apptTime(a) ? new Date(apptTime(a)).toISOString() : null, sm_status: "completed" };
    try {
      const c = (await sm(smKey, "contacts/locate", { IdSearch: Number(a.ContactId), Skip: 0, Limit: 1 })).Matches?.[0];
      const phone = e164(c?.Phone ?? c?.PrimaryPhone), email = String(c?.Email ?? c?.PrimaryEmail ?? "").trim();
      const hc = await findHlContact(token, locationId, phone, email);
      if (!hc) {
        out.push({ ...base, action: "skipped_no_hl_contact" });
        if (mode === "live") await sb.from("consult_completion_log").insert({ ...base, action: "skipped_no_hl_contact", detail: `no HighLevel contact for ${phone || "-"} / ${email || "-"}` });
        continue;
      }
      if (mode !== "live") { out.push({ ...base, hl_contact_id: hc.id, action: "would_tag" }); continue; }
      const note = await tagContact(token, hc.id, {
        last_consult_appt_id: String(a.AppointmentId),
        last_consult_date: new Date(apptTime(a) || Date.now()).toISOString().slice(0, 10),
      });
      await sb.from("consult_completion_log").insert({ ...base, hl_contact_id: hc.id, action: "tagged", detail: note || null });
      out.push({ ...base, hl_contact_id: hc.id, action: "tagged" });
    } catch (e) {
      const detail = String(e).slice(0, 500);
      out.push({ ...base, action: "error", detail });
      if (mode === "live") {
        await sb.from("consult_completion_log").insert({ ...base, action: "error", detail, attempt_count: errors + 1 });
        if (errors + 1 >= MAX_ATTEMPTS) await sb.from("notify_queue").insert({ kind: "consult_completion_tagger_error",
          recipient_email: s.default_recipient || "slivingston@kitchentuneup.com", subject: `Consult survey tagger failed (${brand})`,
          body: `Could not tag ${brand} appointment ${a.AppointmentId} for the survey text after ${MAX_ATTEMPTS} tries: ${detail}`,
          source: `consult-completion-tagger:${key}`, status: "pending" });
      }
    }
  }
  return out;
}

Deno.serve(async (req) => {
  const s = await loadSecrets();
  if (!s.cron_secret || req.headers.get("x-cron-secret") !== s.cron_secret) return new Response("forbidden", { status: 403 });
  const url = new URL(req.url);
  const mode = (url.searchParams.get("mode") === "dry_run") ? "dry_run" : (s.tagger_mode || "dry_run");
  // ?hours= widens the freshness window, for DRY RUNS ONLY (testing the matching against older consults).
  const freshHours = mode === "dry_run" ? Math.min(Number(url.searchParams.get("hours")) || FRESH_HOURS, 24 * 30) : FRESH_HOURS;
  if (mode === "off") return Response.json({ mode, skipped: "tagger_mode=off" });
  const results: Record<string, unknown> = {};
  for (const b of BRANDS) {
    try { results[b] = await runBrand(b, s, mode, freshHours); }
    catch (e) { results[b] = [{ brand: b, error: String(e).slice(0, 300) }]; }
  }
  return Response.json({ mode, results });
});
