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
// The text also invites questions ("Need more info? Just text us back"), so:
//   - a rating WITH a request ("4, can you send pricing?") records the rating as need_info and/or
//     callback_requested, which makes consult-feedback alert the office whatever the score;
//   - written feedback with NO number ("the designer was great but I need to think about cost") is
//     not dropped: the office gets an alert, ServiceMinder gets a note, the contact is tagged, and the
//     client gets one short acknowledgement. Only the FIRST written reply in 7 days does this: after
//     that it's a conversation the team is having in HighLevel, and alerting on every "Tuesday works"
//     would be noise. (A later 1-5 rating is still recorded.)
// Opt-outs (STOP etc.) and one- or two-word replies with no number ("ok", "thanks") are left alone.
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
const OPT_OUT = /^(stop|stopall|unsubscribe|cancel|end|quit|help|info)[\s.!]*$/;   // carrier keywords count only as the whole message
export function parseRating(body: string): number | null {
  const t = String(body || "").toLowerCase().trim();
  if (!t || OPT_OUT.test(t)) return null;
  if (/\b10\s*(\/|out of)\s*10\b/.test(t)) return 5;
  const nums = (t.match(/(?<!\d|\d\.)\d+(?!\d|\.\d)/g) ?? []).map(Number);   // "2." counts; "2.5" and "555" don't
  const hit = nums.find((n) => n >= 1 && n <= 5);
  if (hit) return hit;
  if (nums.length) return null;                                    // a number, but not 1-5
  // A number word is a rating only as the reply's first word, before "star(s)"/"out of", or in a short
  // reply ("five", "a four") -- not inside a sentence ("between two options").
  const short = t.split(/\s+/).length <= 3;
  for (const [w, n] of Object.entries(WORDS))
    if (new RegExp(`^${w}\\b|\\b${w}\\s+(stars?|out of)\\b`).test(t) || (short && new RegExp(`\\b${w}\\b`).test(t))) return n;
  for (const [w, n] of Object.entries(PRAISE).sort((a, b) => b[0].length - a[0].length)) if (new RegExp(`\\b${w}\\b`).test(t)) return n;
  return null;
}

/** Does the reply ask for something? needInfo: a question or a request for information/pricing;
 *  callback: asks to be called or contacted. Deliberately narrow: "great price" is praise, not a request. */
export function parseIntent(body: string): { needInfo: boolean; callback: boolean } {
  const t = String(body || "").toLowerCase().trim();
  if (!t || OPT_OUT.test(t)) return { needInfo: false, callback: false };
  const callback = /^(please )?call\b|\b(call me|call us|(can|could|would) (you|someone|somebody) (please )?call|please call|call back|callback|give (me|us) a call|reach out|contact me|contact us|talk to (someone|somebody|you)|speak (to|with) (someone|somebody|you))\b/.test(t);
  const needInfo = !/\bno (more )?questions?\b/.test(t) && (/\?/.test(t) ||
    /\b(more info|more information|need (some |more )?info|info (on|about)|information (on|about)|details (on|about)|send (me|us)|can you send|question|questions|how much|what (would|will|does) it cost|pricing (on|for)|still deciding|need to think|thinking about it|not sure yet)\b/.test(t));
  return { needInfo, callback };
}

const STEVEN_EMAIL = "slivingston@kitchentuneup.com";   // same alert address consult-feedback uses

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

/** A reply with words but no 1-5: alert the office, note ServiceMinder, tag HighLevel, acknowledge once.
 *  Deduplicated by HighLevel message id (notify_queue.source), so a re-fired workflow can't double-alert. */
async function writtenFeedback(brand: string, s: Record<string, string>, token: string, contactId: string,
  msg: { body: string; id: string }, intent: { needInfo: boolean; callback: boolean },
  log: { sm_contact_id: number; sm_appt_id: number; agent_name: string | null } | null) {
  const source = `consult-sms-reply:${contactId}:${msg.id}`;
  const { data: dup } = await sb.from("notify_queue").select("id").eq("source", source).limit(1);
  if (dup?.length) return json(200, { ignored: "already handled", message_id: msg.id });
  const { data: recent } = await sb.from("notify_queue").select("id").like("source", `consult-sms-reply:${contactId}:%`)
    .gte("created_at", new Date(Date.now() - 7 * 86400_000).toISOString()).limit(1);
  if (recent?.length) return json(200, { ignored: "follow-up message in a conversation the team already has open in HighLevel" });

  const label = intent.callback ? "callback requested" : intent.needInfo ? "needs more information" : "written feedback";
  const results: Record<string, string> = { recorded: label };
  const body = `Consult survey text reply (${brand}) – ${label}. Client wrote: "${msg.body.slice(0, 600)}". ` +
    (log ? `SM contact ${log.sm_contact_id}, appt ${log.sm_appt_id}${log.agent_name ? `, designer ${log.agent_name}` : ""}. ` : "No matching ServiceMinder consult found. ") +
    `Reply in the HighLevel conversation (contact ${contactId}).`;
  const { error } = await sb.from("notify_queue").insert({ kind: "consult_feedback_alert", recipient_email: STEVEN_EMAIL,
    subject: `Consult survey text (${brand}) – ${label}`, body, source, status: "pending" });
  results.alert = error ? String(error.message).slice(0, 120) : "queued";

  if (log?.sm_contact_id) {
    try {
      await sm(s[`SM_KEY_${brand}`], "contacts/addnote", { ContactId: Number(log.sm_contact_id), Note: {
        Title: `Consultation feedback (text reply) — ${label}`,
        Body: `Appointment ${log.sm_appt_id}${log.agent_name ? ` with ${log.agent_name}` : ""}\nReply: "${msg.body.slice(0, 600)}"` } });
      results.smNote = "ok";
    } catch (e) { results.smNote = String(e).slice(0, 120); }
  }
  try {
    await hl(token, `/contacts/${contactId}/tags`, { method: "POST",
      body: JSON.stringify({ tags: ["consult-survey-replied", ...(intent.needInfo || intent.callback ? ["consult-follow-up"] : [])] }) });
    results.tags = "ok";
  } catch (e) { results.tags = String(e).slice(0, 120); }

  let first = "";
  if (log?.sm_contact_id) try {
    const c = (await sm(s[`SM_KEY_${brand}`], "contacts/locate", { IdSearch: Number(log.sm_contact_id), Skip: 0, Limit: 1 })).Matches?.[0];
    first = String(c?.FirstName || c?.Name || "").trim().split(/\s+/)[0] || "";
  } catch { /* greeting without a name */ }
  const hi = first ? `, ${first}` : "";
  const text = intent.needInfo || intent.callback
    ? `Thank you${hi}! We'll get back to you shortly about your question.`
    : `Thank you for sharing that${hi}. We read every reply ourselves, and it genuinely helps.`;
  try {
    await hl(token, `/conversations/messages`, { method: "POST", body: JSON.stringify({ type: "SMS", contactId, message: text }) });
    results.reply = "sent";
  } catch (e) { results.reply = String(e).slice(0, 120); }
  return json(200, results);
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
  const rating = parseRating(msg.body), intent = parseIntent(msg.body);
  const words = msg.body.trim().split(/\s+/).filter(Boolean).length;
  if (!rating && (OPT_OUT.test(msg.body.toLowerCase().trim()) || (!intent.needInfo && !intent.callback && words < 3)))
    return json(200, { ignored: "not a rating, request or written feedback", body: msg.body.slice(0, 80) });

  let log: { sm_contact_id: number; sm_appt_id: number; agent_name: string | null } | null =
    await fromSurveyLink(s[`SM_KEY_${brand}`], String(b.survey_link ?? b.customData?.survey_link ?? "")).catch(() => null);
  if (!log) {
    const { data: logs } = await sb.from("consult_completion_log")
      .select("sm_contact_id,sm_appt_id,agent_name,processed_at").eq("brand", brand).eq("hl_contact_id", contactId).eq("action", "tagged")
      .gte("processed_at", new Date(Date.now() - LOOKBACK_DAYS * 86400_000).toISOString()).order("processed_at", { ascending: false }).limit(1);
    log = logs?.[0] ?? null;
  }
  if (!rating) return await writtenFeedback(brand, s, token, contactId, msg, intent, log);
  if (!log?.sm_appt_id) return json(200, { ignored: "no recent completed consult for this contact" });

  const { data: existing } = await sb.from("consult_feedback").select("id").eq("appt_id", log.sm_appt_id).limit(1);
  if (existing?.length) return json(200, { ignored: "already answered", appt_id: log.sm_appt_id });

  const intake = await fetch(`${SUPA}/functions/v1/consult-feedback`, { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ brand, contact_id: log.sm_contact_id, appt_id: log.sm_appt_id, agent_name: log.agent_name, hl_user_id: null,
      rating, missing_items: [], feedback_text: `Text reply: "${msg.body.slice(0, 300)}"`, callback_requested: intent.callback,
      decision: intent.needInfo ? "need_info" : null }) });
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
  const text = intent.needInfo || intent.callback
    ? `Thank you${hi}! We'll get back to you shortly about your question.`
    : rating >= 4
    ? `Thank you${hi}! That means a lot to us and our team.${link ? ` Anything you'd like to add? ${link}` : ""}`
    : `Thank you for being honest${hi}. We're sorry it fell short, and someone from our team will reach out personally.${link ? ` Anything you'd like to add: ${link}` : ""}`;
  try {
    await hl(token, `/conversations/messages`, { method: "POST", body: JSON.stringify({ type: "SMS", contactId, message: text }) });
    results.reply = "sent";
  } catch (e) { results.reply = String(e).slice(0, 120); }

  return json(200, results);
});
