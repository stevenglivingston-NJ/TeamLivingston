/**
 * Worker entry. Phase 1 exposes the pricing engine and the SM cron sync;
 * the customer funnel routes (sessions, photos, checkout) land in P3/P4.
 */

import { computeQuote, type QuoteInput } from "./pricing/engine";
import type { LevelBucket } from "./pricing/rateTable";
import { loadRateTable } from "./pricing/store";
import { syncPricing } from "./sync/pricingSync";

export interface Env {
  PRICING_KV: KVNamespace;
  DB: D1Database;
  PHOTOS: R2Bucket;
  SERVICEMINDER_API_KEY: string;
}

const LEVELS: readonly LevelBucket[] = ["L1_2", "L3", "L4"];

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
        return json({ error: "expected { openings: number, level: L1_2|L3|L4, whiteWash?, sdd? }" }, 400);
      }
      const rates = await loadRateTable(env.PRICING_KV);
      if (!rates) return json({ error: "no rate table available; sync has not run" }, 503);
      const result = computeQuote(
        {
          openings: body.openings,
          level: body.level as LevelBucket,
          whiteWash: body.whiteWash === true,
          sdd: body.sdd === true,
        },
        rates.table,
      );
      return json({ ratesStale: rates.stale, ratesFetchedAt: rates.table.fetchedAt, ...result });
    }

    return json({ error: "not found" }, 404);
  },
};

function json(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data, null, 2), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
