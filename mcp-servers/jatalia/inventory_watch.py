#!/usr/bin/env python3
"""Inventory watch for the Jatalia standup (owners: Mohit and Italia).

Answers three questions from Helium 10 data, with no estimating by hand:

1. Which listings are about to run out?
   - Amazon FBM and Walmart seller-fulfilled listings carry a *listing quantity* that
     Earthwise/eZdia set by hand. When it counts down to 0 the listing goes out of stock
     even though Earthwise still holds the seed. That is the commonest stock-out here.
   - FBA / WFS stock: days of cover at the trailing-30-day sales rate, inbound included.
2. Which SKUs are already out of stock while still selling?
3. Which FBM SKUs should go to FBA (or WFS), and how many units?
   The saving per unit is FBM shipping minus (FBA fee + Earthwise services). It is shown
   twice: at the direct-ship product cost, and at the rate Earthwise currently invoices
   for FBA/WFS stock (2x while invoices #116408 / #116511 are disputed). A SKU is only
   "send now" if it still saves money at the invoiced rate.

Inputs (raw Helium 10 tool output saved as JSON):
  --amazon-inv   get_inventory_values (marketplace US, page_size 1000)
  --walmart-inv  get_wmt_inventory_values (page_size 1000)
  --amazon       get_product_profit_and_loss_summary, 30 days, product_level=sku
  --walmart      get_wmt_product_profit_and_loss_summary, 30 days, sku
  --fba-fees     optional {asin: FBA fulfillment fee per unit} from the SP-API Product
                 Fees estimate (POST /products/fees/v0/items/{asin}/feesEstimate, IsAmazonFulfilled
                 true). Preferred over the fee derived from Helium 10, which lags because
                 FBA fees post at shipment.
Output: --out JSON and --slack text for the standup thread.

Usage:
  python3 inventory_watch.py --amazon-inv ainv.json --walmart-inv winv.json \
      --amazon A30.json --walmart W30.json --out inv.json --slack inv.txt
"""
import argparse, csv, json, math, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sku_guard import DATA, fbm_ship, load, rows_of, wfs_estimate  # noqa: E402
from approval_post import short  # noqa: E402

DEFAULTS = {
    "listing_qty_low_days": 14,
    "listing_qty_critical_units": 5,
    "fba_low_days": 21,
    "fba_critical_days": 10,
    "send_list_min_units_30d": 15,
    "send_cover_days": 45,
    "fba_invoiced_cost_multiplier": 2.0,
}


def product_costs():
    out = {}
    with open(os.path.join(DATA, "amazon_cogs.csv")) as f:
        for r in csv.DictReader(f):
            try:
                out[r["SKU"].strip()] = float(r["PRODUCT COST"])
            except (KeyError, ValueError):
                pass
    return out


def velocity(rows):
    """sku -> (units_30d, sales_30d, amazon_fees_30d)."""
    v = {}
    for r in rows:
        m = r.get("metrics") or {}
        sku = r.get("sku")
        if not sku:
            continue
        u, s, f = v.get(sku, (0, 0.0, 0.0))
        v[sku] = (u + (m.get("units_sold") or 0), s + (m.get("sales") or 0),
                  f + (m.get("amazon_fees") or 0))
    return v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--amazon-inv", required=True)
    ap.add_argument("--walmart-inv")
    ap.add_argument("--amazon", required=True)
    ap.add_argument("--walmart")
    ap.add_argument("--fba-fees")
    ap.add_argument("--rules", default=os.path.join(DATA, "sku_guard_rules.json"))
    ap.add_argument("--out", required=True)
    ap.add_argument("--slack", required=True, help="shared-channel text (no Earthwise rates)")
    ap.add_argument("--slack-private", help="Steven-only text with per-unit savings")
    a = ap.parse_args()

    R = load(a.rules)
    T = {**DEFAULTS, **R.get("inventory", {})}
    C = R["cost_basis"]
    ref_pct = R["marketplace_fees"]["amazon_referral_pct_fallback"]
    pc = product_costs()
    av = velocity(rows_of(load(a.amazon)))
    wv = velocity(rows_of(load(a.walmart))) if a.walmart else {}
    fee_est = load(a.fba_fees) if a.fba_fees else {}

    alerts, send = [], []

    def stock_check(channel, sku, name, mode, avail, inbound, units, sales):
        per_day = units / 30
        rev_day = sales / 30
        days = (avail + inbound) / per_day if per_day else None
        base = dict(channel=channel, sku=sku, name=name[:60], mode=mode, available=avail,
                    inbound=inbound, units_30d=units, revenue_per_day=round(rev_day, 2),
                    days_cover=round(days, 1) if days is not None else None)
        if units == 0:
            return
        if avail + inbound == 0:
            alerts.append({**base, "level": "critical", "issue": "out of stock while selling",
                           "fix": "raise listing quantity" if mode in ("FBM", "Seller") else
                           "send stock / sell from FBM twin meanwhile"})
        elif mode in ("FBM", "Seller"):
            if avail <= T["listing_qty_critical_units"] or (days is not None and days < T["listing_qty_low_days"]):
                alerts.append({**base, "level": "critical" if avail <= T["listing_qty_critical_units"] else "low",
                               "issue": f"listing quantity runs out in ~{max(days, 1):.0f} day(s)",
                               "fix": "raise listing quantity (Earthwise holds the stock)"})
        elif days is not None and days < T["fba_low_days"]:
            alerts.append({**base, "level": "critical" if days < T["fba_critical_days"] else "low",
                           "issue": f"{max(days, 1):.0f} day(s) of {mode} cover incl. inbound",
                           "fix": f"send ~{math.ceil(per_day * T['send_cover_days'] - avail - inbound)} units"})

    # ---- Amazon ----
    inv = rows_of(load(a.amazon_inv))
    by_asin = {}
    for r in inv:
        by_asin.setdefault(r.get("asin"), []).append(r)
    for r in inv:
        sku, name = r["sku"], r.get("product_name") or ""
        i = r.get("inventory") or {}
        mode = (r.get("fulfillment_type") or "").upper()
        units, sales, _ = av.get(sku, (0, 0, 0))
        stock_check("amazon", sku, name, mode, i.get("available") or 0,
                    i.get("inbound_quantity") or 0, units, sales)

    # FBA send list: FBM SKUs selling steadily.
    for asin, rows in by_asin.items():
        fbm = [r for r in rows if (r.get("fulfillment_type") or "").upper() == "FBM"]
        fba = [r for r in rows if (r.get("fulfillment_type") or "").upper() == "FBA"]
        for r in fbm:
            sku, name = r["sku"], r.get("product_name") or ""
            units, sales, _ = av.get(sku, (0, 0, 0))
            if units < T["send_list_min_units_30d"]:
                continue
            fee = fee_est.get(asin)
            for f in fba if fee is None else []:  # Amazon fees per unit minus referral
                fu, fs, ff = av.get(f["sku"], (0, 0, 0))
                if fu:
                    fee = round(-ff / fu - ref_pct * (fs / fu), 2)
            if fee is not None and fee < 2.5:  # below any real FBA fee: fees not posted yet
                fee = None
            asin_units = sum(av.get(x["sku"], (0, 0, 0))[0] for x in rows)
            fba_stock = sum((x.get("inventory") or {}).get("available", 0) +
                            (x.get("inventory") or {}).get("inbound_quantity", 0) for x in fba)
            qty = max(math.ceil(asin_units / 30 * T["send_cover_days"]) - fba_stock, 0)
            cost = pc.get(sku)
            ship = C["fbm_shipping_per_unit_override"].get(sku, fbm_ship(name, C["fbm_shipping_by_weight"]))
            item = dict(channel="amazon", sku=sku, name=name[:60], units_30d=units, send_qty=qty,
                        fbm_ship_u=ship, fba_fee_u=fee, product_cost=cost)
            if fee is None or cost is None:
                item.update(verdict="check", reason="no reliable FBA fee - pass --fba-fees from the SP-API fee estimate"
                            if fee is None else "no product cost in amazon_cogs.csv")
            else:
                direct = round(ship - (fee + C["fba_services_per_unit"]), 2)
                invoiced = round(direct - cost * (T["fba_invoiced_cost_multiplier"] - 1), 2)
                item.update(saving_u_direct=direct, saving_u_invoiced=invoiced,
                            saving_mo_direct=round(direct * units, 0),
                            saving_mo_invoiced=round(invoiced * units, 0))
                item["verdict"] = ("send now" if invoiced > 0 else
                                   "send once Earthwise bills FBA stock at the direct rate" if direct > 0
                                   else "keep FBM")
            send.append(item)

    # ---- Walmart ----
    if a.walmart_inv:
        for r in rows_of(load(a.walmart_inv)):
            sku, name = r["sku"], r.get("product_name") or ""
            units, sales, _ = wv.get(sku, (0, 0, 0))
            wfs = (r.get("wfs_available") or 0)
            if wfs or r.get("wfs_inbound"):
                stock_check("walmart", sku, name, "WFS", wfs, r.get("wfs_inbound") or 0, units, sales)
            else:
                stock_check("walmart", sku, name, "Seller", r.get("sf_available") or 0, 0, units, sales)
            if units >= T["send_list_min_units_30d"] and not wfs and not r.get("wfs_inbound"):
                cost = pc.get(sku)
                ship = fbm_ship(name, C["fbm_shipping_by_weight"])
                fee = wfs_estimate(name, C["walmart_wfs_fee_estimate"])
                direct = round(ship - fee - C["fba_services_per_unit"], 2)
                item = dict(channel="walmart", sku=sku, name=name[:60], units_30d=units,
                            send_qty=math.ceil(units / 30 * T["send_cover_days"]),
                            fbm_ship_u=ship, wfs_fee_u_est=fee, product_cost=cost,
                            saving_u_direct=direct)
                if cost is not None:
                    inv_s = round(direct - cost * (T["fba_invoiced_cost_multiplier"] - 1), 2)
                    item.update(saving_u_invoiced=inv_s,
                                verdict="send now" if inv_s > 0 else
                                "send once Earthwise bills WFS stock at the direct rate" if direct > 0
                                else "keep seller-fulfilled")
                else:
                    item.update(verdict="check", reason="no product cost on file")
                send.append(item)

    alerts.sort(key=lambda x: (x["level"] != "critical", -x["revenue_per_day"]))
    send.sort(key=lambda x: -(x.get("saving_mo_direct") or x.get("units_30d") or 0))
    out = dict(alerts=alerts, send_list=send, thresholds=T,
               note="FBA/WFS savings exclude any conversion lift from the Prime / 2-day badge.")
    with open(a.out, "w") as f:
        json.dump(out, f, indent=1)

    crit = [x for x in alerts if x["level"] == "critical"]
    low = [x for x in alerts if x["level"] == "low"]

    def render(private):
        L = ["*:package: Stock & FBA/WFS*"]
        for title, items in (("Out of stock / about to", crit), ("Running low", low)):
            if items:
                L.append(f"\n_{title}_ ({len(items)})")
                for x in items[:8]:
                    L.append(f"• *{short(x['name'])}*  ·  {'AMZ' if x['channel'] == 'amazon' else 'WMT'} {x['mode']}  ·  `{x['sku']}`\n"
                             f"     {x['issue']}  ·  ${x['revenue_per_day']:,.0f}/day in sales at risk  →  {x['fix']}")
                if len(items) > 8:
                    L.append(f"  +{len(items) - 8} more")
        if send:
            L.append(f"\n_FBA / WFS send list_ ({len(send)})")
            for x in send[:8]:
                line = (f"• *{short(x['name'])}*  ·  {'AMZ' if x['channel'] == 'amazon' else 'WMT'}  ·  `{x['sku']}`\n"
                        f"     {x['units_30d']} sold/30d  ·  send {x['send_qty']}  →  *{x['verdict']}*")
                if private and "saving_u_direct" in x:
                    line += (f"  ·  saves ${x['saving_u_direct']:.2f}/unit at the direct rate, "
                             f"${x.get('saving_u_invoiced', 0):.2f} at the invoiced rate")
                elif x.get("reason"):
                    line += f"  ·  _{x['reason']}_"
                L.append(line)
        if len(L) == 1:
            L.append("No stock issues.")
        return "\n".join(L) + "\n"

    with open(a.slack, "w") as f:  # shared: no Earthwise rates
        f.write(render(False).replace("send once Earthwise bills FBA stock at the direct rate", "waiting on Earthwise's FBA pricing")
                .replace("send once Earthwise bills WFS stock at the direct rate", "waiting on Earthwise's WFS pricing"))
    if a.slack_private:
        with open(a.slack_private, "w") as f:
            f.write(render(True))
    print(f"{len(crit)} critical, {len(low)} low, {len(send)} send-list rows -> {a.out}")


if __name__ == "__main__":
    main()
