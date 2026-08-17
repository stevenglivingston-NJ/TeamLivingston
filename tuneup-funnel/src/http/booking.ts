/**
 * Phase 4: scheduling, agreement consent, HighLevel deposit, and the booking
 * chain. Payment uses the HighLevel payment integration (owner decision) rather
 * than Stripe. The 50% deposit is collected via HighLevel; on confirmed payment
 * the ServiceMinder appointment is booked on the Tune-Up Residential calendar.
 *
 * Slot-hold rule (build spec): the chosen slot is held 15 minutes pending
 * payment and released if unpaid — enforced by only booking SM after the
 * HighLevel payment confirms, and by re-validating the slot at booking time.
 */

import type { SmEnv } from "../sm/client";
import { bookAppointment, fetchSlots, jobDurationMinutes, type Slot } from "../sm/schedule";
import { AGREEMENT_VERSION } from "../agreement";
import {
  fanoutBooking,
  fanoutCheckout,
  type ClientContext,
  type FanoutEnv,
} from "../tracking/fanout";
import type { Defer } from "./funnel";

export interface BookingEnv extends SmEnv, FanoutEnv {
  DB: D1Database;
  /** HighLevel payment-integration config (owner provides). When unset, the
   *  funnel falls back to "the team will send your deposit invoice". */
  HIGHLEVEL_PAYMENT_URL?: string;
  HIGHLEVEL_API_KEY?: string;
}

function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

async function logEvent(db: D1Database, sessionId: string | null, event: string, detail: unknown) {
  try {
    await db
      .prepare("INSERT INTO funnel_events (session_id, created_at, event, detail) VALUES (?1, ?2, ?3, ?4)")
      .bind(sessionId, new Date().toISOString(), event, detail == null ? null : JSON.stringify(detail))
      .run();
  } catch {
    /* best effort */
  }
}

/** GET /api/slots?date=YYYY-MM-DD&openings=N — available Tune-Up appointment times. */
export async function getSlots(env: BookingEnv, date: string, openings: number): Promise<Response> {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) {
    return jsonResponse({ error: "date must be YYYY-MM-DD" }, 400);
  }
  const duration = jobDurationMinutes(Number.isFinite(openings) ? openings : 20);
  let slots: Slot[] = [];
  let available = true;
  try {
    slots = await fetchSlots(env, date, duration);
  } catch {
    // SM unreachable or the Tune-Up calendar has no agent availability yet →
    // don't dead-end the customer; offer the call-to-confirm path.
    available = false;
  }
  return jsonResponse({ durationMinutes: duration, available, slots });
}

/** POST /api/agreement — record e-consent to the service agreement. */
export async function recordAgreement(
  env: BookingEnv,
  body: { sessionId?: string; name?: string; agreedAt?: string },
): Promise<Response> {
  if (!body.sessionId || !body.name) {
    return jsonResponse({ error: "sessionId and name required" }, 400);
  }
  await logEvent(env.DB, body.sessionId, "agreement_signed", {
    version: AGREEMENT_VERSION,
    name: body.name,
    agreedAt: body.agreedAt ?? new Date().toISOString(),
  });
  return jsonResponse({ ok: true, agreementVersion: AGREEMENT_VERSION });
}

/**
 * POST /api/checkout — start the 50% deposit via HighLevel payments.
 * Returns a payment URL the SPA opens. When HighLevel payment config is absent,
 * returns a graceful fallback so the funnel still completes (team invoices the
 * deposit).
 */
export async function startDeposit(
  env: BookingEnv,
  body: { sessionId?: string; depositCents?: number; slotStart?: string },
  client: ClientContext,
  defer: Defer,
): Promise<Response> {
  if (!body.sessionId || typeof body.depositCents !== "number" || !body.slotStart) {
    return jsonResponse({ error: "sessionId, depositCents, slotStart required" }, 400);
  }
  await logEvent(env.DB, body.sessionId, "checkout_started", {
    depositCents: body.depositCents,
    slotStart: body.slotStart,
  });
  defer(fanoutCheckout(env, { sessionId: body.sessionId, depositCents: body.depositCents, client }));

  if (!env.HIGHLEVEL_PAYMENT_URL || !env.HIGHLEVEL_API_KEY) {
    // Not yet wired — the team will send the HighLevel deposit invoice.
    return jsonResponse({ mode: "invoice_fallback", ok: true });
  }

  // TODO(owner-config): call the HighLevel payment integration to create a
  // deposit payment link for body.depositCents tied to this session, then
  // return its URL. HighLevel confirms payment via webhook → /api/booking/confirm.
  // Shape depends on the HL payment integration Steven enables.
  return jsonResponse({ mode: "highlevel", paymentUrl: env.HIGHLEVEL_PAYMENT_URL, ok: true });
}

/**
 * POST /api/booking/confirm — called after the HighLevel deposit is confirmed
 * (by the HL payment webhook in production; also callable by the team). Books
 * the SM appointment and marks the session booked.
 */
export async function confirmBooking(
  env: BookingEnv,
  body: {
    sessionId?: string;
    name?: string;
    phone?: string;
    email?: string;
    address1?: string;
    city?: string;
    state?: string;
    zip?: string;
    scheduledStart?: string;
    openings?: number;
    notes?: string;
    quoteCents?: number;
    depositCents?: number;
    level?: string;
  },
  client: ClientContext,
  defer: Defer,
): Promise<Response> {
  const required = ["sessionId", "name", "phone", "email", "scheduledStart"] as const;
  for (const k of required) {
    if (!body[k]) return jsonResponse({ error: `${k} required` }, 400);
  }
  const durationMinutes = jobDurationMinutes(body.openings ?? 20);
  try {
    const result = await bookAppointment(env, {
      name: body.name!,
      phone: body.phone!,
      email: body.email!,
      address1: body.address1 ?? "",
      city: body.city ?? "",
      state: body.state ?? "NJ",
      zip: body.zip ?? "",
      scheduledStart: body.scheduledStart!,
      durationMinutes,
      notes: body.notes ?? "KTU Instant Tune-Up online booking",
    });
    await env.DB.prepare("UPDATE quote_sessions SET status = 'booked', updated_at = ?2 WHERE id = ?1")
      .bind(body.sessionId, new Date().toISOString())
      .run();
    await logEvent(env.DB, body.sessionId!, "deposit_paid_booked", {
      appointmentId: result.appointmentId,
      contactId: result.contactId,
    });
    // Phase 5: HighLevel tuneup-booked (HL workflow notifies Sonya/office)
    // + Meta CAPI Purchase + GA4 purchase — deferred, never blocks the booking.
    defer(
      fanoutBooking(env, {
        sessionId: body.sessionId!,
        name: body.name!,
        phone: body.phone!,
        email: body.email!,
        address1: body.address1,
        city: body.city,
        state: body.state,
        zip: body.zip,
        scheduledStart: body.scheduledStart!,
        openings: body.openings,
        quoteCents: typeof body.quoteCents === "number" ? body.quoteCents : null,
        depositCents: typeof body.depositCents === "number" ? body.depositCents : null,
        level: body.level ?? null,
        smAppointmentId: result.appointmentId,
        smContactId: result.contactId,
        client,
      }),
    );
    return jsonResponse({ ok: true, ...result });
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    await logEvent(env.DB, body.sessionId!, "booking_failed", { message });
    // Payment succeeded but SM booking failed → team must finish manually.
    return jsonResponse({ ok: false, error: message, needsManualBooking: true }, 502);
  }
}
