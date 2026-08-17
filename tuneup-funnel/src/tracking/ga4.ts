/**
 * Phase 5: GA4 Measurement Protocol (server-side events).
 *
 * The SPA's gtag covers page/stage analytics; the Worker sends the two
 * money events (generate_lead, purchase) server-side so they land even when
 * the confirmation page is never painted (e.g. HL payment webhook path).
 * The SPA's client_id (the _ga cookie value) is forwarded so MP events join
 * the same GA4 session as the browser hits.
 *
 * Env: GA4_MEASUREMENT_ID (wrangler.toml var, G-XXXX) + GA4_API_SECRET
 * (secret, created under Admin → Data Streams → Measurement Protocol).
 * Unset → recorded no-op.
 */

export interface Ga4Env {
  GA4_MEASUREMENT_ID?: string;
  GA4_API_SECRET?: string;
}

export interface Ga4EventInput {
  name: "generate_lead" | "purchase";
  /** GA client id from the SPA's _ga cookie; falls back to the session id. */
  clientId: string;
  valueCents?: number;
  transactionId?: string;
  params?: Record<string, string | number>;
}

/** Build the MP payload (pure; unit-tested). */
export function buildGa4Payload(input: Ga4EventInput): Record<string, unknown> {
  const params: Record<string, unknown> = { ...input.params, currency: "USD" };
  if (typeof input.valueCents === "number") params.value = input.valueCents / 100;
  if (input.transactionId) params.transaction_id = input.transactionId;
  return {
    client_id: input.clientId,
    events: [{ name: input.name, params }],
  };
}

export async function sendGa4Event(
  env: Ga4Env,
  input: Ga4EventInput,
): Promise<{ ok: boolean; skipped?: "no_config"; error?: string }> {
  if (!env.GA4_MEASUREMENT_ID || !env.GA4_API_SECRET) return { ok: false, skipped: "no_config" };
  try {
    const url =
      `https://www.google-analytics.com/mp/collect?measurement_id=${encodeURIComponent(env.GA4_MEASUREMENT_ID)}` +
      `&api_secret=${encodeURIComponent(env.GA4_API_SECRET)}`;
    const res = await fetch(url, { method: "POST", body: JSON.stringify(buildGa4Payload(input)) });
    // MP returns 2xx even for malformed payloads; treat non-2xx as transport error.
    if (!res.ok) return { ok: false, error: `GA4 MP HTTP ${res.status}` };
    return { ok: true };
  } catch (err) {
    return { ok: false, error: err instanceof Error ? err.message : String(err) };
  }
}
