import type { LevelBucket } from "../pricing/rateTable";

/** One customer photo, ready to send to the vision model. */
export interface PhotoInput {
  /** Base64-encoded image bytes (no data: prefix). */
  data: string;
  mediaType: "image/jpeg" | "image/png" | "image/webp" | "image/gif";
  /** Which funnel slot this came from, e.g. "full-kitchen wide" — shown to the model. */
  slot?: string;
}

/** Raw structured output from the vision model (schema-enforced). */
export interface VisionResult {
  /** Priced bucket. SM merges levels 1 and 2 into L1_2. */
  level: LevelBucket;
  /** 0–1 confidence in the level assignment. */
  confidence: number;
  /** True when a white-washed/pickled finish is detected → premium applies. */
  whiteWash: boolean;
  whiteWashConfidence: number;
  /** Openings the model counted across the wide shots; null if not countable. */
  estimatedOpenings: number | null;
  /**
   * Level-5 signals: non-repairable damage, DIY damage, or work a Tune-Up
   * cannot do (sun-damage, discolored melamine end panels). Not a Tune-Up
   * candidate → human review + offer core services.
   */
  notACandidate: boolean;
  /** Plain-English condition summary — shown to the team and (edited) to the customer. */
  conditionNotes: string;
  /** Anything the team should double-check (nicotine suspicion, poor photo quality, ...). */
  flags: string[];
}

/** Final routing decision after applying business rules to the model output. */
export type ClassificationOutcome =
  | {
      route: "instant_quote";
      result: VisionResult;
      /** True when AI opening count differs from the customer's by more than the threshold. */
      openingMismatch: boolean;
    }
  | {
      route: "human_review";
      result: VisionResult | null;
      /** Why the funnel must not show an instant price. */
      reasons: string[];
    };
