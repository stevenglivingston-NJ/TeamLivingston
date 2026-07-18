# Tune-Up Damage Levels & Process Reference

Distilled 2026-07-17 from the owner's KTU Drive folder (**Vendors & Products → Tune up**,
folder `1VGPeREqORA88gvFx6JPdrlr8H7cGUkdC`). This is the canonical rubric for the Phase 2
vision classifier and the plain-English "why this level" copy at the price-reveal gate.

## The KTU damage rating system (1–5)

Mnemonic from the manual: finishing wood is substrate → stain (color) → finish.
Damage levels reverse that order — Level 1 is the finish, Level 2 the stain, Level 3 the substrate.

| Level | Definition | Repair required |
|-------|-----------|-----------------|
| **1** | Damage only into the first layer of **finish**. Minor scratches. | Finish repair + sheen adjustment |
| **2** | Through finish into the **color/stain layer** — stain and finish missing. | Stain + finish repair |
| **3** | Through finish and color into the **substrate** (wood). Fingernail gouges, deep scratches. | Epoxy + stain + finish repair |
| **4** | Cabinets **mostly absent of finish**; damage (types 1–3) exceeds **30%** of a door's/kitchen's surface. Also caused by excessive water damage, abuse/over-cleaning, or **nicotine/smoke** (requires 5–8 cleaning passes, +4–5 hours). | Advanced techniques — Tune-Up Artist only |
| **5** | **Non-repairable** — DIY damage or 1–4 damage so extensive that other core services are needed. | **Not a Tune-Up candidate.** Offer refacing / redooring / new cabinets |

## Service tiers (what the levels buy)

| Tier | Damage covered | Duration | Notes |
|------|---------------|----------|-------|
| Maintenance Tune-Up | ~none (cleaning, sheen, a few dings) | 2–3 hours | Future-service upsell after any job |
| **Basic Tune-Up** | Levels 1 & 2 | One day | The original Tune-Up; total damage ≤ **10%** of a cabinetry section's surface |
| **Standard Tune-Up** | Levels 1–3 | 1–2 days | Use when damage exceeds the Basic threshold |
| Level 4 job | Level 4 | longer | Beyond Standard; advanced artist required |

## Mapping to the funnel's pricing buckets

The funnel/AI classifier outputs three priced buckets plus two routed outcomes:

| Classifier output | Meaning | Funnel behavior |
|-------------------|---------|-----------------|
| `L1_2` | Basic Tune-Up damage | Instant quote at the L1_2 rate |
| `L3` | Standard Tune-Up damage | Instant quote at the L3 rate |
| `L4` | Level 4 damage (>30% surface, heavy water/nicotine) | Instant quote at the L4 rate |
| Level 5 signals | Non-repairable / DIY damage | **No quote.** Human review → offer core services (refacing/redooring) — still a lead |
| Low confidence | — | No quote; "finalized within 2 hours" human-pricing route |

## Sales-evaluation rules (from "Tune Up Sales Training — Evaluation of projects")

Source: sales-training PDF supplied by owner 2026-07-18 (Bruce Morgan, updated 1/2/2023 —
suggest filing in the Drive Tune up folder alongside the manuals).

- **Pricing dimensions**: Maintenance/Basic/Standard pricing is based on kitchen size
  (**openings AND exposed end panels**), degree of damage, **wood species**, and **stain
  color** — not openings alone. The classifier reports species/stain/end panels for the
  team; whether they feed automated pricing is an owner decision (see README gaps).
- **DIY repairs are a Level 4/5 signal.** Non-original finish — sheen glossy/flat vs the
  factory finish or vs the door backs, visible brush strokes, touch-up products sealed
  over damage — is *not* a Basic/Standard candidate.
- **Masking products** (scratch cover, Old English, Liquid Gold) can hide moderate-to-heavy
  damage and push the true rating higher — uniform oily luster on worn kitchens → rate
  conservative and flag.
- **Wet Test** (in-person only): a damp cloth over a scratch/dry area — damage that
  temporarily disappears is unsealed and repairable; damage that stays visible has been
  DIY-sealed and is hard to repair. Photos can't run it, but **dry woodgrain zones**
  (end panels, doors below the sink, above a coffee maker/rice cooker) should be flagged
  for the in-person check.
- **Nicotine tell**: yellowish/brown residue regardless of stain color; wipes off yellow
  onto a cleaning cloth. Smoking in the home ⇒ Level 4 territory.
- **Homeowner questions worth asking in the funnel** (kitchen-details gate, P3): "Has
  anyone smoked in the home?" and "Have any touch-up or polish products (Old English,
  scratch cover) been used on the cabinets?" — both cheaply resolve what photos can hide.
- **Level-5 pivot script**: tell the homeowner the damage is beyond the Tune-Up process and
  give them permission to consider refacing/new cabinets — this is the human-review
  follow-up call's framing for `notACandidate` results.
- Sell at the ability of the team's Tune-Up Artist; salesperson reviews photos with the
  artist — mirrors the funnel's human-review lane.

### Visual signals for the Phase 2 classifier (from the manual/process docs)

- **Thresholds**: damage >10% of a section ⇒ beyond Basic (→ L3); damage >30% ⇒ L4.
- **Water damage zones**: sink base (wet towels over doors → top rail/center panel), around
  dishwasher and stove; false fronts below sink. This is why required photo #4 is the sink
  base with bottom edge visible.
- **Grease/grime**: film above the stove and black grime at handle areas is normal L1/L2;
  it hides damage that appears after cleaning — bias slightly conservative when heavy.
- **Nicotine/smoke discoloration** escalates Basic → Standard or L4 (never L1_2).
- **Sun damage / discolored melamine end panels**: NOT repairable by a Tune-Up — treat like
  a Level-5 signal for that surface, note it in condition notes.
- **White-washed/pickled finish**: handled by the separate "Recoating process" (Finish-Up
  product, all species & whitewash) — this is the white-wash premium flag in pricing.

### Explicit non-scope (never promise in quote copy)

No color change or complete refinishing; no hinge-system conversion (boring doors); no sun-damage
repair; no end-panel replacement; no cabinet modification, height changes, or added cabinets;
no glass-insert conversions; no nicotine removal within a standard quote.

## Customer prep (feeds P4/P5 confirmation email + SMS)

From "Client Instructions – Tune-Up": empty cabinets/drawers (at minimum dishes/glasses/
cookware/open food), clear countertops and stovetop and fridge-top, arrange pet care, flag odor
sensitivity (crew ventilates; odors gone by end of day), have new hardware in hand if replacing.
Consultations and these instructions are free — never priced.

## Source files (KTU Drive → Vendors & Products → Tune up)

| File | Drive ID | Use |
|------|----------|-----|
| Basic Kitchen Tune-Up Process.pdf | `1RZ154udX1kU-IytwqqSkeC8QsKpnF_12` | Damage rating system + Basic process (this doc's primary source) |
| Tune-Up Manual.pdf (18.9 MB) | `1s4UO9D0hBVnvW_vOVoaby51ZEwFOai49` | Full manual — P2 must ingest for the detailed rubric |
| 2270522450_tune-up-manual.pdf (17.5 MB) | `1mUx7Vty-Lek4z-xxJoS5cAibsudGl7ZR` | Earlier manual upload (duplicate exists in folder) |
| Tune-Up Checklist.pdf | `1ni1HMYoi8WyEUSFRoDhJBNpivE6pFAZY` | Job-day process; Original vs Recoating (whitewash) finishing |
| Client Instructions - Tune-Up.pdf | `1y4GxbnKZF4-epAoo8l-n47B2aWMzikJP` | Customer prep for confirmation comms |
| Tune-Up_20Products.pdf | `1t9lVXQ-AR_0F0my-tfkoMa3Gf-Wq4gSI` | Product list (ops reference) |
| Tune-Up suppliers (Google Doc) | `1LqaXk0rORGPiqeyyLsZ-BqjNxVi4XPjqbE1XjXiJCKc` | Supplier list (ops reference) |
| 2025 KTU Starter Kit (Mohawk).xlsx | `1DCcH7A5zqkb0TN8YUov9F7v5QlQVSD4N` | Product kit (ops reference) |
| Before/after JPG pairs (~30 files) + Morrison PDFs | — | **P2 calibration set** (photos ↔ level actually charged) + landing-page gallery candidates |
| Screenshots 2026-07-17 (5 PNG) | — | Before/after gallery composites for the landing page |
