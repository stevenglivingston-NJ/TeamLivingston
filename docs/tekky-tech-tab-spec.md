# Axyom Intranet — "Tech Stack" Tab (UI contract)

Owner-facing tab to be added to the Axyom intranet (dash.goaxyom.com) **after the
current redesign lands**. It renders Tekky's output — the UI derives nothing
itself; everything comes from four `intranet_records` sections in Supabase project
`tguwpswcneywvscxzyef`. Data agent: **Tekky** (`.claude/agents/tekky.md`), daily
scheduled run + on-demand.

## Access
Owner-only (same gate as the Finance tab / `moola_briefing`). The stack map names
env-var keys (names + SET/MISSING only, never values), account IDs, and internal
health — not for general team accounts.

## Data contract (read-only for the UI)

All reads: `SELECT * FROM intranet_records WHERE section = $1 ORDER BY sort_order`.
Row shape: `{id, section, brand, sort_order, fields jsonb, created_at, updated_at}`.
For `tekky_stack`/`tekky_status`/`tekky_briefing` the UI shows only rows with the
latest `fields->>'scan_date'` (Tekky write-then-prunes, but belt-and-suspenders
like the other cards). `tekky_changes` is append-only: show ALL rows, newest first.

| Section | Rows | `fields` shape |
|---|---|---|
| `tekky_stack` | 1 | `{scan_date, generated_at, run, domains:{mcp_stdio[], connectors[], cloudflare{account, workers[], zones[]}, supabase{project, tables[], intranet_records_sections}, intranet[], repo{path, dirs{}}, agents[], saas[]}}` — each component: `{name, kind, status, reason, auth?:{env_vars:[{name, state:"SET"\|"MISSING"}]}, notes}`; agents add `{purpose, outputs[]}`; saas add `{access}` |
| `tekky_status` | ~15–25 | `{component, domain, status:"UP"\|"DEGRADED"\|"DOWN"\|"UNKNOWN", reason, checked_at, scan_date}` — already sorted worst-first via sort_order |
| `tekky_changes` | grows forever | `{ts, kind:"added"\|"removed"\|"modified", component, domain, detail, evidence, scan_date}` |
| `tekky_briefing` | ≤8 | `{severity:"urgent"\|"warn"\|"info", title, detail, source, scan_date}` |

## Layout (top to bottom)

1. **Header strip** — "Tech Stack" + last-scan line from `tekky_stack.generated_at`
   ("Tekky scanned Jul 5, 4:28 AM UTC") + a health tally pill row computed from
   `tekky_status`: `N up · N degraded · N down · N unknown`. If the latest
   `scan_date` is older than 48h, show a stale banner ("Tekky hasn't run since …").
2. **Must-action callouts** — `tekky_briefing` rows, same card treatment as the
   home-page Goldeneye callouts / Finance Moola briefing: severity chip
   (urgent = red, warn = amber, info = neutral), `title` bold, `detail` body,
   `source` small/muted. Urgent rows always visible; warn/info collapsible.
3. **Stack map** — from the single `tekky_stack` row, one collapsible group per
   domain, in this order with these display names:
   - `mcp_stdio` → "MCP servers (direct)"
   - `connectors` → "Connectors (claude.ai)"
   - `cloudflare` → "Cloudflare" (render `account.name` + id in the group header;
     workers as component rows; zones as plain chips)
   - `supabase` → "Supabase" (project ref in header; tables as rows: name,
     row count, RLS check)
   - `intranet` → "Intranet & dashboards" (name is a URL surface — link it)
   - `agents` → "Agent roster" (show `purpose`; `outputs[]` as small code chips)
   - `saas` → "External SaaS" (show `access` as the secondary line)
   - `repo` → "Repository" (simple key/value list of `dirs`)
   Each component row: **health badge + name + reason (muted)**. Badge colors:
   UP green, DEGRADED amber, DOWN red, UNKNOWN gray, REMOVED gray-strikethrough.
   Where `auth.env_vars` exists, render each var as a chip: `NAME` + SET (green) /
   MISSING (red). **Never render anything but the name and state — there are no
   values in the data by design; do not add any.**
   Group headers show a count + worst-status dot so a collapsed group still
   signals trouble.
4. **Changelog feed** — `tekky_changes` newest-first (order by `fields->>'ts'`
   desc), vertical timeline: kind icon (added ＋ / removed − / modified Δ),
   `component` bold, `detail`, `evidence` muted, timestamp. Paginate/lazy-load
   past ~30 entries; this section only grows.

## Behavior notes
- Empty-state: if no `tekky_*` rows exist, show "Tekky hasn't run yet" — never a
  blank tab.
- The tab is read-only; no write paths from the UI.
- Filter control (optional, nice-to-have): by domain and by status, applied to
  both the stack map and the status tally.
- Keep rendering resilient: unknown extra JSON keys must be ignored, missing
  optional keys (`notes`, `reason`, `auth`) render as absent, and an unrecognized
  `status` value renders as the UNKNOWN badge.
