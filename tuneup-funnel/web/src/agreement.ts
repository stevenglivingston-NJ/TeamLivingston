/**
 * Customer-facing service agreement. Version must match the Worker's
 * AGREEMENT_VERSION (src/agreement.ts) so recorded e-consent ties to this text.
 *
 * ⚠️ DRAFT — not launch-ready. The scope-of-work section is a placeholder until
 * the owner supplies the ServiceMinder proposal text (the agreement must mirror
 * it), and the whole document needs final attorney confirmation once that text
 * is in. The fixed NJ Home Improvement Contractor elements below are in place.
 */

export const AGREEMENT_VERSION = "v0-draft-2026-07-18";

export const HIC_NUMBER = "13VH10775400";
export const CONTRACTOR = "First Generation USA LLC d/b/a Kitchen Tune-Up Bloomfield";
export const CONTRACTOR_ADDRESS = "1285 Broad St, Suite 2, Bloomfield, NJ 07003";
export const CONTRACTOR_PHONE = "(973) 521-1182";

export interface AgreementSection {
  heading: string;
  body: string;
  /** Marks a section whose final wording is still pending owner/attorney input. */
  pending?: boolean;
}

export const AGREEMENT_SECTIONS: AgreementSection[] = [
  {
    heading: "Parties & Contractor Registration",
    body: `This Home Improvement Contract is between ${CONTRACTOR} ("Contractor"), ${CONTRACTOR_ADDRESS}, ${CONTRACTOR_PHONE}, and the customer named below ("Owner"). Contractor is registered with the New Jersey Division of Consumer Affairs, NJ Home Improvement Contractor Registration No. ${HIC_NUMBER}.`,
  },
  {
    heading: "Scope of Work",
    pending: true,
    body: `Kitchen Tune-Up cabinet restoration (Tune-Up service) at the Owner's service address, as described in your instant quote and confirmed by on-site inspection. [FINAL SCOPE-OF-WORK TEXT PENDING — this section will mirror the ServiceMinder proposal text the owner supplies before launch.]`,
  },
  {
    heading: "Price",
    body: `The total price is the firm price shown in your quote. This is a firm base price. If our on-site inspection finds conditions not visible in your photos, any adjustment will be sent to you for approval before any work begins. Optional add-ons, if any, appear on your invoice. A 50% deposit is due to reserve your appointment; the balance is due at completion. No sales tax applies (New Jersey capital improvement).`,
  },
  {
    heading: "Dates",
    body: `Start and completion dates will be set with your scheduled appointment. The Tune-Up is typically completed in one day. Your appointment date is shown on your confirmation.`,
  },
  {
    heading: "Your 3-Day Right to Cancel",
    body: `You, the Owner, may cancel this transaction at any time prior to midnight of the third business day after the date of this contract. If you cancel within this period, any deposit you paid will be refunded in full. To cancel, notify Kitchen Tune-Up Bloomfield in writing at the address or phone above. After the 3-business-day rescission period, this signed agreement is binding.`,
  },
  {
    heading: "Refunds",
    body: `Full refund of your deposit within the 3-business-day cancellation period above. In addition, if our on-site inspection results in a price adjustment that you decline, your deposit is refunded in full. After the rescission period, cancellations are governed by this agreement.`,
  },
  {
    heading: "What a Tune-Up Is Not",
    body: `A Tune-Up is artistic restoration of your existing finish — not complete refinishing, color change, refacing, or new cabinets. It does not include hinge-system conversion, sun-damage repair, replacing discolored end panels, cabinet modifications, or nicotine/smoke removal. If your cabinets need more than a Tune-Up, we'll discuss other options with you.`,
  },
  {
    heading: "Photos & Privacy",
    body: `The photos you submit are used to prepare your quote and are processed by an automated analysis service. They are stored securely and used only for your project. See our privacy policy for details.`,
  },
];
