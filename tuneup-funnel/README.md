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
- Also reports **wood species, stain color, and exposed end-panel count** — per the sales
  training doc these affect real pricing; today they inform the team only (see gaps).
- **P3 note**: the kitchen-details gate should ask "has anyone smoked in the home?" and
  "have polish/touch-up products (Old English, scratch cover) been used?" — photos can't
  always see either, and both change the level (docs/levels-and-process.md).

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
- AI level buckets are `L1_2`, `L3`, `L4` (SM merges levels 1 and 2). SM now carries a
  single merged "Tune-Up Level 1 & 2" part, so each bucket maps to exactly one SM part.

## ServiceMinder mapping (live-verified 2026-07-18, after template rebuild)

Rates live as **parts** on service `30382 Tune-Up Residential`
(`POST https://serviceminder.io/api/services/all` with `IncludeParts: true`).
Mapping is by part ID in `src/config.ts`. The owner rebuilt the Tune-Up template
2026-07-18 with **per-opening pricing** and added the White Wash Premium part —
this closed the earlier pricing gaps. **Part IDs were repurposed in the rebuild**
(old "Level 2" `1557033` is now White Wash Premium), so verify by name if SM is
re-templated again:

| Role | SM part | ID | Live value 2026-07-18 |
|------|---------|----|--------------------|
| Uplift (effective base) | Tune-Up Uplift | 199137 | $390.35 |
| L1_2 (merged) | Tune-Up Level 1 & 2 | 199138 | **$96.00 / opening** |
| L3 | Tune-Up Level 3 | 199139 | **$112.00 / opening** |
| L4 | Tune-Up Level 4 | 199140 | **$136.00 / opening** |
| White-wash premium | White Wash Premium | 1557033 | $620.00 |
| Base | service `BasePrice` | — | $0.00 (see note) |

Rates are read live; the values above are just the current snapshot. White-wash
quotes now price instantly (no longer routed to human review on that ground).

### Remaining SM note (owner confirm)

- **Effective base = uplift only ($390.35).** Service `BasePrice` still reads $0 via the
  API. The spec envisioned base ~$250 + uplift ~$389.65 ≈ $639.65. If a separate ~$250
  base is intended, set `BasePrice` on service 30382 (the cron picks it up in 15 min);
  otherwise the uplift serves as the base and quotes run ~$250 lower before the $2k floor.
- The proposal-template screenshot showed cents-level values ($96.485, $389.65, $618.50)
  slightly different from the service-part values the cron reads ($96.00, $390.35, $620.00).
  The engine uses the **service parts** (source of truth per spec) — reconcile if the
  template's cents values are the intended ones.
- `end panels / wood species / stain color` (from the sales-training doc) are reported by
  the classifier but not yet in automated pricing — owner decision whether they should be.

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

### Cloudflare resources

Created 2026-07-18 (real IDs in `wrangler.toml`):
- **D1** `ktu-tuneup` — `e8697721-207d-42d5-8014-c8240b690ee4` (schema applied)
- **KV** `ktu-tuneup-pricing` — `eac228b23726485389a6236be9f72e0a`
- **R2** `ktu-tuneup-photos` — **pending**: enable R2 in the Cloudflare dashboard
  (billing gate), then `wrangler r2 bucket create ktu-tuneup-photos` and uncomment the
  `[[r2_buckets]]` block. Photos aren't needed until the P3 funnel + P2 classify go live.

```bash
wrangler d1 migrations apply ktu-tuneup --remote   # or already applied via API
wrangler secret put SERVICEMINDER_API_KEY
wrangler secret put ANTHROPIC_API_KEY
wrangler deploy
```

Secrets (Wrangler): `SERVICEMINDER_API_KEY` (P1), `ANTHROPIC_API_KEY` (P2); later phases
add `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `HIGHLEVEL_WEBHOOK_URL`, `META_CAPI_TOKEN`.
`META_PIXEL_ID` is a non-secret var (already set in `wrangler.toml`). Never commit secrets.

## Integration reference (for later phases)

| System | Detail |
|--------|--------|
| Meta Pixel ID | `109034988941656` (KTU Bloomfield NJ; domain verified) — in `wrangler.toml` |
| HighLevel calendar | **"Tune-up"** — Phase 4 books here |
| ServiceMinder calendar | **"Tune-Up Residential"** — SM-side booking target |
| NJ HIC # | See `docs/legal-and-launch.md` — a number is on file but a conflict needs owner resolution before it goes in the contract |

## Do-not-launch checklist (from build spec)

Tracked in **`docs/legal-and-launch.md`**. Status: attorney sign-off ✅ (owner-confirmed),
refund/rescission policy ✅ (defined), Meta Pixel ✅, SM pricing ✅. Still open: SM proposal
text (agreement source), NJ HIC number conflict, calibration photos labeled, R2 enabled,
HighLevel notification recipient list, gallery photo selection.
