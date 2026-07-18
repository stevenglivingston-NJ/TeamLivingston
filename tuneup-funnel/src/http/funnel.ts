/**
 * Funnel session/lead/callback/photo endpoints backing the Phase 3 SPA. Every
 * gate writes to D1 (build spec: every gate writes to D1) via these handlers.
 * HighLevel fan-out and the Meta CAPI purchase event land in Phase 5; for now
 * leads/callbacks are persisted and flagged for that push.
 */

export interface FunnelEnv {
  DB: D1Database;
  PHOTOS?: R2Bucket;
}

/** Columns a client may patch on quote_sessions — a strict allowlist (no SQL injection). */
const SESSION_COLUMNS = new Set([
  "stage",
  "zip",
  "in_service_area",
  "openings",
  "cabinet_material",
  "cabinet_age",
  "smoking_in_home",
  "polish_products",
  "level",
  "ai_confidence",
  "white_wash",
  "quote_cents",
  "floor_applied",
  "deposit_cents",
  "status",
]);

function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

async function logEvent(
  db: D1Database,
  sessionId: string | null,
  event: string,
  detail: unknown,
): Promise<void> {
  try {
    await db
      .prepare("INSERT INTO funnel_events (session_id, created_at, event, detail) VALUES (?1, ?2, ?3, ?4)")
      .bind(sessionId, new Date().toISOString(), event, detail == null ? null : JSON.stringify(detail))
      .run();
  } catch {
    /* audit is best-effort */
  }
}

export async function createSession(env: FunnelEnv): Promise<Response> {
  const id = crypto.randomUUID();
  const now = new Date().toISOString();
  await env.DB.prepare(
    "INSERT INTO quote_sessions (id, created_at, updated_at, stage, status) VALUES (?1, ?2, ?2, 'landing', 'open')",
  )
    .bind(id, now)
    .run();
  await logEvent(env.DB, id, "session_created", null);
  return jsonResponse({ id });
}

export async function patchSession(env: FunnelEnv, id: string, body: Record<string, unknown>): Promise<Response> {
  const sets: string[] = [];
  const values: unknown[] = [];
  for (const [key, value] of Object.entries(body)) {
    if (!SESSION_COLUMNS.has(key)) continue;
    values.push(value);
    sets.push(`${key} = ?${values.length}`);
  }
  values.push(new Date().toISOString());
  const updatedAtIdx = values.length;
  values.push(id);
  const idIdx = values.length;

  const setClause = sets.length ? `${sets.join(", ")}, ` : "";
  const result = await env.DB.prepare(
    `UPDATE quote_sessions SET ${setClause}updated_at = ?${updatedAtIdx} WHERE id = ?${idIdx}`,
  )
    .bind(...values)
    .run();

  if (result.meta.changes === 0) return jsonResponse({ error: "session not found" }, 404);
  await logEvent(env.DB, id, "gate", body);
  return jsonResponse({ ok: true });
}

export async function createLead(
  env: FunnelEnv,
  body: { sessionId?: string; name?: string; phone?: string; email?: string },
): Promise<Response> {
  if (!body.sessionId || !body.name || !body.phone || !body.email) {
    return jsonResponse({ error: "sessionId, name, phone, email required" }, 400);
  }
  const id = crypto.randomUUID();
  await env.DB.prepare(
    "INSERT INTO leads (id, session_id, created_at, name, phone, email, callback_requested) VALUES (?1, ?2, ?3, ?4, ?5, ?6, 0)",
  )
    .bind(id, body.sessionId, new Date().toISOString(), body.name, body.phone, body.email)
    .run();
  await logEvent(env.DB, body.sessionId, "lead_captured", { name: body.name });
  // TODO(P5): fire to HighLevel immediately on submit.
  return jsonResponse({ ok: true, id });
}

export async function createCallback(
  env: FunnelEnv,
  body: { sessionId?: string | null; name?: string; phone?: string; bestTime?: string },
): Promise<Response> {
  if (!body.name || !body.phone) return jsonResponse({ error: "name and phone required" }, 400);
  const id = crypto.randomUUID();
  await env.DB.prepare(
    "INSERT INTO leads (id, session_id, created_at, name, phone, email, callback_requested) VALUES (?1, ?2, ?3, ?4, ?5, '', 1)",
  )
    .bind(id, body.sessionId ?? null, new Date().toISOString(), body.name, body.phone)
    .run();
  await logEvent(env.DB, body.sessionId ?? null, "callback_requested", { bestTime: body.bestTime ?? null });
  // TODO(P5): notify team + tag `tuneup-callback` in HighLevel; instrument as a conversion.
  return jsonResponse({ ok: true, id });
}

/** Store one captured photo in R2. Returns the object key. */
export async function uploadPhoto(
  env: FunnelEnv,
  sessionId: string,
  slot: string,
  request: Request,
): Promise<Response> {
  if (!env.PHOTOS) {
    return jsonResponse({ error: "photo storage not enabled yet (R2 pending)" }, 503);
  }
  if (!sessionId || !slot) return jsonResponse({ error: "session and slot required" }, 400);
  const safeSlot = slot.replace(/[^a-z0-9_-]/gi, "");
  const key = `sessions/${sessionId}/${safeSlot}.jpg`;
  const contentType = request.headers.get("Content-Type") ?? "image/jpeg";
  await env.PHOTOS.put(key, request.body, { httpMetadata: { contentType } });
  await logEvent(env.DB, sessionId, "photo_uploaded", { slot: safeSlot });
  return jsonResponse({ key });
}
