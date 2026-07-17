import { describe, expect, it } from "vitest";
import { buildRateTable, type SmServicesPayload } from "../src/pricing/rateTable";
import liveSnapshot from "./fixtures/sm-services-live-2026-07-17.json";

const NOW = new Date("2026-07-17T12:00:00Z");

describe("buildRateTable against the live SM snapshot (2026-07-17)", () => {
  const table = buildRateTable(liveSnapshot as SmServicesPayload, NOW);

  it("extracts every rate to the penny", () => {
    expect(table.serviceId).toBe(30382);
    expect(table.baseMilli).toBe(0); // SM gap: BasePrice is $0 today (see README)
    expect(table.upliftMilli).toBe(619350); // $619.35
    expect(table.levelRatesMilli.L3).toBe(29870);
    expect(table.levelRatesMilli.L4).toBe(31930);
  });

  it("uses the higher of Level 1/Level 2 for the merged L1_2 bucket", () => {
    expect(table.levelRatesMilli.L1_2).toBe(27810); // max($25.75, $27.81)
  });

  it("is complete for plain quotes but flags the missing white-wash part", () => {
    expect(table.complete).toBe(true);
    expect(table.whiteWashPremiumMilli).toBeNull();
    expect(table.missing.join(" ")).toContain("whiteWashPremium");
  });
});

describe("buildRateTable failure modes", () => {
  it("throws when the Tune-Up Residential service is absent", () => {
    expect(() => buildRateTable({ Matches: [] }, NOW)).toThrow(/30382/);
  });

  it("marks the table incomplete when a level part is missing", () => {
    const broken = structuredClone(liveSnapshot) as SmServicesPayload;
    broken.Matches[0].AvailableParts = broken.Matches[0].AvailableParts!.filter(
      (p) => p.Id !== 199139, // drop Tune-Up Level 3
    );
    const table = buildRateTable(broken, NOW);
    expect(table.complete).toBe(false);
    expect(table.missing.join(" ")).toContain("level3");
  });

  it("ignores inactive parts", () => {
    const broken = structuredClone(liveSnapshot) as SmServicesPayload;
    broken.Matches[0].AvailableParts!.find((p) => p.Id === 199140)!.IsActive = false;
    const table = buildRateTable(broken, NOW);
    expect(table.complete).toBe(false);
    expect(table.missing.join(" ")).toContain("level4");
  });
});
