/**
 * Thin client for the Cloudflare Worker API. All funnel gates write to D1 through
 * these calls so the session/audit trail is server-side (build spec: every gate
 * writes to D1). Network failures never block the customer — callers fall back
 * to local state and the funnel keeps moving.
 */

import type { LevelBucket } from "./types";

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${path} → HTTP ${res.status}`);
  return (await res.json()) as T;
}

export async function createSession(): Promise<{ id: string }> {
  return post("/api/session", {});
}

export async function saveProgress(
  id: string,
  patch: Record<string, unknown>,
): Promise<void> {
  await post(`/api/session/${id}`, patch);
}

export async function submitLead(
  id: string,
  lead: { name: string; phone: string; email: string },
): Promise<void> {
  await post("/api/lead", { sessionId: id, ...lead });
}

export async function requestCallback(payload: {
  sessionId: string | null;
  name: string;
  phone: string;
  bestTime: string;
}): Promise<void> {
  await post("/api/callback", payload);
}

export interface PreviewResult {
  quotable: boolean;
  quoteCents?: number;
  depositCents?: number;
  floorApplied?: boolean;
  whiteWashCents?: number | null;
  reasons?: string[];
}

export async function previewQuote(input: {
  openings: number;
  level: LevelBucket;
  whiteWash: boolean;
}): Promise<PreviewResult> {
  return post("/api/quote/preview", input);
}

/** Upload one captured photo; returns the R2 key. */
export async function uploadPhoto(
  sessionId: string,
  slotKey: string,
  file: File,
): Promise<{ key: string } | { error: string }> {
  const res = await fetch(
    `/api/photo?session=${encodeURIComponent(sessionId)}&slot=${encodeURIComponent(slotKey)}`,
    { method: "POST", headers: { "Content-Type": file.type }, body: file },
  );
  return (await res.json()) as { key: string } | { error: string };
}

export interface ClassifyOutcome {
  route: "instant_quote" | "human_review";
  result: {
    level: LevelBucket;
    confidence: number;
    whiteWash: boolean;
    conditionNotes: string;
    estimatedOpenings: number | null;
  } | null;
  openingMismatch?: boolean;
  reasons?: string[];
}

export async function classifyPhotos(
  photoKeys: string[],
  openings: number,
): Promise<ClassifyOutcome> {
  return post("/api/vision/classify", { photoKeys, openings });
}

export function formatUsd(cents: number): string {
  return `$${(cents / 100).toLocaleString("en-US", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  })}`;
}
