/**
 * Rate-table persistence in KV: `pricing:current` (1h TTL, freshness signal)
 * with `pricing:last-good` (no TTL) as the outage fallback. A quote served
 * from last-good is marked stale so later phases can decide whether to show
 * it or route to human pricing.
 */

import { KV_KEYS, PRICING_CURRENT_TTL_SECONDS } from "../config";
import type { RateTable } from "./rateTable";

export interface KvLike {
  get(key: string): Promise<string | null>;
  put(key: string, value: string, options?: { expirationTtl?: number }): Promise<void>;
}

export async function saveRateTable(kv: KvLike, table: RateTable): Promise<void> {
  const json = JSON.stringify(table);
  await kv.put(KV_KEYS.current, json, { expirationTtl: PRICING_CURRENT_TTL_SECONDS });
  if (table.complete) {
    await kv.put(KV_KEYS.lastGood, json);
  }
}

export async function loadRateTable(
  kv: KvLike,
): Promise<{ table: RateTable; stale: boolean } | null> {
  const current = await kv.get(KV_KEYS.current);
  if (current) return { table: JSON.parse(current) as RateTable, stale: false };
  const lastGood = await kv.get(KV_KEYS.lastGood);
  if (lastGood) return { table: JSON.parse(lastGood) as RateTable, stale: true };
  return null;
}
