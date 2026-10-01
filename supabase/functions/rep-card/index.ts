import "jsr:@supabase/functions-js/edge-runtime.d.ts";

/**
 * Public rep-card lookup: GET /rep-card?hl_user_id=&brand=KTU|BTU
 *
 * Returns ONLY { display_name, title, photo_url, video_url } for the profile
 * that is customer_facing=true, has this hl_user_id, and carries `brand` in
 * its brands[] array. No match -> falls back to the brand default stored in
 * app_secrets (REP_DEFAULT_KTU / REP_DEFAULT_BTU, JSON-encoded).
 *
 * verify_jwt is OFF: this is called directly from public brand websites
 * (ktuleads.com / the BTU equivalent) with no user session. It never returns
 * email, phone or any other profile column — the select() names exactly the
 * 4 allowed fields, never '*'.
 *
 * CORS is restricted to the two public brand domains. The BTU domain was not
 * found documented anywhere in this codebase (CLAUDE.md / COORDINATION.md /
 * the intranet's Tools section only name integration.ktuleads.com for KTU) —
 * rather than guess it, the BTU origin is read from app_secrets key
 * ALLOWED_ORIGIN_BTU at request time and left unset here. Until Steven sets
 * it, BTU-origin requests will not receive an Access-Control-Allow-Origin
 * header (same-origin/no-CORS callers still work; browser cross-origin calls
 * from the BTU site will be blocked client-side until configured).
 */

const SUPA = Deno.env.get("SUPABASE_URL")!;
const SVC = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
const svcHeaders = {
  "Content-Type": "application/json",
  apikey: SVC,
  authorization: `Bearer ${SVC}`,
  "Content-Profile": "public",
  "Accept-Profile": "public",
};

const ALLOWED_ORIGIN_KTU = "https://ktuleads.com";

async function getSecret(key: string): Promise<string | null> {
  const r = await fetch(
    `${SUPA}/rest/v1/app_secrets?key=eq.${encodeURIComponent(key)}&select=value`,
    { headers: svcHeaders },
  );
  if (!r.ok) return null;
  const rows = await r.json();
  return rows?.[0]?.value ?? null;
}

function corsHeaders(origin: string | null, allowedBtu: string | null) {
  const allowed = [ALLOWED_ORIGIN_KTU, allowedBtu].filter(Boolean) as string[];
  const h: Record<string, string> = {
    "Content-Type": "application/json",
    "Cache-Control": "public, max-age=300",
    Vary: "Origin",
  };
  if (origin && allowed.includes(origin)) h["Access-Control-Allow-Origin"] = origin;
  h["Access-Control-Allow-Methods"] = "GET, OPTIONS";
  h["Access-Control-Allow-Headers"] = "content-type";
  return h;
}

Deno.serve(async (req) => {
  const url = new URL(req.url);
  const origin = req.headers.get("origin");
  // ALLOWED_ORIGIN_BTU: optional app_secrets override once Steven confirms the
  // real BTU public domain. Falls back to null (no BTU origin allowed) until set.
  const allowedBtu = await getSecret("ALLOWED_ORIGIN_BTU");
  const headers = corsHeaders(origin, allowedBtu);

  if (req.method === "OPTIONS") return new Response("ok", { headers });
  if (req.method !== "GET") return new Response(JSON.stringify({ error: "GET only" }), { status: 405, headers });

  const hlUserId = url.searchParams.get("hl_user_id");
  const brand = url.searchParams.get("brand");

  if (!hlUserId || !brand || !["KTU", "BTU"].includes(brand)) {
    return new Response(JSON.stringify({ error: "hl_user_id and brand (KTU|BTU) required" }), { status: 400, headers });
  }

  const q = new URLSearchParams({
    select: "customer_display_name,display_name,customer_title,photo_url,intro_video_url",
    hl_user_id: `eq.${hlUserId}`,
    customer_facing: "eq.true",
    brands: `cs.{${brand}}`,
    limit: "1",
  });
  const r = await fetch(`${SUPA}/rest/v1/profiles?${q.toString()}`, { headers: svcHeaders });
  if (r.ok) {
    const rows = await r.json();
    const p = rows?.[0];
    if (p) {
      return new Response(JSON.stringify({
        display_name: p.customer_display_name || p.display_name || null,
        title: p.customer_title || null,
        photo_url: p.photo_url || null,
        video_url: p.intro_video_url || null,
      }), { status: 200, headers });
    }
  }

  // Fallback: brand default from app_secrets.
  const defaultsRaw = await getSecret(brand === "KTU" ? "REP_DEFAULT_KTU" : "REP_DEFAULT_BTU");
  let d: Record<string, unknown> = {};
  try { d = defaultsRaw ? JSON.parse(defaultsRaw) : {}; } catch { d = {}; }
  return new Response(JSON.stringify({
    display_name: d.display_name ?? null,
    title: d.title ?? null,
    photo_url: d.photo_url ?? null,
    video_url: d.video_url ?? null,
  }), { status: 200, headers });
});
