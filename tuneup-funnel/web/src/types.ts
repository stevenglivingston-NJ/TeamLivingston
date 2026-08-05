export type Stage =
  | "landing"
  | "zip"
  | "details"
  | "photos"
  | "contact"
  | "price"
  | "schedule"
  | "agreement"
  | "deposit"
  | "confirmation";

export type LevelBucket = "L1_2" | "L3" | "L4";

export interface PhotoSlot {
  key: string;
  label: string;
  instruction: string;
  required: boolean;
  /** Object URL for preview once captured. */
  previewUrl?: string;
  /** The captured file, pending upload. */
  file?: File;
}

export interface FunnelState {
  sessionId: string | null;
  stage: Stage;
  zip: string;
  inServiceArea: boolean | null;
  openings: number;
  cabinetMaterial: string;
  cabinetAge: string;
  smokingInHome: "yes" | "no" | "unsure" | "";
  polishProductsUsed: "yes" | "no" | "unsure" | "";
  photos: PhotoSlot[];
  contact: { name: string; phone: string; email: string };
  /** Service address, collected before booking (SM needs it to book). */
  address: { address1: string; city: string; state: string; zip: string };
  /** Chosen appointment slot (ISO start), once picked. */
  selectedSlot: string | null;
  /** Price-reveal result once computed. */
  quote: QuoteReveal | null;
}

/** What the price-reveal screen renders. */
export interface QuoteReveal {
  quotable: boolean;
  quoteCents?: number;
  depositCents?: number;
  floorApplied?: boolean;
  whiteWashCents?: number | null;
  level?: LevelBucket;
  reasoning?: string;
  /** True when the funnel routed to human pricing instead of an instant quote. */
  humanReview: boolean;
  reasons?: string[];
}
