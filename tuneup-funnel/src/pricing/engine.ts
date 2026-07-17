/**
 * The pricing engine. Pure and deterministic — all inputs explicit, no I/O —
 * so it can be unit-tested to the penny against ServiceMinder values.
 *
 * Effective Base = SM base + SM uplift          (uplift never shown as a line)
 * Subtotal       = Effective Base + level rate × openings [+ white-wash premium]
 * Quote          = max(Subtotal, $2,000 floor)  → cents, half-up
 * SDD discount   = min(10% of Quote, $2,500)    → cents, half-up; valid 24h
 * Deposit        = 50% of (Quote − discount)    → cents, half-up
 */

import { QUOTE_RULES } from "../config";
import { milliToCents, mulDivHalfUp } from "./money";
import type { LevelBucket, RateTable } from "./rateTable";

export interface QuoteInput {
  openings: number;
  level: LevelBucket;
  /** AI-detected pickled/white-washed finish → premium auto-added. */
  whiteWash: boolean;
  /** SDD promo code applied. */
  sdd: boolean;
}

export type QuoteResult =
  | {
      quotable: true;
      /** Firm price shown to the customer, cents. */
      quoteCents: number;
      /** True when the $2,000 minimum overrode the computed subtotal. */
      floorApplied: boolean;
      /** Premium included in the quote, cents; null when not applied. */
      whiteWashCents: number | null;
      sddDiscountCents: number;
      /** Quote − SDD discount, cents. */
      totalCents: number;
      /** 50% of total, cents. */
      depositCents: number;
    }
  | {
      quotable: false;
      /** Why this must route to human pricing instead of an instant quote. */
      reasons: string[];
    };

export function computeQuote(input: QuoteInput, rates: RateTable): QuoteResult {
  const reasons: string[] = [];
  if (!Number.isInteger(input.openings) || input.openings <= 0) {
    reasons.push(`invalid opening count: ${input.openings}`);
  }
  if (!rates.complete) {
    reasons.push(...rates.missing);
  }
  if (input.whiteWash && (rates.whiteWashPremiumMilli === null || rates.whiteWashPremiumMilli <= 0)) {
    reasons.push("white-wash finish detected but no White Wash Premium rate in ServiceMinder");
  }
  if (reasons.length > 0) return { quotable: false, reasons };

  const effectiveBaseMilli = rates.baseMilli + rates.upliftMilli;
  const whiteWashMilli = input.whiteWash ? rates.whiteWashPremiumMilli! : 0;
  const subtotalMilli =
    effectiveBaseMilli + rates.levelRatesMilli[input.level] * input.openings + whiteWashMilli;

  const subtotalCents = milliToCents(subtotalMilli);
  const floorApplied = subtotalCents < QUOTE_RULES.floorCents;
  const quoteCents = floorApplied ? QUOTE_RULES.floorCents : subtotalCents;

  const sddDiscountCents = input.sdd
    ? Math.min(mulDivHalfUp(quoteCents, QUOTE_RULES.sddPercent, 100), QUOTE_RULES.sddCapCents)
    : 0;

  const totalCents = quoteCents - sddDiscountCents;
  const depositCents = mulDivHalfUp(totalCents, QUOTE_RULES.depositPercent, 100);

  return {
    quotable: true,
    quoteCents,
    floorApplied,
    whiteWashCents: input.whiteWash ? milliToCents(whiteWashMilli) : null,
    sddDiscountCents,
    totalCents,
    depositCents,
  };
}

/** SDD expiry: 24 hours from the moment the price was revealed. */
export function sddDeadline(quotedAt: Date): Date {
  return new Date(quotedAt.getTime() + QUOTE_RULES.sddValidHours * 3_600_000);
}
