/**
 * Service-agreement version tag. The full customer-facing agreement text lives
 * in the SPA (web/src/agreement.ts); this constant ties a recorded e-consent
 * (funnel_events "agreement_signed") to the exact agreement version the customer
 * saw. Bump it whenever the agreement wording changes.
 *
 * v0-draft: legal boilerplate present (NJ HIC #13VH10775400, 3-day rescission,
 * refund policy). The scope-of-work section still needs the ServiceMinder
 * proposal text from the owner and is marked as such in the SPA — do NOT mark
 * this agreement launch-ready until that text is in and attorney re-confirms.
 */
export const AGREEMENT_VERSION = "v0-draft-2026-07-18";
