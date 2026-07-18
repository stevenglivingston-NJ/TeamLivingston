/**
 * Business constants and the ServiceMinder mapping.
 *
 * Rates themselves are NEVER hardcoded here — they are pulled live from
 * ServiceMinder by the cron sync. This file only says WHERE in SM each rate
 * lives (service/part IDs, live-verified 2026-07-18) and the fixed business
 * rules from the build spec ($2k floor, deposit).
 */

export const SM_API_BASE = "https://serviceminder.io/api";

export const SM_PRICING = {
  /** "Tune-Up Residential" — the service whose BasePrice + parts drive quotes. */
  serviceId: 30382,
  partIds: {
    /** "Tune-Up Uplift" — merged into the displayed base, never a customer-visible line. */
    uplift: 199137,
    /**
     * "Tune-Up Level 1 & 2" — SM now carries a single merged part for the L1_2
     * bucket (the owner rebuilt the Tune-Up template 2026-07-18 with per-opening
     * pricing). No more max(L1, L2) — the merged part is authoritative.
     */
    level12: 199138,
    level3: 199139,
    level4: 199140,
    /**
     * "White Wash Premium" — created 2026-07-18. NOTE: SM reused part ID 1557033
     * (formerly "Tune-Up Level 2") for this, so the mapping changed with the
     * template rebuild. Verify by name, not just ID, if SM is re-templated again.
     */
    whiteWashPremium: 1557033 as number | null,
  },
} as const;

export const QUOTE_RULES = {
  /** $2,000 project minimum. */
  floorCents: 200_000,
  /** Deposit is 50% of the quote. */
  depositPercent: 50,
} as const;

export const VISION = {
  /** Vision-capable model for cabinet condition analysis. */
  model: "claude-opus-4-8",
  /** Below this classifier confidence, skip price reveal → human pricing. */
  minConfidence: 0.7,
  /** AI-estimated openings differing from customer count by more than this → flag. */
  openingMismatchThreshold: 2,
  /** 4 required + 4 optional photo slots. */
  maxPhotos: 8,
} as const;

export const KV_KEYS = {
  /** Freshly synced rate table; TTL'd so staleness is detectable. */
  current: "pricing:current",
  /** Last successfully validated table; no TTL — outage fallback. */
  lastGood: "pricing:last-good",
} as const;

/** KV TTL for pricing:current. Cron runs every 15 min; 1h tolerates 3 missed runs. */
export const PRICING_CURRENT_TTL_SECONDS = 3600;
