#!/usr/bin/env python3
"""Jatalia portfolio price + ad optimizer.

Goal: maximize total profit dollars across Amazon + Walmart SKUs, subject to
  1. no SKU loses money (net after product cost, marketplace fees, shipping,
     refunds, ads and eZdia; Amazon's eZdia flat fee is shared by revenue,
     Walmart's is a channel-level fixed cost - see sku_guard_rules.json), and
  2. the blended portfolio margin after ALL costs (incl. both eZdia flat
     fees) is >= the target (25%, falling back to 20% if 25% is infeasible),
  3. no marketplace price below the Shopify retail price for the same pack,
  4. each price stays within [-15%, +30%] of what customers paid in the
     last 30 days (outside that band the demand model is a guess).
Among options within 1% of the best profit, the higher-revenue one wins.

Demand model per SKU (30-day units q0 at realized price p0, ad spend a0,
ad-attributed share s):
    q(p, k) = q0 * ((1 - s) + s * k**0.6) * (p / p0) ** -e
where k is the ad-spend multiplier (1, .75, .5, .25, 0) - ad-driven units
fall with diminishing returns as spend is cut, and organic units fall by
HALO x the ad units lost (ads hold organic rank). Top sellers keep at least
MIN_AD_K_TOP of their spend. e is price elasticity.
Base e = 1.5 (single-seller branded niche); results are re-scored at
e = 1.0 and 2.5 to show the range.

Solved with a Lagrange multiplier on the margin constraint: each SKU
independently maximizes (1+lam)*profit - lam*T*revenue over its price x
ad grid; lam is bisected until the portfolio margin clears T.
"""
import argparse, csv, json, math, os, re

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")

AD_K = (1.0, 0.75, 0.5, 0.25, 0.0)
AD_CURVE = 0.6
HALO = 0.5          # organic units lost per ad-attributed unit lost (ads lift rank)
MIN_AD_K_TOP = 0.5  # top sellers (>= TOP_UNITS/30d) keep at least half their ad spend
TOP_UNITS = 40
FBM_SHIP = ((0.5, 6.60), (1, 8.40), (2, 10.80), (5, 15.60), (10, 21.60), (25, 33.60), (1e9, 54.00))
WFS_FEE = ((0.5, 4.09), (1, 5.22), (5, 8.15), (1e9, 16.71))
FBA_SERVICES = 0.70
REFERRAL = 0.15
EZ_SHARE = 0.0325
EZ_FLAT = {"amazon": 2500.0, "walmart": 1750.0}
BAND = (0.85, 1.30)
MIN_UNITS = 3


def size_lb(name):
    n = (name or "").lower().replace("½", "1/2").replace("¼", "1/4")
    m = re.search(r"(\d+(?:\.\d+)?|\d+/\d+)\s*(lb|lbs|oz)\b", n)
    if not m:
        return 1.0
    q, unit = m.group(1), m.group(2)
    v = (int(q.split("/")[0]) / int(q.split("/")[1])) if "/" in q else float(q)
    return v / 16 if unit == "oz" else v


def tier(lb, table):
    for cap, v in table:
        if lb <= cap:
            return v
    return table[-1][1]


def end95(x):
    return math.floor(x) + 0.95 if x - math.floor(x) <= 0.95 else math.floor(x) + 1.95


def load(p):
    with open(p) as f:
        return json.load(f)


def rows_of(o):
    d = o.get("data", o) if isinstance(o, dict) else o
    return d.get("rows", d) if isinstance(d, dict) else d


def inventory_modes(path):
    """sku -> 'FBA' | 'FBM' from Helium 10 get_inventory_values (the current state)."""
    if not path:
        return {}
    with open(path) as f:
        obj = json.load(f)
    d = obj.get("data", obj)
    rows = d.get("rows", []) if isinstance(d, dict) else d
    return {r["sku"]: (r.get("fulfillment_type") or "").upper() for r in rows if r.get("sku")}


def build_items(args):
    inv_mode = inventory_modes(getattr(args, "amazon_inv", None))
    cost, ew_of, cost_ew = {}, {}, {}
    with open(os.path.join(DATA, "amazon_cogs.csv")) as f:
        for r in csv.DictReader(f):
            try:
                c = float(r["PRODUCT COST"] or 0)
            except ValueError:
                continue
            if c > 0:
                cost[r["SKU"].strip()] = c
                ew = (r.get("SHOPIFY_SKU") or "").strip()
                if ew:
                    ew_of[r["SKU"].strip()] = ew
                    cost_ew.setdefault(ew, c)
    shop = {}
    for p in load(args.shopify).get("products", []):
        for v in p.get("variants", []):
            if v.get("sku"):
                shop[v["sku"].strip()] = float(v["price"])
    adshare = load(args.adshare) if args.adshare else {}

    items, skipped = [], []
    for channel, path in (("amazon", args.amazon), ("walmart", args.walmart)):
        if not path:
            continue
        for r in rows_of(load(path)):
            m = r["metrics"]
            sku, name = r.get("sku"), r.get("product_name") or ""
            q0, sales = m.get("units_sold") or 0, m.get("sales") or 0
            a0 = -(m.get("advertising_cost") or 0)
            pc = cost.get(sku) or cost_ew.get(sku)
            if q0 < MIN_UNITS or not pc:
                if q0 or a0:
                    skipped.append(dict(channel=channel, sku=sku, units=q0, ad_spend=round(a0, 2),
                                        why="no cost on file" if not pc else f"<{MIN_UNITS} units"))
                continue
            p0 = sales / q0
            ref = min(-(m.get("refund") or 0) / sales, 0.10) if q0 >= 10 else 0.03
            lb = size_lb(name)
            if channel == "amazon":
                fees_u = -(m.get("amazon_fees") or 0) / q0
                fixed_fee = max(fees_u - REFERRAL * p0, 0)
                cur = inv_mode.get(sku)  # live inventory beats the fee heuristic
                fba = (cur == "FBA") if cur else fixed_fee > 2
                fulfil = fixed_fee + FBA_SERVICES if fba else tier(lb, FBM_SHIP)
                mode = "FBA" if fba else "FBM"
            else:
                wfs = (r.get("fulfillment_type") or "").upper() == "WFS"
                fulfil = tier(lb, WFS_FEE) if wfs else tier(lb, FBM_SHIP)
                mode = "WFS" if wfs else "Seller"
            s = adshare.get(r.get("asin") or "", None)
            if s is None:
                s = min(0.6, 1.1 * (a0 / sales)) if sales else 0.0
            items.append(dict(channel=channel, sku=sku, asin=r.get("asin"), name=name[:48], mode=mode,
                              p0=p0, q0=q0, a0=a0, s=s, ref=ref, fixed=pc + fulfil, cost=pc,
                              shop=shop.get(ew_of.get(sku, sku))))
    return items, skipped


def units(it, p, k, e):
    ad_lost = it["s"] * (1 - k ** AD_CURVE)
    base = max(1 - ad_lost - HALO * ad_lost, 0.05)
    return it["q0"] * base * (p / it["p0"]) ** -e


def options(it, e, flat_share):
    """All feasible (price, ad multiplier) choices for one SKU."""
    lo = it["p0"] * BAND[0]
    if it["shop"]:
        lo = max(lo, it["shop"])
    hi = max(it["p0"] * BAND[1], lo)
    pct = REFERRAL + it["ref"] + EZ_SHARE
    grid, p = [], lo
    while p <= hi + 1e-9:
        grid.append(round(p, 2))
        p += 0.50
    grid.append(round(hi, 2))
    out = []
    for p in grid:
        for k in AD_K:
            if it["q0"] >= TOP_UNITS and it["a0"] > 0 and k < MIN_AD_K_TOP:
                continue
            q = units(it, p, k, e)
            a = it["a0"] * k
            rev = q * p
            prof = q * (p * (1 - pct) - it["fixed"]) - a
            sku_net = prof - flat_share * rev          # what the SKU itself must clear
            if sku_net < 0:
                continue
            out.append((p, k, q, rev, prof))
    return out


def solve(items, e, target, flat_share, mu=0.0):
    opts = [options(it, e, flat_share[it["channel"]]) for it in items]
    flat = sum(EZ_FLAT.values())

    def pick(lam):
        chosen = []
        for it, op in zip(items, opts):
            if not op:
                chosen.append(None)
                continue
            score = lambda o: (1 + lam) * o[4] - lam * target * o[3] + mu * o[3]
            best = max(score(o) for o in op)
            near = [o for o in op if score(o) >= best - abs(best) * 0.01]
            chosen.append(max(near, key=lambda o: o[3]))
        rev = sum(c[3] for c in chosen if c)
        prof = sum(c[4] for c in chosen if c) - flat
        return chosen, rev, prof

    lo, hi = 0.0, 50.0
    chosen, rev, prof = pick(0.0)
    if rev and prof / rev >= target:
        return chosen, rev, prof, 0.0
    c_hi, r_hi, p_hi = pick(hi)
    if not r_hi or p_hi / r_hi < target:
        return c_hi, r_hi, p_hi, None  # infeasible at this target
    for _ in range(40):
        mid = (lo + hi) / 2
        c, r, p = pick(mid)
        if r and p / r >= target:
            hi, chosen, rev, prof = mid, c, r, p
        else:
            lo = mid
    return chosen, rev, prof, hi


def rescore(items, chosen, e):
    rev = prof = 0.0
    for it, c in zip(items, chosen):
        if not c:
            continue
        p, k = c[0], c[1]
        q = units(it, p, k, e)
        pct = REFERRAL + it["ref"] + EZ_SHARE
        rev += q * p
        prof += q * (p * (1 - pct) - it["fixed"]) - it["a0"] * k
    prof -= sum(EZ_FLAT.values())
    return rev, prof


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--amazon", required=True)
    ap.add_argument("--walmart")
    ap.add_argument("--shopify", required=True)
    ap.add_argument("--adshare", help="{asin: ad-attributed unit share}")
    ap.add_argument("--amazon-inv", help="get_inventory_values JSON: current FBA/FBM per SKU")
    ap.add_argument("--elasticity", type=float, default=1.5)
    ap.add_argument("--revenue-weight", type=float, default=None,
                    help="profit-vs-revenue weight mu; default = pick from the frontier")
    ap.add_argument("--frontier", action="store_true")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    items, skipped = build_items(a)
    ch_rev = {ch: sum(i["p0"] * i["q0"] for i in items if i["channel"] == ch) for ch in ("amazon", "walmart")}
    flat_share = {"amazon": EZ_FLAT["amazon"] / (ch_rev["amazon"] or 1), "walmart": 0.0}

    now_rev = sum(i["p0"] * i["q0"] for i in items)
    now_prof = sum(i["q0"] * (i["p0"] * (1 - REFERRAL - i["ref"] - EZ_SHARE) - i["fixed"]) - i["a0"]
                   for i in items) - sum(EZ_FLAT.values())

    # Profit-vs-revenue frontier at the 25% floor (falls back to 20%).
    frontier = []
    for target in (0.25, 0.22, 0.20):
        for mu in (0.0, 0.05, 0.10, 0.20, 0.30):
            c, r, pr, lam = solve(items, a.elasticity, target, flat_share, mu)
            if lam is not None:
                frontier.append(dict(mu=mu, target=target, revenue=round(r), profit=round(pr),
                                     margin=round(pr / r, 3), _c=c, _lam=lam))
    if a.frontier:
        for f in frontier:
            print(f"mu={f['mu']:.2f} target={f['target']:.0%} revenue=${f['revenue']:,} profit=${f['profit']:,} margin={f['margin']:.1%}")
    # Pick: the highest-revenue point that keeps >= 95% of max profit and
    # >= 20% blended margin after eZdia (profit dollars first; revenue only
    # where it costs <5% of profit).
    best_p = max(f["profit"] for f in frontier)
    if a.revenue_weight is not None:
        pick = min(frontier, key=lambda f: abs(f["mu"] - a.revenue_weight))
    else:
        pick = max((f for f in frontier if f["profit"] >= 0.95 * best_p and f["margin"] >= 0.20),
                   key=lambda f: f["revenue"])
    plan = (pick["target"], pick["_c"], pick["revenue"], pick["profit"], pick["_lam"])
    if plan is None:
        plan = (None, chosen, rev, prof, None)
    target, chosen, rev, prof, lam = plan

    rows = []
    for it, c in zip(items, chosen):
        pct = REFERRAL + it["ref"] + EZ_SHARE
        now = it["q0"] * (it["p0"] * (1 - pct) - it["fixed"]) - it["a0"]
        if not c:
            rows.append(dict(channel=it["channel"], sku=it["sku"], name=it["name"], mode=it["mode"],
                             price_now=round(it["p0"], 2), units_now=it["q0"], profit_now=round(now, 2),
                             action="cannot_be_profitable",
                             note="no price within +30% / ad level makes it break even at current cost"))
            continue
        p, k, q, r_, pr = c
        rows.append(dict(channel=it["channel"], sku=it["sku"], asin=it["asin"], name=it["name"], mode=it["mode"],
                         shopify=it["shop"], cost=it["cost"],
                         price_now=round(it["p0"], 2), price_new=end95(p) if abs(p - it["p0"]) > 0.25 else round(it["p0"], 2),
                         price_change=round(p / it["p0"] - 1, 3), ad_spend_now=round(it["a0"], 2),
                         ad_spend_new=round(it["a0"] * k, 2), units_now=it["q0"], units_new=round(q, 1),
                         revenue_now=round(it["p0"] * it["q0"], 2), revenue_new=round(r_, 2),
                         profit_now=round(now, 2), profit_new=round(pr, 2)))
    rows.sort(key=lambda r: (r.get("profit_new", -1e9) - r["profit_now"]), reverse=True)

    sens = {}
    for e in (1.0, a.elasticity, 2.5):
        r_, p_ = rescore(items, chosen, e)
        sens[str(e)] = dict(revenue=round(r_), profit=round(p_), margin=round(p_ / r_, 3) if r_ else None)
    out = dict(target_margin=target, lagrange=lam, elasticity=a.elasticity,
               frontier=[{k: v for k, v in f.items() if not k.startswith("_")} for f in frontier],
               now=dict(revenue=round(now_rev), profit=round(now_prof), margin=round(now_prof / now_rev, 3)),
               plan=dict(revenue=round(rev), profit=round(prof), margin=round(prof / rev, 3) if rev else None),
               sensitivity=sens, ezdia_flat=EZ_FLAT, skus=rows, skipped=skipped)
    with open(a.out, "w") as f:
        json.dump(out, f, indent=1)
    print(json.dumps({k: out[k] for k in ("target_margin", "now", "plan", "sensitivity")}, indent=1))


if __name__ == "__main__":
    main()
