/**
 * Phase 5 tracking: hashing/normalization to Meta spec, CAPI payload shape
 * (event_id dedup, cents→dollars), GA4 MP payload, HL name splitting, and the
 * no-config no-op guarantees (the funnel must never depend on ads/CRM config).
 */

import { describe, expect, it } from "vitest";
import {
  buildMetaEvent,
  normalizeEmail,
  normalizePhone,
  sendMetaEvent,
  sha256Hex,
} from "../src/tracking/meta";
import { buildGa4Payload, sendGa4Event } from "../src/tracking/ga4";
import { splitName, upsertHlContact } from "../src/hl/client";

describe("Meta user-data normalization", () => {
  it("lowercases and trims email", () => {
    expect(normalizeEmail("  Steven@Gmail.COM ")).toBe("steven@gmail.com");
  });

  it("strips phone formatting and adds US country code to 10-digit numbers", () => {
    expect(normalizePhone("(973) 521-1182")).toBe("19735211182");
    expect(normalizePhone("973-521-1182")).toBe("19735211182");
  });

  it("keeps an existing country code", () => {
    expect(normalizePhone("+1 973 521 1182")).toBe("19735211182");
  });

  it("sha256 matches the known vector", async () => {
    // Meta's published example hash for "test@example.com" (already normalized).
    expect(await sha256Hex("test@example.com")).toBe(
      "973dfe463ec85785f5f95af5ba3906eedb2d931c24e69824a89ea65dba4e813b",
    );
  });
});

describe("buildMetaEvent", () => {
  const client = {
    eventId: "evt-123",
    url: "https://ktubloomfield.com/tuneup",
    fbp: "fb.1.1.2",
    ip: "203.0.113.9",
    userAgent: "UA",
  };

  it("carries the browser eventId for dedup and converts cents to dollars", async () => {
    const event = await buildMetaEvent({
      eventName: "Purchase",
      email: "test@example.com",
      valueCents: 145_268,
      client,
      eventTimeMs: 1_700_000_000_000,
    });
    expect(event.event_id).toBe("evt-123");
    expect(event.event_time).toBe(1_700_000_000);
    expect(event.event_source_url).toBe(client.url);
    expect((event.custom_data as { value: number }).value).toBe(1452.68);
    const userData = event.user_data as Record<string, unknown>;
    expect(userData.em).toEqual([
      "973dfe463ec85785f5f95af5ba3906eedb2d931c24e69824a89ea65dba4e813b",
    ]);
    expect(userData.client_ip_address).toBe("203.0.113.9");
    expect(userData.fbp).toBe("fb.1.1.2");
  });

  it("omits event_id when the browser never supplied one (server-only event)", async () => {
    const event = await buildMetaEvent({
      eventName: "Lead",
      client: {},
      eventTimeMs: 1_700_000_000_000,
    });
    expect(event.event_id).toBeUndefined();
    expect(event.action_source).toBe("website");
  });
});

describe("buildGa4Payload", () => {
  it("builds a purchase with transaction id and dollar value", () => {
    const payload = buildGa4Payload({
      name: "purchase",
      clientId: "123.456",
      valueCents: 200_000,
      transactionId: "sess-1",
    });
    expect(payload.client_id).toBe("123.456");
    const [event] = payload.events as Array<{ name: string; params: Record<string, unknown> }>;
    expect(event.name).toBe("purchase");
    expect(event.params.value).toBe(2000);
    expect(event.params.transaction_id).toBe("sess-1");
    expect(event.params.currency).toBe("USD");
  });
});

describe("HighLevel client", () => {
  it("splits names the way HL expects", () => {
    expect(splitName("Steven Livingston")).toEqual({
      firstName: "Steven",
      lastName: "Livingston",
    });
    expect(splitName("Cher")).toEqual({ firstName: "Cher", lastName: "" });
    expect(splitName("Mary Anne van der Berg")).toEqual({
      firstName: "Mary",
      lastName: "Anne van der Berg",
    });
  });
});

describe("no-config no-ops (funnel never blocks on ads/CRM config)", () => {
  it("HL upsert skips without PIT/location", async () => {
    const result = await upsertHlContact({}, { name: "A B", phone: "19735551212", tags: [] });
    expect(result).toEqual({ ok: false, skipped: "no_config" });
  });

  it("Meta send skips without pixel/token", async () => {
    const result = await sendMetaEvent({}, {
      eventName: "Lead",
      client: {},
      eventTimeMs: Date.now(),
    });
    expect(result).toEqual({ ok: false, skipped: "no_config" });
  });

  it("GA4 send skips without measurement id/secret", async () => {
    const result = await sendGa4Event({}, { name: "generate_lead", clientId: "x" });
    expect(result).toEqual({ ok: false, skipped: "no_config" });
  });
});
