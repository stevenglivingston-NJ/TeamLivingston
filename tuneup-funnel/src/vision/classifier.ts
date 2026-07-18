/**
 * Cabinet-condition classifier: photos → Claude vision → structured VisionResult
 * → routing decision. The API call is isolated in classifyPhotos(); decide() is
 * pure so the routing rules are unit-testable without the model.
 */

import Anthropic from "@anthropic-ai/sdk";
import { VISION } from "../config";
import type { ClassificationOutcome, PhotoInput, VisionResult } from "./types";
import { CLASSIFIER_OUTPUT_SCHEMA, CLASSIFIER_SYSTEM_PROMPT, classifierUserText } from "./prompt";

export interface VisionEnv {
  ANTHROPIC_API_KEY: string;
}

/** Send the photos to Claude and return the schema-validated result. */
export async function classifyPhotos(
  env: VisionEnv,
  photos: PhotoInput[],
  declaredOpenings: number | null,
): Promise<VisionResult> {
  if (photos.length === 0) throw new Error("no photos to classify");
  if (photos.length > VISION.maxPhotos) {
    throw new Error(`too many photos: ${photos.length} > ${VISION.maxPhotos}`);
  }

  const client = new Anthropic({ apiKey: env.ANTHROPIC_API_KEY });

  const content: Anthropic.ContentBlockParam[] = photos.flatMap(
    (photo, i): Anthropic.ContentBlockParam[] => [
      { type: "text", text: `Photo ${i + 1}${photo.slot ? ` — slot: ${photo.slot}` : ""}:` },
      {
        type: "image",
        source: { type: "base64", media_type: photo.mediaType, data: photo.data },
      },
    ],
  );
  content.push({ type: "text", text: classifierUserText(declaredOpenings) });

  const response = await client.messages.create({
    model: VISION.model,
    max_tokens: 16000,
    thinking: { type: "adaptive" },
    system: [
      {
        type: "text",
        text: CLASSIFIER_SYSTEM_PROMPT,
        cache_control: { type: "ephemeral" },
      },
    ],
    output_config: {
      format: { type: "json_schema", schema: CLASSIFIER_OUTPUT_SCHEMA },
    },
    messages: [{ role: "user", content }],
  });

  if (response.stop_reason === "refusal") {
    throw new Error("vision model refused the request");
  }
  const text = response.content.find(
    (block): block is Anthropic.TextBlock => block.type === "text",
  );
  if (!text) throw new Error("vision model returned no text block");
  return parseVisionResult(text.text);
}

export function parseVisionResult(json: string): VisionResult {
  const raw = JSON.parse(json) as VisionResult;
  if (!["L1_2", "L3", "L4"].includes(raw.level)) {
    throw new Error(`invalid level bucket: ${raw.level}`);
  }
  if (typeof raw.confidence !== "number" || raw.confidence < 0 || raw.confidence > 1) {
    throw new Error(`invalid confidence: ${raw.confidence}`);
  }
  return raw;
}

/**
 * Apply the business rules to a model result. Pure — no I/O.
 *
 * Routing (build spec): low confidence, Level-5 signals, or uncertain white-wash
 * → NO instant price; "your quote is being finalized within 2 hours" + human
 * pricing. Opening mismatch beyond the threshold is flagged but still quotable.
 */
export function decide(
  result: VisionResult | null,
  declaredOpenings: number | null,
): ClassificationOutcome {
  if (result === null) {
    return { route: "human_review", result: null, reasons: ["classifier produced no result"] };
  }

  const reasons: string[] = [];
  if (result.notACandidate) {
    reasons.push("Level-5 signals: not a Tune-Up candidate — offer core services (refacing/redooring)");
  }
  if (result.confidence < VISION.minConfidence) {
    reasons.push(
      `classifier confidence ${result.confidence.toFixed(2)} below ${VISION.minConfidence}`,
    );
  }
  if (result.whiteWash && result.whiteWashConfidence < VISION.minConfidence) {
    reasons.push(
      `white-wash suspected but confidence ${result.whiteWashConfidence.toFixed(2)} too low to auto-price`,
    );
  }
  if (reasons.length > 0) {
    return { route: "human_review", result, reasons };
  }

  const openingMismatch =
    declaredOpenings !== null &&
    result.estimatedOpenings !== null &&
    Math.abs(result.estimatedOpenings - declaredOpenings) > VISION.openingMismatchThreshold;

  return { route: "instant_quote", result, openingMismatch };
}
