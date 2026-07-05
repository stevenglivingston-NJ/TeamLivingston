// Axyom notify_queue dispatcher — MCP-independent delivery.
//
// Why this exists: notification delivery used to depend on scheduled agent
// sessions whose MCP connectors flap at startup — pings sat pending for hours
// (twice in two days). This function runs inside Supabase itself, invoked
// every minute by pg_cron + pg_net, so delivery never depends on an agent
// session being healthy. Ax's sweeps remain a backstop for rows this
// function can't deliver.
//
// Channels:
//   email — HighLevel conversations API (PIT + location id in dispatch_config;
//           contacts are upserted by email, so any recipient works)
//   slack — optional incoming webhook (dispatch_config key slack_webhook_url);
//           posts to the channel the webhook targets (#intranet-alerts).
//           Absent webhook, slack delivery is skipped (email still goes out).
//
// Config table: public.dispatch_config (RLS on, no policies — service role only)
//   ghl_pit            HighLevel Private Integration Token
//   ghl_location_id    HighLevel location (KTU: nHLCxHPidnhV1NFzRtZZ)
//   email_from         From header, e.g. "Axyom <noreply@...>"
//   default_recipient  Fallback when a row has no recipient_email
//   slack_webhook_url  Optional Slack incoming webhook
import { createClient } from "npm:@supabase/supabase-js@2";

const sb = createClient(
  Deno.env.get("SUPABASE_URL")!,
  Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!,
);

async function loadConfig(): Promise<Record<string, string>> {
  const { data, error } = await sb.from("dispatch_config").select("key,value");
  if (error) throw error;
  return Object.fromEntries((data ?? []).map((r) => [r.key, r.value]));
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

async function sendEmail(
  c: Record<string, string>,
  to: string,
  subject: string,
  body: string,
): Promise<void> {
  const auth = { Authorization: `Bearer ${c.ghl_pit}`, "Content-Type": "application/json" };
  const up = await fetch("https://services.leadconnectorhq.com/contacts/upsert", {
    method: "POST",
    headers: { ...auth, Version: "2021-07-28" },
    body: JSON.stringify({ locationId: c.ghl_location_id, email: to }),
  });
  const upj = await up.json();
  const contactId = upj?.contact?.id;
  if (!contactId) {
    throw new Error("GHL contact upsert failed: " + JSON.stringify(upj).slice(0, 200));
  }
  const msg = await fetch("https://services.leadconnectorhq.com/conversations/messages", {
    method: "POST",
    headers: { ...auth, Version: "2021-04-15" },
    body: JSON.stringify({
      type: "Email",
      contactId,
      subject,
      html: `<div style="font-family:sans-serif;white-space:pre-wrap">${escapeHtml(body)}</div>`,
      emailFrom: c.email_from || undefined,
    }),
  });
  if (!msg.ok) {
    throw new Error("GHL email send failed: " + (await msg.text()).slice(0, 200));
  }
}

async function sendSlack(c: Record<string, string>, text: string): Promise<boolean> {
  if (!c.slack_webhook_url) return false;
  const r = await fetch(c.slack_webhook_url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  if (!r.ok) throw new Error("Slack webhook failed: HTTP " + r.status);
  return true;
}

Deno.serve(async () => {
  const c = await loadConfig();
  const { data: rows, error } = await sb
    .from("notify_queue")
    .select("*")
    .eq("status", "pending")
    .order("created_at")
    .limit(25);
  if (error) return Response.json({ error: error.message }, { status: 500 });

  const results: unknown[] = [];
  for (const r of rows ?? []) {
    const via: string[] = [];
    try {
      const to = r.recipient_email || c.default_recipient || "stevenglivingston@gmail.com";
      const slackText = `🔔 *${r.subject || "Axyom notification"}*\n${r.body || ""}`;
      try {
        if (await sendSlack(c, slackText)) via.push("slack-webhook");
      } catch (_e) {
        via.push("slack-error"); // Slack failure never blocks email delivery
      }
      await sendEmail(c, to, r.subject || "Axyom notification", r.body || "");
      via.push(`email:${to}`);
      // status guard avoids double-marking if a sweep raced us
      await sb.from("notify_queue")
        .update({
          status: "sent",
          sent_at: new Date().toISOString(),
          result: { via: via.join("+"), dispatcher: "edge" },
        })
        .eq("id", r.id)
        .eq("status", "pending");
      results.push({ id: r.id, ok: true, via });
    } catch (e) {
      const prev = (r.result && typeof r.result === "object" ? r.result : {}) as Record<string, unknown>;
      const retries = Number(prev.retries ?? 0) + 1;
      // Leave pending for 2 retries (next minute / sweep backstop), then error out.
      await sb.from("notify_queue")
        .update(
          retries >= 3
            ? { status: "error", result: { ...prev, retries, error: String(e).slice(0, 300), dispatcher: "edge" } }
            : { result: { ...prev, retries, error: String(e).slice(0, 300), dispatcher: "edge" } },
        )
        .eq("id", r.id);
      results.push({ id: r.id, ok: false, error: String(e).slice(0, 120) });
    }
  }
  return Response.json({ processed: results.length, results });
});
