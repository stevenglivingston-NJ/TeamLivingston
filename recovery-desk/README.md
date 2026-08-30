# KTU Recovery Desk — `ktubloomfield.com/follow-up`

The shared call list Ben and Sonya work together: every cancelled consultation
and expired quote from 2026, with owner, status, next step, last contact and
notes. Self-hosted because artifact sharing is turned off on the Claude account,
so the published Artifact cannot be opened by the team.

Same page as the Artifact, different plumbing. The Artifact keeps shared state
in the Claude runtime (`db`/`room`); those do not exist on our own domain, so
this copy keeps it in Supabase and reaches it through the Worker.

## Why it is built this way

The page carries live customer names, addresses and phone numbers. So:

- **A passcode gates every route**, held as a Worker secret. A correct passcode
  sets an HMAC-signed cookie, so the passcode is never stored in the browser and
  a cookie cannot be forged.
- **The page holds no database credential at all.** It calls
  `/follow-up/api/state` on the Worker, which talks to Supabase server-side.
  Someone who gets through the gate still cannot query the database directly.
- **Only the work lives in the database.** `recovery_desk` holds owner, status,
  next step, date, method and notes — no names, phones or addresses. The
  customer roster is baked into the gated HTML and is never returned by the API,
  which keeps the two blast radii separate.
- `noindex` / `noarchive` on every response, as a header and a meta tag.
  There is deliberately no `robots.txt` handler: the route is scoped to
  `/follow-up*`, so the site's own robots.txt belongs to the marketing origin
  and is not ours to override.

## Deploy

```bash
cd recovery-desk
npm install                 # first time only

# secrets — set once, never committed
npx wrangler secret put DESK_PASSCODE     # the passcode you give Ben and Sonya
npx wrangler secret put SUPABASE_URL      # https://tguwpswcneywvscxzyef.supabase.co
npx wrangler secret put SUPABASE_KEY      # Supabase anon key (RLS limits it to recovery_desk)

npm run deploy              # builds dist/worker.js, then wrangler deploy
```

`SUPABASE_KEY` should be the **anon** key, not the service-role key. RLS on
`recovery_desk` already allows `anon` to read and write that one table and
nothing else, so the anon key is sufficient and is the least privilege that
works.

## The live URL is the `www` form

**https://www.ktubloomfield.com/follow-up**

Both routes are registered, but the bare apex does not work and cannot be made
to: `ktubloomfield.com/follow-up` is 301'd to `www` by a redirect that runs
*before* Workers in Cloudflare's request pipeline, so the Worker never sees it.
The `www` route serves correctly. Send people the `www` link.

## Changing the list

`parts/` holds the three page fragments and `tracker_min.json`, the roster. They
are produced by the analysis in the repo root, so regenerate them there rather
than editing by hand, then `npm run deploy`.

## Build note

`build.mjs` inlines the page into the Worker with a **function** replacement,
not a string one. The page contains `'$' + …` for money formatting, and a string
replacement reads `$'` as "everything after the match" and splices the rest of
the file into the literal — which produced a Worker that would not parse. Keep
the function form.
