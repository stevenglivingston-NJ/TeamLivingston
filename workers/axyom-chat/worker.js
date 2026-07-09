/**
 * Ask Axyom — chat backend for the Axyom intranet (dash.goaxyom.com).
 *
 * POST /api/chat  { messages: [{role, content}], token: <supabase user access token> }
 *   → SSE stream of the assistant reply (see README.md for the event contract).
 *
 * Secrets (never hardcoded — set via `wrangler secret put`):
 *   ANTHROPIC_API_KEY   — Claude API key
 *   GHL_PIT_KTU         — HighLevel Private Integration Token, KTU location
 *   GHL_PIT_BTU         — HighLevel Private Integration Token, BTU location
 *   SM_KEY_KTU/SM_KEY_BTU — ServiceMinder (future; tool degrades gracefully until set)
 */

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

// Browser-safe publishable anon key — the same one already shipped in the
// intranet's index.html. NOT a secret. RLS is enforced by the user's own token.
const SUPABASE_URL = "https://tguwpswcneywvscxzyef.supabase.co";
const SUPABASE_ANON_KEY = "sb_publishable_hKLxzY6OYVcAYDI-ymF0LQ_i6fxw2yC";

const ANTHROPIC_URL = "https://api.anthropic.com/v1/messages";
const ANTHROPIC_VERSION = "2023-06-01";
const MODEL = "claude-sonnet-5";
const MAX_OUTPUT_TOKENS = 8000;

const GHL_BASE = "https://services.leadconnectorhq.com";
const GHL_VERSION = "2021-07-28";
const GHL_LOCATIONS = {
  KTU: "nHLCxHPidnhV1NFzRtZZ",
  BTU: "0uWA8M5BzHrrcJftuaDe",
};

const ALLOWED_ORIGINS = new Set([
  "https://dash.goaxyom.com",
  // Local UI development against `wrangler dev`:
  "http://localhost:8788",
  "http://127.0.0.1:8788",
]);

// Input limits
const MAX_MESSAGES = 40;
const MAX_MESSAGE_CHARS = 8000;
const MAX_TOTAL_CHARS = 60000;

// Hard cap on agentic tool-loop iterations
const MAX_TOOL_ITERATIONS = 8;

// Cap on any single tool result fed back to the model
const MAX_TOOL_RESULT_CHARS = 20000;

// Known intranet_records briefing sections (documented for the model; the tool
// accepts any section string so new sections work without a redeploy).
const KNOWN_SECTIONS = [
  "moola_briefing",
  "goldeneye_callouts",
  "pipeline_briefing",
  "foreman_briefing",
  "client_status",
  "reports",
  "team_dates",
  "mkt_plan_items",
];

// Agent fleet that dispatch_task can target.
const AGENTS = ["ax", "moola", "foreman", "goldeneye", "paid", "harvest", "cellar", "tekky", "any"];
const PRIORITIES = ["low", "normal", "high", "urgent"];
const MAX_INSTRUCTION_CHARS = 2000;

// Task queue lives in intranet_records under this section — the zero-migration
// path: it reuses the existing table, RLS policies, and the intranet's
// section/fields conventions (section, brand, sort_order, fields jsonb,
// updated_at). A dedicated ax_tasks table (typed columns, status index,
// history) would be better long-term; see README "Dispatcher integration".
const TASK_SECTION = "ax_tasks";

// Sections written by Tekky (systems/infra diagnostics agent). These are being
// introduced — code defensively: they may not exist yet.
const TEKKY_SECTIONS = ["tekky_status", "tekky_briefing", "tekky_stack"];

// Per-agent briefing sections used for the freshness fallback in
// get_system_status. All are daily writers; older than STALE_HOURS = stale.
const AGENT_SECTIONS = [
  { agent: "moola", section: "moola_briefing" },
  { agent: "goldeneye", section: "goldeneye_callouts" },
  { agent: "foreman", section: "foreman_briefing" },
  { agent: "paid", section: "pipeline_briefing" },
  { agent: "(shared)", section: "client_status" },
  { agent: "(shared)", section: "reports" },
];
const STALE_HOURS = 36;
const INTRANET_URL = "https://dash.goaxyom.com/";

// ---------------------------------------------------------------------------
// Tool definitions (Claude API schema)
// ---------------------------------------------------------------------------

const TOOLS = [
  {
    name: "get_briefings",
    description:
      "Read the latest pre-computed agent briefings and callouts from the Axyom intranet " +
      "(Supabase table intranet_records). This is the fastest source for daily finance " +
      "(moola_briefing), customer-engagement callouts (goldeneye_callouts), pipeline " +
      "(pipeline_briefing), project ops (foreman_briefing), and client status " +
      `(client_status). Known sections: ${KNOWN_SECTIONS.join(", ")}. ` +
      "Call this FIRST for questions about daily numbers, callouts, briefings, or anything " +
      "already shown on the intranet. Rows are returned newest-first with their jsonb fields.",
    input_schema: {
      type: "object",
      properties: {
        section: {
          type: "string",
          description:
            "Optional section filter, e.g. 'moola_briefing'. Omit to get the most " +
            "recently updated rows across all sections.",
        },
        limit: {
          type: "integer",
          description: "Max rows to return (default 12, max 50).",
        },
      },
      required: [],
    },
  },
  {
    name: "search_contacts",
    description:
      "Search HighLevel CRM contacts for Kitchen Tune-Up (KTU) or Bath Tune-Up (BTU) by " +
      "name, email, or phone. Returns matching contacts with their ids. Call this when the " +
      "user asks about a specific customer or lead.",
    input_schema: {
      type: "object",
      properties: {
        business: {
          type: "string",
          enum: ["KTU", "BTU"],
          description: "Which business location to search.",
        },
        query: {
          type: "string",
          description: "Name, email, or phone fragment to search for.",
        },
      },
      required: ["business", "query"],
    },
  },
  {
    name: "get_contact_details",
    description:
      "Fetch full HighLevel contact details by contactId (from search_contacts), plus that " +
      "contact's appointments and pipeline opportunities when available.",
    input_schema: {
      type: "object",
      properties: {
        business: {
          type: "string",
          enum: ["KTU", "BTU"],
          description: "Which business location the contact belongs to.",
        },
        contactId: {
          type: "string",
          description: "HighLevel contact id from search_contacts.",
        },
      },
      required: ["business", "contactId"],
    },
  },
  {
    name: "serviceminder_lookup",
    description:
      "Look up ServiceMinder data (contacts, appointments, invoices, proposals) for KTU or " +
      "BTU. NOTE: this integration may not be connected yet — if it reports 'not connected', " +
      "tell the user plainly that ServiceMinder data is unavailable and answer from other sources.",
    input_schema: {
      type: "object",
      properties: {
        business: {
          type: "string",
          enum: ["KTU", "BTU"],
          description: "Which business location to query.",
        },
        kind: {
          type: "string",
          enum: ["contact", "appointments", "invoices", "proposals"],
          description: "What to look up.",
        },
        query: {
          type: "string",
          description: "Search term (contact name, invoice number, date range hint).",
        },
      },
      required: ["business", "kind"],
    },
  },
  {
    name: "dispatch_task",
    description:
      "Queue a command/task for the agent fleet. Use this when the user asks to FIX, change, " +
      "investigate, or have an agent do something. Targets: ax (hourly dispatcher — Slack, " +
      "email, JobTread/ServiceMinder notes), moola (finance/CFO), foreman (KTU/BTU projects), " +
      "goldeneye (customer engagement), paid (KTU/BTU marketing), harvest (Earthwise growth), " +
      "cellar (Earthwise supply/fulfillment), tekky (systems/infra diagnostics & repair), or " +
      "'any' (first available agent). Write a crisp, self-contained instruction — the agent " +
      "won't see this conversation. Diagnose first (get_system_status / get_briefings), then " +
      "dispatch with what you learned.",
    input_schema: {
      type: "object",
      properties: {
        agent: {
          type: "string",
          enum: AGENTS,
          description: "Which agent should handle this task.",
        },
        instruction: {
          type: "string",
          description:
            "Self-contained instruction for the agent (max 2000 chars). Include the specific " +
            "system, symptom/goal, and any ids or names the agent will need.",
        },
        priority: {
          type: "string",
          enum: PRIORITIES,
          description: "Task priority (default: normal).",
        },
      },
      required: ["agent", "instruction"],
    },
  },
  {
    name: "get_system_status",
    description:
      "Instant health diagnostics for the whole Axyom stack. Reads Tekky's latest status/" +
      "briefing/stack reports when present, checks how fresh every agent's briefing section is " +
      "(flagging stale or silent agents), reports the pending task-queue depth, and live-checks " +
      "that the intranet itself is reachable. Call this FIRST when the user reports something " +
      "broken, asks 'is X working', or asks for a system/agent health check.",
    input_schema: { type: "object", properties: {}, required: [] },
  },
];

// ---------------------------------------------------------------------------
// System prompt
// ---------------------------------------------------------------------------

function buildSystemPrompt(profile) {
  const roleLine =
    profile.role === "admin"
      ? "They are the OWNER (admin) — full access across all three businesses."
      : profile.role === "ecommerce"
        ? "Their workspace is Earthwise/Jatalia (ecommerce). Focus answers there; they do not work KTU/BTU jobs."
        : "Their workspace is KTU/BTU home services. Focus answers there; Earthwise ecommerce detail is not their day-to-day.";

  return `You are Ax — Team Livingston's business assistant, living inside the Axyom intranet (dash.goaxyom.com) as the "Ask Axyom" chat. You are direct, warm, and concise.

## The businesses
- **KTU** — Kitchen Tune-Up, 1285 Broad St Suite 2, Bloomfield NJ 07003 (kitchen remodeling franchise).
- **BTU** — Bath Tune-Up, same address (bath remodeling franchise).
- **Jatalia / Earthwise** — Earthwise Seeds ecommerce (Shopify, Amazon, Walmart; ops dashboard jataliamarketplace.com).
- The agent team writes daily briefings to the intranet: Moola (CFO, finance), Goldeneye (customer-engagement callouts), Foreman (KTU/BTU project ops), Paid (KTU/BTU paid marketing), Harvest (Earthwise growth), Cellar (Earthwise supply/fulfillment), Tekky (systems/infra diagnostics & repair). Ax (you, in your hourly Slack form) is the dispatcher that executes and relays queued tasks.

## Who you're talking to
${profile.display_name ? `Name: ${profile.display_name}.` : ""} ${roleLine}

## How you answer
- **Never invent numbers.** Every figure must come from a tool call in this conversation. If you can't reach the data, say exactly which system was unreachable — never guess.
- Lead with the answer/number, then 1–3 supporting lines, then cite the source system ("intranet moola_briefing, updated today", "HighLevel KTU, pulled just now").
- get_briefings is your fastest source — the agent team pre-computes daily numbers there. Check it before reaching for live CRM lookups.
- For specific customers/leads use search_contacts → get_contact_details (HighLevel).
- ServiceMinder may not be connected yet; if the tool says so, state that plainly.
- Keep customer PII minimal: first name + last initial is usually enough unless the user asked about a specific person.
- Keep replies short — this is a chat widget, not a report.

## Diagnose & dispatch
You can DIAGNOSE and DISPATCH — you are not purely read-only anymore, but your only write is queueing tasks:
- **Diagnose**: get_system_status (stack health, stale/silent agents, intranet reachability) and get_briefings (what the agents already found). Use these before claiming anything is broken or fixed.
- **Dispatch**: dispatch_task queues a command for any agent (ax, moola, foreman, goldeneye, paid, harvest, cellar, tekky, or 'any'). Write the instruction so the agent can act on it cold — it will not see this chat.
- When the user says "fix X" / "have Y do Z": (1) diagnose with tools, (2) if an agent can handle it, dispatch_task with a crisp instruction (systems/infra problems → tekky; finance → moola; projects → foreman; engagement → goldeneye; KTU/BTU marketing → paid; Earthwise growth → harvest; Earthwise supply → cellar; comms/notes/sync → ax; unsure → any), (3) tell the user exactly what was queued and when it will run — Ax's hourly dispatcher picks tasks up at the top of the hour; scheduled agents act on their next daily run. Never claim the fix already happened.
- Direct DATA edits (changing a record, a status, a client note) are still not yours to make — point those to the intranet's own editors, or dispatch to ax if it's a note/status sync the dispatcher handles.`;
}

// ---------------------------------------------------------------------------
// Small helpers
// ---------------------------------------------------------------------------

function corsHeaders(origin) {
  const allowed = ALLOWED_ORIGINS.has(origin) ? origin : "https://dash.goaxyom.com";
  return {
    "Access-Control-Allow-Origin": allowed,
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
    "Access-Control-Max-Age": "86400",
    Vary: "Origin",
  };
}

function jsonResponse(body, status, origin) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...corsHeaders(origin) },
  });
}

function truncate(str, max) {
  return str.length > max ? str.slice(0, max) + `\n…[truncated at ${max} chars]` : str;
}

function sseEncode(event, data) {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
}

// ---------------------------------------------------------------------------
// Auth: verify Supabase token, load profile (RLS applies via the user's token)
// ---------------------------------------------------------------------------

async function verifyUser(token) {
  const res = await fetch(`${SUPABASE_URL}/auth/v1/user`, {
    headers: { apikey: SUPABASE_ANON_KEY, Authorization: `Bearer ${token}` },
  });
  if (!res.ok) return null;
  const user = await res.json();
  return user && user.id ? user : null;
}

async function loadProfile(token, user) {
  const fallback = {
    role: "homeservices",
    display_name: (user.email || "user").split("@")[0],
  };
  try {
    const res = await fetch(
      `${SUPABASE_URL}/rest/v1/profiles?id=eq.${encodeURIComponent(user.id)}&select=role,display_name&limit=1`,
      { headers: { apikey: SUPABASE_ANON_KEY, Authorization: `Bearer ${token}` } },
    );
    if (!res.ok) return fallback;
    const rows = await res.json();
    if (Array.isArray(rows) && rows[0]) {
      return {
        role: rows[0].role || fallback.role,
        display_name: rows[0].display_name || fallback.display_name,
      };
    }
  } catch (_) {
    /* fall through */
  }
  return fallback;
}

// ---------------------------------------------------------------------------
// Tool implementations (server-side)
// ---------------------------------------------------------------------------

async function toolGetBriefings(input, ctx) {
  const limit = Math.min(Math.max(Number(input.limit) || 12, 1), 50);
  const params = new URLSearchParams({
    select: "id,section,brand,fields,updated_at",
    order: "updated_at.desc",
    limit: String(limit),
  });
  if (input.section) params.set("section", `eq.${input.section}`);
  const res = await fetch(`${SUPABASE_URL}/rest/v1/intranet_records?${params}`, {
    headers: { apikey: SUPABASE_ANON_KEY, Authorization: `Bearer ${ctx.token}` },
  });
  if (!res.ok) {
    return {
      ok: false,
      error: `Supabase REST returned ${res.status}. The intranet database may be unreachable or this user's access does not cover these rows.`,
    };
  }
  const rows = await res.json();
  if (!Array.isArray(rows) || rows.length === 0) {
    return {
      ok: true,
      rows: [],
      note: input.section
        ? `No rows in section '${input.section}'. Known sections: ${KNOWN_SECTIONS.join(", ")}.`
        : "No rows returned.",
    };
  }
  return { ok: true, count: rows.length, rows };
}

function ghlHeaders(pit) {
  return {
    Authorization: `Bearer ${pit}`,
    Version: GHL_VERSION,
    Accept: "application/json",
  };
}

function ghlPit(env, business) {
  return business === "KTU" ? env.GHL_PIT_KTU : env.GHL_PIT_BTU;
}

function slimContact(c) {
  if (!c) return c;
  return {
    id: c.id,
    firstName: c.firstName,
    lastName: c.lastName,
    email: c.email,
    phone: c.phone,
    companyName: c.companyName,
    tags: c.tags,
    source: c.source,
    dateAdded: c.dateAdded,
    city: c.city,
    state: c.state,
    address1: c.address1,
    assignedTo: c.assignedTo,
    lastActivity: c.lastActivity,
  };
}

async function toolSearchContacts(input, ctx) {
  const business = input.business === "BTU" ? "BTU" : "KTU";
  const pit = ghlPit(ctx.env, business);
  if (!pit) {
    return { ok: false, error: `HighLevel is not configured for ${business} (missing PIT secret).` };
  }
  const params = new URLSearchParams({
    locationId: GHL_LOCATIONS[business],
    query: String(input.query || "").slice(0, 200),
    limit: "10",
  });
  const res = await fetch(`${GHL_BASE}/contacts/?${params}`, { headers: ghlHeaders(pit) });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    return { ok: false, error: `HighLevel ${business} contacts search returned ${res.status}: ${truncate(body, 300)}` };
  }
  const data = await res.json();
  const contacts = (data.contacts || []).map(slimContact);
  return { ok: true, business, count: contacts.length, contacts };
}

async function toolGetContactDetails(input, ctx) {
  const business = input.business === "BTU" ? "BTU" : "KTU";
  const pit = ghlPit(ctx.env, business);
  if (!pit) {
    return { ok: false, error: `HighLevel is not configured for ${business} (missing PIT secret).` };
  }
  const id = encodeURIComponent(String(input.contactId || ""));
  const headers = ghlHeaders(pit);

  const contactRes = await fetch(`${GHL_BASE}/contacts/${id}`, { headers });
  if (!contactRes.ok) {
    const body = await contactRes.text().catch(() => "");
    return { ok: false, error: `HighLevel ${business} contact fetch returned ${contactRes.status}: ${truncate(body, 300)}` };
  }
  const contactData = await contactRes.json();
  const result = { ok: true, business, contact: contactData.contact || contactData };

  // Best-effort extras — never fail the tool if these endpoints error.
  const [apptRes, oppRes] = await Promise.all([
    fetch(`${GHL_BASE}/contacts/${id}/appointments`, { headers }).catch(() => null),
    fetch(
      `${GHL_BASE}/opportunities/search?${new URLSearchParams({
        location_id: GHL_LOCATIONS[business],
        contact_id: String(input.contactId || ""),
      })}`,
      { headers },
    ).catch(() => null),
  ]);
  if (apptRes && apptRes.ok) {
    const a = await apptRes.json().catch(() => null);
    if (a) result.appointments = a.events || a.appointments || a;
  } else {
    result.appointments_note = "appointments unavailable";
  }
  if (oppRes && oppRes.ok) {
    const o = await oppRes.json().catch(() => null);
    if (o) result.opportunities = o.opportunities || o;
  } else {
    result.opportunities_note = "opportunities unavailable";
  }
  return result;
}

async function toolServiceMinderLookup(input, ctx) {
  const business = input.business === "BTU" ? "BTU" : "KTU";
  const key = business === "KTU" ? ctx.env.SM_KEY_KTU : ctx.env.SM_KEY_BTU;
  if (!key) {
    return {
      ok: false,
      not_connected: true,
      error:
        `ServiceMinder is not connected yet for ${business} (API key pending). ` +
        "Tell the user ServiceMinder data is unavailable for now and answer from the intranet briefings or HighLevel instead.",
    };
  }
  // Interface is ready; endpoint wiring lands with the keys.
  return {
    ok: false,
    not_connected: true,
    error:
      `ServiceMinder key for ${business} is configured, but the lookup endpoints are not wired ` +
      "into Ask Axyom yet. Answer from the intranet briefings or HighLevel for now.",
  };
}

function supaHeaders(token, extra) {
  return { apikey: SUPABASE_ANON_KEY, Authorization: `Bearer ${token}`, ...(extra || {}) };
}

/**
 * dispatch_task — enqueue a command for the agent fleet.
 *
 * Queue record (intranet_records row, section 'ax_tasks'):
 *   { section: "ax_tasks", brand: "Both", sort_order: <next in section>,
 *     fields: { requested_by, agent, instruction, priority,
 *               status: "queued", created_at, source: "ask_axyom" } }
 * Status lifecycle (consumed by the hourly Ax dispatcher):
 *   queued → processing → done | relayed | error
 * Inserted with the USER'S token, so RLS decides who may queue tasks.
 */
async function toolDispatchTask(input, ctx) {
  const agent = String(input.agent || "").toLowerCase().trim();
  if (!AGENTS.includes(agent)) {
    return { ok: false, error: `agent must be one of: ${AGENTS.join(", ")}` };
  }
  const instruction = String(input.instruction || "").trim();
  if (!instruction) return { ok: false, error: "instruction is required" };
  if (instruction.length > MAX_INSTRUCTION_CHARS) {
    return { ok: false, error: `instruction too long (max ${MAX_INSTRUCTION_CHARS} chars) — tighten it` };
  }
  const priority = PRIORITIES.includes(input.priority) ? input.priority : "normal";

  // Follow the intranet convention: next sort_order within the section.
  let sortOrder = 1;
  try {
    const r = await fetch(
      `${SUPABASE_URL}/rest/v1/intranet_records?section=eq.${TASK_SECTION}&select=sort_order&order=sort_order.desc&limit=1`,
      { headers: supaHeaders(ctx.token) },
    );
    if (r.ok) {
      const rows = await r.json();
      if (Array.isArray(rows) && rows[0] && Number.isFinite(rows[0].sort_order)) {
        sortOrder = rows[0].sort_order + 1;
      }
    }
  } catch (_) {
    /* non-fatal — sort_order is cosmetic for a queue */
  }

  const fields = {
    requested_by: ctx.user.email || ctx.user.id,
    agent,
    instruction,
    priority,
    status: "queued",
    created_at: new Date().toISOString(),
    source: "ask_axyom",
  };

  const res = await fetch(`${SUPABASE_URL}/rest/v1/intranet_records`, {
    method: "POST",
    headers: supaHeaders(ctx.token, {
      "Content-Type": "application/json",
      Prefer: "return=representation",
    }),
    body: JSON.stringify({ section: TASK_SECTION, brand: "Both", sort_order: sortOrder, fields }),
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    return {
      ok: false,
      error:
        `Could not queue the task — Supabase returned ${res.status}: ${truncate(body, 300)}. ` +
        "This user's account may not have write access (RLS), or the database is unreachable. " +
        "Tell the user the task was NOT queued.",
    };
  }
  const rows = await res.json().catch(() => []);
  const id = Array.isArray(rows) && rows[0] ? rows[0].id : undefined;

  return {
    ok: true,
    queued: { id, agent, instruction, priority, requested_by: fields.requested_by, status: "queued" },
    expectations:
      agent === "ax" || agent === "any"
        ? "Ax's hourly dispatcher picks this up on its next run (top of the hour) and executes or routes it."
        : `Ax's hourly dispatcher relays this to ${agent} within the hour; ${agent} is a scheduled agent, so the work itself lands on ${agent}'s next daily run. For anything truly urgent, also flag it to Steven directly.`,
  };
}

/**
 * get_system_status — instant diagnostics across the stack.
 * Tekky sections preferred; falls back to per-agent briefing freshness.
 */
async function toolGetSystemStatus(input, ctx) {
  const headers = supaHeaders(ctx.token);
  const now = Date.now();

  // 1) Tekky reports (may not exist yet — defensive)
  let tekky = null;
  try {
    const r = await fetch(
      `${SUPABASE_URL}/rest/v1/intranet_records?section=in.(${TEKKY_SECTIONS.join(",")})&select=section,fields,updated_at&order=updated_at.desc&limit=15`,
      { headers },
    );
    if (r.ok) {
      const rows = await r.json();
      if (Array.isArray(rows) && rows.length > 0) tekky = rows;
    }
  } catch (_) {
    /* fall through to freshness check */
  }

  // 2) Freshness of every known agent section (always included — it's cheap
  //    and catches a silent agent even when Tekky itself is fine)
  const freshness = await Promise.all(
    AGENT_SECTIONS.map(async ({ agent, section }) => {
      try {
        const r = await fetch(
          `${SUPABASE_URL}/rest/v1/intranet_records?section=eq.${section}&select=updated_at&order=updated_at.desc&limit=1`,
          { headers },
        );
        if (!r.ok) return { agent, section, status: `query_error_${r.status}` };
        const rows = await r.json();
        if (!Array.isArray(rows) || rows.length === 0) {
          return { agent, section, status: "silent", note: "no rows — agent has never written here (or RLS hides it)" };
        }
        const ageHours = Math.round(((now - Date.parse(rows[0].updated_at)) / 36e5) * 10) / 10;
        return {
          agent,
          section,
          last_updated: rows[0].updated_at,
          age_hours: ageHours,
          status: ageHours > STALE_HOURS ? "stale" : "fresh",
        };
      } catch (_) {
        return { agent, section, status: "unreachable" };
      }
    }),
  );

  // 3) Pending task-queue depth
  let taskQueue = { note: "unavailable" };
  try {
    const params = new URLSearchParams({ select: "id", limit: "100" });
    params.set("section", `eq.${TASK_SECTION}`);
    params.set("fields->>status", "eq.queued");
    const r = await fetch(`${SUPABASE_URL}/rest/v1/intranet_records?${params}`, { headers });
    if (r.ok) {
      const rows = await r.json();
      taskQueue = { queued_tasks: Array.isArray(rows) ? rows.length : 0 };
    }
  } catch (_) {
    /* leave unavailable */
  }

  // 4) Live intranet reachability
  let intranet = { url: INTRANET_URL, reachable: false };
  try {
    const r = await fetch(INTRANET_URL, { method: "HEAD", signal: AbortSignal.timeout(5000) });
    intranet = { url: INTRANET_URL, reachable: r.ok, http_status: r.status };
  } catch (err) {
    intranet.error = err.name === "TimeoutError" ? "timed out after 5s" : err.message || String(err);
  }

  return {
    ok: true,
    checked_at: new Date(now).toISOString(),
    tekky:
      tekky || {
        note:
          "Tekky sections (tekky_status/tekky_briefing/tekky_stack) have no rows yet — " +
          "using per-agent briefing freshness below as the health signal.",
      },
    agent_freshness: freshness,
    stale_threshold_hours: STALE_HOURS,
    task_queue: taskQueue,
    intranet,
  };
}

const TOOL_IMPLS = {
  get_briefings: toolGetBriefings,
  search_contacts: toolSearchContacts,
  get_contact_details: toolGetContactDetails,
  serviceminder_lookup: toolServiceMinderLookup,
  dispatch_task: toolDispatchTask,
  get_system_status: toolGetSystemStatus,
};

async function executeTool(name, input, ctx) {
  const impl = TOOL_IMPLS[name];
  if (!impl) return { content: JSON.stringify({ ok: false, error: `Unknown tool: ${name}` }), isError: true };
  try {
    const result = await impl(input || {}, ctx);
    return {
      content: truncate(JSON.stringify(result), MAX_TOOL_RESULT_CHARS),
      isError: result && result.ok === false,
    };
  } catch (err) {
    return {
      content: JSON.stringify({ ok: false, error: `Tool '${name}' failed: ${err.message || String(err)}` }),
      isError: true,
    };
  }
}

// ---------------------------------------------------------------------------
// Anthropic streaming call — one Messages API turn
// ---------------------------------------------------------------------------

/**
 * Calls the Messages API with stream:true. Forwards text deltas via onText.
 * Returns { content: <assistant content blocks>, stopReason }.
 * Throws on non-200 or malformed stream.
 */
async function anthropicTurn(env, system, messages, onText) {
  const res = await fetch(ANTHROPIC_URL, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "x-api-key": env.ANTHROPIC_API_KEY,
      "anthropic-version": ANTHROPIC_VERSION,
    },
    body: JSON.stringify({
      model: MODEL,
      max_tokens: MAX_OUTPUT_TOKENS,
      system,
      messages,
      tools: TOOLS,
      stream: true,
    }),
  });

  if (!res.ok) {
    let detail = "";
    try {
      const errBody = await res.json();
      detail = errBody?.error?.message || JSON.stringify(errBody);
    } catch (_) {
      detail = await res.text().catch(() => "");
    }
    const err = new Error(`Claude API error ${res.status}: ${truncate(detail, 400)}`);
    err.status = res.status;
    throw err;
  }

  const blocks = []; // finalized content blocks, in order
  const open = {}; // index -> partial block state
  let stopReason = null;

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const handleEvent = (data) => {
    switch (data.type) {
      case "content_block_start": {
        const b = data.content_block;
        if (b.type === "text") {
          open[data.index] = { type: "text", text: b.text || "" };
        } else if (b.type === "tool_use") {
          open[data.index] = { type: "tool_use", id: b.id, name: b.name, _json: "" };
        } else if (b.type === "thinking") {
          open[data.index] = { type: "thinking", thinking: b.thinking || "", signature: "" };
        } else if (b.type === "redacted_thinking") {
          open[data.index] = { type: "redacted_thinking", data: b.data };
        } else {
          open[data.index] = { ...b };
        }
        break;
      }
      case "content_block_delta": {
        const blk = open[data.index];
        if (!blk) break;
        const d = data.delta;
        if (d.type === "text_delta") {
          blk.text += d.text;
          onText(d.text);
        } else if (d.type === "input_json_delta") {
          blk._json += d.partial_json;
        } else if (d.type === "thinking_delta") {
          blk.thinking += d.thinking;
        } else if (d.type === "signature_delta") {
          blk.signature = (blk.signature || "") + d.signature;
        }
        break;
      }
      case "content_block_stop": {
        const blk = open[data.index];
        if (!blk) break;
        if (blk.type === "tool_use") {
          let parsed = {};
          try {
            parsed = blk._json ? JSON.parse(blk._json) : {};
          } catch (_) {
            parsed = {};
          }
          blocks[data.index] = { type: "tool_use", id: blk.id, name: blk.name, input: parsed };
        } else {
          delete blk._json;
          blocks[data.index] = blk;
        }
        delete open[data.index];
        break;
      }
      case "message_delta": {
        if (data.delta && data.delta.stop_reason) stopReason = data.delta.stop_reason;
        break;
      }
      case "error": {
        throw new Error(`Claude stream error: ${data.error?.message || "unknown"}`);
      }
      default:
        break; // message_start, message_stop, ping
    }
  };

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    // SSE events are separated by a blank line
    let idx;
    while ((idx = buffer.indexOf("\n\n")) !== -1) {
      const rawEvent = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      for (const line of rawEvent.split("\n")) {
        if (line.startsWith("data:")) {
          const payload = line.slice(5).trim();
          if (!payload) continue;
          let data;
          try {
            data = JSON.parse(payload);
          } catch (_) {
            continue;
          }
          handleEvent(data);
        }
      }
    }
  }

  // Compact: drop holes, keep order
  const content = blocks.filter(Boolean);
  return { content, stopReason };
}

// ---------------------------------------------------------------------------
// The agentic loop, streamed to the client as SSE
// ---------------------------------------------------------------------------

async function runChat(env, ctx, system, userMessages, writer) {
  const encoder = new TextEncoder();
  const send = (event, data) => writer.write(encoder.encode(sseEncode(event, data)));

  const messages = [...userMessages];
  let iterations = 0;

  try {
    while (true) {
      iterations += 1;
      if (iterations > MAX_TOOL_ITERATIONS) {
        await send("error", {
          message: `Stopped after ${MAX_TOOL_ITERATIONS} tool iterations — the question may be too broad. Try asking something more specific.`,
          code: "tool_loop_limit",
        });
        break;
      }

      const { content, stopReason } = await anthropicTurn(env, system, messages, (text) => {
        send("text", { text });
      });

      if (stopReason === "tool_use") {
        messages.push({ role: "assistant", content });
        const toolUses = content.filter((b) => b.type === "tool_use");
        const results = [];
        for (const tu of toolUses) {
          await send("tool", { name: tu.name, status: "start" });
          const { content: resultContent, isError } = await executeTool(tu.name, tu.input, ctx);
          await send("tool", { name: tu.name, status: isError ? "error" : "done" });
          results.push({
            type: "tool_result",
            tool_use_id: tu.id,
            content: resultContent,
            ...(isError ? { is_error: true } : {}),
          });
        }
        // All tool results go back in ONE user message.
        messages.push({ role: "user", content: results });
        continue;
      }

      if (stopReason === "pause_turn") {
        messages.push({ role: "assistant", content });
        continue;
      }

      if (stopReason === "refusal") {
        await send("error", {
          message: "The assistant declined to answer this request.",
          code: "refusal",
        });
        break;
      }

      // end_turn / max_tokens / anything else — we're done.
      await send("done", { stop_reason: stopReason || "end_turn" });
      break;
    }
  } catch (err) {
    // Structured SSE error — upstream failures degrade gracefully.
    await send("error", {
      message: err.message || "Upstream request failed.",
      code: err.status ? `upstream_${err.status}` : "upstream_error",
    }).catch(() => {});
  } finally {
    try {
      await writer.close();
    } catch (_) {
      /* client already gone */
    }
  }
}

// ---------------------------------------------------------------------------
// Request validation
// ---------------------------------------------------------------------------

function validateMessages(raw) {
  if (!Array.isArray(raw) || raw.length === 0) return { error: "messages must be a non-empty array" };
  if (raw.length > MAX_MESSAGES) return { error: `too many messages (max ${MAX_MESSAGES})` };
  let total = 0;
  const messages = [];
  for (const m of raw) {
    if (!m || (m.role !== "user" && m.role !== "assistant")) {
      return { error: "each message needs role 'user' or 'assistant'" };
    }
    if (typeof m.content !== "string" || !m.content.trim()) {
      return { error: "each message needs non-empty string content" };
    }
    if (m.content.length > MAX_MESSAGE_CHARS) {
      return { error: `a message exceeds ${MAX_MESSAGE_CHARS} characters` };
    }
    total += m.content.length;
    messages.push({ role: m.role, content: m.content });
  }
  if (total > MAX_TOTAL_CHARS) return { error: `conversation exceeds ${MAX_TOTAL_CHARS} characters` };
  if (messages[0].role !== "user") return { error: "first message must be from the user" };
  if (messages[messages.length - 1].role !== "user") return { error: "last message must be from the user" };
  return { messages };
}

// ---------------------------------------------------------------------------
// Worker entry
// ---------------------------------------------------------------------------

export default {
  async fetch(request, env, executionCtx) {
    const origin = request.headers.get("Origin") || "";
    const url = new URL(request.url);

    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: corsHeaders(origin) });
    }

    if (url.pathname !== "/api/chat") {
      return jsonResponse({ error: "not found" }, 404, origin);
    }
    if (request.method !== "POST") {
      return jsonResponse({ error: "method not allowed" }, 405, origin);
    }
    if (!env.ANTHROPIC_API_KEY) {
      return jsonResponse({ error: "server not configured (missing ANTHROPIC_API_KEY)" }, 500, origin);
    }

    let body;
    try {
      body = await request.json();
    } catch (_) {
      return jsonResponse({ error: "invalid JSON body" }, 400, origin);
    }

    const token = typeof body.token === "string" ? body.token.trim() : "";
    if (!token) return jsonResponse({ error: "missing token" }, 401, origin);

    const validated = validateMessages(body.messages);
    if (validated.error) return jsonResponse({ error: validated.error }, 400, origin);

    // --- Auth: verify the Supabase user token ---
    let user;
    try {
      user = await verifyUser(token);
    } catch (err) {
      return jsonResponse({ error: "auth service unreachable" }, 502, origin);
    }
    if (!user) return jsonResponse({ error: "invalid or expired session" }, 401, origin);

    const profile = await loadProfile(token, user);
    const system = buildSystemPrompt(profile);
    const toolCtx = { env, token, user, profile };

    // --- Stream the reply as SSE ---
    const { readable, writable } = new TransformStream();
    const writer = writable.getWriter();
    const loop = runChat(env, toolCtx, system, validated.messages, writer);
    if (executionCtx && executionCtx.waitUntil) executionCtx.waitUntil(loop);

    return new Response(readable, {
      status: 200,
      headers: {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        Connection: "keep-alive",
        ...corsHeaders(origin),
      },
    });
  },
};

// Exported for tests (node tests import these directly).
// Note: only function exports — workerd rejects non-handler named exports.
export {
  validateMessages,
  buildSystemPrompt,
  executeTool,
  anthropicTurn,
  runChat,
  corsHeaders,
};
