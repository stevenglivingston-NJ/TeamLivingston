/**
 * Customer-facing service agreement. Version must match the Worker's
 * AGREEMENT_VERSION (src/agreement.ts) so recorded e-consent ties to this text.
 *
 * Scope of Work mirrors the ServiceMinder "Tune-Up Residential" service
 * description (service 30382) — the text SM prints on Tune-Up proposals —
 * pulled live 2026-08-11. Owner marked the agreement attorney-signed-off
 * 2026-07-18; per docs/legal-and-launch.md, this scope insertion is a material
 * completion of that document and should get a final attorney read before
 * launch. NJ Home Improvement Contractor elements are in place.
 */

export const AGREEMENT_VERSION = "v1-2026-08-11";

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
    body: `Contractor will perform the Kitchen Tune-Up core service on the Owner's kitchen cabinetry at the service address, covering the number of cabinet openings (doors and drawer fronts) stated in your quote, at the condition level assessed from your photos, including the white-wash treatment only if it appears on your quote. The Tune-Up core service process: chemically clean, degrease and prep existing cabinetry to artistically repair stain and finish damage; adjustment of sheen along with install of new rubber bumper pads on doors and drawer fronts if needed; inspect and adjust door hinges and drawer glides. The process does not change the existing color or repair major sun damage, and does not unwarp doors. This process is an artistic restoration created to improve the overall appearance of the cabinetry and should not be confused with complete refinishing. The scope is confirmed by on-site inspection before work begins.`,
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
