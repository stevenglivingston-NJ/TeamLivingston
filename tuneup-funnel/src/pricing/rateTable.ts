/**
 * Builds the pricing RateTable from a ServiceMinder /services/all payload
 * (IncludeParts: true). The AI classifier outputs three buckets — L1_2, L3, L4
 * (SM merges levels 1 and 2). SM carries a single merged "Tune-Up Level 1 & 2"
 * part for the L1_2 bucket, so each bucket maps to exactly one SM part.
 */

import { QUOTE_RULES, SM_PRICING } from "../config";
import { dollarsToMilli } from "./money";

export type LevelBucket = "L1_2" | "L3" | "L4";

export interface RateTable {
  fetchedAt: string;
  serviceId: number;
  /** Effective base price, milli-dollars. */
  baseMilli: number;
  /** Where baseMilli came from: SM's BasePrice, or the owner-confirmed fallback while SM reads 0. */
  baseSource: "sm" | "owner_fallback";
  /** "Tune-Up Uplift" part, milli-dollars. Merged into the displayed base. */
  upliftMilli: number;
  levelRatesMilli: Record<LevelBucket, number>;
  /** null until the White Wash Premium part exists in SM (see config.ts). */
  whiteWashPremiumMilli: number | null;
  /** True when every rate needed for a plain (non-white-wash) quote is present and positive. */
  complete: boolean;
  /** Human-readable list of what's missing/zero, for ops and the audit log. */
  missing: string[];
}

interface SmPart {
  Id: number;
  Name: string | null;
  UnitPrice: number | null;
  IsActive: boolean;
}

interface SmService {
  Id: number;
  BasePrice: number | null;
  AvailableParts?: SmPart[] | null;
}

export interface SmServicesPayload {
  Matches: SmService[];
  ResultCode?: number;
  Message?: string;
}

export function buildRateTable(payload: SmServicesPayload, now: Date): RateTable {
  const missing: string[] = [];
  const service = payload.Matches?.find((s) => s.Id === SM_PRICING.serviceId);
  if (!service) {
    throw new Error(`ServiceMinder payload has no service ${SM_PRICING.serviceId}`);
  }

  const parts = new Map<number, SmPart>();
  for (const p of service.AvailableParts ?? []) {
    if (p.IsActive) parts.set(p.Id, p);
  }

  const partMilli = (id: number | null, label: string): number => {
    if (id === null) {
      missing.push(`${label}: no SM part ID configured`);
      return 0;
    }
    const part = parts.get(id);
    if (!part || part.UnitPrice == null) {
      missing.push(`${label}: part ${id} not found on service ${SM_PRICING.serviceId}`);
      return 0;
    }
    const milli = dollarsToMilli(part.UnitPrice);
    if (milli <= 0) missing.push(`${label}: part ${id} has non-positive price`);
    return milli;
  };

  const smBaseMilli = dollarsToMilli(service.BasePrice ?? 0);
  // SM base wins whenever it's set; the owner-confirmed $275 covers the gap
  // while the service record's Base Price still reads 0 (see config.ts).
  const baseSource: RateTable["baseSource"] = smBaseMilli > 0 ? "sm" : "owner_fallback";
  const baseMilli = smBaseMilli > 0 ? smBaseMilli : QUOTE_RULES.baseFallbackMilli;
  if (baseSource === "owner_fallback") {
    missing.push("base: SM BasePrice is 0 — using owner-confirmed $275 fallback (set BasePrice on service 30382 to clear this)");
  }
  const upliftMilli = partMilli(SM_PRICING.partIds.uplift, "uplift");
  const level12 = partMilli(SM_PRICING.partIds.level12, "level12");
  const level3 = partMilli(SM_PRICING.partIds.level3, "level3");
  const level4 = partMilli(SM_PRICING.partIds.level4, "level4");

  const whiteWashPremiumMilli =
    SM_PRICING.partIds.whiteWashPremium === null
      ? null
      : partMilli(SM_PRICING.partIds.whiteWashPremium, "whiteWashPremium");
  if (SM_PRICING.partIds.whiteWashPremium === null) {
    missing.push("whiteWashPremium: no SM part configured");
  }

  const levelRatesMilli: Record<LevelBucket, number> = {
    L1_2: level12,
    L3: level3,
    L4: level4,
  };

  // A quotable table needs the uplift part, a positive base, and positive level
  // rates. Uplift is checked on its own — the base fallback must never paper
  // over a missing/deleted SM part. White-wash is intentionally excluded: its
  // absence only blocks white-wash quotes.
  const complete =
    upliftMilli > 0 &&
    baseMilli > 0 &&
    Object.values(levelRatesMilli).every((r) => r > 0);
  if (!complete) missing.push("rate table incomplete: effective base or a level rate is missing/zero");

  return {
    fetchedAt: now.toISOString(),
    serviceId: SM_PRICING.serviceId,
    baseMilli,
    baseSource,
    upliftMilli,
    levelRatesMilli,
    whiteWashPremiumMilli,
    complete,
    missing,
  };
}
