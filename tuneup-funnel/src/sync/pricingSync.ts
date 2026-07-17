/**
 * The 15-minute cron job: ServiceMinder → RateTable → KV, with a D1 audit row
 * per run so pricing changes and sync failures are traceable.
 */

import { buildRateTable, type RateTable } from "../pricing/rateTable";
import { saveRateTable, type KvLike } from "../pricing/store";
import { fetchSmServices, type SmEnv } from "../sm/client";

export interface D1Like {
  prepare(sql: string): {
    bind(...args: unknown[]): { run(): Promise<unknown> };
  };
}

export interface SyncDeps {
  env: SmEnv;
  kv: KvLike;
  db?: D1Like;
  now?: () => Date;
  fetchImpl?: typeof fetch;
}

export interface SyncResult {
  ok: boolean;
  table?: RateTable;
  error?: string;
}

export async function syncPricing(deps: SyncDeps): Promise<SyncResult> {
  const now = deps.now ?? (() => new Date());
  try {
    const payload = await fetchSmServices(deps.env, deps.fetchImpl);
    const table = buildRateTable(payload, now());
    await saveRateTable(deps.kv, table);
    await audit(deps.db, now(), table.complete ? "sync_ok" : "sync_incomplete", {
      missing: table.missing,
      baseMilli: table.baseMilli,
      upliftMilli: table.upliftMilli,
      levelRatesMilli: table.levelRatesMilli,
      whiteWashPremiumMilli: table.whiteWashPremiumMilli,
    });
    return { ok: true, table };
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    // KV untouched on failure: pricing:current ages out and pricing:last-good
    // keeps serving until SM is reachable again.
    await audit(deps.db, now(), "sync_error", { message });
    return { ok: false, error: message };
  }
}

async function audit(
  db: D1Like | undefined,
  at: Date,
  event: string,
  detail: unknown,
): Promise<void> {
  if (!db) return;
  try {
    await db
      .prepare(
        "INSERT INTO rate_snapshots (fetched_at, event, detail) VALUES (?1, ?2, ?3)",
      )
      .bind(at.toISOString(), event, JSON.stringify(detail))
      .run();
  } catch {
    // Audit is best-effort; a D1 hiccup must not fail the sync itself.
  }
}
