---
name: competitor-watch
description: >-
  Competitor Watch — weekly competitive scan for Earthwise/Jatalia on Amazon and Walmart.
  Finds who is gaining on us or beating us (rank, price, reviews, ads, content, new
  launches) in our categories: alternative lawn seed (clover, microclover, no-mow fescue,
  pet-safe lawn), native wildflower mixes, creeping thyme, and seed tackifier. Reports the
  few things we should copy, counter or exploit, with dollars where possible. Use weekly
  (Monday) and before a pricing, listing or ad-budget change on a category.
model: inherit
---

# Competitor Watch

One weekly post in the competitor channel (the Slack channel id goes in
`mcp-servers/jatalia/data/sku_guard_rules.json` → `slack.competitor_channel_id`; until it
exists, write the report to the run directory and post nothing). It is short: what changed,
who is winning where we aren't, and what to do about it.

## Session rules

Same as `jatalia-standup.md`:
- No repo writes. Scratch files go in `/tmp/competitor-watch/run-<timestamp>/`.
- No `rm`.
- Connectors only: **Helium10** and **BTU Zapier connection** (Slack). Reuse the Helium 10
  `session_id` and make its calls one at a time.

## Our catalog to defend

Our ASINs come from `list_my_products` (seller `A233HPBAC68WSK`, marketplace `US`). Top
earners as of 2026-10:
- Low Grow No Mow 1 lb and 5 lb (B0FCSPZGNM, B0FCSMFCFK)
- PetLawn ½, 1 and 5 lb (B0FCSL1K4D, B0FGCJR2XS, B0FGCSRHXQ)
- EcoSeed 1 and 5 lb (B0FGCYVRXY, B0FK54CTQJ)
- Microclover ½ and 1 lb (B0FCPH1ZZ8, B0FG2WK7B2)
- Tri-Clover (B0FG34MTCY, B0FGJDXXRW)
- Seed-Tac (B0FCPMLQCD, B0FHJ31TQP)
- Thyme for a Change (B0FCMH9Z9Q, B0FGJJMM35)
- Shady and native wildflower mixes

## The scan

1. **Who we compete with.** For each top ASIN, run `search_competitors_by_asin` and
   `get_keywords_by_asin` to get the top 5 competitor ASINs by shared keywords and sales.
   Keep a stable watch list in the report header and add newcomers.
2. **Are they gaining on us?** Compare against last week's report:
   - BSR trend (`get_asin_bsr_history`, 30 days)
   - estimated sales (`get_sales_velocity` / `get_listing_details`)
   - review count and rating velocity (`get_asin_reviews_history`)
   - price moves (`get_asin_price_history`)

   Call it **gaining** when a competitor's sales or BSR trend beats ours over the same 30
   days in a shared keyword set.
3. **Where they win and we don't:**
   - Keywords: high-volume searches where they rank top 10 and we're absent or below
     page 1 (`compare_asin_keywords`, `get_keyword_performance_with_competitors`).
   - Ads: their sponsored share on those terms; product-target ads on our listings
     (`search_product_targets_by_asin`).
   - Content: title, image count, A+, video and listing score (`compare_listings`,
     `get_listing_score`).
   - Offer: price per lb or per sq ft against ours, coupons, Subscribe & Save, bundles,
     pack sizes we don't offer.
   - Walmart: the same terms via `analyze_walmart_keywords` and
     `search_competitors_by_item_id`.
4. **Launches and threats:**
   - New ASINs in our niches (`search_products` with category and keyword filters,
     launched in the last 60 days).
   - Hijackers or extra sellers on our ASINs (`get_buybox_summary`).
   - Review attacks: a sudden fall in rating on our ASINs.

## The post (≤20 lines; details in the thread)

```
:mag: *Competitor Watch — week of <date>*
*Gaining on us:* <competitor> on <term/category> — <metric delta> (n lines max 3)
*Winning where we aren't:* <term/size/feature> — <who>, est. $/mo at stake (max 3)
*Do this week:* 1) … 2) … 3) …  (owner: Vinay / Steven / eZdia)
*Watch list:* <n> competitors · <n> new launches · Buy Box: <ok / issue>
_Details in thread 🧵_
```

Recommendations must be things we can act on: a keyword to add with a bid cap, a pack size
or bundle to launch, a price or coupon move that stays above the 25% floor (check with
`sku_guard.py`), a content fix, or a Sponsored Display or retargeting test. Never suggest a
move that takes a SKU below break-even.
