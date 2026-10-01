import "jsr:@supabase/functions-js/edge-runtime.d.ts";

/**
 * Public consult-feedback intake: POST /consult-feedback
 * Body: { brand, contact_id, appt_id, hl_user_id, agent_name, rating,
 *         missing_items[], feedback_text, callback_requested, decision? }
 *
 * rating is a fully labeled 1-5 scale (survey v2, 2026-09-27) -- see RATING below.
 * decision is optional: "ready" | "need_info" | "not_now".
 *
 * verify_jwt is OFF (called from a public post-consult survey with no user
 * session). This function holds the service-role key directly, so unlike
 * queue-notify it needs no shared-secret handshake — it IS the trusted
 * service-role caller.
 *
 * - Validates types (rating int 1-5, feedback_text <= 2000 chars).
 * - Inserts into consult_feedback. appt_id is unique; a second answer for the same
 *   appointment (a text-message rating, then detail added through the survey link)
 *   UPDATES the row: rating replaced, comments appended, callback/decision merged,
 *   and it only alerts again if it adds a callback request or "needs more information".
 * - Forwards the same JSON to the brand's HighLevel inbound webhook
 *   (HL_FEEDBACK_WEBHOOK_KTU/BTU in app_secrets — placeholders until Steven
 *   supplies the real URLs), retried once on failure, logged not fatal.
 * - rating <= 3 OR callback_requested OR decision = need_info -> inserts a notify_queue alert row
 *   directly (this function already holds service-role access, so it does
 *   not need to go through the queue-notify HTTP function, which exists for
 *   *external* non-service-role callers).
 */

const SUPA = Deno.env.get("SUPABASE_URL")!;
const SVC = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
const svcHeaders = {
  "Content-Type": "application/json",
  apikey: SVC,
  authorization: `Bearer ${SVC}`,
  "Content-Profile": "public",
  "Accept-Profile": "public",
};

// Steven's alert address, per the convention already used for pricing_alert /
// system-critical notify_queue rows (see queue-notify's ALLOWED list and
// existing notify_queue rows — slivingston@kitchentuneup.com is the
// established address for this kind of operational alert).
const STEVEN_EMAIL = "slivingston@kitchentuneup.com";

// The survey's labeled scale (design.ktubtu.com/feedback, portal/src/feedback.js) -- keep in step.
const RATING: Record<number, string> = {
  5: "Superb — covered every detail", 4: "Very good — just a few gaps", 3: "Good — some questions left open",
  2: "Fair — I've seen better", 1: "Poor — not what I expected",
};
const DECISION: Record<string, string> = {
  ready: "Ready to move forward", need_info: "Still undecided — needs more information", not_now: "Not moving forward right now",
};

const CORS = {
  "Content-Type": "application/json",
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
  "Access-Control-Allow-Headers": "content-type",
};

function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: CORS });
}

async function getSecret(key: string): Promise<string | null> {
  const r = await fetch(
    `${SUPA}/rest/v1/app_secrets?key=eq.${encodeURIComponent(key)}&select=value`,
    { headers: svcHeaders },
  );
  if (!r.ok) return null;
  const rows = await r.json();
  return rows?.[0]?.value ?? null;
}

/** Shape the outbound HighLevel payload for its field mapping / If-Else steps,
 *  which match on plain strings, not JSON arrays or booleans. This is a
 *  presentation transform only — the DB row keeps missing_items as text[]
 *  and callback_requested as boolean. */
function toHlPayload(row: Record<string, unknown>): Record<string, unknown> {
  const missing = Array.isArray(row.missing_items) ? (row.missing_items as string[]) : [];
  return {
    ...row,
    missing_items: missing.join(", "),
    callback_requested: row.callback_requested ? "Yes" : "No",
    rating_label: RATING[row.rating as number] ?? "",
    decision: row.decision ? DECISION[row.decision as string] ?? row.decision : "",
  };
}

async function forwardToHighLevel(brand: string, payload: Record<string, unknown>) {
  const url = await getSecret(brand === "KTU" ? "HL_FEEDBACK_WEBHOOK_KTU" : "HL_FEEDBACK_WEBHOOK_BTU");
  if (!url) return; // not configured yet — nothing to forward to
  const hlBody = toHlPayload(payload);
  const attempt = () =>
    fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(hlBody) });
  try {
    const r1 = await attempt();
    if (r1.ok) return;
    const r2 = await attempt();
    if (!r2.ok) console.error("consult-feedback: HL webhook forward failed twice", brand, r2.status);
  } catch (e) {
    try {
      const r2 = await attempt();
      if (!r2.ok) console.error("consult-feedback: HL webhook forward failed (retry after error)", brand, r2.status);
    } catch (e2) {
      console.error("consult-feedback: HL webhook forward errored twice", brand, String(e), String(e2));
    }
  }
}

// Low rating, a callback request, or an undecided client who needs more information:
// alert straight into notify_queue so someone follows up.
async function queueAlert(brand: string, row: Record<string, unknown>, rating: number, missingItems: string[] | null,
                          feedbackText: string | null, callbackRequested: boolean, decision: string | null) {
  const needInfo = decision === "need_info";
  const items = (missingItems ?? []).join(", ") || "none noted";
  const tags = [callbackRequested ? "callback requested" : null, needInfo ? "needs more information" : null].filter(Boolean).join(" – ");
  const subject = `Consult feedback ALERT (${brand}) – ${rating}/5 ${RATING[rating]?.split(" — ")[0] ?? ""}${tags ? " – " + tags : ""}`;
  const body =
    `Consult feedback ALERT (${brand}) – rep ${row.agent_name ?? "unknown"}, ${rating}/5 (${RATING[rating] ?? ""}), ` +
    `decision: ${decision ? DECISION[decision] : "not answered"}, ` +
    `missing: ${items}, comment: ${feedbackText ?? "(none)"}, ` +
    `callback: ${callbackRequested ? "yes" : "no"}, SM contact ${row.contact_id ?? "unknown"}, appt ${row.appt_id}`;
  const alertRes = await fetch(`${SUPA}/rest/v1/notify_queue`, {
    method: "POST",
    headers: svcHeaders,
    body: JSON.stringify({ kind: "consult_feedback_alert", recipient_email: STEVEN_EMAIL, subject, body, source: "consult-feedback", status: "pending" }),
  });
  if (!alertRes.ok) console.error("consult-feedback: notify_queue insert failed", await alertRes.text());
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: CORS });
  if (req.method !== "POST") return json(405, { error: "POST only" });

  let b: Record<string, unknown>;
  try { b = await req.json(); } catch { return json(400, { error: "invalid JSON" }); }

  const brand = String(b.brand ?? "");
  if (!["KTU", "BTU"].includes(brand)) return json(400, { error: "brand must be KTU or BTU" });

  const rating = b.rating;
  if (!Number.isInteger(rating) || (rating as number) < 1 || (rating as number) > 5) {
    return json(400, { error: "rating must be an integer 1-5" });
  }

  const feedbackText = b.feedback_text != null ? String(b.feedback_text) : null;
  if (feedbackText != null && feedbackText.length > 2000) {
    return json(400, { error: "feedback_text must be 2000 characters or fewer" });
  }

  const missingItems = Array.isArray(b.missing_items) ? b.missing_items.map(String) : null;
  const callbackRequested = Boolean(b.callback_requested);
  const decision = b.decision == null || b.decision === "" ? null : String(b.decision);
  if (decision != null && !(decision in DECISION)) return json(400, { error: "decision must be ready, need_info or not_now" });
  const contactId = b.contact_id != null ? Number(b.contact_id) : null;
  const apptId = b.appt_id != null ? Number(b.appt_id) : null;
  if (apptId == null || !Number.isFinite(apptId)) return json(400, { error: "appt_id required" });

  const row = {
    brand,
    contact_id: Number.isFinite(contactId as number) ? contactId : null,
    appt_id: apptId,
    hl_user_id: b.hl_user_id != null ? String(b.hl_user_id) : null,
    agent_name: b.agent_name != null ? String(b.agent_name) : null,
    rating,
    missing_items: missingItems,
    feedback_text: feedbackText,
    callback_requested: callbackRequested,
    decision,
  };

  const insertRes = await fetch(`${SUPA}/rest/v1/consult_feedback`, {
    method: "POST",
    headers: { ...svcHeaders, Prefer: "return=representation" },
    body: JSON.stringify(row),
  });

  if (!insertRes.ok) {
    const text = await insertRes.text();
    // Postgres unique_violation surfaces as PostgREST code 23505.
    if (insertRes.status === 409 || text.includes("23505")) {
      // Second answer for the same appointment: a client who replied to the survey TEXT with a
      // number, then used the link to add detail. Update the row (web answer wins on rating;
      // comments are appended) instead of dropping the detail on the floor.
      const prevRes = await fetch(`${SUPA}/rest/v1/consult_feedback?appt_id=eq.${apptId}&select=feedback_text,missing_items,callback_requested,decision`, { headers: svcHeaders });
      const prev = (await prevRes.json().catch(() => []))?.[0] ?? {};
      const patch: Record<string, unknown> = {
        rating,
        callback_requested: Boolean(prev.callback_requested) || callbackRequested,
        feedback_text: [prev.feedback_text, feedbackText].filter(Boolean).join(" | ") || null,
      };
      if (missingItems?.length) patch.missing_items = missingItems;
      if (decision) patch.decision = decision;
      const up = await fetch(`${SUPA}/rest/v1/consult_feedback?appt_id=eq.${apptId}`, { method: "PATCH", headers: svcHeaders, body: JSON.stringify(patch) });
      if (!up.ok) { console.error("consult-feedback: update failed", up.status, (await up.text()).slice(0, 300)); return json(200, { ok: true, note: "already received" }); }
      // Only alert again when this answer adds something to act on.
      const newlyActionable = (callbackRequested && !prev.callback_requested) || (decision === "need_info" && prev.decision !== "need_info");
      if (newlyActionable) await queueAlert(brand, row, rating as number, missingItems, feedbackText, callbackRequested, decision);
      return json(200, { ok: true, note: "updated" });
    }
    console.error("consult-feedback: insert failed", insertRes.status, text.slice(0, 500));
    return json(502, { error: "insert failed" });
  }

  // Forward to HighLevel (best-effort, retried once, never blocks the response's success).
  await forwardToHighLevel(brand, row);

  if ((rating as number) <= 3 || callbackRequested || decision === "need_info") {
    await queueAlert(brand, row, rating as number, missingItems, feedbackText, callbackRequested, decision);
  }

  return json(200, { ok: true });
});
