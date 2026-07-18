/**
 * Calibration harness: runs the vision classifier against past jobs with known
 * charged levels and reports accuracy + a confusion matrix.
 *
 * Usage:
 *   1. cp calibration/manifest.example.json calibration/manifest.json
 *   2. put BEFORE photos under calibration/photos/... and label each job
 *   3. ANTHROPIC_API_KEY=sk-... npm run calibrate
 */

import { readFileSync } from "node:fs";
import { extname, join } from "node:path";
import { classifyPhotos, decide } from "../src/vision/classifier";
import type { PhotoInput } from "../src/vision/types";
import type { LevelBucket } from "../src/pricing/rateTable";

interface CalibrationJob {
  job: string;
  levelCharged: LevelBucket;
  whiteWash: boolean;
  declaredOpenings: number | null;
  photos: string[];
}

const MEDIA_TYPES: Record<string, PhotoInput["mediaType"]> = {
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".png": "image/png",
  ".webp": "image/webp",
  ".gif": "image/gif",
};

async function main(): Promise<void> {
  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey) throw new Error("set ANTHROPIC_API_KEY");

  const root = join(import.meta.dirname, "..", "calibration");
  const manifest = JSON.parse(readFileSync(join(root, "manifest.json"), "utf8")) as {
    jobs: CalibrationJob[];
  };

  const buckets: LevelBucket[] = ["L1_2", "L3", "L4"];
  const confusion = new Map<string, number>();
  let correct = 0;
  let humanReview = 0;
  let whiteWashHits = 0;
  let whiteWashTotal = 0;

  for (const job of manifest.jobs) {
    const photos: PhotoInput[] = job.photos.map((rel) => {
      const mediaType = MEDIA_TYPES[extname(rel).toLowerCase()];
      if (!mediaType) throw new Error(`${job.job}: unsupported photo type ${rel}`);
      return { data: readFileSync(join(root, rel)).toString("base64"), mediaType, slot: rel };
    });

    const result = await classifyPhotos({ ANTHROPIC_API_KEY: apiKey }, photos, job.declaredOpenings);
    const outcome = decide(result, job.declaredOpenings);

    const predicted = result.level;
    const hit = predicted === job.levelCharged;
    if (hit) correct += 1;
    if (outcome.route === "human_review") humanReview += 1;
    confusion.set(
      `${job.levelCharged}→${predicted}`,
      (confusion.get(`${job.levelCharged}→${predicted}`) ?? 0) + 1,
    );

    if (job.whiteWash) {
      whiteWashTotal += 1;
      if (result.whiteWash) whiteWashHits += 1;
    }

    console.log(
      `${hit ? "✓" : "✗"} ${job.job}: charged=${job.levelCharged} predicted=${predicted} ` +
        `conf=${result.confidence.toFixed(2)} route=${outcome.route}` +
        (result.flags.length ? ` flags=[${result.flags.join("; ")}]` : ""),
    );
  }

  const total = manifest.jobs.length;
  console.log(`\nAccuracy: ${correct}/${total} (${((100 * correct) / total).toFixed(1)}%)`);
  console.log(`Routed to human review: ${humanReview}/${total}`);
  if (whiteWashTotal > 0) console.log(`White-wash detected: ${whiteWashHits}/${whiteWashTotal}`);
  console.log("\nConfusion (charged→predicted):");
  for (const actual of buckets) {
    const row = buckets
      .map((p) => `${p}: ${confusion.get(`${actual}→${p}`) ?? 0}`)
      .join("  ");
    console.log(`  ${actual}  →  ${row}`);
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
