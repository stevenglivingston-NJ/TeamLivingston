# Source Registry — Prospect Agent

Per-municipality and cross-market research sources. Statuses: **stable** (used
successfully), **verify** (standard/expected URL — confirm on first use), and
**paid/authorized-only** (use only if the account is authorized).

> **Primary records — deeds, entities, owners — live in
> [`records-access.md`](records-access.md).** That file has the tested
> enrichment cascade (address → deed index → LLC → registered agent →
> portfolio), the Essex PRESS gotchas, office phone numbers and emails, and the
> Daniel's Law limits on parcel data. Use it whenever a lead says
> "buyer undisclosed" or names only an LLC.
Last updated: 2026-09-12.

## Cross-market sources (every scan)

| Source | What it yields | URL / access | Status |
|---|---|---|---|
| LoopNet | Active multifamily listings, value-add language, photos | loopnet.com — search "multifamily for sale [town] NJ" | stable (2026-08-12: town search pages fetch OK; filter out "nearby" spillover; individual listing pages sometimes block) |
| CityFeet / Homes.com | Listing cards corroborating LoopNet; small-multifamily inventory | cityfeet.com, homes.com | stable (2026-08-12: fetched OK) |
| Crexi | Active listings + some auction/under-contract status | crexi.com | degraded (2026-08-12: 403 on all fetches — manual check only) |
| Marcus & Millichap | Listings + closed-deal press | marcusmillichap.com | verify |
| Kislak Company | NJ multifamily listings + sale announcements | kislakrealty.com | verify |
| Gebroe-Hammer Associates | Essex County multifamily deal announcements | via WebSearch news | stable |
| CBRE / C&W / JLL NJ | Institutional listings, market reports | firm sites | verify |
| Jersey Digs | Development news, project stages, developer names (heavy Newark/Essex coverage) | jerseydigs.com | stable |
| RE-NJ (Real Estate NJ) | NJ CRE transactions, financings, development | re-nj.com | stable |
| TAPinto (per-town editions) | Planning-board coverage, local development news | tapinto.net/towns/... | stable |
| Montclair Local | Montclair development + planning coverage | montclairlocal.news | degraded (403 on fetch historically; 2026-09-21: rate-limited 429 on repeated fetches — headlines/dates via search snippets) |
| ROI-NJ | NJ deal announcements | roi-nj.com | stable as of 2026-09-21 (direct fetches succeeded this run) |
| TAPinto (all town editions) | Planning-board coverage | tapinto.net | degraded (2026-09-21: 403 on direct fetch — search-snippet only) |
| Essex News Daily | East Orange/Orange/Bloomfield-area news | essexnewsdaily.com | degraded (2026-09-21: site search returned zero indexed results this run — needs a direct site visit next cycle, not just a search-engine query) |
| MyVeronaNJ | Verona council/board coverage | myveronanj.com | degraded (403 on fetch; snippets usable) |
| Village Green NJ | Maplewood/South Orange development coverage | villagegreennj.com | stable |
| Essex News Daily | East Orange/Orange/Bloomfield-area news | essexnewsdaily.com | verify |
| GlobeSt / The Real Deal / Traded NJ | Transaction + financing news | via WebSearch | stable |
| NJ property tax records (MOD-IV) | Assessed value, year built, block/lot, class — **NOT owner names** | taxrecords-nj.com (link directory; **no Essex County**) · njogis-newjersey.opendata.arcgis.com | degraded (2026-09-12: `OWNER_NAME` is redacted in the public MOD-IV extract; NJACTB discontinued its statewide search 2023-01-01 under Daniel's Law; njparcels.com no longer publishes owner info — **get owner identity from the deed index instead**) |
| **Essex County Register of Deeds (PRESS)** | **Grantor/grantee, instrument #, recording date, block/lot** for deeds, mortgages, notices of settlement, foreclosures — the authoritative answer to "who bought it" | **https://press.essexregister.com/prodpress/clerk/ClerkHome.aspx?op=basic** — free, no login · 973-621-4960 · info@essexregister.com | **stable (2026-09-12: fully tested — resolved the 47 Union St buyer. Index online 2001→present; document images in-office only. See `records-access.md`)** |
| NJ business-entity search (DORES) | Entity ID, registered city, type, **formation date** (free). Registered agent + office address via $5.00+$1.25 Status Report | njportal.com/DOR/BusinessNameSearch · scripted at `prospect/tools/nj_dores.py` · reports at njportal.com/dor/businessrecords/ | stable (2026-09-12: tested; free tier does **not** include registered agent) |
| LinkedIn | Decision-maker roles, growth hires, PM/developer activity | linkedin.com — public/professional info only | stable (respect ToS; no scraping) |
| Google Maps / Street View | Visual property + neighborhood context only | ToS-compliant viewing | stable |
| CoStar | Comps, ownership, debt | **paid/authorized-only** — not currently authorized | not in use |

## Primary corridor — municipal sources

For each town: (a) planning-board agendas/minutes, (b) zoning board, (c)
building department / permits where posted, (d) redevelopment plans, (e) legal
notices. All municipal URLs are **verify** until first successful use.

| Municipality | Municipal site (verify) | Notes |
|---|---|---|
| Montclair | montclairnjusa.org | Planning Board + HPC very active; check Lackawanna Plaza & Seymour St redevelopment items; Montclair Local + TAPinto Montclair cover hearings |
| Glen Ridge | glenridgenj.org | Low volume — monthly check sufficient |
| Maplewood | maplewoodnj.gov | Springfield Ave + Village redevelopment; Village Green coverage |
| South Orange | southorange.org | Village center redevelopment agendas; Village Green coverage |
| West Orange | westorange.org | Essex Green / Executive Dr area items; larger garden-apartment stock |
| Verona | veronanj.org | Pompton Ave corridor applications |
| Cedar Grove | cedargrovenj.org | Pompton Ave / former hospital-site development |
| Livingston | livingstonnj.org | Town-center + Route 10 corridor redevelopment |
| Millburn | twp.millburn.nj.us | Downtown Millburn apartment items |
| North Caldwell / Essex Fells / Roseland / Fairfield | northcaldwell.org / essexfells.org / roselandnj.org / fairfieldnj.org | Low volume; Roseland-Fairfield office-conversion watch |
| Summit | cityofsummit.org | Expansion market — monthly check |

## Secondary market — municipal sources

| Municipality | Municipal site (verify) | Notes |
|---|---|---|
| Newark | newarknj.gov | Central Planning Board weekly agendas; Jersey Digs covers most projects; track developer/GC names for Tier-4 relationships |
| East Orange | eastorange-nj.gov | Transit-oriented development around Brick Church/EO stations |
| Orange | orangenj.gov | Valley Arts district + transit village |
| Bloomfield | bloomfieldtwpnj.com | Bloomfield Center redevelopment; home turf (KTU/BTU) |
| Belleville | bellevillenj.org | Washington Ave corridor |
| Nutley | nutleynj.org | Franklin Ave + ON3 spillover |

## Senior housing & publicly funded work (added 2026-09-12)

Sources for Tier 5 and Tier 6. None of these were in the registry before
2026-09-12, and none overlap the transaction sources above — this is a
separate weekly sweep, not a filter on the existing one.

| Source | What it yields | URL / access | Status |
|---|---|---|---|
| NJHMFA LIHTC allocations & awards | Named sponsor, project address, unit count, tenant type (FAMILY / SENIOR / SENIOR 55+ / 62+), LIHTC type (New / Mod Rehab / Sub Rehab / Rehab-Occupied) and a **direct contact name + phone** for every applicant | nj.gov/dca/hmfa/developers/lihtc/allocationawards/ | stable (2026-09-12: index page fetches OK; the award lists are PDFs — download and parse locally, WebFetch cannot read them) |
| NJHMFA 9% applicant list (current round) | The full current-round filing list | .../docs/lihtc/awards/2026/2026_applicant_list.pdf | stable (2026-09-12: parsed successfully) |
| NJ Purchasing Group (BidNet Direct) | Open solicitations from participating housing authorities, counties, municipalities | bidnetdirect.com/new-jersey | **registration required** — free "Limited" package; vendor support 800-835-4603 opt 2. Direct WebFetch 403s (2026-09-12) — check signed-in, or via browser |
| Newark Housing Authority | Its own solicitations; $27.3M 2026 HUD Capital Fund award | bidnetdirect.com/new-jersey/newarkhousingauthority · newarkha.org | verify |
| East Orange Housing Authority | Concord Towers (64u, 1963) + Vista Village (180u, 1969), both elderly/disabled; property managers named on site | eoha.org/public-housing | stable (2026-09-12: fetched OK) |
| HUD Capital Fund award coverage | Which NJ authorities just received modernization money, and how much | via WebSearch (WHYY / RE-NJ / TAPinto carry the NJ allocations) | stable |
| NJ DPMC advertisements | State-building projects; needs DPMC classification to bid | nj.gov/treasury/dpmc | verify — later-stage, not weekly |
| Senior Housing News / Seniors Housing Business | Operator expansion, new development, ownership change in NJ | seniorhousingnews.com · seniorshousingbusiness.com | verify |
| Private senior-living operator sites | Community list, ED contact, new-community announcements | brandycare.com, chelseaseniorliving.com, junipercommunities.com, sunriseseniorliving.com, brightviewseniorliving.com | verify |

**Handling rules for this sweep**

- A LIHTC **application is not an award.** Label it `applicant — not awarded`
  every time, and never let outreach language imply the project is funded.
- Housing-authority work is **bid work**. Surface it as a solicitation with a
  closing date, and state plainly whether the PWCR/bonding gates are cleared —
  if they are not, the correct output is "not biddable yet", not a lead.
- Publicly owned senior buildings are mostly pre-1978: flag **EPA RRP
  lead-safe** applicability on every one of them.
- Property managers and superintendents listed on an authority's own site are
  published business contacts and may be recorded; do not go looking for
  personal contact details for public employees.

## Scan cadence

- **Weekly (Mon):** LoopNet/Crexi searches per primary town; Jersey Digs +
  RE-NJ + Village Green + TAPinto sweeps; broker announcement search; top-10
  town planning agendas.
- **Bi-weekly:** secondary-market planning agendas; LinkedIn growth-hire scan.
- **Monthly:** deed/mortgage sweep on watched properties (tax records +
  register); PM roster refresh; low-volume towns (Glen Ridge, Essex Fells,
  North Caldwell, Fairfield, Summit).
- **Weekly (Mon, added 2026-09-12):** NJ Purchasing Group open solicitations;
  housing-authority procurement pages for Newark, East Orange, Orange,
  Irvington, Bloomfield, Montclair and Essex County.
- **Quarterly (added 2026-09-12):** NJHMFA award/applicant list refresh —
  reconcile last round's applicants against awards and promote the winners.

## Gaps / sources to add

- CoStar or PropertyShark authorization would unlock ownership + debt data.
- County legal-notice aggregator (njpublicnotices.com — verify) for hearing
  notices naming applicants.
- MLS access via a broker relationship for small-multifamily photo review
  (dated-kitchen confirmation).
- An Essex County housing-authority roster with a procurement contact per
  authority (only Newark and East Orange are mapped as of 2026-09-12).
- NJ certificate-of-need / assisted-living licensure filings, which would give
  private senior-living construction a real transaction signal instead of the
  door-knock treatment it gets today.
