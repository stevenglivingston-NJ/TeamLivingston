/** Static brand/content config for the funnel. */

export const PHONE_DISPLAY = "(973) 521-1182";
export const PHONE_TEL = "+19735211182";

export const SERVICE_ZIP_PREFIXES = [
  // Bloomfield NJ and nearby — placeholder service area; owner to confirm the
  // real radius. ZIP gate treats anything outside this list as out-of-area.
  "070", "071", "072", "073", "074",
];

export const AWARDS = "4× 2026 National HFC Awards";

export interface GalleryItem {
  src: string;
  caption: string;
}

// Real KTU before/after composites (owner Drive → Vendors & Products → Tune up),
// optimized into web/public/gallery. Vite serves them under /tuneup/gallery/.
export const GALLERY: GalleryItem[] = [
  { src: "gallery/worn-oak-base.jpg", caption: "Worn oak base cabinets — restored in one day" },
  { src: "gallery/whitewash-restore.jpg", caption: "White-washed finish, brought back to life" },
  { src: "gallery/door-detail-restore.jpg", caption: "Chipped door edges repaired and blended" },
  { src: "gallery/edge-wear-restore.jpg", caption: "Handle-area wear, refinished" },
  { src: "gallery/cabinet-run-restore.jpg", caption: "Full cabinet run, tuned up" },
];

export interface SlotDef {
  key: string;
  label: string;
  instruction: string;
  required: boolean;
}

// 4 required + 4 optional, per the build spec's guided-capture list.
export const PHOTO_SLOTS: SlotDef[] = [
  { key: "wide", label: "Full kitchen (wide)", instruction: "Stand in the doorway and capture the whole kitchen.", required: true },
  { key: "run", label: "Longest cabinet run", instruction: "Straight-on shot of your longest row of cabinets.", required: true },
  { key: "worn", label: "Most worn door", instruction: "Close-up of the most worn or damaged door or drawer front.", required: true },
  { key: "sink", label: "Under the sink", instruction: "Sink base cabinet — include the bottom edge (water-damage zone).", required: true },
  { key: "opposite", label: "Opposite wall", instruction: "Second run or opposite wall (optional).", required: false },
  { key: "drawer", label: "Drawer edge", instruction: "Close-up of a drawer front edge (optional).", required: false },
  { key: "endpanel", label: "End panel", instruction: "A cabinet end panel (optional).", required: false },
  { key: "inside", label: "Inside a door", instruction: "Inside of one door — original finish reference (optional).", required: false },
];

export const FIRM_PRICE_COPY =
  "This is your firm base price. If our inspection finds conditions not visible in your photos, any adjustment is sent to you before any work begins. Optional add-ons appear on your invoice.";
