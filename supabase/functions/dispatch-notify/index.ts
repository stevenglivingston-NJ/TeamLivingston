// Axyom notify_queue dispatcher — v7. Email (HighLevel) + targeted Slack.
//
// Why this exists: notification delivery used to depend on scheduled agent
// sessions whose MCP connectors flap at startup — pings sat pending for hours.
// This function runs inside Supabase itself, invoked every minute by pg_cron +
// pg_net, so delivery never depends on an agent session being healthy.
//
// Channels:
//   email — HighLevel conversations API (PIT + location id in dispatch_config;
//           contacts are upserted by email, so any recipient works).
//   slack — resolves the recipient against the live Slack workspace roster
//           (by email, then by a "→ Name" suffix in the subject), DMs them
//           first (im:write), and falls back to posting in `slack_channel_id`
//           with an @mention. A row whose `kind` starts `task_` and whose
//           `source` matches `team_tasks:<uuid>` gets a "✅ Mark done" button
//           (action_id `task_done`) — handled by the separate `slack-actions`
//           function. Without a Slack bot token, falls back to
//           `slack_webhook_url` (plain text, no DM routing / task button).
//
// v7 fix (this revision): each channel is tracked independently via
// Promise.allSettled instead of a shared try/catch. Previously an unhandled
// sendEmail rejection (e.g. a revoked GHL PIT throwing "upsert failed")
// aborted the whole row and hid a successful Slack delivery behind a
// retried/errored row, while a Slack failure was silently swallowed into
// `via` as if it had delivered. Now a row is `sent` if ANY configured channel
// actually delivered, failures land in `result.partial_failures`, and only a
// total blackout across every configured channel errors the row.
//
// Secrets (preferred over the dispatch_config table, so they never land in
// backups/dumps/query logs):
//   GHL_PIT          HighLevel Private Integration Token — `supabase secrets set GHL_PIT=...`
//   SLACK_BOT_TOKEN  Slack bot token (scopes chat:write, users:read.email, im:write)
// loadConfig() overlays both onto the config object; the dispatch_config /
// app_secrets rows are fallbacks only.
//
// Config table: public.dispatch_config (RLS on, no policies — service role only)
//   ghl_pit            HighLevel PIT — fallback only; prefer the GHL_PIT secret
//   ghl_location_id    HighLevel location (KTU: nHLCxHPidnhV1NFzRtZZ)
//   email_from         From header, e.g. "Axyom <tlivingston@kitchentuneup.com>"
//   default_recipient  Fallback when a row has no recipient_email
//   slack_bot_token    Slack bot token — fallback only; prefer the SLACK_BOT_TOKEN secret
//   slack_channel_id   Channel to post to when a DM can't be opened / no recipient match
//   slack_webhook_url  Legacy incoming webhook, used only when no bot token is configured
//   cron_secret        Shared secret pg_cron sends as the x-cron-secret header
import { createClient } from "npm:@supabase/supabase-js@2";

const sb = createClient(
  Deno.env.get("SUPABASE_URL")!,
  Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!,
);

async function loadConfig(): Promise<Record<string, string>> {
  const { data } = await sb.from("dispatch_config").select("key,value");
  const cfg: Record<string, string> = Object.fromEntries((data ?? []).map((r) => [r.key, r.value]));
  const secretPit = Deno.env.get("GHL_PIT");
  if (secretPit) cfg.ghl_pit = secretPit;
  const envSlack = Deno.env.get("SLACK_BOT_TOKEN");
  if (envSlack) cfg.slack_bot_token = envSlack;
  if (!cfg.slack_bot_token) {
    const { data: s } = await sb.from("app_secrets").select("value").eq("key", "SLACK_BOT_TOKEN").maybeSingle();
    if (s?.value) cfg.slack_bot_token = s.value;
  }
  return cfg;
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

async function sendEmail(c: Record<string, string>, to: string, subject: string, body: string): Promise<void> {
  const auth = { Authorization: `Bearer ${c.ghl_pit}`, "Content-Type": "application/json" };
  const up = await fetch("https://services.leadconnectorhq.com/contacts/upsert", {
    method: "POST",
    headers: { ...auth, Version: "2021-07-28" },
    body: JSON.stringify({ locationId: c.ghl_location_id, email: to }),
  });
  const upj = await up.json();
  const contactId = upj?.contact?.id;
  if (!contactId) throw new Error("GHL contact upsert failed: " + JSON.stringify(upj).slice(0, 200));

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
  if (!msg.ok) throw new Error("GHL email send failed: " + (await msg.text()).slice(0, 200));
}

type SlackUser = { id: string; name: string; display: string; email: string };
let userCache: SlackUser[] | null = null;

async function slackApi(token: string, method: string, body: unknown) {
  const r = await fetch(`https://slack.com/api/${method}`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
  return await r.json();
}

async function slackUsers(token: string): Promise<SlackUser[]> {
  if (userCache) return userCache;
  const out: SlackUser[] = [];
  let cursor = "";
  do {
    const r = await fetch(
      `https://slack.com/api/users.list?limit=100${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`,
      { headers: { Authorization: `Bearer ${token}` } },
    );
    const j = await r.json();
    if (!j.ok) break;
    for (const m of j.members ?? []) {
      if (m.deleted || m.is_bot || m.id === "USLACKBOT") continue;
      out.push({
        id: m.id,
        name: (m.real_name || "").toLowerCase(),
        display: (m.profile?.display_name || "").toLowerCase(),
        email: (m.profile?.email || "").toLowerCase(),
      });
    }
    cursor = j.response_metadata?.next_cursor || "";
  } while (cursor);
  userCache = out;
  return out;
}

function matchUser(users: SlackUser[], email: string | null, subject: string): SlackUser | null {
  const em = (email || "").toLowerCase();
  if (em) {
    const hit = users.find((u) => u.email === em);
    if (hit) return hit;
  }
  const m = subject.match(/→\s*([A-Za-z][A-Za-z .'-]{1,40})/);
  if (m) {
    const n = m[1].trim().toLowerCase();
    const f = n.split(/\s+/)[0];
    const hit = users.find((u) => u.name === n || u.display === n || (f.length > 2 && (u.name.startsWith(f) || u.display.startsWith(f))));
    if (hit) return hit;
  }
  return null;
}

function taskIdFromSource(source: string | null): string | null {
  const m = (source || "").match(/team_tasks:([0-9a-f-]{36})/i);
  return m ? m[1] : null;
}

function slackBlocks(text: string, taskId: string | null) {
  const blocks: unknown[] = [{ type: "section", text: { type: "mrkdwn", text } }];
  if (taskId) {
    blocks.push({
      type: "actions",
      elements: [{ type: "button", text: { type: "plain_text", text: "✅ Mark done" }, style: "primary", action_id: "task_done", value: taskId }],
    });
  }
  return blocks;
}

async function sendSlack(
  c: Record<string, string>,
  r: { recipient_email?: string; subject?: string; body?: string; source?: string; kind?: string },
): Promise<string> {
  const token = c.slack_bot_token;
  const text = `🔔 *${r.subject || "Axyom"}*\n${r.body || ""}`;
  const taskId = /^task_/.test(r.kind || "") ? taskIdFromSource(r.source ?? null) : null;

  if (!token) {
    if (!c.slack_webhook_url) return "slack-skipped";
    const w = await fetch(c.slack_webhook_url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }) });
    if (!w.ok) throw new Error("webhook " + w.status);
    return "slack-webhook";
  }

  const users = await slackUsers(token);
  const target = matchUser(users, r.recipient_email ?? null, r.subject || "");
  const blocks = slackBlocks(text, taskId);

  if (target) {
    const opened = await slackApi(token, "conversations.open", { users: target.id });
    if (opened.ok && (opened.channel as { id?: string })?.id) {
      const dm = await slackApi(token, "chat.postMessage", { channel: (opened.channel as { id: string }).id, text, blocks });
      if (dm.ok) return `slack-dm:${target.id}`;
    }
    if (c.slack_channel_id) {
      const mentionText = `<@${target.id}> ${text}`;
      const pm = await slackApi(token, "chat.postMessage", {
        channel: c.slack_channel_id,
        text: mentionText,
        blocks: [{ type: "section", text: { type: "mrkdwn", text: mentionText } }, ...(taskId ? [blocks[1]] : [])],
      });
      if (pm.ok) return `slack-mention:${target.id}`;
      throw new Error("post " + pm.error);
    }
  } else if (c.slack_channel_id) {
    const pm = await slackApi(token, "chat.postMessage", { channel: c.slack_channel_id, text, blocks });
    if (pm.ok) return "slack-channel";
    throw new Error("post " + pm.error);
  }
  return "slack-skipped";
}

Deno.serve(async (req) => {
  const c = await loadConfig();
  // Auth: shared secret in dispatch_config, sent by the pg_cron job as x-cron-secret.
  if (!c.cron_secret || req.headers.get("x-cron-secret") !== c.cron_secret) {
    return new Response("forbidden", { status: 403 });
  }
  // Dormant until a delivery channel is configured — claim nothing so no row is
  // prematurely marked error.
  if (!c.ghl_pit && !c.slack_bot_token && !c.slack_webhook_url) {
    return Response.json({ skipped: "no channel" });
  }

  const { data: rows, error } = await sb.from("notify_queue").select("*").eq("status", "pending").order("created_at").limit(25);
  if (error) return Response.json({ error: error.message }, { status: 500 });

  const results: unknown[] = [];
  for (const r of rows ?? []) {
    const via: string[] = [];
    const failures: string[] = [];
    try {
      const to = r.recipient_email || c.default_recipient || "stevenglivingston@gmail.com";

      const [slackResult, emailResult] = await Promise.allSettled([
        sendSlack(c, r),
        c.ghl_pit ? sendEmail(c, to, r.subject || "Axyom", r.body || "") : Promise.resolve(null),
      ]);

      // Record only the channels that actually delivered — see the v7 note above.
      if (slackResult.status === "fulfilled") {
        via.push(slackResult.value);
      } else {
        failures.push("slack: " + String(slackResult.reason).slice(0, 150));
      }
      if (c.ghl_pit) {
        if (emailResult.status === "fulfilled") {
          via.push(`email:${to}`);
        } else {
          failures.push("email: " + String(emailResult.reason).slice(0, 150));
        }
      }

      // One surviving channel is still a delivery — only a total blackout counts
      // as failure.
      if (via.length === 0) {
        throw new Error(failures.join(" | ") || "no delivery channel succeeded");
      }

      // status guard avoids double-marking if a sweep raced us
      await sb
        .from("notify_queue")
        .update({
          status: "sent",
          sent_at: new Date().toISOString(),
          result: { via: via.join("+"), dispatcher: "edge-v7", ...(failures.length ? { partial_failures: failures } : {}) },
        })
        .eq("id", r.id)
        .eq("status", "pending");
      results.push({ id: r.id, ok: true, via });
    } catch (e) {
      const prev = (r.result && typeof r.result === "object" ? r.result : {}) as Record<string, unknown>;
      const retries = Number(prev.retries ?? 0) + 1;
      // Leave pending for 2 retries (next minute), then error out.
      await sb
        .from("notify_queue")
        .update(
          retries >= 3
            ? { status: "error", result: { ...prev, retries, error: String(e).slice(0, 300) } }
            : { result: { ...prev, retries, error: String(e).slice(0, 300) } },
        )
        .eq("id", r.id);
      results.push({ id: r.id, ok: false, error: String(e).slice(0, 120) });
    }
  }
  return Response.json({ processed: results.length, results, v: 7 });
});
