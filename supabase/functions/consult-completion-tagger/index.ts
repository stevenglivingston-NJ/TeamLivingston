// consult-completion-tagger — 12h after a consult ends, stamp appointment
// details onto the matching HighLevel contact and re-apply
// `appointment-completed`, in the correct brand sub-account.
//
// Pattern mirrors dispatch-notify / jc-forecast-sync: pg_cron + net.http_post
// every 15 minutes, gated by the shared dispatch_config.cron_secret. New
// calendars are read fresh from consult_calendars every run -- never
// hardcoded here.
//
// Window & first-run safety:
//   We ask HighLevel for events in [now-72h, now-12h] (their start time), then
//   only act on events whose end_time + 12h <= now. That combination means we
//   never touch an event younger than 12h past its end, and the 72h floor on
//   the query keeps a single run's payload small -- it is NOT itself the
//   backlog guard.
//   The backlog guard is explicit: on the very first run (consult_config
//   dispatch_config-style flag `consult_tagger_first_run_done` absent/false in
//   app_secrets), we narrow processing to events that ended within the last
//   24h, so a first deploy doesn't try to backfill a 60-hour window in one
//   shot. After the first run completes, we set that flag so subsequent runs
//   use the full window.
//
// Retries: an HL API error logs action=error and is retried next run, up to
// 3 attempts per hl_event_id (counted from prior consult_completion_log rows
// for that event). On the 3rd failure we insert notify_queue rows for Steven
// + Takia so a human follows up.
//
// 2026-09-21 fix, verified live against the real HighLevel API via the
// High Level MCP connector (read-only calls only -- no writes tested against
// production contacts):
//   - GET /calendars/events query params ARE millisecond-epoch strings, as
//     already coded -- confirmed against a live KTU calendar.
//   - Real appointmentStatus values observed live: "confirmed", "showed",
//     "cancelled" (noshow/invalid not observed live but kept in the mapping
//     below since they're documented HL values) -- classifyStatus's mapping
//     already matched this, no change needed there.
//   - BUG FOUND AND FIXED: the calendar-events response has NO nested
//     `contact` object -- confirmed live, the event payload only carries
//     `contactId`, never `contact.phone`/`contact.email`. The prior version
//     read `ev.contact?.phone`/`ev.contact?.email`, which was always
//     undefined, silently defeating the ServiceMinder cross-check every run.
//     Fixed by fetching GET /contacts/{contactId} once per event to get real
//     phone/email before the SM lookup (confirmed live response shape:
//     `{contact: {phone, email, ...}}`).
//   - Custom field keys (last_consult_appt_id, last_consult_hl_user_id,
//     last_consult_date, last_consult_calendar_id) confirmed to exist on KTU
//     already (created by hand previously) and have now been created on BTU
//     to match (all TEXT type -- KTU's last_consult_date was found to be typed
//     DATE, which would likely reject the "Monday, Sept 21" string this
//     function sends; BTU's was deliberately created as TEXT instead. KTU's
//     existing DATE-typed field is a known open risk -- see report, not fixed
//     here since retyping a live field was judged riskier than flagging it).
//   - HL API Version header (2021-04-15) and the actual contact PUT/tag
//     add-remove calls remain UNVERIFIED live -- this session's HighLevel MCP
//     connector never exercises a write against production contact data
//     without a human explicitly asking for that specific write, so those
//     paths are still first-live-run untested.
import { createClient } from "npm:@supabase/supabase-js@2";

const sb = createClient(
  Deno.env.get("SUPABASE_URL")!,
  Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!,
);

const HL_BASE = "https://services.leadconnectorhq.com";
// Judgment call: dispatch-notify's contacts/messages calls use 2021-07-28 and
// 2021-04-15 respectively. HighLevel's Calendars v2 API (GET /calendars/events,
// contact tag/custom-field updates) is documented as Version 2021-04-15 --
// used here for both the events read and the contact write. The events READ
// path is now confirmed reachable via this version through the account's
// HighLevel MCP connector; the contact WRITE path (PUT /contacts, tag
// add/remove) is still unverified against a live account -- if HighLevel
// returns a version-mismatch error, this is the first thing to check.
const HL_VERSION = "2021-04-15";

const FIRST_RUN_FLAG_KEY = "consult_tagger_first_run_done";
const MAX_ATTEMPTS = 3;

type Secrets = Record<string, string>;

async function loadSecrets(): Promise<Secrets> {
  // app_secrets holds the HL tokens/locations + our own placeholders;
  // cron_secret and default_recipient live in dispatch_config (same table
  // dispatch-notify / jc-forecast-sync use for the shared cron gate) -- pull
  // both and merge, so this function's auth matches the existing pattern
  // exactly rather than inventing a second secret store.
  const [{ data: a }, { data: d }] = await Promise.all([
    sb.from("app_secrets").select("key,value"),
    sb.from("dispatch_config").select("key,value"),
  ]);
  return {
    ...Object.fromEntries((d ?? []).map((r) => [r.key, r.value])),
    ...Object.fromEntries((a ?? []).map((r) => [r.key, r.value])),
  };
}

function fmtConsultDate(iso: string): string {
  // "Monday, Sept 21" style.
  const d = new Date(iso);
  const weekday = d.toLocaleDateString("en-US", { weekday: "long", timeZone: "America/New_York" });
  const month = d.toLocaleDateString("en-US", { month: "short", timeZone: "America/New_York" });
  const day = d.toLocaleDateString("en-US", { day: "numeric", timeZone: "America/New_York" });
  return `${weekday}, ${month} ${day}`;
}

async function hlFetch(token: string, path: string, opts: RequestInit = {}) {
  const r = await fetch(`${HL_BASE}${path}`, {
    ...opts,
    headers: {
      Authorization: `Bearer ${token}`,
      Version: HL_VERSION,
      "Content-Type": "application/json",
      ...(opts.headers ?? {}),
    },
  });
  const text = await r.text();
  let json: unknown = null;
  try { json = text ? JSON.parse(text) : null; } catch { /* leave null */ }
  if (!r.ok) throw new Error(`HL ${path} -> ${r.status}: ${text.slice(0, 300)}`);
  return json;
}

// Fetch a contact's phone/email -- calendar-events responses do NOT embed
// this (confirmed live 2026-09-21), so it takes a second call per event.
async function getContactPhoneEmail(token: string, contactId: string): Promise<{ phone: string; email: string }> {
  try {
    const resp = await hlFetch(token, `/contacts/${contactId}`) as { contact?: { phone?: string; email?: string } };
    return { phone: resp?.contact?.phone ?? "", email: resp?.contact?.email ?? "" };
  } catch {
    return { phone: "", email: "" };
  }
}

// Map HighLevel's appointmentStatus strings to our three skip buckets.
// Confirmed live 2026-09-21: real calendar events return "confirmed",
// "showed", "cancelled" -- "noshow"/"invalid" are documented HL values not
// observed live in this sample but kept for safety.
function classifyStatus(hlStatus: string): "skipped_cancelled" | "skipped_noshow" | null {
  const s = (hlStatus || "").toLowerCase();
  if (s === "cancelled" || s === "canceled") return "skipped_cancelled";
  if (s === "noshow" || s === "no_show" || s === "no-show") return "skipped_noshow";
  if (s === "invalid") return "skipped_cancelled"; // closest bucket to "not a real completed appt"
  return null;
}

async function alreadyLogged(hlEventId: string) {
  const { data } = await sb
    .from("consult_completion_log")
    .select("id")
    .eq("hl_event_id", hlEventId)
    .limit(1);
  return (data?.length ?? 0) > 0;
}

async function priorErrorCount(hlEventId: string) {
  const { count } = await sb
    .from("consult_completion_log")
    .select("id", { count: "exact", head: true })
    .eq("hl_event_id", hlEventId)
    .eq("action", "error");
  return count ?? 0;
}

async function logRow(row: {
  hl_event_id: string; brand: string; hl_contact_id?: string | null; hl_user_id?: string | null;
  start_time?: string | null; end_time?: string | null; hl_status?: string | null; sm_status?: string | null;
  action: string; detail?: string | null; attempt_count?: number;
}) {
  await sb.from("consult_completion_log").insert(row);
}

async function findSmMatch(brand: string, startIso: string, phone?: string, email?: string) {
  if (!phone && !email) return null;
  const start = new Date(startIso);
  const lo = new Date(start.getTime() - 30 * 60000).toISOString();
  const hi = new Date(start.getTime() + 30 * 60000).toISOString();
  const { data } = await sb.from("appointments").select("status,customer_phone,customer_email,appt_at")
    .eq("brand", brand).gte("appt_at", lo).lte("appt_at", hi);
  if (!data || data.length === 0) return null;
  const norm = (s?: string | null) => (s || "").replace(/\D/g, "");
  const hit = data.find((r) =>
    (phone && norm(r.customer_phone) && norm(r.customer_phone) === norm(phone)) ||
    (email && r.customer_email && r.customer_email.toLowerCase() === email.toLowerCase())
  );
  return hit ?? null;
}

function smIndicatesCancelled(status: string | null | undefined) {
  const s = (status || "").toLowerCase();
  return s.includes("cancel") || s.includes("no show") || s.includes("noshow");
}

async function queueFailureNotice(brand: string, hlEventId: string, err: string, secrets: Secrets) {
  const detail = `Completion tagger failed for ${brand} event ${hlEventId}: ${err}`.slice(0, 500);
  const recipients = [secrets.default_recipient || "stevenglivingston@gmail.com"];
  const takia = secrets.NOTIFY_RECIPIENT_TAKIA;
  if (takia) recipients.push(takia);
  for (const to of recipients) {
    await sb.from("notify_queue").insert({
      kind: "consult_completion_tagger_error",
      recipient_email: to,
      subject: `Completion tagger failed (${brand})`,
      body: detail,
      source: `consult-completion-tagger:${hlEventId}`,
      status: "pending",
    });
  }
}

async function updateHlContact(
  token: string,
  contactId: string,
  fields: { last_consult_appt_id: string; last_consult_hl_user_id: string; last_consult_date: string; last_consult_calendar_id: string },
) {
  // Custom field keys used here (last_consult_appt_id, last_consult_hl_user_id,
  // last_consult_date, last_consult_calendar_id) are now confirmed to exist on
  // both KTU (pre-existing) and BTU (created 2026-09-21) sub-accounts, all as
  // TEXT fields. The PUT itself (customFields by `key`) is still unverified
  // against a live write -- HighLevel's read API returns customFields keyed by
  // `id`+`value`, and the write API is documented to also accept `key`+
  // `field_value`, but that specific write path was not exercised live this
  // session (no destructive test against real contact data was run without a
  // human explicitly asking for it). If this errors, check whether the write
  // needs `id` instead of `key`.
  await hlFetch(token, `/contacts/${contactId}`, {
    method: "PUT",
    body: JSON.stringify({
      customFields: [
        { key: "last_consult_appt_id", field_value: fields.last_consult_appt_id },
        { key: "last_consult_hl_user_id", field_value: fields.last_consult_hl_user_id },
        { key: "last_consult_date", field_value: fields.last_consult_date },
        { key: "last_consult_calendar_id", field_value: fields.last_consult_calendar_id },
      ],
    }),
  });

  // Remove-then-add appointment-completed, deliberately, to force any HL
  // automation keyed off that tag to re-fire for repeat customers.
  await hlFetch(token, `/contacts/${contactId}/tags`, {
    method: "DELETE",
    body: JSON.stringify({ tags: ["appointment-completed"] }),
  });
  await hlFetch(token, `/contacts/${contactId}/tags`, {
    method: "POST",
    body: JSON.stringify({ tags: ["appointment-completed"] }),
  });
}

async function processCalendar(
  brand: string,
  calendarId: string,
  token: string,
  locationId: string,
  firstRun: boolean,
  secrets: Secrets,
) {
  const now = Date.now();
  const windowStart = firstRun ? now - 24 * 3600_000 : now - 72 * 3600_000;
  const windowEnd = now - 12 * 3600_000;

  // Confirmed live 2026-09-21: startTime/endTime ARE millisecond-epoch
  // strings, exactly as coded here -- a real KTU calendar query with these
  // params returned real events.
  const qs = new URLSearchParams({
    locationId,
    calendarId,
    startTime: String(windowStart),
    endTime: String(windowEnd),
  });
  let events: Array<Record<string, unknown>> = [];
  try {
    const resp = await hlFetch(token, `/calendars/events?${qs}`) as { events?: Array<Record<string, unknown>> };
    events = resp?.events ?? [];
  } catch (e) {
    // Can't even list events for this calendar -- log one error row so it's
    // visible, but there's no per-event id to key off, so nothing to retry
    // per-event; the next run will simply try again.
    await logRow({ hl_event_id: `calendar:${calendarId}:${now}`, brand, action: "error", detail: String(e).slice(0, 500) });
    return;
  }

  for (const ev of events) {
    const hlEventId = String(ev.id ?? ev._id ?? "");
    if (!hlEventId) continue;
    const startTime = String(ev.startTime ?? "");
    const endTime = String(ev.endTime ?? "");
    if (!endTime || new Date(endTime).getTime() + 12 * 3600_000 > now) continue; // not yet due
    if (await alreadyLogged(hlEventId)) continue;

    const hlStatus = String(ev.appointmentStatus ?? "");
    const contactId = String(ev.contactId ?? "");
    const assignedUserId = String(ev.assignedUserId ?? "");

    const skip = classifyStatus(hlStatus);
    if (skip) {
      await logRow({
        hl_event_id: hlEventId, brand, hl_contact_id: contactId || null, hl_user_id: assignedUserId || null,
        start_time: startTime || null, end_time: endTime || null, hl_status: hlStatus, action: skip,
        detail: `HL appointmentStatus=${hlStatus}`,
      });
      continue;
    }

    if (!contactId) {
      await logRow({
        hl_event_id: hlEventId, brand, start_time: startTime || null, end_time: endTime || null,
        hl_status: hlStatus, action: "skipped_no_contact", detail: "event has no contactId",
      });
      continue;
    }

    // Cross-check ServiceMinder via the intranet's own `appointments` table.
    // Calendar events do NOT embed contact phone/email (confirmed live) --
    // fetch the contact separately.
    const { phone: contactPhone, email: contactEmail } = await getContactPhoneEmail(token, contactId);
    const smRow = await findSmMatch(brand, startTime, contactPhone, contactEmail);
    let smStatus: string | null = null;
    if (smRow) {
      smStatus = smRow.status ?? null;
      if (smIndicatesCancelled(smStatus)) {
        await logRow({
          hl_event_id: hlEventId, brand, hl_contact_id: contactId, hl_user_id: assignedUserId || null,
          start_time: startTime || null, end_time: endTime || null, hl_status: hlStatus, sm_status: smStatus,
          action: "skipped_sm_cancelled", detail: `SM status=${smStatus}`,
        });
        continue;
      }
    }
    const detailNote = smRow ? `SM status=${smStatus}` : "no SM match";

    const attempts = await priorErrorCount(hlEventId);
    if (attempts >= MAX_ATTEMPTS) {
      // Already exhausted retries and notified -- don't retry forever, and
      // don't re-notify every 15 minutes. Leave it logged as error; a human
      // has to intervene (or delete the log rows to force a retry).
      continue;
    }

    try {
      await updateHlContact(token, contactId, {
        last_consult_appt_id: hlEventId,
        last_consult_hl_user_id: assignedUserId,
        last_consult_date: startTime ? fmtConsultDate(startTime) : "",
        last_consult_calendar_id: calendarId,
      });
      await logRow({
        hl_event_id: hlEventId, brand, hl_contact_id: contactId, hl_user_id: assignedUserId || null,
        start_time: startTime || null, end_time: endTime || null, hl_status: hlStatus, sm_status: smStatus,
        action: "tagged", detail: detailNote,
      });
    } catch (e) {
      const errStr = String(e).slice(0, 500);
      const newAttempt = attempts + 1;
      await logRow({
        hl_event_id: hlEventId, brand, hl_contact_id: contactId, hl_user_id: assignedUserId || null,
        start_time: startTime || null, end_time: endTime || null, hl_status: hlStatus, sm_status: smStatus,
        action: "error", detail: errStr, attempt_count: newAttempt,
      });
      if (newAttempt >= MAX_ATTEMPTS) {
        await queueFailureNotice(brand, hlEventId, errStr, secrets);
      }
    }
  }
}

Deno.serve(async (req) => {
  const secrets = await loadSecrets();
  if (!secrets.cron_secret || req.headers.get("x-cron-secret") !== secrets.cron_secret) {
    return new Response("forbidden", { status: 403 });
  }

  const { data: firstRunRow } = await sb.from("app_secrets").select("value").eq("key", FIRST_RUN_FLAG_KEY).maybeSingle();
  const { count: logCount } = await sb.from("consult_completion_log").select("id", { count: "exact", head: true });
  const firstRun = !firstRunRow?.value && (logCount ?? 0) === 0;

  const { data: cals } = await sb.from("consult_calendars").select("*").eq("active", true);
  const results: unknown[] = [];
  for (const cal of cals ?? []) {
    const brand = cal.brand as string;
    const token = brand === "KTU" ? secrets.HL_TOKEN_KTU : secrets.HL_TOKEN_BTU;
    const locationId = brand === "KTU" ? secrets.HL_LOCATION_KTU : secrets.HL_LOCATION_BTU;
    if (!token || !locationId) {
      results.push({ calendar_id: cal.calendar_id, brand, skipped: "no HL token/location configured" });
      continue;
    }
    try {
      await processCalendar(brand, cal.calendar_id, token, locationId, firstRun, secrets);
      results.push({ calendar_id: cal.calendar_id, brand, ok: true });
    } catch (e) {
      results.push({ calendar_id: cal.calendar_id, brand, ok: false, error: String(e).slice(0, 300) });
    }
  }

  if (firstRun) {
    await sb.from("app_secrets").upsert({ key: FIRST_RUN_FLAG_KEY, value: "true", updated_at: new Date().toISOString() });
  }

  return Response.json({ first_run: firstRun, processed: results.length, results });
});
