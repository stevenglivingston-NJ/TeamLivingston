import { describe, expect, it } from "vitest";
import { KV_KEYS } from "../src/config";
import type { KvLike } from "../src/pricing/store";
import { loadRateTable } from "../src/pricing/store";
import { syncPricing } from "../src/sync/pricingSync";
import liveSnapshot from "./fixtures/sm-services-live-2026-07-17.json";

const NOW = () => new Date("2026-07-17T12:00:00Z");
const ENV = { SERVICEMINDER_API_KEY: "test-key" };

function memoryKv(): KvLike & { data: Map<string, string> } {
  const data = new Map<string, string>();
  return {
    data,
    async get(key) {
      return data.get(key) ?? null;
    },
    async put(key, value) {
      data.set(key, value);
    },
  };
}

function fetchReturning(body: unknown, status = 200): typeof fetch {
  return (async () =>
    new Response(JSON.stringify(body), { status })) as unknown as typeof fetch;
}

describe("syncPricing", () => {
  it("writes both current and last-good on a successful sync", async () => {
    const kv = memoryKv();
    const result = await syncPricing({ env: ENV, kv, now: NOW, fetchImpl: fetchReturning(liveSnapshot) });
    expect(result.ok).toBe(true);
    expect(result.table?.upliftMilli).toBe(619_350);
    expect(kv.data.has(KV_KEYS.current)).toBe(true);
    expect(kv.data.has(KV_KEYS.lastGood)).toBe(true);
  });

  it("leaves KV untouched when ServiceMinder is down", async () => {
    const kv = memoryKv();
    kv.data.set(KV_KEYS.lastGood, JSON.stringify({ sentinel: true }));
    const result = await syncPricing({ env: ENV, kv, now: NOW, fetchImpl: fetchReturning({}, 500) });
    expect(result.ok).toBe(false);
    expect(result.error).toContain("500");
    expect(kv.data.get(KV_KEYS.lastGood)).toContain("sentinel");
    expect(kv.data.has(KV_KEYS.current)).toBe(false);
  });

  it("surfaces ServiceMinder application errors", async () => {
    const kv = memoryKv();
    const result = await syncPricing({
      env: ENV,
      kv,
      now: NOW,
      fetchImpl: fetchReturning({ ResultCode: 3, Message: "Invalid API key" }),
    });
    expect(result.ok).toBe(false);
    expect(result.error).toContain("Invalid API key");
  });

  it("does not update last-good with an incomplete table", async () => {
    const broken = structuredClone(liveSnapshot) as typeof liveSnapshot;
    broken.Matches[0].AvailableParts = broken.Matches[0].AvailableParts.filter(
      (p) => p.Id !== 199137, // drop the uplift → effective base becomes $0
    );
    const kv = memoryKv();
    kv.data.set(KV_KEYS.lastGood, JSON.stringify({ sentinel: true }));
    const result = await syncPricing({ env: ENV, kv, now: NOW, fetchImpl: fetchReturning(broken) });
    expect(result.ok).toBe(true);
    expect(result.table?.complete).toBe(false);
    expect(kv.data.get(KV_KEYS.lastGood)).toContain("sentinel"); // preserved
    expect(kv.data.has(KV_KEYS.current)).toBe(true); // current still reflects reality
  });
});

describe("loadRateTable fallback", () => {
  it("serves last-good marked stale when current has expired", async () => {
    const kv = memoryKv();
    const table = { fetchedAt: "2026-07-17T00:00:00Z", complete: true };
    kv.data.set(KV_KEYS.lastGood, JSON.stringify(table));
    const loaded = await loadRateTable(kv);
    expect(loaded?.stale).toBe(true);
    expect(loaded?.table.fetchedAt).toBe("2026-07-17T00:00:00Z");
  });

  it("returns null when nothing has ever synced", async () => {
    expect(await loadRateTable(memoryKv())).toBeNull();
  });
});
