/**
 * ServiceMinder scheduling + booking client (Phase 4). Reads live slots from the
 * Tune-Up Residential calendar and books via quickbook (creates the SM contact
 * and the appointment in one call). Booking is the final step of the payment
 * chain — only called after the HighLevel deposit is confirmed.
 */

import { SM_API_BASE, SM_PRICING } from "../config";
import type { SmEnv } from "./client";

/** ~4h base on-site; scale a little with kitchen size. Owner can tune. */
export function jobDurationMinutes(openings: number): number {
  if (openings <= 15) return 240;
  if (openings <= 25) return 300;
  return 360;
}

export interface Slot {
  /** ISO datetime the appointment would start. */
  start: string;
  /** Service agent id, if SM assigns one to the slot. */
  agentId?: number;
}

interface SlotSearchResponse {
  Slots?: Array<{ ScheduledStart?: string; Start?: string; ServiceAgentId?: number }>;
  ResultCode?: number;
  Message?: string;
}

export async function fetchSlots(
  env: SmEnv,
  targetDate: string,
  durationMinutes: number,
  fetchImpl: typeof fetch = fetch,
): Promise<Slot[]> {
  const res = await fetchImpl(`${SM_API_BASE}/appointments/slotsearch`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      ApiKey: env.SERVICEMINDER_API_KEY,
      ServiceId: SM_PRICING.serviceId,
      ContactId: 0,
      TargetDate: targetDate,
      Duration: String(durationMinutes),
      Quantity: 1,
      Timeframe: "Anytime",
      SlotWindowDays: 14,
      Slots: [],
      AddOnParts: [],
      NotificationOptions: [],
    }),
  });
  if (!res.ok) throw new Error(`SM slotsearch failed: HTTP ${res.status}`);
  const data = (await res.json()) as SlotSearchResponse;
  return (data.Slots ?? [])
    .map((s) => ({ start: s.ScheduledStart ?? s.Start ?? "", agentId: s.ServiceAgentId }))
    .filter((s) => s.start !== "");
}

export interface BookingRequest {
  name: string;
  phone: string;
  email: string;
  address1: string;
  city: string;
  state: string;
  zip: string;
  scheduledStart: string; // ISO
  durationMinutes: number;
  notes: string;
}

interface QuickbookResponse {
  AppointmentId?: number;
  ContactId?: number;
  ResultCode?: number;
  Message?: string;
}

export async function bookAppointment(
  env: SmEnv,
  req: BookingRequest,
  fetchImpl: typeof fetch = fetch,
): Promise<{ appointmentId: number; contactId: number }> {
  const res = await fetchImpl(`${SM_API_BASE}/appointments/quickbook`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      ApiKey: env.SERVICEMINDER_API_KEY,
      Name: req.name,
      PriPhone: req.phone,
      Email: req.email,
      Address1: req.address1,
      City: req.city,
      State: req.state,
      Zip: req.zip,
      // "Tune-Up Residential" — SM matches the service by name here.
      Service: "Tune-Up Residential",
      ScheduledStart: req.scheduledStart,
      Duration: req.durationMinutes,
      Quantity: 1,
      InternalNotes: req.notes,
      Confirmed: true,
    }),
  });
  if (!res.ok) throw new Error(`SM quickbook failed: HTTP ${res.status}`);
  const data = (await res.json()) as QuickbookResponse;
  if (data.ResultCode !== undefined && data.ResultCode !== 0) {
    throw new Error(`SM quickbook error: ${data.Message ?? data.ResultCode}`);
  }
  return { appointmentId: data.AppointmentId ?? 0, contactId: data.ContactId ?? 0 };
}
