/**
 * Minimal ServiceMinder Open API client (https://serviceminder.io/api).
 * Auth is the location API key inside the POST body, same convention as the
 * existing serviceminder-mcp server.
 */

import { SM_API_BASE, SM_PRICING } from "../config";
import type { SmServicesPayload } from "../pricing/rateTable";

export interface SmEnv {
  SERVICEMINDER_API_KEY: string;
}

export async function fetchSmServices(
  env: SmEnv,
  fetchImpl: typeof fetch = fetch,
): Promise<SmServicesPayload> {
  const res = await fetchImpl(`${SM_API_BASE}/services/all`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      ApiKey: env.SERVICEMINDER_API_KEY,
      IncludeParts: true,
      IncludeInactive: false,
      Matches: [],
    }),
  });
  if (!res.ok) {
    throw new Error(`ServiceMinder services/all failed: HTTP ${res.status}`);
  }
  const payload = (await res.json()) as SmServicesPayload;
  if (payload.ResultCode !== undefined && payload.ResultCode !== 0) {
    throw new Error(`ServiceMinder services/all error: ${payload.Message ?? payload.ResultCode}`);
  }
  if (!payload.Matches?.some((s) => s.Id === SM_PRICING.serviceId)) {
    throw new Error(`ServiceMinder response missing service ${SM_PRICING.serviceId}`);
  }
  return payload;
}
