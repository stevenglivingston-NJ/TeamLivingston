/**
 * Business constants and the ServiceMinder mapping.
 *
 * Rates themselves are NEVER hardcoded here — they are pulled live from
 * ServiceMinder by the cron sync. This file only says WHERE in SM each rate
 * lives (service/part IDs, live-verified 2026-07-17) and the fixed business
 * rules from the build spec ($2k floor, SDD, deposit).
 */

export const SM_API_BASE = "https://serviceminder.io/api";

export const SM_PRICING = {
  /** "Tune-Up Residential" — the service whose BasePrice + parts drive quotes. */
  serviceId: 30382,
  partIds: {
    /** "Tune-Up Uplift" — merged into the displayed base, never a customer-visible line. */
    uplift: 199137,
    level1: 199138,
    level2: 1557033,
    level3: 199139,
    level4: 199140,
    /**
     * "White Wash Premium" does not exist in SM yet (gap found during Phase 1
     * scaffold — see README). Set the part ID here once the owner creates it;
     * until then white-wash-flagged quotes are non-quotable → human review.
     */
    whiteWashPremium: null as number | null,
  },
} as const;

export const QUOTE_RULES = {
  /** $2,000 project minimum. */
  floorCents: 200_000,
  /** SDD promo: 10% off, capped at $2,500, valid 24h from quote. */
  sddPercent: 10,
  sddCapCents: 250_000,
  sddValidHours: 24,
  /** Deposit is 50% of the post-discount quote. */
  depositPercent: 50,
} as const;

export const KV_KEYS = {
  /** Freshly synced rate table; TTL'd so staleness is detectable. */
  current: "pricing:current",
  /** Last successfully validated table; no TTL — outage fallback. */
  lastGood: "pricing:last-good",
} as const;

/** KV TTL for pricing:current. Cron runs every 15 min; 1h tolerates 3 missed runs. */
export const PRICING_CURRENT_TTL_SECONDS = 3600;
