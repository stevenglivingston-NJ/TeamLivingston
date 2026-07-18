# KTU Instant Tune-Up Funnel

Instant-quote + booking funnel for Kitchen Tune-Up Bloomfield (First Generation USA LLC).
Deploys to `ktubloomfield.com/tuneup`. Full build spec lives with the owner (CLAUDE build-spec
doc); this README covers what is implemented so far.

## Status: Phase 1 scaffold

| Phase | Scope | Status |
|-------|-------|--------|
| P0 | SM API verification, brand extraction, Stripe setup, agreement draft, calibration set | SM services/rates verified readable ✅; rest pending |
| **P1** | **Pricing engine + SM cron sync + $2k floor, unit-tested to the penny** (SDD dropped per owner 2026-07-18) | **Done** |
| **P2** | **Vision classifier (level buckets, white-wash detect, opening cross-check)** | **Built — needs calibration run** |
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
R2: customer photo bucket (photos land here in P3; /api/vision/classify reads them)
```

## Vision classifier (Phase 2)

`src/vision/` — cabinet-condition analysis via the Anthropic API (Claude vision,
`claude-opus-4-8`, structured JSON output):

- **Rubric-driven prompt** (`prompt.ts`) built from `docs/levels-and-process.md` — the KTU
  1–5 damage system, 10%/30% thresholds, water zones, nicotine escalation, white-wash
  detection, Level-5 "not a candidate" signals. Rubric changes go in the doc first.
- **Output**: level bucket (`L1_2`/`L3`/`L4`), confidence, white-wash flag + confidence,
  estimated opening count, Level-5 flag, plain-English condition notes, review flags.
- **Routing rules** (`classifier.ts` → `decide()`, pure/unit-tested): confidence < 0.7,
  Level-5 signals, uncertain white-wash, or any API failure → **human review** ("quote
  finalized within 2 hours") — never a guessed price. AI-vs-customer opening count
  differing by > 2 is flagged but stays quotable.
- **Endpoint**: `POST /api/vision/classify` `{ photoKeys: string[], openings?: number }` —
  reads photos from R2, returns the routing outcome.

### Calibration (owner/Ben action needed before launch)

Per the build spec, calibrate against 15–25 past jobs (photos + level actually charged):

```bash
cp calibration/manifest.example.json calibration/manifest.json
# download BEFORE photos from KTU Drive → Vendors & Products → Tune up
# into calibration/photos/<job>/ and label each job's charged level
ANTHROPIC_API_KEY=sk-... npm run calibrate   # prints accuracy + confusion matrix
```

P6's blind AI-vs-Ben check on 10 kitchens uses the same harness.

## Pricing rules implemented

All amounts are integer math — rates in **milli-dollars** (1/1000 USD, exact for SM's
3-decimal rates like $96.485), money in **cents**, half-up rounding at defined points only:

```
Effective Base = SM base + SM uplift            (uplift merged, never shown as a line)
Subtotal       = Effective Base + level rate × openings [+ white-wash premium]
Quote          = max(Subtotal, $2,000 floor)    → rounded to cents
Deposit        = 50% of Quote                   → rounded to cents
```

> The Same Day Discount (SDD) was **removed 2026-07-18 per owner** — the funnel has no
> promo pricing. SM's "Tune Up Discount" part (199161) is ignored.

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
4. `L1_2` merged-bucket rate policy (currently `max(L1, L2)`) needs owner sign-off.

(A fourth gap — SM's "TUSDD $250 Same Day Discount" note vs the spec's 10% SDD — was
resolved 2026-07-18: the owner dropped the SDD entirely.)

## Reference material (Google Drive)

KTU Google Drive → **Vendors & Products → Tune up**
(folder `1VGPeREqORA88gvFx6JPdrlr8H7cGUkdC`, owner `ktubloomfieldnj@gmail.com`, access verified):
https://drive.google.com/drive/folders/1VGPeREqORA88gvFx6JPdrlr8H7cGUkdC

Contains: the Kitchen Tune-Up manuals and process PDFs (level determination, pricing flow,
checklists, client prep), before/after job photos (calibration set for the P2 vision
classifier), and gallery composites. The damage-level rubric and process rules have been
distilled into **`docs/levels-and-process.md`** — the P2 classifier and the price-reveal
copy must be built from that rubric, calibrated against the folder's photos + the level
actually charged per job.

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
