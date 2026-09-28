// consult-sms-reply (2026-09-28): HighLevel "Customer replied" webhook for the post-consult survey
// text ("How did your consultation go? Reply with a number 1-5").
//
// verify_jwt is OFF (HighLevel can't send a Supabase JWT). Nothing in the posted body is trusted:
// we take only the contact + location ids from it, then read the client's latest inbound SMS
// ourselves through the HighLevel API with our own token. A forged post can at most make us re-read
// a real conversation; it cannot plant a rating.
//
// On a reply of 1-5 (digits or words, e.g. "5", "5!", "five", "4 stars", "10/10"):
//   - ties it to the ServiceMinder appointment, either from the `survey_link` the HighLevel workflow
//     sends back (set on the contact from ServiceMinder's "Appointment Completed" webhook; its
//     c/a/h are verified against ServiceMinder exactly like the survey page does) or, failing that,
//     from consult_completion_log (consult-completion-tagger v2),
//   - records it through consult-feedback (same table, same alerts: <=3 alerts the office),
//   - adds a ServiceMinder contact note,
//   - tags the HighLevel contact consult-survey-done + consult-promoter/neutral/detractor,
//   - texts back a short thank-you with a link to add detail (the survey page, answer preselected).
// Anything else (a question, "call me", STOP) is left in the HighLevel conversation for the team.
import { createClient } from "npm:@supabase/supabase-js@2";

const SUPA = Deno.env.get("SUPABASE_URL")!;
const sb = createClient(SUPA, Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!);
const HL_BASE = "https://services.leadconnectorhq.com";
const SM = "https://serviceminder.io/api";
const RATING: Record<number, string> = { 5: "Superb", 4: "Very good", 3: "Good", 2: "Fair", 1: "Poor" };
// Number words are checked before praise words ("five stars, Ben was great" is a 5, not a 4).
const WORDS: Record<string, number> = { one: 1, two: 2, three: 3, four: 4, five: 5 };
const PRAISE: Record<string, number> = { superb: 5, excellent: 5, "very good": 4, great: 4, good: 3, fair: 2, poor: 1 };
const LOOKBACK_DAYS = 21;
const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

/** 1-5 from a text reply, or null. "5", "5!", "4 stars", "I'd say a 4", "five", "10/10" all count;
 *  opt-out keywords and numbers outside 1-5 ("8", "555") don't. With several numbers, the first 1-5 wins. */
export function parseRating(body: string): number | null {
  const t = String(body || "").toLowerCase().trim();
  if (!t || /^(stop|stopall|unsubscribe|cancel|end|quit|help|info)\b/.test(t)) return null;
  if (/\b10\s*(\/|out of)\s*10\b/.test(t)) return 5;
  const nums = (t.match(/(?<![\d.])\d+(?![\d.])/g) ?? []).map(Number);
  const hit = nums.find((n) => n >= 1 && n <= 5);
  if (hit) return hit;
  if (nums.length) return null;                                    // a number, but not 1-5
  for (const table of [WORDS, PRAISE])
    for (const [w, n] of Object.entries(table).sort((a, b) => b[0].length - a[0].length)) if (new RegExp(`\\b${w}\\b`).test(t)) return n;
  return null;
}

async function secrets() {
  const { data } = await sb.from("app_secrets").select("key,value");
  return Object.fromEntries((data ?? []).map((r) => [r.key, r.value])) as Record<string, string>;
}

async function hl(token: string, path: string, opts: RequestInit = {}) {
  const r = await fetch(`${HL_BASE}${path}`, { ...opts,
    headers: { Authorization: `Bearer ${token}`, Version: "2021-07-28", "Content-Type": "application/json", Accept: "application/json", ...(opts.headers ?? {}) } });
  const t = await r.text();
  if (!r.ok) throw new Error(`HL ${opts.method ?? "GET"} ${path.split("?")[0]} -> ${r.status}: ${t.slice(0, 200)}`);
  try { return t ? JSON.parse(t) : null; } catch { return null; }
}

async function sm(key: string, ep: string, body: Record<string, unknown>) {
  const r = await fetch(`${SM}/${ep}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...body, ApiKey: key }) });
  const t = await r.text();
  if (!r.ok || !t) throw new Error(`ServiceMinder ${ep} ${r.status}`);
  return JSON.parse(t);
}

/** ServiceMinder ids from the survey link (…/f/k?c=<contact>&a=<appointment>&h=<hash>), trusted only
 *  after ServiceMinder confirms the hash belongs to that contact and the appointment is theirs. */
async function fromSurveyLink(smKey: string, link: string) {
  const m = link.match(/[?&]c=(\d{4,10}).*?[?&]a=(\d{4,10}).*?[?&]h=([0-9a-f]{32})/i);
  if (!m || !smKey) return null;
  const [, c, a, h] = m;
  const contact = (await sm(smKey, "contacts/locate", { IdSearch: Number(c), Skip: 0, Limit: 1 })).Matches?.[0];
  if (!contact || String(contact.Id) !== c || String(contact.Hash ?? "").toLowerCase() !== h.toLowerCase()) return null;
  const q = await sm(smKey, "appointments/query", { ContactId: Number(c), Skip: 0, Take: 100, IncludeContact: false, Appointments: [] });
  const appt = (q.Appointments ?? []).find((x: Record<string, any>) => String(x.AppointmentId) === a);
  if (!appt) return null;
  return { sm_contact_id: Number(c), sm_appt_id: Number(a), agent_name: String(appt.ServiceAgentName ?? "").trim() || null };
}

/** The client's most recent inbound SMS in the last 2 hours, read from HighLevel itself. */
async function latestInboundSms(token: string, locationId: string, contactId: string) {
  const conv = await hl(token, `/conversations/search?locationId=${locationId}&contactId=${contactId}&limit=5`);
  const since = Date.now() - 2 * 3600_000;
  let best: { body: string; at: number; id: string } | null = null;
  for (const c of conv?.conversations ?? []) {
    const m = await hl(token, `/conversations/${c.id}/messages?limit=10`);
    for (const x of m?.messages?.messages ?? m?.messages ?? []) {
      const at = Date.parse(x.dateAdded ?? "") || 0;
      const sms = /sms/i.test(String(x.messageType ?? x.type ?? ""));
      if (x.direction === "inbound" && sms && at >= since && (!best || at > best.at)) best = { body: String(x.body ?? ""), at, id: String(x.id) };
    }
  }
  return best;
}

Deno.serve(async (req) => {
  if (req.method !== "POST") return json(405, { error: "POST only" });
  let b: Record<string, any>;
  try { b = await req.json(); } catch { return json(400, { error: "invalid JSON" }); }
  const contactId = String(b.contact_id ?? b.contactId ?? b.contact?.id ?? "");
  const locationId = String(b.location?.id ?? b.locationId ?? b.location_id ?? "");
  const s = await secrets();
  const brand = locationId && locationId === s.HL_LOCATION_KTU ? "KTU" : locationId && locationId === s.HL_LOCATION_BTU ? "BTU" : "";
  if (!contactId || !brand) return json(200, { ignored: "unknown contact or location" });
  const token = s[`HL_TOKEN_${brand}`] || s[`GHL_PIT_${brand}`];
  if (!token) return json(200, { ignored: `no HighLevel token for ${brand}` });

  const msg = await latestInboundSms(token, locationId, contactId).catch((e) => { console.error(String(e)); return null; });
  if (!msg) return json(200, { ignored: "no recent inbound SMS" });
  const rating = parseRating(msg.body);
  if (!rating) return json(200, { ignored: "reply is not a 1-5 rating", body: msg.body.slice(0, 80) });

  let log: { sm_contact_id: number; sm_appt_id: number; agent_name: string | null } | null =
    await fromSurveyLink(s[`SM_KEY_${brand}`], String(b.survey_link ?? b.customData?.survey_link ?? "")).catch(() => null);
  if (!log) {
    const { data: logs } = await sb.from("consult_completion_log")
      .select("sm_contact_id,sm_appt_id,agent_name,processed_at").eq("brand", brand).eq("hl_contact_id", contactId).eq("action", "tagged")
      .gte("processed_at", new Date(Date.now() - LOOKBACK_DAYS * 86400_000).toISOString()).order("processed_at", { ascending: false }).limit(1);
    log = logs?.[0] ?? null;
  }
  if (!log?.sm_appt_id) return json(200, { ignored: "no recent completed consult for this contact" });

  const { data: existing } = await sb.from("consult_feedback").select("id").eq("appt_id", log.sm_appt_id).limit(1);
  if (existing?.length) return json(200, { ignored: "already answered", appt_id: log.sm_appt_id });

  const intake = await fetch(`${SUPA}/functions/v1/consult-feedback`, { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ brand, contact_id: log.sm_contact_id, appt_id: log.sm_appt_id, agent_name: log.agent_name, hl_user_id: null,
      rating, missing_items: [], feedback_text: `Text reply: "${msg.body.slice(0, 300)}"`, callback_requested: false }) });
  if (!intake.ok) return json(502, { error: `consult-feedback ${intake.status}` });

  const results: Record<string, string> = { recorded: `${rating}/5` };
  const smKey = s[`SM_KEY_${brand}`];
  let first = "", link = "";
  try {
    const c = (await sm(smKey, "contacts/locate", { IdSearch: Number(log.sm_contact_id), Skip: 0, Limit: 1 })).Matches?.[0];
    first = String(c?.FirstName || c?.Name || "").trim().split(/\s+/)[0] || "";
    if (c?.Hash) link = `https://design.ktubtu.com/f/${brand === "KTU" ? "k" : "b"}?c=${log.sm_contact_id}&a=${log.sm_appt_id}&h=${c.Hash}&r=${rating}`;
    await sm(smKey, "contacts/addnote", { ContactId: Number(log.sm_contact_id), Note: {
      Title: `Consultation feedback (text reply) — ${rating}/5 ${RATING[rating]}`,
      Body: `Appointment ${log.sm_appt_id}${log.agent_name ? ` with ${log.agent_name}` : ""}\nRating: ${rating}/5 — ${RATING[rating]}\nReply: "${msg.body.slice(0, 300)}"` } });
    results.smNote = "ok";
  } catch (e) { results.smNote = String(e).slice(0, 120); }

  try {
    await hl(token, `/contacts/${contactId}/tags`, { method: "POST",
      body: JSON.stringify({ tags: ["consult-survey-done", rating >= 5 ? "consult-promoter" : rating === 4 ? "consult-neutral" : "consult-detractor"] }) });
    results.tags = "ok";
  } catch (e) { results.tags = String(e).slice(0, 120); }

  const hi = first ? `, ${first}` : "";
  const text = rating >= 4
    ? `Thank you${hi}! That means a lot to us and our team.${link ? ` Anything you'd like to add? ${link}` : ""}`
    : `Thank you for being honest${hi}. We're sorry it fell short, and someone from our team will reach out personally.${link ? ` Anything you'd like to add: ${link}` : ""}`;
  try {
    await hl(token, `/conversations/messages`, { method: "POST", body: JSON.stringify({ type: "SMS", contactId, message: text }) });
    results.reply = "sent";
  } catch (e) { results.reply = String(e).slice(0, 120); }

  return json(200, results);
});
