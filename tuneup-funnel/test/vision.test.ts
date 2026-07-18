import { describe, expect, it } from "vitest";
import { decide, parseVisionResult } from "../src/vision/classifier";
import { CLASSIFIER_OUTPUT_SCHEMA, CLASSIFIER_SYSTEM_PROMPT } from "../src/vision/prompt";
import type { VisionResult } from "../src/vision/types";

const good: VisionResult = {
  level: "L3",
  confidence: 0.88,
  whiteWash: false,
  whiteWashConfidence: 0.95,
  estimatedOpenings: 18,
  notACandidate: false,
  conditionNotes: "Deep scratches into the substrate near handles; sink base shows water wear.",
  flags: [],
};

describe("decide — routing rules", () => {
  it("high-confidence result → instant quote", () => {
    const outcome = decide(good, 17);
    expect(outcome.route).toBe("instant_quote");
    if (outcome.route === "instant_quote") expect(outcome.openingMismatch).toBe(false);
  });

  it("low confidence → human review, never a guessed price", () => {
    const outcome = decide({ ...good, confidence: 0.55 }, 17);
    expect(outcome.route).toBe("human_review");
    if (outcome.route === "human_review") {
      expect(outcome.reasons.join(" ")).toContain("confidence 0.55");
    }
  });

  it("Level-5 signals → human review with core-services routing", () => {
    const outcome = decide({ ...good, notACandidate: true }, 17);
    expect(outcome.route).toBe("human_review");
    if (outcome.route === "human_review") {
      expect(outcome.reasons.join(" ")).toContain("not a Tune-Up candidate");
    }
  });

  it("uncertain white-wash → human review (premium changes the price)", () => {
    const outcome = decide({ ...good, whiteWash: true, whiteWashConfidence: 0.5 }, 17);
    expect(outcome.route).toBe("human_review");
  });

  it("confident white-wash stays quotable", () => {
    const outcome = decide({ ...good, whiteWash: true, whiteWashConfidence: 0.9 }, 17);
    expect(outcome.route).toBe("instant_quote");
  });

  it("opening mismatch beyond threshold is flagged but still quotable", () => {
    const outcome = decide({ ...good, estimatedOpenings: 25 }, 17); // |25−17| = 8 > 2
    expect(outcome.route).toBe("instant_quote");
    if (outcome.route === "instant_quote") expect(outcome.openingMismatch).toBe(true);
  });

  it("mismatch within threshold, or missing counts, is not flagged", () => {
    for (const [estimated, declared] of [
      [19, 17],
      [null, 17],
      [19, null],
    ] as const) {
      const outcome = decide({ ...good, estimatedOpenings: estimated }, declared);
      expect(outcome.route).toBe("instant_quote");
      if (outcome.route === "instant_quote") expect(outcome.openingMismatch).toBe(false);
    }
  });

  it("null result (model/API failure) → human review", () => {
    const outcome = decide(null, 17);
    expect(outcome.route).toBe("human_review");
  });
});

describe("parseVisionResult", () => {
  it("accepts a valid schema-shaped payload", () => {
    expect(parseVisionResult(JSON.stringify(good))).toEqual(good);
  });

  it("rejects unknown level buckets and out-of-range confidence", () => {
    expect(() => parseVisionResult(JSON.stringify({ ...good, level: "L2" }))).toThrow(/bucket/);
    expect(() => parseVisionResult(JSON.stringify({ ...good, confidence: 1.4 }))).toThrow(
      /confidence/,
    );
  });
});

describe("prompt/schema consistency", () => {
  it("schema requires every VisionResult field", () => {
    expect(CLASSIFIER_OUTPUT_SCHEMA.required).toEqual(
      expect.arrayContaining(Object.keys(good)),
    );
    expect(CLASSIFIER_OUTPUT_SCHEMA.additionalProperties).toBe(false);
  });

  it("system prompt carries the load-bearing rubric rules", () => {
    for (const needle of ["30%", "10%", "sink base", "nicotine", "pickled", "L1_2"]) {
      expect(CLASSIFIER_SYSTEM_PROMPT).toContain(needle);
    }
  });
});
