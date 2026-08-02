# Infrastructure Optimization Guide

## Supabase Edge Functions

### dispatch-notify (Notification Dispatcher)

**Recent Optimizations (2026-07-09):**

- ✅ Added 10s timeout to HighLevel API calls (prevents hangs)
- ✅ Added 5s timeout to Slack webhooks (quick fail)
- ✅ Parallelized Slack + Email sends (both run concurrently, ~50% latency reduction)
- ✅ Doubled batch size from 25 → 50 rows per invocation
- ✅ Optimized column selection (only fetch required fields)

**Expected Impact:** 50% latency reduction, 2x throughput capacity

**Health Monitoring:**

Call `dispatch_notify_health_check()` (SQL function) every 10 minutes to verify notifications are being processed:

```sql
select * from dispatch_notify_health_check();
```

Returns:
- `healthy` (boolean): true if processing on schedule
- `last_processed_at` (timestamp): when last notification was sent
- `pending_count` (bigint): notifications waiting to be sent
- `minutes_since_last_process` (int): age of last dispatch

Alert if:
- `healthy = false` AND `pending_count > 0` (dispatcher stalled)
- `minutes_since_last_process > 5` (missed pg_cron invocation)

---

## Render Hosted Services

### Clarity MCP Service (ktubtu-mcp-clarity)

**Current Problem:** Cold-start latency ~50-60s after 15-min inactivity

Render free tier puts services to sleep after inactivity, requiring a full startup on next request. This causes:
- Agents retry 10x with exponential backoff
- Report generation delays (clarity dashboard data is slow to load)
- Network flap errors during SessionStart hook bootstrap

**Recommended Fix (COST: +$7/month):**

Upgrade to Render Pro tier to eliminate sleep-after-inactivity:
1. Go to https://dashboard.render.com/services
2. Click `ktubtu-mcp-clarity` service
3. Click "Settings" → "Plan" → "Pro"
4. Approve $7/month charge
5. Deployment will remain online indefinitely

**Alternative (No Cost):**

Implement keep-alive probe that pings the service every 9 minutes:

```bash
# Add to a cron job or scheduled function
curl -s "https://ktubtu-mcp-clarity.onrender.com/health" > /dev/null
```

(Requires Render service to expose a `/health` endpoint)

---

## Database Optimization

### Connection Pool

Currently, SessionStart hook spawns 8 MCP servers concurrently. This causes connection spikes during agent bootstrap. Consider:

1. **Add sequence to bootstrap.sh:** Stagger server registration by 1-2s each
2. **Monitor:** Add logs to bootstrap.sh to track registration timing
3. **Tune pg_max_connections:** If running near limit, increase on Supabase Pro plan

### Supabase Flaps

Intermittent "connection failed" errors during agent startup are likely caused by:
- High connection churn during concurrent bootstrap
- RLS policy evaluation lag under load
- Render MCP service cold-start races

**Mitigations:**
- ✅ Already done: Agents now use fresh sessions (no persistent session conflicts)
- ✅ Already done: Staggered agent schedules (5 AM → 2 PM → hourly to avoid simultaneous startup)
- [ ] Recommended: Reduce concurrent MCP server registrations (add delay in bootstrap.sh)

---

## Monitoring Checklist

Daily:
- [ ] Run `select * from dispatch_notify_health_check()` — verify `healthy = true`
- [ ] Check Supabase logs for edge function errors (↑ latency / timeouts)

Weekly:
- [ ] Verify Render service uptime (https://status.render.com)
- [ ] Check CloudFlare Workers uptime (https://www.cloudflarestatus.com)
- [ ] Review Supabase performance (Dashboard → Performance tab)

---

## Next Steps

1. **Immediate:** Deploy the dispatch-notify optimizations (already committed)
2. **This week:** Upgrade Render to Pro tier ($7/month) — OR implement keep-alive probe
3. **This week:** Add monitoring alert for dispatch_notify_health_check()
4. **Next sprint:** Profile SessionStart hook — reduce concurrent MCP bootstrap

