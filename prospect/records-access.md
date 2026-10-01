# Records Access — deeds, entities and owners

How to turn a lead ("25-unit building sold, buyer undisclosed") into a named
counterparty you can actually call. Every source below was tested on
**2026-09-12**; status notes say what worked and what did not.

Companion to `source-registry.md` (which lists *where news comes from*). This
file is about **primary records** — the deed index, the business registry, and
the assessor.

---

## 1. The enrichment cascade

Run these in order. Most leads resolve at step 3; step 4 costs $6.25 and is
worth it only for a lead you intend to pitch.

| # | Question | Source | Cost | Yields |
|---|---|---|---|---|
| 1 | What's the block & lot? | Municipal property portal / listing sites | free | block, lot, class, year built |
| 2 | Who actually bought it, and when? | **Essex PRESS** deed index | free | grantor, grantee, instrument #, recording date, block/lot |
| 3 | What is that LLC? | **NJ DORES** name search (`tools/nj_dores.py`) | free | entity ID, registered city, type, **formation date** |
| 4 | Where do I send mail? | NJ DORES **Status Report** | $5.00 + $1.25 | registered agent + registered office address |
| 5 | Who else do they own? | PRESS **By Name**, county-wide | free | full local portfolio, lenders, co-borrowers |

**Step 5 is the one people skip and it is the most valuable.** A By Name search
on the buying entity returns every recorded document it touches — which reveals
the rest of the portfolio, the lender, and (on mortgages) the individual
principals who signed as guarantors.

### Two scoring signals this cascade produces

- **SPE formation date within ~90 days of the purchase** → this is an
  acquisition vehicle, not a legacy holding. The CapEx decision is live now.
  (Observed: `25 WATSESSING REALTY LLC` formed 2026-01-05; `EAST CENTRE REALTY
  LLC` formed 2025-12-16; `JUSTIN SQUARE LLC` formed 2025-12-19.)
- **Multiple sibling LLCs sharing one registered city** → one sponsor behind
  several buildings. Promote to Tier 2 (portfolio) and pitch the Unit-Turn
  Program, not a single-building job.

---

## 2. Essex County — PRESS (the deed index)

**The one that matters. Free, no login, no registration.**

- Landing page: <https://press.essexregister.com/prodpress/index.aspx>
- **Go straight here instead:**
  <https://press.essexregister.com/prodpress/clerk/ClerkHome.aspx?op=basic>
- Coverage: **1 May 2001 → present**. Older records are in the Public Vault at
  the Hall of Records (in person only).

### Four search modes

| Mode | Use it when | Notes |
|---|---|---|
| **By Document Type** | You know the town and roughly when it recorded | Municipality + doc type + date range. The workhorse. |
| **By Name** | You have an entity or person | Portfolio mapping. Leave the date range wide (2001→today). |
| **By Block and Lot** | You have the parcel | Most precise; get block/lot from step 1 first. |
| **By Instrument Number** | You have the instrument # | Direct hit. |

Document types include DEED, MORTGAGE, NOTICE OF SETTLEMENT, ASSIGNMENT OF
MORTGAGE, LIS PENDENS FORECLOSURE, CANCELLATION OF MORTGAGE, UCC filings.

**NOTICE OF SETTLEMENT is underrated** — it is filed *before* closing and names
the buyer, seller and lender. It is an early-warning signal: a Notice of
Settlement with no matching deed yet means a deal is in progress right now.

### Gotchas (all hit during testing)

- Results cap at **"more than 100 records"** with no pagination past the first
  page — narrow the date range rather than raising the per-page count.
- Date format is **mm/dd/yyyy**.
- A deed row appears **once per grantor × grantee pair**, so a sale with 2
  sellers and 4 buyers produces 8 identical-looking rows. Deduplicate on
  instrument number.
- **Press coverage dates lag recording dates by weeks.** 47 Union St was
  reported by RE-NJ on 2026-01-30 but recorded 2026-01-09. Always search a
  window that starts ~30 days *before* the press date.
- The in-app browser sometimes renders the results page as empty on the first
  `read_page`; wait 3–5s and re-read. Navigating back to the `ClerkHome.aspx`
  URL directly is more reliable than clicking the tab links.
- **Document images are in-office only, not on the web.** The index is fully
  online; the scanned deed is not. Consideration (sale price) therefore has to
  come from the press or the assessor, not from PRESS.

### Free monitoring

**Record Alert** — <https://www.landex.com/recordalert/essex> — free email
notification when a document records against a named party or block/lot. Worth
arming on every Tier-1 lead and every relationship target: it turns the weekly
scan into a push alert for the properties we care about most.

---

## 3. NJ business registry (DORES)

- **Free name search:** <https://www.njportal.com/DOR/BusinessNameSearch>
  Returns business name, entity ID, registered city, entity type, formation
  date. Does **not** return the registered agent or members.
- **Scripted:** `prospect/tools/nj_dores.py` (tested 2026-09-12).
  ```
  python3 prospect/tools/nj_dores.py "47 UNION" "28 MORSE" "209 MONTAGUE"
  python3 prospect/tools/nj_dores.py --file entities.txt --json
  ```
  Strip the `LLC`/`Inc` suffix — DORES matches on a name prefix.
- **Status Report — $5.00 + $1.25 online fee:**
  <https://www.njportal.com/dor/businessrecords/> — this is the cheap unlock.
  It returns the **registered agent and registered office address**, which is a
  real mailing address for an otherwise anonymous LLC. Standing certificates
  ($25–$100) are for lawyers; we never need them.
- DORES can also search **by registered agent and by principal name**, which
  works in reverse: one principal → every entity they are named on.

---

## 4. Assessment / parcel data — degraded, know why

**Daniel's Law changed this.** New Jersey now requires redaction of certain
individuals (judges, law enforcement, prosecutors) from published records, and
the statewide aggregators responded by switching owner data off:

- **NJACTB (`njactb.org`) discontinued its Tax List (MOD-IV) and Property Sales
  (SR1A) search on 2023-01-01** and now refers all requests to the 21
  individual counties. *`source-registry.md` previously listed this as a live
  source — it is not.*
- **The publicly distributed MOD-IV extract has `OWNER_NAME` redacted.**
- **njparcels.com** states it no longer provides owner information.

**Consequence:** do not plan to get owner-of-record from a statewide parcel
feed. Owner identity now comes from the **deed index** (step 2), which is
exactly why PRESS matters. Parcel sources are still fine for block/lot, year
built, lot size and class — just not for names.

Still useful for step 1:
- **Montclair Properties Information Portal** — municipal, per-parcel data.
  <https://www.montclairnjusa.org/Government/Departments/Building-Office/Montclair-Properties-Information-Portal>
- **NJOGIS Open Data** — parcel + MOD-IV composite downloads (bulk, no owner
  names). <https://njogis-newjersey.opendata.arcgis.com/>
- **taxrecords-nj.com** — a link directory to county assessor portals. Covers
  Bergen, Hudson, Morris, Union, Passaic-area towns and others — **but not
  Essex.** Verify per county before relying on it.

---

## 5. Office contacts

Business lines from each office's own published pages. Call the Register for
anything the index cannot answer — they are the authority on their own records.

| Office | Phone | Email / search | Address |
|---|---|---|---|
| **Essex County Register of Deeds & Mortgages** | **973-621-4960** | **info@essexregister.com** · [PRESS](https://press.essexregister.com/prodpress/clerk/ClerkHome.aspx?op=basic) | Hall of Records, Room 130, 465 Dr. Martin Luther King Jr. Blvd., Newark NJ 07102 |
| Essex County Clerk | — | <https://www.essexclerk.com/> | Same building |
| **Bergen County Clerk — Land Records** | **201-336-7036** | <https://bclrs.co.bergen.nj.us/landrecords/> | Hackensack |
| **Passaic County Clerk — Land Records** | — | <https://www.passaiccountynj.org/government/passaic-county-clerk/land-records> | Registry Vault open 8:30a–4:15p, arrive by 4:00p |
| **Union County Clerk** | — | <https://clerk.ucnj.org/> | Elizabeth |
| NJ DORES — Business Records Service | — | <https://www.njportal.com/dor/businessrecords/> | Trenton |

Essex record room hours: **8:30 a.m.–4:30 p.m., Mon–Fri** (image viewing
terminals until 4:00 p.m.).

Bergen, Passaic and Union have their own online systems with different
interfaces and, in some cases, registration or subscription for full copies —
**verify each on first use.** Only Essex PRESS has been tested.

---

## 6. Where the line is

These are public records and searching them is exactly what they are for. The
rule that keeps this clean:

- **Entities and business roles: yes.** An LLC that bought an apartment
  building, its registered agent, its registered office, the lender on the
  mortgage, the broker on the deal — all fair, all business.
- **Individuals' private details: no.** Principals' names appear in the index
  (as guarantors on mortgages, as executors, as grantors of their own homes).
  Recording that a named person is the principal behind a commercial LLC is
  fine. Going looking for their home address, personal mobile or family details
  is not, and we do not use people-search or skip-trace services to do it.
- **When an owner has no business web presence, the contact path is the broker
  or the registered agent — not a harder search.** That is a feature: a warm
  broker introduction converts better than a cold letter anyway.
- Never state a sale price, an owner or a deal status from the index without
  the instrument number and recording date to back it, and keep labelling
  everything `verified` / `probable` / `inferred` as the agent spec requires.
