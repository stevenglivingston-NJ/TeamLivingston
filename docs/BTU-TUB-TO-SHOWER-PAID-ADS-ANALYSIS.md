# BTU Tub-to-Shower Conversion — Competitive Analysis & Landing Page Optimization

**Date:** 2026-07-30 · **Scope:** Tub-to-shower conversion for Bath Tune-Up Bloomfield (Google Ads acct 4477036900, HL location `0uWA8M5BzHrrcJftuaDe`)
**Data sources:** Meta Ad Library (live active US ads, 2026-07-30), live page fetch of `bathtuneupbloomfield.com/tubtoshowerconversions` and the site sitemap, Bath Tune-Up corporate stylesheet (`bathtuneup.com/dist/sites/btu/css/styles.css`), NJ market pricing research, BBB business profile

> ## ⚠️ Read this before acting on the numbers
> This analysis is **deliberately missing two things the KTU refacing analysis had**, because the data was not reachable this session. I have not estimated around the gaps.
>
> | Missing | Why | What to do |
> |---|---|---|
> | **BTU account performance** (spend, clicks, conversions, Quality Score, search-term bleed) | The custom `google-ads` MCP server registered at bootstrap but exposes no tools in this session, and the `Zapier` connector requires re-authorization | Re-run §4's queries once authorized — see §4 for the exact GAQL |
> | **Geo-scoped keyword volumes** (Essex County / NJ / US) | No Semrush connector (requires authorization) and no Keyword Planner access | Re-run §3's Keyword Planner pull before any budget decision |
>
> Everything below this box is observed, not inferred. **The landing-page rebuild does not depend on the missing data** — the page defects are verified directly against the live HTML, and the competitive message analysis comes from live ad creative. Budget and bid decisions *do* depend on it, so §6 marks those recommendations as blocked.

---

## 1. The headline finding

Bath Tune-Up Bloomfield is selling a **$12,000–$25,000+** tub-to-shower conversion into a paid market where the loudest competitors advertise **"50% Off Installation"** and **"1-Day Walk-In Showers"**, and where independent NJ pricing research puts the typical tub-to-shower quote at **$6,000–$15,000**.

That is not a pricing mistake — a full tear-out conversion genuinely is a different product than an acrylic liner dropped over the old surfaces. But it is a **positioning gap that the current page does nothing to close.** The live page states its price range honestly and then never explains why it is roughly double the number a shopper just saw in a Facebook ad. A homeowner comparing tabs has no reason on the page to conclude the difference is scope rather than markup.

The second finding is larger in upside: **the dominant emotional hook in this entire category is senior safety and aging-in-place**, and the live page mentions mobility exactly once, in a passing clause. Jacuzzi Bath Remodel and Mad City Bath Remodel both run "Seniors Save Thousands" as primary creative. BTU is leaving the category's strongest motivator almost entirely unaddressed.

## 2. Competitor paid landscape (Meta Ad Library, active US ads, 2026-07-30)

A search for `tub to shower conversion` returns **~3,029 active US ads**. The advertiser mix and verbatim messaging:

| Competitor | Presence in results | Their ad message (verbatim) |
|---|---|---|
| **Jacuzzi Bath Remodel** | Dominant — 17 of the first 30 ads, one page ID (738853125986883) | "Save Thousands On A Bath Remodel" · "Save Thousands With **50% Off Install**" · "**50% Off Installation — Seniors Save**" · "**Seniors Save** Thousands On A Bath Remodel" |
| **Premier Home Pros** / **Premier-Home Pros** (two pages) | 5 of first 30 | "Get **50% OFF** A Shower / Tub Remodel For A Limited Time" · "50% OFF Bath/Shower Installation!!!" · "🔥 50% Off Installation- **Limited Time** Homeowners" |
| **ProEdge Remodeling** | 3 of first 30 | "**Here's What a 1-Day Walk-In Shower Should Cost You**" — cost-transparency as the hook |
| **Mad City Bath Remodel** | On the walk-in-shower query | "**Seniors Save** Thousands On A Shower Remodel" |
| **PJ Fitzpatrick** | 20+ ads, **town-by-town creative across NJ** | "Save Thousands On A Bath Remodel In **Rahway** / **Piscataway** / **North Brunswick** / **Asbury Park** / **Marlton** / **West Deptford** / **Absecon** / **Egg Harbor Township**" |
| **Five Star Bath Solutions** | Franchise network | "🚿 Think your bathroom is too small to feel spacious?" — problem-agitation angle |
| **Better Home Services** | 1 | "Need a New Bathroom?" |

**What wins these auctions:** a hard percentage discount, senior/safety targeting, a one-day speed claim, and town-level personalization.

**What attacks BTU directly:** the "$6,000 one-day insert" framing. Every 50%-off and 1-day ad in that table trains the Essex County shopper to expect a single-day job at half BTU's price. BTU's answer has to be on the page, not left to the sales call.

**Notably absent from the paid set:** Bath Fitter, Re-Bath and West Shore Home did not surface in these queries. Worth a targeted check before treating them as non-competitors — absence from two Ad Library queries is weak evidence, not proof.

### 2b. What BTU has that none of them do

Real, defensible, and currently underplayed on the page:
- **400+ completed projects in Essex County** — hyper-local proof a national brand cannot claim.
- **4.9 average rating** (review count unverified — see §5).
- **100% employee-installed, no subcontractors, ever** — the single strongest trust differentiator against the national install-crew model.
- **A named designer (Karen) and a dedicated project manager** — a human, local, uncopyable specific.
- **A rating from the Better Business Bureau.**
- **$0 down, 0% interest for 12 months** — matches competitor financing.
- **Honest published price ranges** — most competitors force a home visit to get a number.

## 3. Keyword economics — NOT AVAILABLE THIS SESSION

Neither Semrush nor Google Keyword Planner was reachable (see the box at the top). **I am not publishing volume estimates I could not measure.** The KTU refacing analysis established the pattern that matters here: national volume is the right lens for reading competitor ad copy and the *wrong* lens for sizing an Essex County campaign, where the same terms ran 200–1,200× smaller. Assume the same order-of-magnitude collapse applies to the tub-to-shower cluster until measured.

**Run this before any budget decision.** Keyword Planner, `geoTargetConstants` scoped to Essex County, then New Jersey, then US, for:

```
tub to shower conversion / tub to shower conversion near me / tub to shower conversion cost
convert tub to shower / tub to shower remodel / walk in shower installation
walk in shower conversion / bathtub to shower conversion / shower conversion near me
walk in shower for seniors / handicap accessible shower / curbless shower
one day bath remodel / bathroom remodel near me / bathroom remodeling essex county
```

Two things to look for specifically:
1. **Whether the safety/senior cluster** (`walk in shower for seniors`, `handicap accessible shower`, `curbless shower`) **carries meaningful local volume.** If it does, Section 5 of the new page becomes the primary landing target and deserves its own ad group. This is the highest-value unknown.
2. **The local size of `bathroom remodel` head terms** versus the tub-to-shower cluster — on the KTU job, the adjacent broader service (`cabinet painting`) turned out to be 7× the local volume of the term the campaign was built around, at a fraction of the CPC. The same may well be true of `bathroom remodel` versus `tub to shower conversion` here.

## 4. BTU account performance — NOT AVAILABLE THIS SESSION

The `google-ads` MCP server registered at bootstrap but exposed no tools; the Zapier passthrough requires re-authorization. **No spend, conversion, Quality Score or search-term data is included here, and none is estimated.**

The KTU refacing campaign's root cause was measurable and specific: Quality Score 2/10 with **landing page experience rated BELOW AVERAGE**, producing a 3–8× effective-CPC penalty. The same diagnostic is the first thing to check here, because the page defects in §5 are exactly the kind that drive that rating down.

Queries to run once authorized (account `4477036900`):

```sql
-- Campaign-level 90-day performance
SELECT campaign.name, campaign.status, metrics.cost_micros, metrics.clicks,
       metrics.impressions, metrics.conversions, metrics.conversions_value
FROM campaign WHERE segments.date DURING LAST_90_DAYS AND metrics.impressions > 0

-- The critical one: Quality Score + landing page experience per keyword
SELECT campaign.name, ad_group_criterion.keyword.text,
       ad_group_criterion.keyword.match_type, metrics.cost_micros, metrics.clicks,
       metrics.conversions, ad_group_criterion.quality_info.quality_score,
       ad_group_criterion.quality_info.post_click_quality_score,
       ad_group_criterion.quality_info.creative_quality_score
FROM keyword_view WHERE segments.date DURING LAST_90_DAYS AND metrics.impressions > 0

-- Search-term bleed (competitor brands, DIY, wrong-service queries)
SELECT search_term_view.search_term, metrics.cost_micros, metrics.clicks, metrics.conversions
FROM search_term_view WHERE segments.date DURING LAST_90_DAYS AND metrics.clicks > 0
```

## 5. Landing page audit — `bathtuneupbloomfield.com/tubtoshowerconversions`

Verified directly against the fetched HTML. This page is **materially better than KTU's refacing page was** — the hero form is above the fold, prices are published, the rating and project count are prominent, and financing is stated. The defects are narrower and mostly additive.

**Working:** dedicated tub-to-shower page (not the homepage); hero lead form with Full Name / Phone / Email / ZIP; honest per-service price ranges ($12k–$25k+ conversions, $8k–$15k+ shower remodel, $30k–$65k+ full bath); "days, not weeks" timeline; $0 down / 0% for 12 months; "400+ Projects completed"; 4.9 rating displayed; "100% Employee Installed / No subcontractors, ever"; before/after imagery; Karen the lead designer; "Our Promise to You" five points; Essex County town list; correct ZIP (07003) on this page; title tag a tidy 54 characters.

**Broken / missing (in priority order):**
1. **No structured data whatsoever** — zero `application/ld+json`, no LocalBusiness, no AggregateRating, no FAQPage. The page claims a 4.9 rating that Google cannot read, so it can never render as SERP stars. Highest-ratio fix on the list.
2. **No answer to the price objection.** Prices are published but unjustified against a market advertising 50% off and $6k inserts. The single biggest conversion leak.
3. **Aging-in-place is nearly absent** — one clause ("stylish, low-threshold designs perfect for any age or mobility level") and one word ("accessible") against a competitor set whose primary creative is "Seniors Save Thousands."
4. **Two different phone numbers** — (973) 798-9756 (11 instances) and (973) 521-0688 (4 instances). Splits call tracking and erodes trust. Same defect found on the KTU page.
5. **No warranty or guarantee language anywhere** — verified zero matches for warranty / guarantee / insured / licensed / background-checked. "Our Promise to You" is five soft process values, not a commitment you could hold them to.
6. **The 4-step process section has headings but no described steps** — the identical defect found on KTU's refacing page, on a paid landing page again.
7. **No FAQ section** — no on-page answers for cost, timeline, accessibility, or the resale question.
8. **Only one testimonial** (Tina), and the 4.9 rating carries **no review count**, while competitors publish counts.
9. **Contradictory timeline claims.** The H1 promises "Days, Not Weeks"; the body says conversions are "often completed in as little as one day"; the shower-remodel block says "Some projects completed in hours!" The "hours" claim is a credibility risk and it also undercuts the premium positioning the price range needs.
10. **Stale seasonal urgency** — "Limited Spring/Summer Project Slots Remaining" still live on July 30.
11. **Meta description contains a ★ glyph and an em-dash** and runs 151 characters — the glyph is unreliable in SERP rendering.
12. **Before/after images have no captions** (no town, timeline or scope), muting their proof value.
13. **Homepage footer ZIP is 07028** (Glen Ridge) against 07003 on this page, the GBP and the BBB record — a NAP inconsistency across the same site. Same error class as KTU's.
14. **Off-brand typography** — the site loads Montserrat, Lato and Roboto (HighLevel defaults); Bath Tune-Up corporate is Nunito Sans throughout.
15. **No internal link to this page from the homepage** — the sitemap lists `/tubtoshowerconversions`, but no homepage link to it was found, so it has no internal-link equity for organic.

## 6. Recommendations

**Ready to act on now (page-side, no missing data):**
1. **Rebuild the landing page** with the HighLevel AI builder prompt in [`HL-AI-BUILDER-PROMPT-TUB-TO-SHOWER.md`](./HL-AI-BUILDER-PROMPT-TUB-TO-SHOWER.md). Fixes defects 1–12 and 14 in one pass.
2. **Unify to (973) 798-9756** everywhere and retire (973) 521-0688 from paid pages.
3. **Add the safety/aging-in-place section** as a first-class band, not a clause. Highest-upside single addition on the page.
4. **Add LocalBusiness + AggregateRating + FAQPage JSON-LD** with the real review count.
5. **Confirm and publish the real Google review count**, or drop the count and show the rating alone. Do not ship a fabricated number.
6. **Drop "Some projects completed in hours!"** and standardize on "days, not weeks" everywhere.
7. **Fix the homepage footer ZIP** 07028 → 07003, and **link the homepage to `/tubtoshowerconversions`**.
8. **Replace the Spring/Summer scarcity line** with a season-neutral one, and set a reminder to review seasonal copy quarterly.

**Blocked on the data in §3–§4 — do not decide these until the queries run:**
9. **Any budget or bid change.** No spend, CPL, Quality Score or geo data was available; there is no defensible basis for a budget recommendation in this document. In particular, do not raise spend on the assumption that Essex County holds national-scale tub-to-shower demand — on the KTU job that assumption was off by two orders of magnitude.
10. **Whether the safety/senior cluster earns its own ad group** — decide on the §3 volume pull.
11. **Negative-keyword and search-term cleanup** — needs the `search_term_view` query.

**Worth testing once the page is live:**
12. **Town-level RSA variants** mirroring PJ Fitzpatrick's pattern ("Tub-to-Shower Conversions in Montclair / Glen Ridge / West Orange"), pointed at the rebuilt page.
13. **Lead with the differentiator the nationals cannot match** in RSA copy: employee installers, 400+ local projects, a named designer — not a discount BTU does not offer.

*(Per operating rules: recommendations only — campaign changes need human approval.)*

## 7. Copy-paste prompt for BTU's HighLevel AI page builder

The full prompt is maintained in [`HL-AI-BUILDER-PROMPT-TUB-TO-SHOWER.md`](./HL-AI-BUILDER-PROMPT-TUB-TO-SHOWER.md) — copy the entire fenced block from that file into the HighLevel AI builder for the BTU location (`0uWA8M5BzHrrcJftuaDe`).

## 8. Brand reference (extracted 2026-07-30)

From the Bath Tune-Up corporate stylesheet, for reuse on any future BTU page:

| Role | Value |
|---|---|
| Primary brand blue | `#016188` |
| Bright / secondary blues | `#087dc7`, `#0082b9`, `#009ef4` |
| Button border blue | `#00609c` |
| Accent + all hover states | `#DE9312` (gold) |
| Body & heading text | `#292929` (271 uses — dominant), `#494949` secondary |
| Warm grays | `#747874`, `#837974` |
| Section backgrounds | `#FFFFFF`, `#F3F8FB` (pale blue), `#F1F2F2` (light gray) |
| Callout / table header | `#CDE0EC` |
| Typography | **"Nunito Sans", sans-serif for everything** — headings *and* body (313 declarations; no serif display face, unlike KTU) |
| Button shadow | `0 3px 6px rgba(0,0,0,.16)` / `0 1px 9px rgba(0,0,0,.16)` |
| Do not use | `#188BF6`, `#155EEF` (HighLevel builder defaults, not brand); Montserrat / Lato / Roboto |
