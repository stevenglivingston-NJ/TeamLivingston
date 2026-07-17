/**
 * Builds the pricing RateTable from a ServiceMinder /services/all payload
 * (IncludeParts: true). The AI classifier outputs three buckets — L1_2, L3, L4
 * (SM merges levels 1 and 2). SM currently prices Level 1 and Level 2 as
 * separate parts, so L1_2 uses the higher of the two (conservative) until the
 * owner confirms the merged-rate policy.
 */

import { SM_PRICING } from "../config";
import { dollarsToMilli } from "./money";

export type LevelBucket = "L1_2" | "L3" | "L4";

export interface RateTable {
  fetchedAt: string;
  serviceId: number;
  /** SM service BasePrice, milli-dollars. */
  baseMilli: number;
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

  const baseMilli = dollarsToMilli(service.BasePrice ?? 0);
  const upliftMilli = partMilli(SM_PRICING.partIds.uplift, "uplift");
  const level1 = partMilli(SM_PRICING.partIds.level1, "level1");
  const level2 = partMilli(SM_PRICING.partIds.level2, "level2");
  const level3 = partMilli(SM_PRICING.partIds.level3, "level3");
  const level4 = partMilli(SM_PRICING.partIds.level4, "level4");

  const whiteWashPremiumMilli =
    SM_PRICING.partIds.whiteWashPremium === null
      ? null
      : partMilli(SM_PRICING.partIds.whiteWashPremium, "whiteWashPremium");
  if (SM_PRICING.partIds.whiteWashPremium === null) {
    missing.push("whiteWashPremium: no SM part exists yet (owner to create)");
  }

  const levelRatesMilli: Record<LevelBucket, number> = {
    L1_2: Math.max(level1, level2),
    L3: level3,
    L4: level4,
  };

  // A quotable table needs a positive effective base and positive level rates.
  // White-wash is intentionally excluded: its absence only blocks white-wash quotes.
  const complete =
    baseMilli + upliftMilli > 0 &&
    Object.values(levelRatesMilli).every((r) => r > 0);
  if (!complete) missing.push("rate table incomplete: effective base or a level rate is missing/zero");

  return {
    fetchedAt: now.toISOString(),
    serviceId: SM_PRICING.serviceId,
    baseMilli,
    upliftMilli,
    levelRatesMilli,
    whiteWashPremiumMilli,
    complete,
    missing,
  };
}
