import { describe, expect, it } from "vitest";
import { dollarsToMilli, formatCents, milliToCents, mulDivHalfUp } from "../src/pricing/money";

describe("dollarsToMilli", () => {
  it("holds ServiceMinder 3-decimal rates exactly", () => {
    expect(dollarsToMilli(96.485)).toBe(96485);
    expect(dollarsToMilli(111.329)).toBe(111329);
    expect(dollarsToMilli(136.07)).toBe(136070);
    expect(dollarsToMilli(618.5)).toBe(618500);
    expect(dollarsToMilli(25.75)).toBe(25750);
    expect(dollarsToMilli(0)).toBe(0);
  });

  it("rejects non-finite input", () => {
    expect(() => dollarsToMilli(NaN)).toThrow();
    expect(() => dollarsToMilli(Infinity)).toThrow();
  });
});

describe("milliToCents (half-up)", () => {
  it("rounds .5 tenth-cents up", () => {
    expect(milliToCents(1315045)).toBe(131505); // $1,315.045 → $1,315.05
    expect(milliToCents(2309585)).toBe(230959); // $2,309.585 → $2,309.59
  });
  it("rounds below .5 down", () => {
    expect(milliToCents(1315044)).toBe(131504);
    expect(milliToCents(1315040)).toBe(131504);
  });
  it("keeps exact cents unchanged", () => {
    expect(milliToCents(200000 * 10)).toBe(200000);
  });
});

describe("mulDivHalfUp", () => {
  it("computes 10% with half-up rounding", () => {
    expect(mulDivHalfUp(230959, 10, 100)).toBe(23096); // 23095.9 → 23096
    expect(mulDivHalfUp(200000, 10, 100)).toBe(20000);
    expect(mulDivHalfUp(105, 10, 100)).toBe(11); // 10.5 → 11
    expect(mulDivHalfUp(104, 10, 100)).toBe(10); // 10.4 → 10
  });
  it("computes 50% deposits with half-cent rounding up", () => {
    expect(mulDivHalfUp(207863, 50, 100)).toBe(103932); // 103931.5 → up
    expect(mulDivHalfUp(207862, 50, 100)).toBe(103931);
  });
});

describe("formatCents", () => {
  it("formats for logs", () => {
    expect(formatCents(230959)).toBe("$2,309.59");
    expect(formatCents(5)).toBe("$0.05");
  });
});
