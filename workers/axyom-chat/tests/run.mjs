/**
 * Ask Axyom — local logic tests (no network, no wrangler).
 *
 * Mocks globalThis.fetch and drives the full Worker handler:
 *   1. OPTIONS preflight → 204 + CORS headers
 *   2. POST bad token   → 401
 *   3. POST bad body    → 400
 *   4. Full happy path  → auth ok → Claude asks for get_briefings + search_contacts
 *                         → tools dispatched → final text streamed as SSE
 *   5. Upstream Anthropic failure → structured SSE `error` event
 *   6. Tool-loop hard cap (model keeps calling tools forever) → `error` after 8 iterations
 *
 * Run:  node tests/run.mjs
 */

import worker from "../worker.js";

let passed = 0;
let failed = 0;
function assert(cond, label) {
  if (cond) {
    passed += 1;
    console.log(`  ok  - ${label}`);
  } else {
    failed += 1;
    console.error(`  FAIL - ${label}`);
  }
}

const execCtx = { waitUntil: () => {} };
const env = {
  ANTHROPIC_API_KEY: "test-key",
  GHL_PIT_KTU: "test-pit-ktu",
  GHL_PIT_BTU: "test-pit-btu",
};

function anthropicSSE(events) {
  const body = events
    .map((e) => `event: ${e.type}\ndata: ${JSON.stringify(e)}\n\n`)
    .join("");
  return new Response(body, {
    status: 200,
    headers: { "Content-Type": "text/event-stream" },
  });
}

/** Anthropic stream: tool_use turn. */
function toolUseTurn(toolName, input, id) {
  return anthropicSSE([
    { type: "message_start", message: {} },
    { type: "content_block_start", index: 0, content_block: { type: "text", text: "" } },
    { type: "content_block_delta", index: 0, delta: { type: "text_delta", text: "Checking… " } },
    { type: "content_block_stop", index: 0 },
    { type: "content_block_start", index: 1, content_block: { type: "tool_use", id, name: toolName } },
    { type: "content_block_delta", index: 1, delta: { type: "input_json_delta", partial_json: JSON.stringify(input) } },
    { type: "content_block_stop", index: 1 },
    { type: "message_delta", delta: { stop_reason: "tool_use" }, usage: {} },
    { type: "message_stop" },
  ]);
}

/** Anthropic stream: final text turn. */
function finalTurn(text) {
  return anthropicSSE([
    { type: "message_start", message: {} },
    { type: "content_block_start", index: 0, content_block: { type: "text", text: "" } },
    ...text.split(" ").map((w) => ({
      type: "content_block_delta",
      index: 0,
      delta: { type: "text_delta", text: w + " " },
    })),
    { type: "content_block_stop", index: 0 },
    { type: "message_delta", delta: { stop_reason: "end_turn" }, usage: {} },
    { type: "message_stop" },
  ]);
}

async function readSSE(response) {
  const raw = await response.text();
  const events = [];
  for (const chunk of raw.split("\n\n")) {
    if (!chunk.trim()) continue;
    let event = "message";
    let data = null;
    for (const line of chunk.split("\n")) {
      if (line.startsWith("event:")) event = line.slice(6).trim();
      if (line.startsWith("data:")) data = JSON.parse(line.slice(5).trim());
    }
    events.push({ event, data });
  }
  return events;
}

function chatRequest(body) {
  return new Request("https://dash.goaxyom.com/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json", Origin: "https://dash.goaxyom.com" },
    body: JSON.stringify(body),
  });
}

// ---------------------------------------------------------------------------

async function test1_preflight() {
  console.log("\n[1] OPTIONS preflight");
  const res = await worker.fetch(
    new Request("https://dash.goaxyom.com/api/chat", {
      method: "OPTIONS",
      headers: { Origin: "https://dash.goaxyom.com" },
    }),
    env,
    execCtx,
  );
  assert(res.status === 204, "status 204");
  assert(res.headers.get("Access-Control-Allow-Origin") === "https://dash.goaxyom.com", "ACAO header");
  assert((res.headers.get("Access-Control-Allow-Methods") || "").includes("POST"), "allows POST");
}

async function test2_badToken() {
  console.log("\n[2] POST with invalid token → 401");
  globalThis.fetch = async (url) => {
    if (String(url).includes("/auth/v1/user")) {
      return new Response(JSON.stringify({ message: "invalid JWT" }), { status: 401 });
    }
    throw new Error(`unexpected fetch: ${url}`);
  };
  const res = await worker.fetch(
    chatRequest({ token: "garbage", messages: [{ role: "user", content: "hi" }] }),
    env,
    execCtx,
  );
  assert(res.status === 401, "status 401");
  const body = await res.json();
  assert(/invalid|expired/i.test(body.error), "error message mentions invalid session");
  assert(res.headers.get("Access-Control-Allow-Origin") === "https://dash.goaxyom.com", "CORS on error response");
}

async function test3_badBody() {
  console.log("\n[3] POST with bad bodies → 400/401");
  const cases = [
    [{ token: "t" }, 400, "missing messages"],
    [{ messages: [{ role: "user", content: "hi" }] }, 401, "missing token"],
    [{ token: "t", messages: [{ role: "system", content: "x" }] }, 400, "bad role"],
    [{ token: "t", messages: [{ role: "user", content: "x".repeat(9000) }] }, 400, "oversize message"],
    [{ token: "t", messages: Array.from({ length: 41 }, () => ({ role: "user", content: "x" })) }, 400, "too many messages"],
  ];
  for (const [body, expected, label] of cases) {
    const res = await worker.fetch(chatRequest(body), env, execCtx);
    assert(res.status === expected, `${label} → ${expected}`);
  }
}

async function test4_happyPath() {
  console.log("\n[4] Full agentic loop: auth → tools → streamed answer");
  let anthropicCalls = 0;
  const anthropicBodies = [];
  const toolFetches = [];

  globalThis.fetch = async (url, init) => {
    const u = String(url);
    if (u.includes("/auth/v1/user")) {
      return new Response(JSON.stringify({ id: "user-123", email: "steven@example.com" }), { status: 200 });
    }
    if (u.includes("/rest/v1/profiles")) {
      return new Response(JSON.stringify([{ role: "admin", display_name: "Steven" }]), { status: 200 });
    }
    if (u.includes("/rest/v1/intranet_records")) {
      toolFetches.push({ kind: "supabase", url: u, auth: undefined });
      return new Response(
        JSON.stringify([
          { id: 1, section: "moola_briefing", brand: "Both", fields: { headline: "Cash up $12k" }, updated_at: "2026-07-05" },
        ]),
        { status: 200 },
      );
    }
    if (u.startsWith("https://services.leadconnectorhq.com/contacts/?")) {
      toolFetches.push({ kind: "ghl-search", url: u, headers: init?.headers });
      return new Response(
        JSON.stringify({ contacts: [{ id: "c1", firstName: "Jane", lastName: "Doe", email: "j@x.com" }] }),
        { status: 200 },
      );
    }
    if (u.startsWith("https://api.anthropic.com/v1/messages")) {
      anthropicCalls += 1;
      anthropicBodies.push(JSON.parse(init.body));
      if (anthropicCalls === 1) return toolUseTurn("get_briefings", { section: "moola_briefing" }, "tu_1");
      if (anthropicCalls === 2) return toolUseTurn("search_contacts", { business: "KTU", query: "Jane" }, "tu_2");
      return finalTurn("Cash is up $12k per this morning's Moola briefing.");
    }
    throw new Error(`unexpected fetch: ${u}`);
  };

  const res = await worker.fetch(
    chatRequest({ token: "valid-token", messages: [{ role: "user", content: "How's cash, and find Jane?" }] }),
    env,
    execCtx,
  );
  assert(res.status === 200, "status 200");
  assert((res.headers.get("Content-Type") || "").includes("text/event-stream"), "SSE content type");

  const events = await readSSE(res);
  const text = events.filter((e) => e.event === "text").map((e) => e.data.text).join("");
  const toolEvents = events.filter((e) => e.event === "tool");
  const doneEvents = events.filter((e) => e.event === "done");

  assert(anthropicCalls === 3, `3 Claude turns (got ${anthropicCalls})`);
  assert(text.includes("Cash is up $12k"), "final answer text streamed");
  assert(
    toolEvents.some((e) => e.data.name === "get_briefings" && e.data.status === "done"),
    "get_briefings dispatched + done",
  );
  assert(
    toolEvents.some((e) => e.data.name === "search_contacts" && e.data.status === "done"),
    "search_contacts dispatched + done",
  );
  assert(doneEvents.length === 1 && doneEvents[0].data.stop_reason === "end_turn", "done event with end_turn");

  // Verify the tool_result was echoed back to Claude correctly
  const secondTurn = anthropicBodies[1];
  const toolResultMsg = secondTurn.messages.at(-1);
  assert(toolResultMsg.role === "user" && toolResultMsg.content[0].type === "tool_result", "tool_result sent back in one user message");
  assert(toolResultMsg.content[0].tool_use_id === "tu_1", "tool_use_id matches");
  assert(JSON.parse(toolResultMsg.content[0].content).rows[0].fields.headline === "Cash up $12k", "supabase rows in tool result");
  assert(anthropicBodies[0].model === "claude-sonnet-5", "model is claude-sonnet-5");
  assert(anthropicBodies[0].stream === true, "streaming requested");
  assert(anthropicBodies[0].system.includes("Steven"), "system prompt carries user name");
  assert(anthropicBodies[0].system.includes("OWNER"), "system prompt carries admin role");

  // GHL search used the right location + PIT header
  const ghl = toolFetches.find((f) => f.kind === "ghl-search");
  assert(ghl && ghl.url.includes("nHLCxHPidnhV1NFzRtZZ"), "GHL KTU locationId in query");
  assert(ghl && ghl.headers.Authorization === "Bearer test-pit-ktu", "GHL KTU PIT used");
}

async function test5_upstreamFailure() {
  console.log("\n[5] Anthropic upstream failure → structured SSE error");
  globalThis.fetch = async (url) => {
    const u = String(url);
    if (u.includes("/auth/v1/user")) {
      return new Response(JSON.stringify({ id: "user-123", email: "s@x.com" }), { status: 200 });
    }
    if (u.includes("/rest/v1/profiles")) {
      return new Response(JSON.stringify([]), { status: 200 });
    }
    if (u.startsWith("https://api.anthropic.com/")) {
      return new Response(JSON.stringify({ error: { type: "overloaded_error", message: "Overloaded" } }), { status: 529 });
    }
    throw new Error(`unexpected fetch: ${u}`);
  };
  const res = await worker.fetch(
    chatRequest({ token: "valid", messages: [{ role: "user", content: "hi" }] }),
    env,
    execCtx,
  );
  assert(res.status === 200, "SSE stream still opens (200)");
  const events = await readSSE(res);
  const errs = events.filter((e) => e.event === "error");
  assert(errs.length === 1, "exactly one error event");
  assert(errs[0].data.code === "upstream_529", `error code upstream_529 (got ${errs[0]?.data?.code})`);
  assert(/overloaded/i.test(errs[0].data.message), "error message carries upstream detail");
}

async function test6_toolLoopCap() {
  console.log("\n[6] Runaway tool loop capped at 8 iterations");
  let anthropicCalls = 0;
  globalThis.fetch = async (url) => {
    const u = String(url);
    if (u.includes("/auth/v1/user")) {
      return new Response(JSON.stringify({ id: "user-123", email: "s@x.com" }), { status: 200 });
    }
    if (u.includes("/rest/v1/profiles")) {
      return new Response(JSON.stringify([]), { status: 200 });
    }
    if (u.includes("/rest/v1/intranet_records")) {
      return new Response(JSON.stringify([]), { status: 200 });
    }
    if (u.startsWith("https://api.anthropic.com/")) {
      anthropicCalls += 1;
      return toolUseTurn("get_briefings", {}, `tu_${anthropicCalls}`);
    }
    throw new Error(`unexpected fetch: ${u}`);
  };
  const res = await worker.fetch(
    chatRequest({ token: "valid", messages: [{ role: "user", content: "loop forever" }] }),
    env,
    execCtx,
  );
  const events = await readSSE(res);
  const errs = events.filter((e) => e.event === "error");
  assert(anthropicCalls === 8, `exactly 8 Claude turns (got ${anthropicCalls})`);
  assert(errs.length === 1 && errs[0].data.code === "tool_loop_limit", "tool_loop_limit error emitted");
}

async function test7_smStub() {
  console.log("\n[7] ServiceMinder stub degrades gracefully");
  const { executeTool } = await import("../worker.js");
  const r = await executeTool("serviceminder_lookup", { business: "KTU", kind: "invoices" }, { env: {}, token: "t" });
  const parsed = JSON.parse(r.content);
  assert(parsed.not_connected === true, "reports not_connected");
  assert(/not connected yet/i.test(parsed.error), "clear 'not connected yet' message");
  const r2 = await executeTool("serviceminder_lookup", { business: "BTU", kind: "invoices" }, { env: { SM_KEY_BTU: "k" }, token: "t" });
  assert(/configured/.test(JSON.parse(r2.content).error), "with key present, still graceful (wiring pending)");
}

async function test8_dispatchTask() {
  console.log("\n[8] dispatch_task queues a task in intranet_records (RLS via user token)");
  const { executeTool } = await import("../worker.js");
  let insertBody = null;
  let insertHeaders = null;

  globalThis.fetch = async (url, init) => {
    const u = String(url);
    if (u.includes("/rest/v1/intranet_records") && (!init || !init.method || init.method === "GET")) {
      // sort_order lookup
      return new Response(JSON.stringify([{ sort_order: 4 }]), { status: 200 });
    }
    if (u.endsWith("/rest/v1/intranet_records") && init.method === "POST") {
      insertBody = JSON.parse(init.body);
      insertHeaders = init.headers;
      return new Response(JSON.stringify([{ id: "rec-99", ...insertBody }]), { status: 201 });
    }
    throw new Error(`unexpected fetch: ${u}`);
  };

  const ctx = { env: {}, token: "user-token", user: { id: "u1", email: "steven@example.com" } };
  const r = await executeTool(
    "dispatch_task",
    { agent: "tekky", instruction: "GHL BTU sync is failing — diagnose and repair the webhook", priority: "high" },
    ctx,
  );
  const parsed = JSON.parse(r.content);

  assert(r.isError === false, "tool reports success");
  assert(parsed.ok === true && parsed.queued.id === "rec-99", "returns queued record id");
  assert(insertBody.section === "ax_tasks", "section is ax_tasks");
  assert(insertBody.brand === "Both", "brand follows intranet convention");
  assert(insertBody.sort_order === 5, "sort_order = max+1 (intranet convention)");
  const f = insertBody.fields;
  assert(f.requested_by === "steven@example.com", "requested_by = user email");
  assert(f.agent === "tekky" && f.priority === "high" && f.status === "queued", "agent/priority/status set");
  assert(typeof f.created_at === "string" && !Number.isNaN(Date.parse(f.created_at)), "created_at is ISO timestamp");
  assert(f.source === "ask_axyom", "source tagged");
  assert(insertHeaders.Authorization === "Bearer user-token", "insert uses the USER'S token (RLS-safe)");
  assert(/next daily run/i.test(parsed.expectations), "honest expectations for scheduled agents");

  // 'ax' target gets hourly expectations
  const r2 = await executeTool("dispatch_task", { agent: "ax", instruction: "post a reminder" }, ctx);
  assert(/hourly dispatcher|top of the hour/i.test(JSON.parse(r2.content).expectations), "hourly expectations for ax");

  // validation failures
  const bad1 = await executeTool("dispatch_task", { agent: "skynet", instruction: "x" }, ctx);
  assert(bad1.isError && /agent must be one of/.test(JSON.parse(bad1.content).error), "unknown agent rejected");
  const bad2 = await executeTool("dispatch_task", { agent: "moola", instruction: "  " }, ctx);
  assert(bad2.isError && /instruction is required/.test(JSON.parse(bad2.content).error), "empty instruction rejected");
  const bad3 = await executeTool("dispatch_task", { agent: "moola", instruction: "y".repeat(2100) }, ctx);
  assert(bad3.isError && /too long/.test(JSON.parse(bad3.content).error), "oversize instruction rejected");

  // RLS / write failure → honest "NOT queued"
  globalThis.fetch = async (url, init) => {
    if (init && init.method === "POST") return new Response("permission denied", { status: 403 });
    return new Response(JSON.stringify([]), { status: 200 });
  };
  const denied = await executeTool("dispatch_task", { agent: "moola", instruction: "check AR" }, ctx);
  const dp = JSON.parse(denied.content);
  assert(denied.isError && /NOT queued/.test(dp.error) && /403/.test(dp.error), "write failure surfaces clearly");
}

async function test9_systemStatusTekky() {
  console.log("\n[9] get_system_status — Tekky present, everything healthy");
  const { executeTool } = await import("../worker.js");
  const nowIso = new Date().toISOString();

  globalThis.fetch = async (url, init) => {
    const u = String(url);
    if (u.includes("section=in.%28") || u.includes("section=in.(")) {
      return new Response(
        JSON.stringify([{ section: "tekky_status", fields: { overall: "green" }, updated_at: nowIso }]),
        { status: 200 },
      );
    }
    if (u.includes("select=updated_at")) {
      return new Response(JSON.stringify([{ updated_at: nowIso }]), { status: 200 });
    }
    if (u.includes("select=id")) {
      return new Response(JSON.stringify([{ id: 1 }, { id: 2 }]), { status: 200 });
    }
    if (u === "https://dash.goaxyom.com/" && init && init.method === "HEAD") {
      return new Response(null, { status: 200 });
    }
    throw new Error(`unexpected fetch: ${u}`);
  };

  const r = await executeTool("get_system_status", {}, { env: {}, token: "t", user: { id: "u1" } });
  const s = JSON.parse(r.content);
  assert(s.ok === true, "ok");
  assert(Array.isArray(s.tekky) && s.tekky[0].section === "tekky_status", "tekky rows included");
  assert(s.agent_freshness.length >= 6 && s.agent_freshness.every((f) => f.status === "fresh"), "all agents fresh");
  assert(s.task_queue.queued_tasks === 2, "queued task depth reported");
  assert(s.intranet.reachable === true && s.intranet.http_status === 200, "intranet reachable via HEAD");
}

async function test10_systemStatusFallback() {
  console.log("\n[10] get_system_status — no Tekky yet, stale + silent agents, intranet down");
  const { executeTool } = await import("../worker.js");
  const staleIso = new Date(Date.now() - 100 * 3600 * 1000).toISOString(); // 100h old
  const freshIso = new Date().toISOString();

  globalThis.fetch = async (url, init) => {
    const u = String(url);
    if (u.includes("section=in.%28") || u.includes("section=in.(")) {
      return new Response(JSON.stringify([]), { status: 200 }); // tekky absent
    }
    if (u.includes("select=updated_at")) {
      if (u.includes("moola_briefing")) return new Response(JSON.stringify([{ updated_at: freshIso }]), { status: 200 });
      if (u.includes("goldeneye_callouts")) return new Response(JSON.stringify([{ updated_at: staleIso }]), { status: 200 });
      return new Response(JSON.stringify([]), { status: 200 }); // silent
    }
    if (u.includes("select=id")) {
      return new Response(JSON.stringify([]), { status: 200 });
    }
    if (u === "https://dash.goaxyom.com/" && init && init.method === "HEAD") {
      throw new Error("connect timeout");
    }
    throw new Error(`unexpected fetch: ${u}`);
  };

  const r = await executeTool("get_system_status", {}, { env: {}, token: "t", user: { id: "u1" } });
  const s = JSON.parse(r.content);
  const bySection = Object.fromEntries(s.agent_freshness.map((f) => [f.section, f]));
  assert(s.tekky && typeof s.tekky.note === "string" && /no rows yet/.test(s.tekky.note), "tekky-absent fallback noted");
  assert(bySection.moola_briefing.status === "fresh", "moola fresh");
  assert(bySection.goldeneye_callouts.status === "stale" && bySection.goldeneye_callouts.age_hours > 36, "goldeneye flagged stale");
  assert(bySection.foreman_briefing.status === "silent", "foreman flagged silent (no rows)");
  assert(s.task_queue.queued_tasks === 0, "empty queue reported");
  assert(s.intranet.reachable === false && /timeout/i.test(s.intranet.error), "intranet unreachable reported");
}

// ---------------------------------------------------------------------------

const realFetch = globalThis.fetch;
try {
  await test1_preflight();
  await test2_badToken();
  await test3_badBody();
  await test4_happyPath();
  await test5_upstreamFailure();
  await test6_toolLoopCap();
  await test7_smStub();
  await test8_dispatchTask();
  await test9_systemStatusTekky();
  await test10_systemStatusFallback();
} finally {
  globalThis.fetch = realFetch;
}

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
