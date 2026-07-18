import { describe, expect, it } from "vitest";
import { buildRateTable, type SmServicesPayload } from "../src/pricing/rateTable";
import liveSnapshot from "./fixtures/sm-services-live-2026-07-18.json";

const NOW = new Date("2026-07-18T12:00:00Z");

describe("buildRateTable against the live SM snapshot (2026-07-18)", () => {
  const table = buildRateTable(liveSnapshot as SmServicesPayload, NOW);

  it("extracts every rate to the penny", () => {
    expect(table.serviceId).toBe(30382);
    expect(table.baseMilli).toBe(0); // base folded into uplift; service BasePrice is $0
    expect(table.upliftMilli).toBe(390_350); // $390.35
    expect(table.levelRatesMilli.L1_2).toBe(96_000); // $96.00 merged part
    expect(table.levelRatesMilli.L3).toBe(112_000); // $112.00
    expect(table.levelRatesMilli.L4).toBe(136_000); // $136.00
    expect(table.whiteWashPremiumMilli).toBe(620_000); // $620.00 (now exists in SM)
  });

  it("is complete and quotable including white-wash", () => {
    expect(table.complete).toBe(true);
    expect(table.missing).toEqual([]);
  });
});

describe("buildRateTable failure modes", () => {
  it("throws when the Tune-Up Residential service is absent", () => {
    expect(() => buildRateTable({ Matches: [] }, NOW)).toThrow(/30382/);
  });

  it("marks the table incomplete when the merged level part is missing", () => {
    const broken = structuredClone(liveSnapshot) as SmServicesPayload;
    broken.Matches[0].AvailableParts = broken.Matches[0].AvailableParts!.filter(
      (p) => p.Id !== 199138, // drop Tune-Up Level 1 & 2
    );
    const table = buildRateTable(broken, NOW);
    expect(table.complete).toBe(false);
    expect(table.missing.join(" ")).toContain("level12");
  });

  it("ignores inactive parts", () => {
    const broken = structuredClone(liveSnapshot) as SmServicesPayload;
    broken.Matches[0].AvailableParts!.find((p) => p.Id === 199140)!.IsActive = false;
    const table = buildRateTable(broken, NOW);
    expect(table.complete).toBe(false);
    expect(table.missing.join(" ")).toContain("level4");
  });
});
