// Admin console backend: user management with service-role privileges.
// Caller must be a signed-in user whose profiles.role = 'admin'.
// Shared by the intranet Admin Console (dash.goaxyom.com) and the Pricing app
// (pricing.ktubtu.com). Role 'pricing' = field rep with Pricing access only, no intranet.
import { createClient } from 'npm:@supabase/supabase-js@2'

const CORS: Record<string, string> = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type',
  'Access-Control-Allow-Methods': 'POST, OPTIONS',
  'Content-Type': 'application/json',
}
const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: CORS })

const VALID_ROLES = ['admin', 'homeservices', 'ecommerce', 'pricing']
const VALID_BRANDS = ['KTU', 'BTU']
// Customer-facing profile fields (2026-09-21 rep-card feature). Nullable/optional.
const CUSTOMER_FIELDS = [
  'hl_user_id', 'sm_agent_name_ktu', 'sm_agent_name_btu', 'brands',
  'customer_title', 'customer_display_name', 'photo_url', 'intro_video_url',
  'customer_facing',
] as const

Deno.serve(async (req) => {
  if (req.method === 'OPTIONS') return new Response('ok', { headers: CORS })
  if (req.method !== 'POST') return json(405, { error: 'POST only' })

  const admin = createClient(
    Deno.env.get('SUPABASE_URL')!,
    Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!,
  )

  // --- authenticate caller and require admin role ---
  const token = (req.headers.get('authorization') ?? '').replace(/^Bearer\s+/i, '')
  const { data: userData, error: uerr } = await admin.auth.getUser(token)
  if (uerr || !userData?.user) return json(401, { error: 'not signed in' })
  const callerId = userData.user.id
  const { data: callerProf } = await admin
    .from('profiles').select('role').eq('id', callerId).single()
  if (!callerProf || callerProf.role !== 'admin') return json(403, { error: 'admin role required' })

  let body: any
  try { body = await req.json() } catch { return json(400, { error: 'invalid JSON' }) }
  const action = body?.action

  const adminCount = async () => {
    const { count } = await admin.from('profiles')
      .select('id', { count: 'exact', head: true }).eq('role', 'admin')
    return count ?? 0
  }

  try {
    if (action === 'list') {
      const { data: profs, error } = await admin.from('profiles')
        .select('*').order('created_at', { ascending: true })
      if (error) throw error
      const { data: usersPage } = await admin.auth.admin.listUsers({ page: 1, perPage: 200 })
      const lastSeen: Record<string, string | null> = {}
      for (const u of usersPage?.users ?? []) lastSeen[u.id] = u.last_sign_in_at ?? null
      return json(200, {
        users: (profs ?? []).map((p) => ({ ...p, last_sign_in_at: lastSeen[p.id] ?? null })),
      })
    }

    if (action === 'create') {
      const { email, password, display_name, role } = body
      if (!email || !password) return json(400, { error: 'email and password required' })
      if (String(password).length < 8) return json(400, { error: 'password must be at least 8 characters' })
      if (role && !VALID_ROLES.includes(role)) return json(400, { error: 'invalid role' })
      const { data: created, error } = await admin.auth.admin.createUser({
        email, password, email_confirm: true,
        user_metadata: { display_name: display_name || email.split('@')[0] },
      })
      if (error) return json(400, { error: error.message })
      // trigger created the profile; set role/display_name explicitly
      await admin.from('profiles').upsert({
        id: created.user.id, email,
        display_name: display_name || email.split('@')[0],
        role: role || 'homeservices', updated_at: new Date().toISOString(),
      })
      return json(200, { ok: true, user_id: created.user.id })
    }

    if (action === 'set_password') {
      const { user_id, password } = body
      if (!user_id || !password) return json(400, { error: 'user_id and password required' })
      if (String(password).length < 8) return json(400, { error: 'password must be at least 8 characters' })
      const { error } = await admin.auth.admin.updateUserById(user_id, { password })
      if (error) return json(400, { error: error.message })
      return json(200, { ok: true })
    }

    if (action === 'update_profile') {
      const { user_id, role, display_name } = body
      if (!user_id) return json(400, { error: 'user_id required' })
      if (role && !VALID_ROLES.includes(role)) return json(400, { error: 'invalid role' })
      if (role && role !== 'admin') {
        const { data: target } = await admin.from('profiles').select('role').eq('id', user_id).single()
        if (target?.role === 'admin' && (await adminCount()) <= 1)
          return json(400, { error: 'cannot demote the last admin' })
      }
      const patch: Record<string, unknown> = { updated_at: new Date().toISOString() }
      if (role) patch.role = role
      if (display_name !== undefined) patch.display_name = display_name
      const { error } = await admin.from('profiles').update(patch).eq('id', user_id)
      if (error) return json(400, { error: error.message })
      return json(200, { ok: true })
    }

    // Added 2026-09-21 for the customer-facing rep-card feature (Admin Console
    // "Customer-facing profile" section). Same actor/permission model as the
    // rest of this function (admin JWT -> service-role write), so it lives
    // here rather than as a separate edge function.
    if (action === 'update_customer_profile') {
      const { user_id, fields } = body
      if (!user_id) return json(400, { error: 'user_id required' })
      if (!fields || typeof fields !== 'object') return json(400, { error: 'fields object required' })
      const patch: Record<string, unknown> = { updated_at: new Date().toISOString() }
      for (const key of CUSTOMER_FIELDS) {
        if (!(key in fields)) continue
        let v = (fields as Record<string, unknown>)[key]
        if (key === 'brands') {
          if (v == null) { patch.brands = null; continue }
          if (!Array.isArray(v) || v.some((b) => !VALID_BRANDS.includes(b)))
            return json(400, { error: 'brands must be an array of KTU/BTU' })
          patch.brands = v
          continue
        }
        if (key === 'customer_facing') { patch.customer_facing = Boolean(v); continue }
        // text fields: allow null/empty to clear
        patch[key] = v === '' ? null : v
      }
      const { error } = await admin.from('profiles').update(patch).eq('id', user_id)
      if (error) {
        if (String(error.message).includes('profiles_hl_user_id_key'))
          return json(400, { error: 'that HighLevel user id is already assigned to another profile' })
        return json(400, { error: error.message })
      }
      return json(200, { ok: true })
    }

    if (action === 'delete') {
      const { user_id } = body
      if (!user_id) return json(400, { error: 'user_id required' })
      if (user_id === callerId) return json(400, { error: 'cannot delete your own account' })
      const { data: target } = await admin.from('profiles').select('role').eq('id', user_id).single()
      if (target?.role === 'admin' && (await adminCount()) <= 1)
        return json(400, { error: 'cannot delete the last admin' })
      const { error } = await admin.auth.admin.deleteUser(user_id)
      if (error) return json(400, { error: error.message })
      return json(200, { ok: true })
    }

    return json(400, { error: 'unknown action' })
  } catch (e) {
    return json(500, { error: String(e?.message ?? e) })
  }
})
