/**
 * Phase 5 fan-out: one call per funnel moment pushes the contact into
 * HighLevel (tagged so the HL workflow notifies Sonya/the office) and fires
 * the ad-platform conversions (Meta CAPI + GA4 MP).
 *
 * All pushes are best-effort and never throw: results are written to
 * funnel_events (`fanout_*`) so misfires are visible in D1 without ever
 * blocking or breaking the customer's flow. Callers run this via
 * ctx.waitUntil so the HTTP response doesn't wait on third parties.
 */

import { HL_TAGS, upsertHlContact, type HlEnv } from "../hl/client";
import { sendGa4Event, type Ga4Env } from "./ga4";
import { sendMetaEvent, type ClientContext, type MetaEnv } from "./meta";

export type { ClientContext } from "./meta";

export interface FanoutEnv extends HlEnv, MetaEnv, Ga4Env {
  DB: D1Database;
}

async function logEvent(db: D1Database, sessionId: string | null, event: string, detail: unknown) {
  try {
    await db
      .prepare("INSERT INTO funnel_events (session_id, created_at, event, detail) VALUES (?1, ?2, ?3, ?4)")
      .bind(sessionId, new Date().toISOString(), event, detail == null ? null : JSON.stringify(detail))
      .run();
  } catch {
    /* audit is best-effort */
  }
}

/** Pull the client context CAPI wants off the request + SPA-forwarded fields. */
export function clientContextFrom(request: Request, body: Record<string, unknown>): ClientContext {
  const str = (v: unknown) => (typeof v === "string" && v.length > 0 ? v : undefined);
  return {
    eventId: str(body.eventId),
    url: str(body.pageUrl),
    fbp: str(body.fbp),
    fbc: str(body.fbc),
    gaClientId: str(body.gaClientId),
    ip: request.headers.get("CF-Connecting-IP") ?? undefined,
    userAgent: request.headers.get("User-Agent") ?? undefined,
  };
}

export interface LeadFanout {
  sessionId: string | null;
  name: string;
  phone: string;
  email?: string;
  zip?: string;
  /** true → callback request (tag tuneup-callback), else tuneup-lead. */
  callback: boolean;
  /** Customer-stated best time to call (callback path). */
  bestTime?: string | null;
  quoteCents?: number | null;
  client: ClientContext;
}

/** Lead captured or callback requested → HL tag + Meta Lead + GA4 generate_lead. */
export async function fanoutLead(env: FanoutEnv, input: LeadFanout): Promise<void> {
  const tag = input.callback ? HL_TAGS.callback : HL_TAGS.lead;
  const [hl, meta, ga4] = await Promise.all([
    upsertHlContact(env, {
      name: input.name,
      phone: input.phone,
      email: input.email,
      zip: input.zip,
      tags: [tag],
      customFields: {
        tuneup_session_id: input.sessionId,
        tuneup_quote: input.quoteCents != null ? (input.quoteCents / 100).toFixed(2) : null,
        tuneup_best_time: input.bestTime ?? null,
      },
    }),
    sendMetaEvent(env, {
      eventName: "Lead",
      contentName: input.callback ? "tuneup-callback" : "tuneup-lead",
      email: input.email,
      phone: input.phone,
      zip: input.zip,
      client: input.client,
      eventTimeMs: Date.now(),
    }),
    sendGa4Event(env, {
      name: "generate_lead",
      clientId: input.client.gaClientId ?? input.sessionId ?? "anon",
      params: { lead_type: input.callback ? "callback" : "lead" },
    }),
  ]);
  await logEvent(env.DB, input.sessionId, "fanout_lead", { tag, hl, meta, ga4 });
}

export interface CheckoutFanout {
  sessionId: string;
  depositCents: number;
  client: ClientContext;
}

/** Deposit started → Meta InitiateCheckout (no HL push; contact already exists). */
export async function fanoutCheckout(env: FanoutEnv, input: CheckoutFanout): Promise<void> {
  const meta = await sendMetaEvent(env, {
    eventName: "InitiateCheckout",
    contentName: "tuneup-deposit",
    valueCents: input.depositCents,
    client: input.client,
    eventTimeMs: Date.now(),
  });
  await logEvent(env.DB, input.sessionId, "fanout_checkout", { meta });
}

export interface BookingFanout {
  sessionId: string;
  name: string;
  phone: string;
  email: string;
  address1?: string;
  city?: string;
  state?: string;
  zip?: string;
  scheduledStart: string;
  openings?: number;
  quoteCents?: number | null;
  depositCents?: number | null;
  level?: string | null;
  smAppointmentId?: string | number;
  smContactId?: string | number;
  client: ClientContext;
}

/**
 * Deposit paid + SM appointment booked → HL tuneup-booked (workflow notifies
 * Sonya with job facts) + Meta Purchase (value = deposit collected) + GA4
 * purchase. The conversion value is the money actually taken, not the quote —
 * the full job value rides along in custom fields/params.
 */
export async function fanoutBooking(env: FanoutEnv, input: BookingFanout): Promise<void> {
  const [hl, meta, ga4] = await Promise.all([
    upsertHlContact(env, {
      name: input.name,
      phone: input.phone,
      email: input.email,
      address1: input.address1,
      city: input.city,
      state: input.state,
      zip: input.zip,
      tags: [HL_TAGS.booked],
      customFields: {
        tuneup_session_id: input.sessionId,
        tuneup_quote: input.quoteCents != null ? (input.quoteCents / 100).toFixed(2) : null,
        tuneup_deposit: input.depositCents != null ? (input.depositCents / 100).toFixed(2) : null,
        tuneup_openings: input.openings ?? null,
        tuneup_level: input.level ?? null,
        tuneup_appointment: input.scheduledStart,
        tuneup_sm_appointment_id: input.smAppointmentId ?? null,
        tuneup_sm_contact_id: input.smContactId ?? null,
      },
    }),
    sendMetaEvent(env, {
      eventName: "Purchase",
      contentName: "tuneup-deposit-paid",
      email: input.email,
      phone: input.phone,
      zip: input.zip,
      valueCents: input.depositCents ?? undefined,
      client: input.client,
      eventTimeMs: Date.now(),
    }),
    sendGa4Event(env, {
      name: "purchase",
      clientId: input.client.gaClientId ?? input.sessionId,
      valueCents: input.depositCents ?? undefined,
      transactionId: input.sessionId,
      params: {
        openings: input.openings ?? 0,
        quote_value: input.quoteCents != null ? input.quoteCents / 100 : 0,
      },
    }),
  ]);
  await logEvent(env.DB, input.sessionId, "fanout_booking", { hl, meta, ga4 });
}
