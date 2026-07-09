# Ask Axyom — chat backend (`axyom-chat`)

Live business-data chatbot backend for the Axyom intranet (dash.goaxyom.com).
A Cloudflare Worker that authenticates the intranet user's Supabase session,
runs a Claude (`claude-sonnet-5`) agentic tool loop server-side against live
business systems, and streams the answer back as Server-Sent Events.

**Diagnose & dispatch** — the chat can look things up (intranet briefings,
HighLevel CRM), run stack diagnostics (`get_system_status`), and **queue
commands for the agent fleet** (`dispatch_task`). Its only write is
task-queueing; it never edits business data directly — data edits still go
through the intranet's own editors.

## Endpoint

### `POST /api/chat`

Routed at `dash.goaxyom.com/api/chat*` (same host as the intranet, so the UI
can call a relative `/api/chat`). CORS also allows the origin explicitly.

**Request** (`Content-Type: application/json`):

```json
{
  "token": "<the user's Supabase access token — session.access_token>",
  "messages": [
    { "role": "user", "content": "How's cash this morning?" },
    { "role": "assistant", "content": "…previous reply…" },
    { "role": "user", "content": "And any Goldeneye callouts?" }
  ]
}
```

- `messages`: plain-string contents only, roles `user`/`assistant`, first and
  last must be `user`. Limits: ≤ 40 messages, ≤ 8,000 chars each,
  ≤ 60,000 chars total. The UI sends the whole visible conversation each turn
  (the backend is stateless).
- `token`: from the intranet's existing Supabase session
  (`(await sb.auth.getSession()).data.session.access_token`). The Worker
  verifies it against Supabase auth and uses it for all `intranet_records`
  reads, so RLS applies exactly as it does in the browser.

**Error responses** (JSON, before the stream starts):

| Status | Meaning |
|---|---|
| 400 | invalid JSON / messages fail validation (`{"error": "..."}`) |
| 401 | missing, invalid, or expired Supabase token |
| 404 / 405 | wrong path / method |
| 500 | Worker missing `ANTHROPIC_API_KEY` |
| 502 | Supabase auth unreachable |

**Success response**: `200` with `Content-Type: text/event-stream`. Events:

```
event: text
data: {"text":"partial assistant text…"}       ← append to the reply bubble

event: tool
data: {"name":"get_briefings","status":"start"}  ← show "checking intranet…"
data: {"name":"get_briefings","status":"done"}   ← statuses: start | done | error

event: done
data: {"stop_reason":"end_turn"}               ← reply complete, close stream

event: error
data: {"message":"…human-readable…","code":"upstream_529"}
                                               ← terminal; codes: upstream_<status>,
                                                 upstream_error, tool_loop_limit, refusal
```

Exactly one terminal event (`done` or `error`) ends every stream. Note the
stream itself is HTTP 200 even when it ends in `error` — the UI must handle
the `error` event, not just HTTP status.

Minimal UI consumption sketch:

```js
const res = await fetch("/api/chat", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ token, messages }),
});
if (!res.ok) { /* show (await res.json()).error */ }
const reader = res.body.getReader();
// parse SSE frames (split on "\n\n", read `event:` + `data:` lines)
```

### `OPTIONS /api/chat` — CORS preflight, returns 204.

Allowed origins: `https://dash.goaxyom.com` (plus localhost:8788 for dev).

## Tools available to the model

| Tool | Backs onto | Auth | Notes |
|---|---|---|---|
| `get_briefings(section?, limit?)` | Supabase REST `intranet_records` | **the user's own token** (RLS-safe) | Pre-computed agent briefings: `moola_briefing`, `goldeneye_callouts`, `pipeline_briefing`, `foreman_briefing`, `client_status`, … newest-first |
| `search_contacts(business, query)` | HighLevel `GET /contacts/` | `GHL_PIT_KTU` / `GHL_PIT_BTU` | KTU location `nHLCxHPidnhV1NFzRtZZ`, BTU `0uWA8M5BzHrrcJftuaDe` |
| `get_contact_details(business, contactId)` | HighLevel contact + appointments + opportunities | same PITs | extras are best-effort |
| `serviceminder_lookup(business, kind, query?)` | ServiceMinder | `SM_KEY_KTU` / `SM_KEY_BTU` (**pending**) | Graceful stub: returns "not connected yet" until keys land; interface is ready |
| `dispatch_task(agent, instruction, priority?)` | Supabase insert into `intranet_records` | **the user's own token** (RLS decides who may queue) | Queues a command for the fleet: `ax`, `moola`, `foreman`, `goldeneye`, `paid`, `harvest`, `cellar`, `tekky`, or `any`. Priorities: `low`/`normal`/`high`/`urgent`. Instruction ≤ 2,000 chars. |
| `get_system_status()` | Supabase reads + live `HEAD https://dash.goaxyom.com/` | user token / none | Tekky reports (`tekky_status`/`tekky_briefing`/`tekky_stack`) when present; always includes per-agent briefing freshness (fresh / stale >36h / silent), pending `ax_tasks` depth, intranet reachability (5s timeout) |

Safety rails: max 8 tool-loop iterations, tool results capped at 20K chars,
the user's `profiles.role` (admin / homeservices / ecommerce) and display name
are injected into the system prompt to scope answers. The "fix X" pattern the
model is instructed to follow: diagnose (`get_system_status`/`get_briefings`)
→ dispatch (`dispatch_task` with a crisp, self-contained instruction) → tell
the user what was queued and when it will run. It never claims a fix already
happened.

## Task queue record shape (`ax_tasks`)

`dispatch_task` writes one row to the existing `intranet_records` table —
chosen as the **zero-migration path** (reuses the table, its RLS policies, and
the intranet's section conventions). A dedicated `ax_tasks` table with typed
columns and a status index would be better long-term; migrate when convenient
— the record shape below is the contract either way.

```json
{
  "section": "ax_tasks",
  "brand": "Both",
  "sort_order": 7,
  "fields": {
    "requested_by": "stevenglivingston@gmail.com",
    "agent": "tekky",
    "instruction": "GHL BTU sync is failing — diagnose and repair the webhook",
    "priority": "high",
    "status": "queued",
    "created_at": "2026-07-05T14:00:00.000Z",
    "source": "ask_axyom"
  }
}
```

- `agent`: `ax | moola | foreman | goldeneye | paid | harvest | cellar | tekky | any`
- `priority`: `low | normal | high | urgent` (default `normal`)
- `status` lifecycle (written by the consumer, not this Worker):
  `queued → processing → done | relayed | error`
- `sort_order` follows the intranet's max+1 convention; ordering for queue
  consumers should use `fields->>created_at` (or the row's `updated_at`).
- Inserted with the **user's token**, so `requested_by` is verifiable and RLS
  controls who can queue. Both the intranet UI (a future "Tasks" tab) and the
  hourly Ax agent consume this shape.

## Dispatcher integration (change needed in `.claude/agents/ax.md`)

This Worker only **enqueues**. The hourly Ax agent is the consumer — its spec
(`.claude/agents/ax.md`, owned elsewhere; do not edit from here) needs a new
step between its current step 1 (notify_queue) and step 2 (action_queue):

> ### 1.5 Execute/relay `ax_tasks` (Ask Axyom command queue)
> ```sql
> SELECT * FROM intranet_records
> WHERE section='ax_tasks' AND fields->>'status'='queued'
> ORDER BY fields->>'created_at' LIMIT 25;
> ```
> Set each row to `processing` first (idempotency), then route by `fields->>'agent'`:
> - **`ax` / `any`** — execute the instruction yourself NOW, under the existing
>   guardrails (diagnostics, Slack posts, notes/status syncs only — never
>   create/delete jobs, invoices, payments, or contacts). Mark `status='done'`.
> - **any other agent** (`moola`, `foreman`, `goldeneye`, `paid`, `harvest`,
>   `cellar`, `tekky`) — relay: post to #intranet-alerts as
>   `📋 Task for <Agent> (from <requested_by>, <priority>): <instruction>` AND
>   write it where that agent will see it on its next run (e.g. an
>   `agent_inbox` section row tagged with the agent). Mark `status='relayed'`.
> - `urgent` priority → additionally DM Steven on Slack.
> Then: `UPDATE intranet_records SET fields = fields ||
> jsonb_build_object('status','done','handled_at',now()::text,'result','<what happened>')
> WHERE id='<id>';` — use `'relayed'` or `'error'` accordingly; never mark done
> on failure, and don't retry an `error` row more than once (bump a retry
> counter in fields).
> In the daily queue-health check, include ax_tasks rows stuck `queued`/`processing` > 24h.

## Secrets

Never hardcoded. Set once per deploy environment:

```sh
cd workers/axyom-chat
npx wrangler secret put ANTHROPIC_API_KEY   # Claude API key (from Steven)
npx wrangler secret put GHL_PIT_KTU         # HighLevel PIT, KTU
npx wrangler secret put GHL_PIT_BTU         # HighLevel PIT, BTU
# future — when ServiceMinder keys arrive:
npx wrangler secret put SM_KEY_KTU
npx wrangler secret put SM_KEY_BTU
```

The Supabase URL + publishable anon key are compiled in — they are the same
browser-safe values already shipped in `intranet/index.html` (not secrets;
RLS is enforced by the per-user token).

## Deploy

```sh
cd workers/axyom-chat
npx wrangler deploy          # account 2cdff9b17750f72247f2704875696ed5
```

Route: `dash.goaxyom.com/api/chat*` on zone `goaxyom.com`. The intranet
itself stays on the assets-only `ktubtuintranet` Worker (custom domain);
a route match takes precedence over the custom domain for `/api/chat*` —
**verify after first deploy** that `POST https://dash.goaxyom.com/api/chat`
reaches this Worker (a 401 JSON response, not the intranet HTML, means it
works).

Smoke test after deploy:

```sh
curl -i -X OPTIONS https://dash.goaxyom.com/api/chat -H "Origin: https://dash.goaxyom.com"   # expect 204
curl -i -X POST https://dash.goaxyom.com/api/chat -H "Content-Type: application/json" \
  -d '{"token":"bad","messages":[{"role":"user","content":"hi"}]}'                            # expect 401
```

## Local development

```sh
cd workers/axyom-chat
node tests/run.mjs           # mocked end-to-end tests (no network needed)
npx wrangler dev --port 8787 # reads dummy secrets from .dev.vars (gitignored)
```

`wrangler dev` note: the local proxy rewrites `Origin` headers, so the ACAO
value looks off locally — the allowlist logic is covered by `tests/run.mjs`.

## Files

- `worker.js` — the Worker (ES module, zero dependencies)
- `wrangler.toml` — config + secrets documentation
- `tests/run.mjs` — mocked handler tests (`node tests/run.mjs`)
- `.dev.vars` — dummy local secrets (gitignored)
