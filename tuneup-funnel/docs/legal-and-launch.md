# Legal & Launch Reference

Owner decisions and launch-gate status for the KTU Instant Tune-Up funnel.
Legal content the checkout agreement depends on. Updated 2026-07-18.

## Service agreement (checkout contract)

The checkout service agreement **is** the customer contract (the ServiceMinder proposal
is created internally but not sent). It must mirror the SM proposal text and include the
NJ Home Improvement Contractor requirements.

**Built (Phase 4, DRAFT):** `web/src/agreement.ts` holds the agreement the SPA renders at the
Agreement gate, with the fixed NJ HIC elements in place — registration **#13VH10775400**,
firm-price terms, start/completion via the appointment, the **3-day right of rescission**, and
the refund policy. E-consent is recorded server-side (`funnel_events` "agreement_signed" +
`AGREEMENT_VERSION`).

**Still needed from owner:** the **SM proposal text** — the Scope of Work section is a marked
placeholder (`pending: true`) until it's supplied; the agreement mirrors it. Do not launch until
that text is in and the attorney re-confirms the assembled document. This is the last hard
content blocker.

## Payments — HighLevel (owner decision 2026-07-18)

Deposits use the **HighLevel payment integration**, not Stripe. Phase 4 `/api/checkout` creates
the 50% deposit payment; on confirmed payment the HL webhook calls `/api/booking/confirm`, which
books the SM appointment. Until the HL payment config (`HIGHLEVEL_PAYMENT_URL`, `HIGHLEVEL_API_KEY`)
is set, the funnel uses a graceful fallback: it books the appointment and the team sends the HL
deposit invoice. **Needed from owner:** the HighLevel payment-integration details to wire the live
deposit link + webhook.

## Refund & rescission policy (owner-decided 2026-07-18)

Supersedes the build spec's draft tiered refunds. The policy the agreement states:

- **3-day right of rescission (NJ law).** The customer may cancel within **3 business days**
  of signing for a full refund — this is the NJ Home Improvement Practices right of
  rescission, and it must be disclosed in the agreement. Implement the deposit refund path
  for cancellations inside this window.
- **After the rescission window: bound to contract.** No tiered cancellation refunds — once
  the 3 business days pass, the signed agreement governs.
- **Post-inspection adjustment (from build spec, still applies):** if the on-site inspection
  finds conditions not visible in photos and the resulting price adjustment is **declined by
  the customer**, they get a **full refund** of the deposit. The firm-price framing already
  promises this ("any adjustment is sent before work begins").

## Attorney review

Owner marked the agreement **signed off** (2026-07-18). Keep this doc as the record. Any
material change to the agreement text or the refund/rescission language should be re-reviewed.

## NJ HIC registration number — confirmed

**KTU / First Generation USA LLC HIC #: `13VH10775400`** (owner-confirmed 2026-07-18;
services run under KTU). This is the number the checkout agreement carries.

(A second number, `13VH13781500`, exists on other Monday.com items and is **not** KTU's —
likely the BTU/Oracabessa entity. Not used here.)

> The Monday.com record also stores a state-portal login. Those credentials are deliberately
> **not** recorded in this repo — keep them in Monday.com only.

## Launch gate status (build-spec "do not launch without")

| Item | Status |
|------|--------|
| Attorney sign-off on agreement | ✅ owner-confirmed 2026-07-18 |
| Refund tiers / rescission | ✅ defined above |
| SM proposal text (agreement source) | ⬜ **needed from owner** (Scope of Work placeholder) |
| NJ HIC number | ✅ `13VH10775400` (KTU / First Generation USA LLC) |
| Deposit payments | ✅ HighLevel (Phase 4 built; fallback active until HL payment config set) |
| SM Tune-Up calendar availability | ⬜ assign agents/hours so slot search returns times |
| Calibration photos labeled + ingested | ⬜ owner/Ben (see calibration/) |
| Meta Pixel ID | ✅ `109034988941656` |
| Booking/callback notification recipient | ✅ **Sonya (office)** — P5 Worker fan-out built (tags `tuneup-lead/callback/booked`); ⬜ owner builds the HL notification workflows (AI-builder prompt in `docs/highlevel-phase5.md`) |
| Meta CAPI token + GA4 property | ⬜ owner: CAPI token, GA4 `G-` id + MP secret (steps in `docs/highlevel-phase5.md`); Worker no-ops until set |
| HL custom fields for Tune-Up | ⬜ owner: create the 9 `tuneup_*` contact custom fields (list in `docs/highlevel-phase5.md`) |
| SM pricing configured | ✅ live per-door: L1_2 $96 / L3 $112 / L4 $136 / uplift $390.35 / white-wash $620. ⬜ base still $0 — set $275 on SM service 30382 BasePrice |
| Cloudflare D1 + KV | ✅ created 2026-07-18 |
| Cloudflare R2 | ✅ bucket `ktu-tuneup-photos` created 2026-08-06; PHOTOS binding live in wrangler.toml |
| Landing gallery photos + award names | ⬜ owner to select best before/after pairs |
| Stripe account (First Generation USA LLC) | ⬜ needed for Phase 4 |
| Click-to-call number | (973) 521-1182 per build spec — confirm |
