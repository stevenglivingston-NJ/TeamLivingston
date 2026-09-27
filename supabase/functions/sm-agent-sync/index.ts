import "jsr:@supabase/functions-js/edge-runtime.d.ts";

/**
 * Daily ServiceMinder service-agent reconciliation, driven by pg_cron (see
 * migration rep_card_agent_sync_schedule) at 6am ET, same mechanism as
 * jc-forecast-sync (net.http_post + x-cron-secret from dispatch_config) —
 * NOT a Claude Code Remote Routine calling mcp__ServiceMinder__* tools, which
 * would stall forever waiting for a permission prompt nobody is present to
 * answer (see CLAUDE.md "Scheduled runs stall on MCP connector calls" and
 * .claude/agents/tekki.md / moola.md).
 *
 * For each brand (KTU, BTU): pulls serviceminder.io/api/serviceagents/all,
 * skips agents named "Delete" and anyone with a non-empty EndDate (SM's
 * inactive/terminated marker — confirmed live via `sm.sh KTU
 * serviceagents/all '{}'`, which returns a top-level EndDate string per
 * agent, empty for active reps), and for every remaining agent whose Name
 * does not match any profiles.sm_agent_name_ktu / sm_agent_name_btu:
 *   - upserts (brand, sm_agent_name) into unmapped_agents
 *   - queues a notify_queue row telling Steven a rep has no intranet profile
 */

const SUPA = Deno.env.get("SUPABASE_URL")!;
const SRK = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
const SM_BASE = "https://serviceminder.io/api";

const svcHeaders = {
  "Content-Type": "application/json",
  apikey: SRK,
  authorization: `Bearer ${SRK}`,
  "Content-Profile": "public",
  "Accept-Profile": "public",
};

const SM_KEYS: Record<string, string> = { KTU: "", BTU: "" };
async function loadSmKeys() {
  SM_KEYS.KTU = Deno.env.get("SM_KEY_KTU") ?? "";
  SM_KEYS.BTU = Deno.env.get("SM_KEY_BTU") ?? "";
  if (SM_KEYS.KTU && SM_KEYS.BTU) return;
  // Fall back to app_secrets, same keys jc-forecast-sync falls back to.
  const r = await fetch(`${SUPA}/rest/v1/app_secrets?select=key,value&key=in.(SM_KEY_KTU,SM_KEY_BTU)`, { headers: svcHeaders });
  if (!r.ok) return;
  const rows = (await r.json()) as { key: string; value: string }[];
  for (const row of rows) {
    if (row.key === "SM_KEY_KTU" && !SM_KEYS.KTU) SM_KEYS.KTU = row.value;
    if (row.key === "SM_KEY_BTU" && !SM_KEYS.BTU) SM_KEYS.BTU = row.value;
  }
}

async function smCall(brand: "KTU" | "BTU", endpoint: string, body: Record<string, unknown> = {}) {
  const payload = { ...body, ApiKey: SM_KEYS[brand] };
  const r = await fetch(`${SM_BASE}/${endpoint}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const text = await r.text();
  if (!text) throw new Error(`${brand} ${endpoint}: empty body (wrong path or bad key), status ${r.status}`);
  return JSON.parse(text);
}

async function fetchMappedNames(): Promise<{ ktu: Set<string>; btu: Set<string> }> {
  const r = await fetch(
    `${SUPA}/rest/v1/profiles?select=sm_agent_name_ktu,sm_agent_name_btu`,
    { headers: svcHeaders },
  );
  const rows = r.ok ? await r.json() : [];
  const ktu = new Set<string>(), btu = new Set<string>();
  for (const p of rows as { sm_agent_name_ktu?: string; sm_agent_name_btu?: string }[]) {
    if (p.sm_agent_name_ktu) ktu.add(p.sm_agent_name_ktu.trim().toLowerCase());
    if (p.sm_agent_name_btu) btu.add(p.sm_agent_name_btu.trim().toLowerCase());
  }
  return { ktu, btu };
}

async function upsertUnmapped(brand: string, name: string) {
  await fetch(`${SUPA}/rest/v1/unmapped_agents`, {
    method: "POST",
    headers: { ...svcHeaders, Prefer: "resolution=ignore-duplicates" },
    body: JSON.stringify({ brand, sm_agent_name: name }),
  });
}

async function alreadyNotified(brand: string, name: string): Promise<boolean> {
  const r = await fetch(
    `${SUPA}/rest/v1/unmapped_agents?brand=eq.${brand}&sm_agent_name=eq.${encodeURIComponent(name)}&select=first_seen`,
    { headers: svcHeaders },
  );
  if (!r.ok) return false;
  const rows = await r.json();
  return rows.length > 0; // row already existed before this run's upsert (ignore-duplicates left it untouched)
}

async function queueNotify(brand: string, name: string) {
  await fetch(`${SUPA}/rest/v1/notify_queue`, {
    method: "POST",
    headers: svcHeaders,
    body: JSON.stringify({
      kind: "unmapped_agent",
      recipient_email: "slivingston@kitchentuneup.com",
      subject: `New ServiceMinder rep with no intranet profile (${brand})`,
      body: `New ServiceMinder rep ${name} (${brand}) has no intranet customer profile.`,
      source: "sm-agent-sync",
      status: "pending",
    }),
  });
}

Deno.serve(async (req) => {
  const presented = req.headers.get("x-cron-secret") || "";
  const cfg = await fetch(`${SUPA}/rest/v1/dispatch_config?key=eq.cron_secret&select=value`, { headers: svcHeaders });
  const want = cfg.ok ? (await cfg.json())?.[0]?.value : null;
  if (!want || presented !== want) return new Response(JSON.stringify({ error: "unauthorized" }), { status: 401 });

  await loadSmKeys();
  const { ktu, btu } = await fetchMappedNames();
  const result: Record<string, unknown> = {};

  for (const brand of ["KTU", "BTU"] as const) {
    if (!SM_KEYS[brand]) { result[brand] = { error: "no SM key configured" }; continue; }
    try {
      const data = await smCall(brand, "serviceagents/all");
      const matches = (data?.Matches ?? []) as { Name?: string; EndDate?: string }[];
      const mapped = brand === "KTU" ? ktu : btu;
      let newlyFlagged = 0, skipped = 0;
      for (const agent of matches) {
        const name = (agent.Name ?? "").trim();
        if (!name || name.toLowerCase() === "delete") { skipped++; continue; }
        if (agent.EndDate && agent.EndDate.trim() !== "") { skipped++; continue; } // inactive/terminated
        if (mapped.has(name.toLowerCase())) continue; // has an intranet profile
        const wasKnown = await alreadyNotified(brand, name);
        await upsertUnmapped(brand, name);
        if (!wasKnown) {
          await queueNotify(brand, name);
          newlyFlagged++;
        }
      }
      result[brand] = { agents_seen: matches.length, skipped, newly_flagged: newlyFlagged };
    } catch (e) {
      result[brand] = { error: String((e as Error)?.message ?? e) };
    }
  }

  return new Response(JSON.stringify({ ok: true, ran_at: new Date().toISOString(), result }), {
    headers: { "Content-Type": "application/json" },
  });
});
