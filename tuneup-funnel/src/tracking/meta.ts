/**
 * Phase 5: Meta Conversions API (server-side events).
 *
 * Dedup model: the SPA fires the browser-pixel event and passes its eventId to
 * the Worker; the Worker fires the same event name + event_id via CAPI. Meta
 * dedupes the pair, so attribution survives ad blockers / iOS without double
 * counting. Never fire CAPI without the browser-generated event_id when one
 * exists.
 *
 * Match quality: email/phone are SHA-256 hashed (Meta requirement); client IP,
 * user agent, and _fbp/_fbc cookies are passed raw per spec.
 *
 * Env: META_PIXEL_ID (wrangler.toml var) + META_CAPI_TOKEN (secret). Unset →
 * recorded no-op, funnel never blocks on ads config.
 */

export interface MetaEnv {
  META_PIXEL_ID?: string;
  META_CAPI_TOKEN?: string;
}

/** Browser context forwarded by the SPA + read off the request. */
export interface ClientContext {
  eventId?: string;
  url?: string;
  fbp?: string;
  fbc?: string;
  /** GA4 client id from the _ga cookie (joins MP events to the browser session). */
  gaClientId?: string;
  ip?: string;
  userAgent?: string;
}

export type MetaEventName = "Lead" | "InitiateCheckout" | "Purchase";

export interface MetaEventInput {
  eventName: MetaEventName;
  /** Distinguishes funnel moments inside one event name (e.g. callback vs lead). */
  contentName?: string;
  email?: string;
  phone?: string;
  zip?: string;
  /** Purchase/checkout value in cents; converted to dollars for Meta. */
  valueCents?: number;
  client: ClientContext;
  eventTimeMs: number;
}

const CAPI_VERSION = "v21.0";

/** Meta normalization: trim + lowercase email; phone → digits with country code. */
export function normalizeEmail(email: string): string {
  return email.trim().toLowerCase();
}

export function normalizePhone(phone: string): string {
  let digits = phone.replace(/\D/g, "");
  // US default: 10-digit local numbers get the +1 country code (Meta requires it).
  if (digits.length === 10) digits = `1${digits}`;
  return digits;
}

export async function sha256Hex(value: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

/** Build the CAPI payload (pure other than hashing; unit-tested). */
export async function buildMetaEvent(input: MetaEventInput): Promise<Record<string, unknown>> {
  const userData: Record<string, unknown> = {};
  if (input.email) userData.em = [await sha256Hex(normalizeEmail(input.email))];
  if (input.phone) userData.ph = [await sha256Hex(normalizePhone(input.phone))];
  if (input.zip) userData.zp = [await sha256Hex(input.zip.trim().slice(0, 5))];
  if (input.client.ip) userData.client_ip_address = input.client.ip;
  if (input.client.userAgent) userData.client_user_agent = input.client.userAgent;
  if (input.client.fbp) userData.fbp = input.client.fbp;
  if (input.client.fbc) userData.fbc = input.client.fbc;

  const customData: Record<string, unknown> = { currency: "USD" };
  if (input.contentName) customData.content_name = input.contentName;
  if (typeof input.valueCents === "number") customData.value = input.valueCents / 100;

  const event: Record<string, unknown> = {
    event_name: input.eventName,
    event_time: Math.floor(input.eventTimeMs / 1000),
    action_source: "website",
    user_data: userData,
    custom_data: customData,
  };
  if (input.client.eventId) event.event_id = input.client.eventId;
  if (input.client.url) event.event_source_url = input.client.url;
  return event;
}

export interface TrackResult {
  ok: boolean;
  skipped?: "no_config";
  error?: string;
}

/** Fire one CAPI event. Never throws — ads telemetry must not break the funnel. */
export async function sendMetaEvent(env: MetaEnv, input: MetaEventInput): Promise<TrackResult> {
  if (!env.META_PIXEL_ID || !env.META_CAPI_TOKEN) return { ok: false, skipped: "no_config" };
  try {
    const event = await buildMetaEvent(input);
    const res = await fetch(
      `https://graph.facebook.com/${CAPI_VERSION}/${env.META_PIXEL_ID}/events`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ data: [event], access_token: env.META_CAPI_TOKEN }),
      },
    );
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      return { ok: false, error: `CAPI HTTP ${res.status}: ${text.slice(0, 300)}` };
    }
    return { ok: true };
  } catch (err) {
    return { ok: false, error: err instanceof Error ? err.message : String(err) };
  }
}
