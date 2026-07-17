# KTU Instant Tune-Up Funnel

Instant-quote + booking funnel for Kitchen Tune-Up Bloomfield (First Generation USA LLC).
Deploys to `ktubloomfield.com/tuneup`. Full build spec lives with the owner (CLAUDE build-spec
doc); this README covers what is implemented so far.

## Status: Phase 1 scaffold

| Phase | Scope | Status |
|-------|-------|--------|
| P0 | SM API verification, brand extraction, Stripe setup, agreement draft, calibration set | SM services/rates verified readable ✅; rest pending |
| **P1** | **Pricing engine + SM cron sync + $2k floor + SDD, unit-tested to the penny** | **This scaffold** |
| P2 | Vision classifier (level buckets, white-wash detect, opening cross-check) | Not started |
| P3 | Frontend funnel (React SPA, in-app camera, call-back) | Not started |
| P4 | SM calendar + Stripe checkout + webhook booking chain | Not started |
| P5 | HighLevel + Meta Pixel/CAPI + GA4 | Not started |
| P6–P7 | QA, soft launch | Not started |

## Architecture (Phase 1 slice)

```
Cloudflare Worker (src/index.ts)
├── scheduled()  — cron every 15 min: ServiceMinder /services/all → rate table → KV
│                  KV keys: pricing:current (1h TTL) + pricing:last-good (no TTL)
└── fetch()
    ├── GET  /api/health          — liveness + rate-table freshness
    ├── GET  /api/rates           — sanitized current rate table (debugging/ops)
    └── POST /api/quote/preview   — pricing engine dry-run (P3 wires the real funnel)

D1 (db/migrations/0001_init.sql): quote_sessions, leads, funnel_events (audit), rate_snapshots
R2: customer photo bucket binding reserved (used from P2/P3)
```

## Pricing rules implemented

All amounts are integer math — rates in **milli-dollars** (1/1000 USD, exact for SM's
3-decimal rates like $96.485), money in **cents**, half-up rounding at defined points only:

```
Effective Base = SM base + SM uplift            (uplift merged, never shown as a line)
Subtotal       = Effective Base + level rate × openings [+ white-wash premium]
Quote          = max(Subtotal, $2,000 floor)    → rounded to cents
SDD discount   = min(10% of Quote, $2,500)      → rounded to cents; valid 24h from quote
Deposit        = 50% of (Quote − discount)      → rounded to cents
```

- No sales tax (NJ capital improvement).
- Rates are **never hardcoded** — the engine consumes a `RateTable` built from live
  ServiceMinder data (`src/pricing/rateTable.ts`), synced every 15 min by the cron.
- An incomplete rate table (missing/zero rates) makes the affected quote **non-quotable**:
  the funnel must route to human pricing ("quote within 2 hours"), never guess.
- AI level buckets are `L1_2`, `L3`, `L4` (SM merges levels 1 and 2). SM currently prices
  Level 1 and Level 2 separately; the merged `L1_2` rate defaults to the **higher** of the
  two (conservative) — confirm with owner (open item below).

## ServiceMinder mapping (live-verified 2026-07-17)

Rates live as **parts** on service `30382 Tune-Up Residential`
(`POST https://serviceminder.io/api/services/all` with `IncludeParts: true`).
Mapping is by part ID in `src/config.ts`:

| Role | SM part | ID | Live value 2026-07-17 |
|------|---------|----|--------------------|
| Uplift (merged into base) | Tune-Up Uplift | 199137 | $619.35 |
| Level 1 | Tune-Up Level 1 | 199138 | $25.75 / unit |
| Level 2 | Tune-Up Level 2 | 1557033 | $27.81 / unit |
| Level 3 | Tune-Up Level 3 | 199139 | $29.87 / unit |
| Level 4 | Tune-Up Level 4 | 199140 | $31.93 / unit |
| Base | service `BasePrice` | — | **$0.00 (see gaps)** |
| White-wash premium | — | **missing** | not in SM yet |

### ⚠️ SM configuration gaps found during scaffold (owner action needed)

Live SM values disagree with the build-spec approximations. SM is the source of truth,
so either SM needs updating or the spec numbers are stale — Steven to confirm:

1. **No "White Wash Premium" part exists in SM** (spec: ~$618.50 flat). Until it's added
   (and its ID put in `src/config.ts`), white-wash-flagged quotes route to human pricing.
2. **Tune-Up Residential `BasePrice` is $0** (spec: base ~$250). Effective base today is
   just the uplift ($619.35 vs spec's ~$639.65 combined).
3. **Level rates are per *unit* at $25.75–$31.93** vs spec's ~$96.49–$136.07 *per opening*.
   If an "opening" bills as multiple SM units, the funnel needs that multiplier defined.
4. **SM's own discount note says "TUSDD for $250 Same Day Discount"** (part 199161) vs the
   spec's SDD = 10% capped at $2,500 for 24h. Engine implements the spec; reconcile.
5. `L1_2` merged-bucket rate policy (currently `max(L1, L2)`) needs owner sign-off.

## Reference material (Google Drive)

KTU Google Drive → **Vendors & Products → Tune up**
(folder `1VGPeREqORA88gvFx6JPdrlr8H7cGUkdC`, owner `ktubloomfieldnj@gmail.com`, access verified):
https://drive.google.com/drive/folders/1VGPeREqORA88gvFx6JPdrlr8H7cGUkdC

Contains: the Kitchen Tune-Up **tune-up manual** (`2270522450_tune-up-manual.pdf` — process,
level determination, pricing flow), before/after job photos (calibration set for the P2
vision classifier), and process screenshots. P2 must derive its level rubric from the
manual and calibrate against these photos + the level actually charged per job.

## Develop / test

```bash
cd tuneup-funnel
npm install
npm test            # vitest — engine unit-tested to the penny
npm run typecheck
npm run dev         # wrangler dev (needs .dev.vars, see .dev.vars.example)
```

Deploy (once Cloudflare resources exist — IDs in wrangler.toml are placeholders):

```bash
wrangler d1 create ktu-tuneup && wrangler kv namespace create PRICING_KV
wrangler r2 bucket create ktu-tuneup-photos
wrangler d1 migrations apply ktu-tuneup --remote
wrangler secret put SERVICEMINDER_API_KEY   # + others per build spec as later phases land
wrangler deploy
```

Secrets (Wrangler): `SERVICEMINDER_API_KEY` (Phase 1); later phases add `STRIPE_SECRET_KEY`,
`STRIPE_WEBHOOK_SECRET`, `ANTHROPIC_API_KEY`, `HIGHLEVEL_WEBHOOK_URL`, `META_CAPI_TOKEN`,
`META_PIXEL_ID`. Never commit real values.

## Do-not-launch checklist (from build spec)

Attorney sign-off on agreement + rescission/SDD interplay · final refund tiers · SM proposal
text · calibration photos ingested · Pixel ID + HighLevel recipients · **plus the SM
configuration gaps above**.
