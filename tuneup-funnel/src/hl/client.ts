/**
 * Phase 5: HighLevel (LeadConnector v2) contact upsert for the KTU location.
 *
 * The funnel pushes contacts into HighLevel at three moments — lead captured,
 * callback requested, deposit paid + booked — each with a tag the HL workflow
 * (built in the HighLevel AI builder) triggers on to notify Sonya/the office
 * and run nurture. The repo owns the *push*; HighLevel owns the *reaction*,
 * so the team can retune notifications without a code deploy.
 *
 * Auth: HIGHLEVEL_API_KEY is the KTU Private Integration Token (PIT) — the
 * same secret the Phase 4 payment path uses. When it's unset the upsert is a
 * recorded no-op: the funnel never blocks on CRM config.
 */

export interface HlEnv {
  /** KTU Private Integration Token (secret; `wrangler secret put HIGHLEVEL_API_KEY`). */
  HIGHLEVEL_API_KEY?: string;
  /** HighLevel location — KTU = nHLCxHPidnhV1NFzRtZZ (wrangler.toml var). */
  HIGHLEVEL_LOCATION_ID?: string;
}

/** Tags the HL workflows key on. Keep in sync with docs/highlevel-phase5.md. */
export const HL_TAGS = {
  lead: "tuneup-lead",
  callback: "tuneup-callback",
  booked: "tuneup-booked",
} as const;

export interface HlContact {
  name: string;
  phone: string;
  email?: string;
  address1?: string;
  city?: string;
  state?: string;
  zip?: string;
  tags: string[];
  /** Free-form funnel facts (quote, openings, level, appointment…). Sent as
   *  customFields by key — the keys must exist as custom fields in HL. */
  customFields?: Record<string, string | number | boolean | null>;
}

export interface HlUpsertResult {
  ok: boolean;
  skipped?: "no_config";
  contactId?: string;
  error?: string;
}

const HL_API = "https://services.leadconnectorhq.com";
const HL_VERSION = "2021-07-28";

/** Split "First Last" the way HL expects; single names go to firstName. */
export function splitName(name: string): { firstName: string; lastName: string } {
  const parts = name.trim().split(/\s+/);
  return { firstName: parts[0] ?? "", lastName: parts.slice(1).join(" ") };
}

/**
 * Upsert the contact (HL dedupes by phone/email) and apply tags + custom
 * fields. Never throws — callers treat CRM push as best-effort and log the
 * outcome to funnel_events.
 */
export async function upsertHlContact(env: HlEnv, contact: HlContact): Promise<HlUpsertResult> {
  if (!env.HIGHLEVEL_API_KEY || !env.HIGHLEVEL_LOCATION_ID) {
    return { ok: false, skipped: "no_config" };
  }
  const { firstName, lastName } = splitName(contact.name);
  const payload: Record<string, unknown> = {
    locationId: env.HIGHLEVEL_LOCATION_ID,
    firstName,
    lastName,
    name: contact.name,
    phone: contact.phone,
    tags: contact.tags,
    source: "KTU Instant Tune-Up funnel",
  };
  if (contact.email) payload.email = contact.email;
  if (contact.address1) payload.address1 = contact.address1;
  if (contact.city) payload.city = contact.city;
  if (contact.state) payload.state = contact.state;
  if (contact.zip) payload.postalCode = contact.zip;
  if (contact.customFields) {
    payload.customFields = Object.entries(contact.customFields)
      .filter(([, v]) => v !== null && v !== undefined)
      .map(([key, value]) => ({ key, field_value: String(value) }));
  }

  try {
    const res = await fetch(`${HL_API}/contacts/upsert`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${env.HIGHLEVEL_API_KEY}`,
        Version: HL_VERSION,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      return { ok: false, error: `HL upsert HTTP ${res.status}: ${text.slice(0, 300)}` };
    }
    const data = (await res.json()) as { contact?: { id?: string } };
    return { ok: true, contactId: data.contact?.id };
  } catch (err) {
    return { ok: false, error: err instanceof Error ? err.message : String(err) };
  }
}
