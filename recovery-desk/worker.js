/**
 * KTU Recovery Desk — self-hosted at ktubloomfield.com/follow-up
 *
 * Why this exists: artifact sharing is disabled on the account, so the team
 * cannot open the published Artifact. This serves the same work list from our
 * own domain instead.
 *
 * The page carries live customer names, addresses and phone numbers, so it is
 * not on the open web:
 *   - a shared passcode gates every route, held as a Worker secret;
 *   - a correct passcode sets an HMAC-signed cookie, so the passcode itself is
 *     never stored in the browser and a forged cookie cannot be minted;
 *   - the page holds NO database credential. It calls /follow-up/api/state on
 *     this Worker, which talks to Supabase with a key that stays server-side.
 *     So even someone who gets through the gate cannot query the database
 *     directly, and the customer roster is never reachable as an API.
 *   - noindex/noarchive plus a robots deny, so it cannot be crawled.
 *
 * Only the work state (owner, status, next step, notes) lives in the database.
 * The customer roster is baked into the gated HTML and never returned by the
 * API, which keeps the two blast radii separate.
 */

const COOKIE = 'ktu_desk';
const TTL_DAYS = 30;
const TABLE = 'recovery_desk';

const enc = new TextEncoder();
const b64url = buf => btoa(String.fromCharCode(...new Uint8Array(buf)))
  .replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');

async function sign(value, secret) {
  const key = await crypto.subtle.importKey('raw', enc.encode(secret),
    { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  return b64url(await crypto.subtle.sign('HMAC', key, enc.encode(value)));
}

/** Constant-time compare so a wrong passcode cannot be discovered by timing. */
function same(a, b) {
  if (typeof a !== 'string' || typeof b !== 'string' || a.length !== b.length) return false;
  let out = 0;
  for (let i = 0; i < a.length; i++) out |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return out === 0;
}

async function makeCookie(secret) {
  const exp = Date.now() + TTL_DAYS * 864e5;
  return `${exp}.${await sign(String(exp), secret)}`;
}

async function cookieOk(raw, secret) {
  if (!raw) return false;
  const [exp, sig] = String(raw).split('.');
  if (!exp || !sig || Number(exp) < Date.now()) return false;
  return same(sig, await sign(exp, secret));
}

function readCookie(req, name) {
  const jar = req.headers.get('cookie') || '';
  for (const part of jar.split(';')) {
    const [k, ...v] = part.trim().split('=');
    if (k === name) return decodeURIComponent(v.join('='));
  }
  return null;
}

const SECURITY = {
  'x-robots-tag': 'noindex, nofollow, noarchive',
  'referrer-policy': 'no-referrer',
  'x-content-type-options': 'nosniff',
  'x-frame-options': 'DENY',
  'cache-control': 'no-store',
};

function page(html, extra = {}) {
  return new Response(html, {
    headers: { 'content-type': 'text/html;charset=utf-8', ...SECURITY, ...extra },
  });
}

function gate(msg) {
  return page(`<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>KTU Recovery Desk</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wght@600;700&family=Public+Sans:wght@400;500&display=swap">
<style>
:root{--ground:#eceff2;--surface:#fff;--line:#d7dde3;--ink:#14181c;--muted:#697786;--brass:#9c6122}
@media(prefers-color-scheme:dark){:root{--ground:#0d1115;--surface:#151b21;--line:#2a333d;--ink:#e7ecf1;--muted:#8593a1;--brass:#d09a52}}
*{box-sizing:border-box}
body{margin:0;min-height:100vh;display:grid;place-items:center;background:var(--ground);color:var(--ink);
 font-family:"Public Sans",system-ui,sans-serif;padding:24px}
.card{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:30px;max-width:400px;width:100%;
 box-shadow:0 1px 2px rgba(16,24,32,.06),0 8px 30px rgba(16,24,32,.08)}
.eyebrow{font-family:Archivo;font-size:10.5px;font-weight:600;letter-spacing:.13em;text-transform:uppercase;color:var(--brass)}
h1{font-family:Archivo;font-size:22px;font-weight:700;margin:4px 0 8px;letter-spacing:-.015em}
p{color:var(--muted);font-size:13.5px;line-height:1.55;margin:0 0 18px}
label{display:block;font-size:11px;font-weight:600;letter-spacing:.07em;text-transform:uppercase;color:var(--muted);margin-bottom:6px}
input{width:100%;padding:11px 12px;font:inherit;color:inherit;background:var(--ground);
 border:1px solid var(--line);border-radius:8px}
button{width:100%;margin-top:12px;padding:11px;font:inherit;font-weight:600;cursor:pointer;color:#fff;
 background:var(--brass);border:none;border-radius:8px}
button:hover{filter:brightness(1.08)}
.err{color:#b3382f;font-size:13px;margin:0 0 14px;font-weight:500}
:focus-visible{outline:2px solid var(--brass);outline-offset:2px}
</style></head><body>
<form class="card" method="POST">
  <div class="eyebrow">Kitchen Tune-Up · Bloomfield NJ</div>
  <h1>Recovery Desk</h1>
  <p>This list holds customer contact details, so it is not public. Enter the team passcode
     Steven sent you. You will stay signed in on this device for 30 days.</p>
  ${msg ? `<p class="err">${msg}</p>` : ''}
  <label for="pc">Team passcode</label>
  <input id="pc" name="passcode" type="password" autocomplete="current-password" autofocus required>
  <button type="submit">Open the desk</button>
</form></body></html>`);
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname.replace(/\/+$/, '') || '/';

    // No /robots.txt handler here on purpose: the route is scoped to
    // /follow-up*, so the site's own robots.txt is served by the marketing
    // origin and is not ours to override. Crawlers are kept off this page by
    // the x-robots-tag header and the meta tag on every response instead —
    // and nothing links to it, so nothing discovers it in the first place.
    const secret = env.DESK_PASSCODE;
    if (!secret) return page('<h1>Not configured</h1><p>DESK_PASSCODE is not set.</p>', { status: '500' });

    // --- sign in ---
    if (request.method === 'POST' && !path.startsWith('/follow-up/api')) {
      const form = await request.formData();
      if (!same(String(form.get('passcode') || ''), secret)) {
        return gate('That passcode is not right. Check the email and try again.');
      }
      const cookie = await makeCookie(secret);
      return new Response(null, {
        status: 303,
        headers: {
          location: '/follow-up',
          'set-cookie': `${COOKIE}=${encodeURIComponent(cookie)}; Path=/; Max-Age=${TTL_DAYS * 86400}; HttpOnly; Secure; SameSite=Lax`,
          ...SECURITY,
        },
      });
    }

    const signedIn = await cookieOk(readCookie(request, COOKIE), secret);

    // --- data, server-side only ---
    if (path === '/follow-up/api/state') {
      if (!signedIn) return new Response('signed out', { status: 401, headers: SECURITY });
      const base = `${env.SUPABASE_URL}/rest/v1/${TABLE}`;
      // This project's PostgREST defaults to the `api` schema, not `public`,
      // so the schema has to be named explicitly on every call or the table
      // reads as missing. (The intranet pins the same thing in supabase-js.)
      const auth = {
        apikey: env.SUPABASE_KEY,
        authorization: `Bearer ${env.SUPABASE_KEY}`,
        'content-type': 'application/json',
        'accept-profile': 'public',
        'content-profile': 'public',
      };

      if (request.method === 'GET') {
        const r = await fetch(`${base}?select=*`, { headers: auth });
        if (!r.ok) return new Response(await r.text(), { status: 502, headers: SECURITY });
        return new Response(await r.text(),
          { headers: { 'content-type': 'application/json', ...SECURITY } });
      }

      if (request.method === 'POST') {
        const b = await request.json();
        if (!b || typeof b.id !== 'string' || !/^r\d{1,4}$/.test(b.id)) {
          return new Response('bad id', { status: 400, headers: SECURITY });
        }
        const clamp = (v, n) => String(v ?? '').slice(0, n);
        const row = {
          id: b.id,
          assignee: clamp(b.assignee || 'Unassigned', 40),
          status: clamp(b.status || 'todo', 40),
          next_step: clamp(b.next, 500),
          last_contact: /^\d{4}-\d{2}-\d{2}$/.test(b.last || '') ? b.last : null,
          method: clamp(b.method || '—', 40),
          notes: clamp(b.notes, 4000),
          updated_by: clamp(b.by, 40),
        };
        const r = await fetch(`${base}?on_conflict=id`, {
          method: 'POST',
          headers: { ...auth, prefer: 'resolution=merge-duplicates,return=minimal' },
          body: JSON.stringify(row),
        });
        if (!r.ok) return new Response(await r.text(), { status: 502, headers: SECURITY });
        return new Response('{"ok":true}',
          { headers: { 'content-type': 'application/json', ...SECURITY } });
      }
      return new Response('method not allowed', { status: 405, headers: SECURITY });
    }

    // --- the desk ---
    if (path === '/follow-up' || path.startsWith('/follow-up/')) {
      if (!signedIn) return gate('');
      return page(env.DESK_HTML || DESK);
    }

    return Response.redirect(url.origin + '/follow-up', 302);
  },
};

// DESK is replaced at build time with the full page.
const DESK = '<h1>Not built</h1>';
