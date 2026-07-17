/**
 * Pricing engine — to-the-penny tests.
 *
 * Two rate tables are exercised:
 *  1. "spec rates" — the build-spec approximations (base $250, uplift $389.65,
 *     L1_2 $96.485, L3 $111.329, L4 $136.07, white-wash $618.50). These prove the
 *     math handles 3-decimal rates exactly.
 *  2. The live SM snapshot from 2026-07-17 via buildRateTable.
 * Expected values were computed independently (exact integer arithmetic), not by
 * running the engine.
 */

import { describe, expect, it } from "vitest";
import { computeQuote, sddDeadline } from "../src/pricing/engine";
import { buildRateTable, type RateTable, type SmServicesPayload } from "../src/pricing/rateTable";
import liveSnapshot from "./fixtures/sm-services-live-2026-07-17.json";

const specRates: RateTable = {
  fetchedAt: "2026-07-17T12:00:00.000Z",
  serviceId: 30382,
  baseMilli: 250_000, // $250
  upliftMilli: 389_650, // $389.65
  levelRatesMilli: { L1_2: 96_485, L3: 111_329, L4: 136_070 },
  whiteWashPremiumMilli: 618_500, // $618.50
  complete: true,
  missing: [],
};

function ok(result: ReturnType<typeof computeQuote>) {
  if (!result.quotable) throw new Error(`expected quotable, got: ${result.reasons.join("; ")}`);
  return result;
}

describe("spec rates — floor, SDD, deposit to the penny", () => {
  it("7 openings L1_2 lands under the floor: $2,000 firm, SDD $200, deposit $900", () => {
    // 639.65 + 96.485×7 = $1,315.045 → floor
    const r = ok(computeQuote({ openings: 7, level: "L1_2", whiteWash: false, sdd: true }, specRates));
    expect(r.floorApplied).toBe(true);
    expect(r.quoteCents).toBe(200_000);
    expect(r.sddDiscountCents).toBe(20_000);
    expect(r.totalCents).toBe(180_000);
    expect(r.depositCents).toBe(90_000);
  });

  it("15 openings L3: $2,309.59, SDD $230.96, total $2,078.63, deposit $1,039.32", () => {
    // 639.65 + 111.329×15 = 2,309.585 → half-up 2,309.59; deposit 103,931.5¢ → half-up
    const r = ok(computeQuote({ openings: 15, level: "L3", whiteWash: false, sdd: true }, specRates));
    expect(r.floorApplied).toBe(false);
    expect(r.quoteCents).toBe(230_959);
    expect(r.sddDiscountCents).toBe(23_096);
    expect(r.totalCents).toBe(207_863);
    expect(r.depositCents).toBe(103_932);
  });

  it("12 openings L4 + white-wash: $2,890.99, SDD $289.10, total $2,601.89, deposit $1,300.95", () => {
    // 639.65 + 136.07×12 + 618.50 = 2,890.99
    const r = ok(computeQuote({ openings: 12, level: "L4", whiteWash: true, sdd: true }, specRates));
    expect(r.quoteCents).toBe(289_099);
    expect(r.whiteWashCents).toBe(61_850);
    expect(r.sddDiscountCents).toBe(28_910); // 28,909.9¢ → half-up
    expect(r.totalCents).toBe(260_189);
    expect(r.depositCents).toBe(130_095); // 130,094.5¢ → half-up
  });

  it("no SDD → no discount, deposit is half the quote", () => {
    const r = ok(computeQuote({ openings: 15, level: "L3", whiteWash: false, sdd: false }, specRates));
    expect(r.sddDiscountCents).toBe(0);
    expect(r.totalCents).toBe(230_959);
    expect(r.depositCents).toBe(115_480); // 115,479.5¢ → half-up
  });

  it("caps the SDD discount at $2,500", () => {
    // Base $30,000 + 96.485×1 = $30,096.485 → half-up $30,096.49; 10% = $3,009.65 → capped
    const bigJob: RateTable = { ...specRates, baseMilli: 30_000_000, upliftMilli: 0 };
    const r = ok(computeQuote({ openings: 1, level: "L1_2", whiteWash: false, sdd: true }, bigJob));
    expect(r.quoteCents).toBe(3_009_649);
    expect(r.sddDiscountCents).toBe(250_000);
    expect(r.totalCents).toBe(2_759_649);
    expect(r.depositCents).toBe(1_379_825); // 1,379,824.5¢ → half-up
  });
});

describe("live SM rates (2026-07-17 snapshot)", () => {
  const live = buildRateTable(liveSnapshot as SmServicesPayload, new Date("2026-07-17T12:00:00Z"));

  it("10 openings L1_2 is under the floor today: $2,000 firm", () => {
    // 0 + 619.35 + 27.81×10 = $897.45 → floor
    const r = ok(computeQuote({ openings: 10, level: "L1_2", whiteWash: false, sdd: false }, live));
    expect(r.floorApplied).toBe(true);
    expect(r.quoteCents).toBe(200_000);
    expect(r.depositCents).toBe(100_000);
  });

  it("white-wash quotes are NOT quotable until the SM part exists", () => {
    const r = computeQuote({ openings: 10, level: "L1_2", whiteWash: true, sdd: false }, live);
    expect(r.quotable).toBe(false);
    if (!r.quotable) expect(r.reasons.join(" ")).toContain("White Wash Premium");
  });
});

describe("non-quotable inputs route to human pricing", () => {
  it("rejects zero/negative/fractional openings", () => {
    for (const openings of [0, -3, 2.5]) {
      const r = computeQuote({ openings, level: "L3", whiteWash: false, sdd: false }, specRates);
      expect(r.quotable).toBe(false);
    }
  });

  it("rejects an incomplete rate table", () => {
    const incomplete: RateTable = {
      ...specRates,
      levelRatesMilli: { ...specRates.levelRatesMilli, L3: 0 },
      complete: false,
      missing: ["level3: part 199139 has non-positive price"],
    };
    const r = computeQuote({ openings: 10, level: "L3", whiteWash: false, sdd: false }, incomplete);
    expect(r.quotable).toBe(false);
    if (!r.quotable) expect(r.reasons.join(" ")).toContain("level3");
  });
});

describe("SDD deadline", () => {
  it("is exactly 24 hours after the quote", () => {
    expect(sddDeadline(new Date("2026-07-17T15:30:00Z")).toISOString()).toBe(
      "2026-07-18T15:30:00.000Z",
    );
  });
});
