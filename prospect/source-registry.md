# Source Registry — Prospect Agent

Per-municipality and cross-market research sources. Statuses: **stable** (used
successfully), **verify** (standard/expected URL — confirm on first use), and
**paid/authorized-only** (use only if the account is authorized).
Last updated: 2026-09-07.

**2026-09-07 finding:** all four parallel research sweeps this week hit direct
`WebFetch` 403s across every listing aggregator (LoopNet, CityFeet, Homes.com,
Crexi, Showcase.com, even Kislak's own property pages) — a broader outage than
this registry previously documented ("stable" / "sometimes blocks"). TAPinto
also 403'd on both attempts this run (was "stable"). WebSearch snippets were
usable as probable-confidence fallback throughout, per the spec's allowance,
but several genuine active listings (Verona, Cedar Grove, Summit) could not be
address-resolved this way and were logged as unconfirmed candidates rather
than CSV rows. Re-verify all "stable" listing sources next run before trusting
this status; if the pattern repeats, escalate to Tekki as a pipe health issue.

## Cross-market sources (every scan)

| Source | What it yields | URL / access | Status |
|---|---|---|---|
| LoopNet | Active multifamily listings, value-add language, photos | loopnet.com — search "multifamily for sale [town] NJ" | degraded (2026-09-07: 403 on every direct fetch this run, town-search and listing pages alike — was "stable" 2026-08-12; use WebSearch snippets, re-test next run) |
| CityFeet / Homes.com | Listing cards corroborating LoopNet; small-multifamily inventory | cityfeet.com, homes.com | degraded (2026-09-07: 403 on every direct fetch — was "stable" 2026-08-12) |
| Crexi | Active listings + some auction/under-contract status | crexi.com | degraded (2026-08-12: 403 on all fetches — manual check only) |
| Marcus & Millichap | Listings + closed-deal press | marcusmillichap.com | verify |
| Kislak Company | NJ multifamily listings + sale announcements | kislakrealty.com | verify |
| Gebroe-Hammer Associates | Essex County multifamily deal announcements | via WebSearch news | stable |
| CBRE / C&W / JLL NJ | Institutional listings, market reports | firm sites | verify |
| Jersey Digs | Development news, project stages, developer names (heavy Newark/Essex coverage) | jerseydigs.com | stable |
| RE-NJ (Real Estate NJ) | NJ CRE transactions, financings, development | re-nj.com | stable |
| TAPinto (per-town editions) | Planning-board coverage, local development news | tapinto.net/towns/... | degraded (2026-09-07: 403 on both attempts this run, Verona/Cedar Grove + Millburn — was "stable"; use search snippets, re-test) |
| nj21st.com | Summit-area planning/hearing coverage | nj21st.com | stable (2026-09-07: added — clean full-text fetch on a Summit Planning Board item) |
| Montclair Local | Montclair development + planning coverage | montclairlocal.news | degraded (403 on fetch; headlines/dates via search snippets) |
| ROI-NJ | NJ deal announcements | roi-nj.com | degraded (403 on fetch; snippets usable) |
| MyVeronaNJ | Verona council/board coverage | myveronanj.com | degraded (403 on fetch; snippets usable) |
| Village Green NJ | Maplewood/South Orange development coverage | villagegreennj.com | stable |
| Essex News Daily | East Orange/Orange/Bloomfield-area news | essexnewsdaily.com | verify |
| GlobeSt / The Real Deal / Traded NJ | Transaction + financing news | via WebSearch | stable |
| NJ property tax records (MOD-IV) | Owner of record, assessed values, year built | taxrecords-nj.com (free) | verify |
| Essex County Register of Deeds | Deeds, mortgages, assignments — capital events | county online search — locate via essexcountynj.org | verify |
| NJ business-entity search (DORES) | LLC registered agents / principals | njportal.com DOR Business Name Search | verify |
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

## Scan cadence

- **Weekly (Mon):** LoopNet/Crexi searches per primary town; Jersey Digs +
  RE-NJ + Village Green + TAPinto sweeps; broker announcement search; top-10
  town planning agendas.
- **Bi-weekly:** secondary-market planning agendas; LinkedIn growth-hire scan.
- **Monthly:** deed/mortgage sweep on watched properties (tax records +
  register); PM roster refresh; low-volume towns (Glen Ridge, Essex Fells,
  North Caldwell, Fairfield, Summit).

## Gaps / sources to add

- CoStar or PropertyShark authorization would unlock ownership + debt data.
- County legal-notice aggregator (njpublicnotices.com — verify) for hearing
  notices naming applicants.
- MLS access via a broker relationship for small-multifamily photo review
  (dated-kitchen confirmation).
