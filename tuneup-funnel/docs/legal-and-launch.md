# Legal & Launch Reference

Owner decisions and launch-gate status for the KTU Instant Tune-Up funnel.
Legal content the checkout agreement depends on. Updated 2026-07-18.

## Service agreement (checkout contract)

The checkout service agreement **is** the customer contract (the ServiceMinder proposal
is created internally but not sent). It must mirror the SM proposal text and include the
NJ Home Improvement Contractor requirements.

**Still needed from owner:** the **SM proposal text** — the source the agreement mirrors.
Until it's supplied, `src/` has no agreement template; Phase 4 checkout can't render the
contract. This is the last hard content blocker for launch.

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
| SM proposal text (agreement source) | ⬜ **needed from owner** |
| NJ HIC number | ✅ `13VH10775400` (KTU / First Generation USA LLC) |
| Calibration photos labeled + ingested | ⬜ owner/Ben (see calibration/) |
| Meta Pixel ID | ✅ `109034988941656` |
| HighLevel notification recipients | ⬜ **needed from owner** (who gets booking/callback alerts) |
| SM pricing configured | ✅ template rebuilt 2026-07-18 (one base-price note in README) |
| Cloudflare D1 + KV | ✅ created 2026-07-18 |
| Cloudflare R2 | ⬜ enable R2 in dashboard, then create bucket |
| Landing gallery photos + award names | ⬜ owner to select best before/after pairs |
| Stripe account (First Generation USA LLC) | ⬜ needed for Phase 4 |
| Click-to-call number | (973) 521-1182 per build spec — confirm |
