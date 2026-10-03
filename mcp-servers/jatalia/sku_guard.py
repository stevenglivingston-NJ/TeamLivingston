#!/usr/bin/env python3
"""SKU Guard - flags Jatalia SKUs that lose money (or miss the 25% floor) on
Amazon and Walmart, decides the price move, and writes the Slack digest.

Pure computation: no network calls except the public Shopify storefront.
The sku-guard agent (.claude/agents/sku-guard.md) fetches the inputs,
runs this, posts the digest, and applies the Amazon price changes.

Inputs (JSON files written by the agent):
  --amazon   Helium 10 get_product_profit_and_loss_summary (product_level=sku,
             marketplace US, trailing 30 days) - the raw tool result.
  --walmart  Helium 10 get_wmt_product_profit_and_loss_summary (sku, 30d).
  --live     optional {sku: {"price": 26.95, "fba_fee": 5.22, "asin": "..."}}
             from get_product_live_status. Falls back to realized price.
  --recent   optional ["SKU", ...] Amazon SKUs whose price changed in the
             last min_days_between_changes days (read from the Slack log).
  --shopify  optional storefront products.json (else fetched via curl).

Outputs: --out decisions JSON, --slack digest text (Slack mrkdwn).

Unit economics per SKU (per unit sold):
  contribution = price - marketplace fees - refunds - product cost
                 - fulfillment (FBA services / FBM label / WFS estimate)
                 - eZdia (3.25% + channel flat fee spread over revenue)
  net          = contribution - ad spend
Product cost is the same for FBA and FBM; only shipping differs.
"""
import argparse, csv, datetime as dt, json, math, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")


def load(p):
    with open(p) as f:
        return json.load(f)


def rows_of(obj):
    d = obj.get("data", obj) if isinstance(obj, dict) else obj
    return d.get("rows", d) if isinstance(d, dict) else d


def round95(x):
    """Round UP to the next .95 ending."""
    return math.ceil(x - 0.95) + 0.95 if x > 0 else x


def size_lb(name):
    n = (name or "").lower().replace("½", "1/2").replace("¼", "1/4")
    m = re.search(r"(\d+(?:\.\d+)?|\d+/\d+)\s*(lb|lbs|oz)\b", n)
    if not m:
        return None
    q, unit = m.group(1), m.group(2)
    v = (int(q.split("/")[0]) / int(q.split("/")[1])) if "/" in q else float(q)
    return v / 16 if unit == "oz" else v


def wfs_estimate(name, table):
    lb = size_lb(name) or 1
    if lb <= 0.5:
        return table["le_0_5lb"]
    if lb <= 1:
        return table["le_1lb"]
    if lb <= 5:
        return table["le_5lb"]
    return table["gt_5lb"]


def fbm_ship(name, table):
    lb = size_lb(name) or 1
    for cap, key in ((0.5, "le_0_5lb"), (1, "le_1lb"), (2, "le_2lb"), (5, "le_5lb"),
                     (10, "le_10lb"), (25, "le_25lb")):
        if lb <= cap:
            return table[key]
    return table["gt_25lb"]


def shopify_prices(path):
    """EW SKU -> retail price, from the public storefront feed."""
    pages = []
    if path:
        pages = [load(path)]
    else:
        for p in range(1, 5):
            r = subprocess.run(["curl", "-sS", "-f", "--max-time", "30",
                                f"https://earthwiseseed.com/products.json?limit=250&page={p}"],
                               capture_output=True, text=True)
            if r.returncode != 0:
                break
            j = json.loads(r.stdout or "{}")
            if not j.get("products"):
                break
            pages.append(j)
    out = {}
    for j in pages:
        for prod in j.get("products", []):
            for v in prod.get("variants", []):
                if v.get("sku"):
                    out[v["sku"].strip()] = float(v["price"])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--amazon", required=True)
    ap.add_argument("--walmart")
    ap.add_argument("--live")
    ap.add_argument("--amazon-inv", help="get_inventory_values JSON: current FBA/FBM per SKU")
    ap.add_argument("--recent")
    ap.add_argument("--shopify")
    ap.add_argument("--rules", default=os.path.join(DATA, "sku_guard_rules.json"))
    ap.add_argument("--out", required=True)
    ap.add_argument("--slack", required=True, help="shared-channel digest (margins only)")
    ap.add_argument("--slack-private", help="Steven-only digest with dollars and costs")
    a = ap.parse_args()

    R = load(a.rules)
    T, G, C, EZ, FEES = R["targets"], R["reprice_guardrails"], R["cost_basis"], R["ezdia"], R["marketplace_fees"]

    # cost + Shopify SKU per seller SKU; EW SKU -> cost too (Walmart-only SKUs)
    cost, ew_of, cost_ew = {}, {}, {}
    with open(os.path.join(DATA, C["source"])) as f:
        for r in csv.DictReader(f):
            try:
                c = float(r["PRODUCT COST"] or 0)
            except ValueError:
                continue
            if c <= 0:
                continue
            cost[r["SKU"].strip()] = c
            ew = (r.get("SHOPIFY_SKU") or "").strip()
            if ew:
                ew_of[r["SKU"].strip()] = ew
                cost_ew.setdefault(ew, c)

    shop = shopify_prices(a.shopify)
    live = load(a.live) if a.live else {}
    inv_mode = {r["sku"]: (r.get("fulfillment_type") or "").upper()
                for r in rows_of(load(a.amazon_inv))} if a.amazon_inv else {}
    recent = set(load(a.recent)) if a.recent else set()

    def product_cost(sku):
        return cost.get(sku) or cost_ew.get(sku)

    def shop_price(sku):
        return shop.get(ew_of.get(sku, sku))

    decisions = []

    def evaluate(channel, r):
        m = r["metrics"]
        sku = r.get("sku")
        name = (r.get("product_name") or "")[:60]
        units = m.get("units_sold") or 0
        sales = m.get("sales") or 0
        ads = -(m.get("advertising_cost") or 0)
        refunds = -(m.get("refund") or 0)
        d = dict(channel=channel, sku=sku, name=name, units=units, ad_spend=round(ads, 2),
                 asin=r.get("asin"), item_id=r.get("item_id"))
        pc = product_cost(sku)
        if pc is None:
            d.update(status="NO_COST", severity="amber",
                     note="no product cost on file - add it to amazon_cogs.csv")
            if units or ads:
                decisions.append(d)
            return
        if units == 0:
            if ads >= T["zero_sale_spend_alert_usd"]:
                d.update(status="AD_SPEND_NO_SALES", severity="red",
                         note=f"${ads:,.0f} ad spend, 0 units in 30 days")
                decisions.append(d)
            return
        realized = sales / units
        lv = live.get(sku, {})
        price = float(lv.get("price") or realized)
        rev_ch = channel_rev[channel] or 1
        ez_pct = EZ["revenue_share_pct"]
        if EZ.get("flat_fee_in_sku_pricing", {}).get(channel, True):
            ez_pct += EZ["monthly_flat_usd"].get(channel, 0) / rev_ch
        ref_pct = min(refunds / sales, 0.10) if units >= 10 and sales else 0.03

        if channel == "amazon":
            fees_u = -(m.get("amazon_fees") or 0) / units
            fee_pct = FEES["amazon_referral_pct_fallback"]
            fixed_fee = max(fees_u - fee_pct * realized, 0)
            if lv.get("fba_fee") is not None and fixed_fee > 2:
                fixed_fee = float(lv["fba_fee"])
            cur = inv_mode.get(sku)  # live inventory beats the fee heuristic
            fba = (cur == "FBA") if cur else fixed_fee > 2  # FBA SKUs carry a per-unit fee
            if not fba:
                fixed_fee = 0.0  # FBA fees from earlier in the window won't recur
            fulfil = C["fba_services_per_unit"] if fba else \
                C["fbm_shipping_per_unit_override"].get(sku, fbm_ship(name, C["fbm_shipping_by_weight"]))
            mode = "FBA" if fba else "FBM"
        else:
            fee_pct = FEES["walmart_referral_pct"]
            fixed_fee = 0.0
            ft = (r.get("fulfillment_type") or "").upper()
            if ft == "WFS":
                fulfil, mode = wfs_estimate(name, C["walmart_wfs_fee_estimate"]), "WFS"
            else:
                fulfil, mode = C["fbm_shipping_per_unit_override"].get(sku, fbm_ship(name, C["fbm_shipping_by_weight"])), "Seller"

        pct_costs = fee_pct + ref_pct + ez_pct
        fixed = pc + fixed_fee + fulfil
        ads_u = ads / units
        contrib_u = price * (1 - pct_costs) - fixed
        net_u = contrib_u - ads_u
        net_m = net_u / price
        allow = T["ad_allowance_pct_of_sales"]
        denom = 1 - pct_costs - allow - T["min_net_margin"]
        req = fixed / denom if denom > 0.05 else float("inf")
        breakeven = fixed / (1 - pct_costs) if pct_costs < 1 else float("inf")
        sp = shop_price(sku)
        d.update(mode=mode, price=round(price, 2), shopify=sp, cost=pc,
                 fees_u=round(fee_pct * price + fixed_fee, 2), fulfil_u=round(fulfil, 2),
                 ezdia_u=round(ez_pct * price, 2), refunds_u=round(ref_pct * price, 2),
                 ads_u=round(ads_u, 2), contrib_u=round(contrib_u, 2), net_u=round(net_u, 2),
                 net_margin=round(net_m, 3), tacos=round(ads / sales, 3) if sales else None,
                 price_for_target=round(req, 2) if req != float("inf") else None,
                 breakeven_price=round(breakeven, 2) if breakeven != float("inf") else None,
                 # Paid: ad sales $ per ad $ needed. Break-even = ads eat all contribution;
                 # target = ads leave the min net margin. Compare with campaign ROAS.
                 breakeven_roas=round(price / contrib_u, 2) if contrib_u > 0 else None,
                 target_roas=round(price / (contrib_u - T["min_net_margin"] * price), 2)
                 if contrib_u - T["min_net_margin"] * price > 0 else None)

        if units < T["min_units_for_decision"]:
            if net_u < 0:
                why = f"ads ${ads_u:.2f}/unit" if ads_u > max(contrib_u, 0) else "price/cost"
                d.update(status="LOSS_LOW_VOLUME", severity="amber",
                         note=f"{units} units, driver: {why} - too few sales to reprice automatically")
                decisions.append(d)
            return

        # what is wrong
        ad_problem = ads_u > max(contrib_u - T["min_net_margin"] * price, 0) and (ads / sales) > allow
        if contrib_u < 0:
            status, sev = "LOSS_BEFORE_ADS", "red"
        elif net_u < 0:
            status, sev = "ADS_CAUSING_LOSS", "red"
        elif net_m < T["min_net_margin"]:
            status, sev = ("ADS_OVER_ALLOWANCE" if ad_problem else "BELOW_TARGET"), "amber"
        elif sp and price < sp and G["never_below_shopify"]:
            status, sev = "BELOW_SHOPIFY", "amber"
        else:
            return  # healthy
        d.update(status=status, severity=sev)

        # price move: only when price (not ads) is the problem, or below Shopify
        target = max(req, sp or 0) if G["never_below_shopify"] else req
        if status in ("ADS_CAUSING_LOSS", "ADS_OVER_ALLOWANCE") and price >= req and (not sp or price >= sp):
            d["action"] = "cut_ads"
            d["note"] = (f"ads ${ads_u:.2f}/unit ({ads / sales:.0%} of sales) vs "
                         f"{allow:.0%} allowance - price is fine at ${price:.2f}")
        elif req == float("inf") or (sp and req > sp * G["unviable_if_required_over_shopify_x"]):
            d["action"] = "decide"
            d["note"] = (f"needs ${req:,.2f} for {T['min_net_margin']:.0%} - more than "
                         f"{G['unviable_if_required_over_shopify_x']:.0f}x Shopify. Cost or ads must change.")
        elif target > price + 0.01:
            step = min(target, price * (1 + G["max_step_pct"]))
            newp = round95(step)
            d["new_price"] = newp
            d["full_target"] = round95(target)
            d["action"] = "reprice"
            if channel == "amazon" and sku in recent:
                d["action"] = "reprice_hold"
                d["note"] = "price changed within the last 7 days - holding"
            elif channel != "amazon" or R["mode"]["amazon_reprice"] != "live":
                d["action"] = "reprice_proposed"
        else:
            d["action"] = "cut_ads" if ad_problem else "review"
        decisions.append(d)

    amz_rows = rows_of(load(a.amazon))
    wmt_rows = rows_of(load(a.walmart)) if a.walmart else []
    channel_rev = {"amazon": sum((r["metrics"].get("sales") or 0) for r in amz_rows),
                   "walmart": sum((r["metrics"].get("sales") or 0) for r in wmt_rows)}
    for r in amz_rows:
        evaluate("amazon", r)
    for r in wmt_rows:
        evaluate("walmart", r)

    channel_alerts = []
    for ch, rev in channel_rev.items():
        flat = EZ["monthly_flat_usd"].get(ch, 0)
        if rev and flat / rev > EZ.get("channel_alert_if_flat_over_pct", 1):
            channel_alerts.append(dict(channel=ch, revenue_30d=round(rev, 2), flat=flat, pct=round(flat / rev, 3),
                                       breakeven_revenue=round(flat / 0.08, 0)))

    order = {"red": 0, "amber": 1}
    decisions.sort(key=lambda d: (order.get(d.get("severity"), 2), d.get("net_u", 0) * (d.get("units") or 0)))
    out = dict(run_at=dt.datetime.utcnow().isoformat(timespec="seconds") + "Z",
               channel_revenue_30d={k: round(v, 2) for k, v in channel_rev.items()},
               ezdia_pct={ch: round(EZ["revenue_share_pct"] + EZ["monthly_flat_usd"].get(ch, 0) / (v or 1), 3)
                          for ch, v in channel_rev.items()},
               mode=R["mode"], channel_alerts=channel_alerts, decisions=decisions)
    with open(a.out, "w") as f:
        json.dump(out, f, indent=1)
    with open(a.slack, "w") as f:  # shared channel: margins only
        f.write(slack_digest(out, R, private=False))
    if a.slack_private:  # Steven's DM: dollars, costs, eZdia, disputes
        with open(a.slack_private, "w") as f:
            f.write(slack_digest(out, R, private=True))
    print(f"{len(decisions)} flagged SKUs -> {a.out}", file=sys.stderr)


def shared_note(note):
    """Strip unit costs and dollar profit from a note for the shared channel."""
    note = re.sub(r"ads \$[\d.,]+/unit \((\d+%) of sales\)", r"ads \1 of sales", note)
    note = re.sub(r"\$[\d.,]+/unit", "", note).replace("  ", " ")
    note = note.replace("no product cost on file - add it to amazon_cogs.csv", "cost missing (Steven)")
    return note


def fmt(d, private=True):
    ch = "AMZ" if d["channel"] == "amazon" else "WMT"
    from approval_post import short  # local import: approval_post is standalone
    head = f"*{short(d['name'])}*  ·  {ch}  ·  `{d['sku']}`"
    bits = []
    if d.get("net_u") is not None:
        bits.append(f"net *${d['net_u']:+.2f}/unit ({d['net_margin']:+.0%})*" if private
                    else f"margin *{d['net_margin']:+.0%}*".replace("-", "−"))
        bits.append(f"{d['units']} sold")
    act = d.get("action")
    if act == "reprice":
        bits.append(f"price ${d['price']:.2f} → *${d['new_price']:.2f}* (target ${d['full_target']:.2f})")
    elif act == "reprice_proposed":
        bits.append(f"proposed ${d['price']:.2f} → *${d['new_price']:.2f}* (target ${d['full_target']:.2f})")
    elif act == "reprice_hold":
        bits.append(f"hold (changed <7d ago), next ${d['new_price']:.2f}")
    if d.get("note"):
        bits.append("_" + (d["note"] if private else shared_note(d["note"])) + "_")
    return "• " + head + "\n     " + "  ·  ".join(bits)


def slack_digest(out, R, private=True):
    """private=True: Steven's DM (dollars, costs, eZdia, disputes). False: the shared channel."""
    D = out["decisions"]
    today = out["run_at"][:10]
    g = lambda pred: [d for d in D if pred(d)]
    loss = g(lambda d: d.get("status") == "LOSS_BEFORE_ADS")
    adsloss = g(lambda d: d.get("status") in ("ADS_CAUSING_LOSS", "AD_SPEND_NO_SALES"))
    below = g(lambda d: d.get("status") in ("BELOW_TARGET", "ADS_OVER_ALLOWANCE", "BELOW_SHOPIFY"))
    other = g(lambda d: d.get("status") in ("LOSS_LOW_VOLUME", "NO_COST"))
    changed = g(lambda d: d.get("action") == "reprice")
    proposed = g(lambda d: d.get("action") == "reprice_proposed")
    rev = out["channel_revenue_30d"]
    if private:
        lines = [f":rotating_light: *SKU Guard — {today}* (trailing 30 days, Amazon ${rev['amazon']:,.0f} · Walmart ${rev['walmart']:,.0f})",
                 f"Floor: {R['targets']['min_net_margin']:.0%} net after product cost, fees, shipping, eZdia "
                 f"(AMZ {out['ezdia_pct']['amazon']:.1%} · WMT {out['ezdia_pct']['walmart']:.1%} of sales), refunds and ads."]
    else:
        lines = [f":rotating_light: *SKU profit check — {today}*  ·  last 30 days",
                 f"_Floor: {R['targets']['min_net_margin']:.0%} margin after all costs. Margins only — no costs here._"]

    def sect(title, items, cap=12):
        if not items:
            return
        lines.append(f"\n*{title}* ({len(items)})")
        lines.extend(fmt(d, private) for d in items[:cap])
        if len(items) > cap:
            lines.append(f"…and {len(items) - cap} more")

    sect(":red_circle: Losing money before ads", loss)
    sect(":money_with_wings: Ads causing losses", adsloss)
    sect(":large_yellow_circle: Below 25% floor", below)
    sect(":grey_question: Needs a look", other, cap=6)
    if changed:
        lines.append(f"\n:white_check_mark: *Amazon prices raised today:* {len(changed)} (raise-only, max +{R['reprice_guardrails']['max_step_pct']:.0%} per step, never below Shopify)")
    if proposed:
        lines.append(f":memo: *Proposed, not applied:* {len(proposed)} ({'Walmart has no pricing API yet' if any(d['channel']=='walmart' for d in proposed) else 'Amazon repricing not live'})")
    for c in (out.get("channel_alerts", []) if private else []):
        lines.append(f"\n:office: *Channel alert — {c['channel'].title()}:* eZdia's ${c['flat']:,.0f}/mo flat fee is "
                     f"{c['pct']:.0%} of 30-day sales (${c['revenue_30d']:,.0f}). No price fixes that; it needs "
                     f"~${c['breakeven_revenue']:,.0f}/mo in sales to get under 8%, or a %-only fee.")
    for x in (R.get("open_invoice_disputes", []) if private else []):
        lines.append(f"\n:warning: *Open invoice dispute* — {x['vendor']} {', '.join(x['invoices'])}: {x['issue']}")
    if len(lines) == 2:
        lines.append("\n:white_check_mark: Every SKU with volume clears the floor.")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
