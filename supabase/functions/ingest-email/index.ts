// ingest-email — OPTIONAL push endpoint for the firstgentalent@gmail.com pipe.
//
// NOTE: the live path is a direct Gmail-MCP PULL — Moola and Goldeneye read the
// firstgentalent inbox themselves each run and write payables/call_notes/contacts.
// This webhook is only needed if a push source (a forwarding rule / external
// poster) is ever wired instead; it writes the same tables so both paths agree.
//
// Auth: shared secret. Send it as header `x-ingest-secret: <value>` OR as a
// query param `?token=<value>` (dispatch_config.ingest_secret). No Supabase JWT
// required (verify_jwt is off) — this is a webhook.
//
// It stores every email raw in `inbox_emails`, makes a best-effort classification
// (invoice vs Perceptionist call note), and — when confident — also creates a
// `payables` row (a bill we owe) or a `call_notes` row. Moola and Goldeneye then
// refine those on their daily runs (dedupe, set priority, compute aging, and
// scrape the contact into the Directory).
import { createClient } from "npm:@supabase/supabase-js@2";

const sb = createClient(
  Deno.env.get("SUPABASE_URL")!,
  Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!,
);

async function ingestSecret(): Promise<string | null> {
  const secret = Deno.env.get("INGEST_SECRET");
  if (secret) return secret;
  const { data } = await sb.from("dispatch_config").select("value").eq("key", "ingest_secret").maybeSingle();
  return data?.value ?? null;
}

function pick(o: Record<string, unknown>, keys: string[]): string {
  for (const k of keys) {
    const v = o[k];
    if (typeof v === "string" && v.trim()) return v.trim();
    if (typeof v === "number") return String(v);
  }
  return "";
}

function guessBrand(t: string): string | null {
  const s = t.toLowerCase();
  if (/kitchen\s*tune|\bktu\b|first generation/.test(s)) return "KTU";
  if (/bath\s*tune|\bbtu\b|oracabessa/.test(s)) return "BTU";
  if (/earthwise|jatalia/.test(s)) return "Earthwise";
  return null;
}

function parseMoney(t: string): number | null {
  const matches = [...t.matchAll(/\$\s?([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{2})?|[0-9]+(?:\.[0-9]{2})?)/g)]
    .map((m) => Number(m[1].replace(/,/g, "")))
    .filter((n) => isFinite(n) && n > 0);
  if (!matches.length) return null;
  // Prefer an amount adjacent to "amount due / balance due / total"; else the max.
  const due = t.match(/(?:amount due|balance due|total due|please pay|total)\D{0,12}\$?\s?([0-9][0-9,]*(?:\.[0-9]{2})?)/i);
  if (due) { const n = Number(due[1].replace(/,/g, "")); if (isFinite(n) && n > 0) return n; }
  return Math.max(...matches);
}

function parseDate(t: string): string | null {
  const m = t.match(/due\s*(?:date|on|by)?\s*[:\-]?\s*([A-Za-z]{3,9}\.?\s+\d{1,2},?\s*\d{2,4}|\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})/i);
  if (!m) return null;
  const d = new Date(m[1]);
  return isNaN(+d) ? null : d.toISOString().slice(0, 10);
}

function parsePhone(t: string): string | null {
  const m = t.match(/(\+?1?[-.\s]?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4})/);
  return m ? m[1].trim() : null;
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok");
  if (req.method !== "POST") return new Response("method not allowed", { status: 405 });

  const secret = await ingestSecret();
  const url = new URL(req.url);
  const given = req.headers.get("x-ingest-secret") || url.searchParams.get("token") || "";
  if (!secret || given !== secret) return new Response("forbidden", { status: 403 });

  let payload: Record<string, unknown> = {};
  try {
    const ct = req.headers.get("content-type") || "";
    if (ct.includes("application/json")) payload = await req.json();
    else { const f = await req.formData(); f.forEach((v, k) => (payload[k] = typeof v === "string" ? v : "")); }
  } catch (_e) { /* fall through with empty payload */ }

  const subject = pick(payload, ["subject", "Subject", "email_subject"]);
  const from_addr = pick(payload, ["from", "from_addr", "From", "sender", "from_email"]);
  const to_addr = pick(payload, ["to", "to_addr", "To"]) || "firstgentalent@gmail.com";
  const body = pick(payload, ["body", "body_plain", "text", "body_plain_text", "plain", "html", "snippet", "Body"]);
  const received = pick(payload, ["received_at", "date", "Date", "received"]);
  const received_at = received && !isNaN(+new Date(received)) ? new Date(received).toISOString() : new Date().toISOString();
  const hay = `${subject}\n${from_addr}\n${body}`;
  const brand = (pick(payload, ["brand"]) || guessBrand(hay)) || null;

  // Classify
  const isCall = /perceptionist|missed call|new call|call from|inbound call|voicemail|caller/i.test(`${from_addr} ${subject} ${body}`);
  const isInvoice = /invoice|statement|amount due|balance due|remittance|past due|payment due|\bbill\b|net\s*\d+/i.test(`${subject} ${body}`);
  const kind = isCall ? "call_note" : isInvoice ? "invoice" : "unknown";

  // 1) Always store raw
  const { data: emailRow, error: e1 } = await sb.from("inbox_emails").insert({
    received_at, from_addr, to_addr, subject, body, kind, brand, raw: payload,
  }).select("id").single();
  if (e1) return Response.json({ error: e1.message }, { status: 500 });
  const emailId = emailRow?.id;

  const created: Record<string, unknown> = { inbox_email: emailId, kind };

  // 2) Best-effort structured row (agents refine later)
  try {
    if (kind === "invoice") {
      const amount = parseMoney(body || subject);
      const inv = (body || subject).match(/invoice\s*#?\s*[:]?\s*([A-Za-z0-9][A-Za-z0-9\-]{2,})/i);
      const vendor = (from_addr.match(/"?([^"<]+?)"?\s*</)?.[1] || from_addr.split("@")[1] || from_addr || "").trim() || null;
      const { data: pRow } = await sb.from("payables").insert({
        brand, vendor, invoice_number: inv?.[1] || null, amount,
        invoice_date: received_at.slice(0, 10), due_date: parseDate(body || ""),
        status: "unpaid", priority: "normal", source: "email:firstgentalent",
        source_email_id: emailId, notes: subject,
      }).select("id").single();
      created.payable = pRow?.id ?? null;
    } else if (kind === "call_note") {
      const { data: cRow } = await sb.from("call_notes").insert({
        brand, caller_phone: parsePhone(body || subject), call_time: received_at,
        summary: (body || subject).slice(0, 1000), disposition: null, follow_up: true,
        source: "perceptionist:firstgentalent", source_email_id: emailId,
      }).select("id").single();
      created.call_note = cRow?.id ?? null;
    }
  } catch (e) { created.parse_error = String(e).slice(0, 200); }

  return Response.json({ ok: true, ...created });
});
