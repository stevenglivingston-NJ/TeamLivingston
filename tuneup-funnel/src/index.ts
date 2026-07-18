/**
 * Worker entry. Phases 1–2 expose the pricing engine, the SM cron sync, and the
 * vision classifier; the customer funnel routes (sessions, checkout) land in P3/P4.
 */

import { computeQuote, type QuoteInput } from "./pricing/engine";
import type { LevelBucket } from "./pricing/rateTable";
import { loadRateTable } from "./pricing/store";
import { syncPricing } from "./sync/pricingSync";
import { classifyPhotos, decide } from "./vision/classifier";
import type { PhotoInput } from "./vision/types";
import {
  createCallback,
  createLead,
  createSession,
  patchSession,
  uploadPhoto,
} from "./http/funnel";

export interface Env {
  PRICING_KV: KVNamespace;
  DB: D1Database;
  PHOTOS?: R2Bucket; // optional until R2 is enabled in the Cloudflare dashboard
  SERVICEMINDER_API_KEY: string;
  ANTHROPIC_API_KEY: string;
}

const LEVELS: readonly LevelBucket[] = ["L1_2", "L3", "L4"];
const IMAGE_TYPES = ["image/jpeg", "image/png", "image/webp", "image/gif"] as const;

export default {
  async scheduled(_event: ScheduledEvent, env: Env, ctx: ExecutionContext): Promise<void> {
    ctx.waitUntil(
      syncPricing({ env, kv: env.PRICING_KV, db: env.DB }).then((result) => {
        if (!result.ok) console.error("pricing sync failed:", result.error);
        else if (!result.table?.complete)
          console.warn("pricing sync incomplete:", result.table?.missing);
      }),
    );
  },

  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);

    // ---- Funnel session / lead / callback / photo (Phase 3) ----
    if (request.method === "POST" && url.pathname === "/api/session") {
      return createSession(env);
    }
    const sessionMatch = url.pathname.match(/^\/api\/session\/([\w-]+)$/);
    if (request.method === "POST" && sessionMatch) {
      const body = await safeJson(request);
      if (body === null) return json({ error: "invalid JSON body" }, 400);
      return patchSession(env, sessionMatch[1], body as Record<string, unknown>);
    }
    if (request.method === "POST" && url.pathname === "/api/lead") {
      const body = await safeJson(request);
      if (body === null) return json({ error: "invalid JSON body" }, 400);
      return createLead(env, body as Record<string, string>);
    }
    if (request.method === "POST" && url.pathname === "/api/callback") {
      const body = await safeJson(request);
      if (body === null) return json({ error: "invalid JSON body" }, 400);
      return createCallback(env, body as Record<string, string>);
    }
    if (request.method === "POST" && url.pathname === "/api/photo") {
      return uploadPhoto(
        env,
        url.searchParams.get("session") ?? "",
        url.searchParams.get("slot") ?? "",
        request,
      );
    }

    if (request.method === "GET" && url.pathname === "/api/health") {
      const rates = await loadRateTable(env.PRICING_KV);
      return json({
        ok: true,
        rates: rates
          ? { fetchedAt: rates.table.fetchedAt, stale: rates.stale, complete: rates.table.complete }
          : null,
      });
    }

    if (request.method === "GET" && url.pathname === "/api/rates") {
      const rates = await loadRateTable(env.PRICING_KV);
      if (!rates) return json({ error: "no rate table synced yet" }, 503);
      return json({ stale: rates.stale, table: rates.table });
    }

    if (request.method === "POST" && url.pathname === "/api/quote/preview") {
      let body: Partial<QuoteInput>;
      try {
        body = (await request.json()) as Partial<QuoteInput>;
      } catch {
        return json({ error: "invalid JSON body" }, 400);
      }
      if (typeof body.openings !== "number" || !LEVELS.includes(body.level as LevelBucket)) {
        return json({ error: "expected { openings: number, level: L1_2|L3|L4, whiteWash? }" }, 400);
      }
      const rates = await loadRateTable(env.PRICING_KV);
      if (!rates) return json({ error: "no rate table available; sync has not run" }, 503);
      const result = computeQuote(
        {
          openings: body.openings,
          level: body.level as LevelBucket,
          whiteWash: body.whiteWash === true,
        },
        rates.table,
      );
      return json({ ratesStale: rates.stale, ratesFetchedAt: rates.table.fetchedAt, ...result });
    }

    // Phase 2: classify photos already uploaded to R2. P3's funnel calls this
    // after the photo gate; the preview shape takes R2 keys + declared openings.
    if (request.method === "POST" && url.pathname === "/api/vision/classify") {
      let body: { photoKeys?: unknown; openings?: unknown };
      try {
        body = (await request.json()) as typeof body;
      } catch {
        return json({ error: "invalid JSON body" }, 400);
      }
      const keys = Array.isArray(body.photoKeys)
        ? body.photoKeys.filter((k): k is string => typeof k === "string")
        : [];
      if (keys.length === 0) {
        return json({ error: "expected { photoKeys: string[], openings?: number }" }, 400);
      }
      const declaredOpenings = typeof body.openings === "number" ? body.openings : null;

      if (!env.PHOTOS) {
        // R2 not enabled yet → cannot read photos → route to human pricing.
        return json(decide(null, declaredOpenings), 503);
      }

      const photos: PhotoInput[] = [];
      for (const key of keys) {
        const object = await env.PHOTOS.get(key);
        if (!object) return json({ error: `photo not found in R2: ${key}` }, 404);
        const mediaType = (object.httpMetadata?.contentType ?? "image/jpeg") as
          (typeof IMAGE_TYPES)[number];
        if (!IMAGE_TYPES.includes(mediaType)) {
          return json({ error: `unsupported photo type for ${key}: ${mediaType}` }, 400);
        }
        photos.push({ data: bytesToBase64(await object.arrayBuffer()), mediaType, slot: key });
      }

      try {
        const result = await classifyPhotos(env, photos, declaredOpenings);
        return json(decide(result, declaredOpenings));
      } catch (err) {
        // Model/API failure: never a guessed price — surface the human-review route.
        const message = err instanceof Error ? err.message : String(err);
        console.error("vision classify failed:", message);
        return json(decide(null, declaredOpenings), 502);
      }
    }

    return json({ error: "not found" }, 404);
  },
};

function bytesToBase64(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunk));
  }
  return btoa(binary);
}

async function safeJson(request: Request): Promise<unknown | null> {
  try {
    return await request.json();
  } catch {
    return null;
  }
}

function json(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data, null, 2), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
