/**
 * Service-agreement version tag. The full customer-facing agreement text lives
 * in the SPA (web/src/agreement.ts); this constant ties a recorded e-consent
 * (funnel_events "agreement_signed") to the exact agreement version the customer
 * saw. Bump it whenever the agreement wording changes.
 *
 * v1-2026-08-11: Scope of Work completed from the ServiceMinder "Tune-Up
 * Residential" service description (service 30382, pulled live 2026-08-11) —
 * the text SM prints on Tune-Up proposals. Legal boilerplate unchanged from
 * v0 (NJ HIC #13VH10775400, 3-day rescission, refund policy). Get a final
 * attorney read of the completed document before launch.
 */
export const AGREEMENT_VERSION = "v1-2026-08-11";
