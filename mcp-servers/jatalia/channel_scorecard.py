#!/usr/bin/env python3
"""Channel scorecard for the Jatalia standup: Shopify (earthwiseseed.com) next to Amazon,
Walmart and Lowe's, last week / last month / same period last year.

Why Shopify is the yardstick: it is the oldest channel and the one with a year of history,
so it carries the seasonal pattern (spring lawn season, fall overseeding). When Shopify and
a marketplace move together it is the market; when they split, it is something we did
(price, stock, ads, rank) and someone should look.

Windows end yesterday (the --asof date, inclusive):
  W   last 7 days        vs PW  the 7 days before   vs LYW the same 7 days 364 days earlier
  M   last 30 days       vs PM  the 30 days before  vs LYM the same 30 days 364 days earlier
  NXT Shopify, the 30 days after LYM last year (what the coming month did a year ago)
364 days keeps weekdays aligned.

Revenue basis, kept like-for-like:
  Shopify  order subtotal after discounts, before shipping and tax, cancelled/test orders out
  Amazon   Helium 10 `sales` (product sales)    Walmart  Helium 10 `sales`
  Lowe's   product total from Earthwise reimbursement emails (no Lowe's API)

Inputs:
  --amazon   get_account_profit_and_loss_summary_series, granularity=day, marketplace US,
             from asof-400d to asof (raw JSON)
  --walmart  get_wmt_account_profit_and_loss_summary_series, same window (raw JSON)
  --lowes    optional [{"start":"YYYY-MM-DD","end":"YYYY-MM-DD","revenue":123.4}, ...]
  --shopify  a Shopify bulk-export JSONL file; or --fetch-shopify to pull it here
             (needs SHOPIFY_ADMIN_TOKEN with read_orders + read_all_orders; the shop
             domain comes from SHOPIFY_SHOP_DOMAIN, default earthwiseseed.myshopify.com)

Usage:
  python3 channel_scorecard.py --asof 2026-10-02 --amazon A400.json --walmart W400.json \
      --fetch-shopify --shopify-save shop.jsonl --lowes lowes.json --out sc.json --slack sc.txt
"""
import argparse, collections, datetime as dt, json, os, subprocess, sys, time

D = dt.date
API = "2025-01"


def day(s):
    return D.fromisoformat(s[:10])


def windows(asof):
    w0 = asof - dt.timedelta(days=6)
    m0 = asof - dt.timedelta(days=29)
    sh = dt.timedelta(days=364)
    return {
        "W": (w0, asof), "PW": (w0 - dt.timedelta(days=7), w0 - dt.timedelta(days=1)),
        "LYW": (w0 - sh, asof - sh),
        "M": (m0, asof), "PM": (m0 - dt.timedelta(days=30), m0 - dt.timedelta(days=1)),
        "LYM": (m0 - sh, asof - sh),
        "NXT": (asof - sh + dt.timedelta(days=1), asof - sh + dt.timedelta(days=30)),
    }


# ---------- series loaders: date -> {revenue, units, ads, orders} ----------

def h10_series(path):
    obj = json.load(open(path))
    data = obj.get("data", obj)
    out = collections.defaultdict(lambda: collections.defaultdict(float))
    keymap = {"sales": "revenue", "units_sold": "units", "advertising_cost": "ads",
              "net_profit": "profit"}
    for m in data.get("metrics", []):
        k = keymap.get(m.get("metric_key"))
        if not k:
            continue
        for d, v in (m.get("values") or {}).items():
            out[day(d)][k] += abs(v or 0) if k == "ads" else (v or 0)
    first = min((d for d, v in out.items() if v.get("revenue")), default=None)
    return out, first


def lowes_series(path):
    """Spread each reimbursement period's revenue evenly over its days."""
    out = collections.defaultdict(lambda: collections.defaultdict(float))
    rows = json.load(open(path))
    for r in rows:
        a, b = day(r["start"]), day(r["end"])
        n = (b - a).days + 1
        for i in range(n):
            out[a + dt.timedelta(days=i)]["revenue"] += r["revenue"] / n
    first = min((day(r["start"]) for r in rows), default=None)
    last = max((day(r["end"]) for r in rows), default=None)
    return out, first, last, sorted(rows, key=lambda r: r["end"])


def curl(args, data=None):
    cmd = ["curl", "-sS", "--max-time", "120"] + args
    if data is not None:
        cmd += ["--data", data]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip()[:300])
    return r.stdout


def shopify_gql(q, variables=None):
    shop = os.environ.get("SHOPIFY_SHOP_DOMAIN", "earthwiseseed.myshopify.com").strip()
    tok = os.environ.get("SHOPIFY_ADMIN_TOKEN", "").strip()
    if not tok:
        raise RuntimeError("SHOPIFY_ADMIN_TOKEN not set")
    body = json.dumps({"query": q, "variables": variables or {}})
    out = curl(["-X", "POST", f"https://{shop}/admin/api/{API}/graphql.json",
                "-H", "Content-Type: application/json", "-H", f"X-Shopify-Access-Token: {tok}"], body)
    j = json.loads(out)
    if j.get("errors"):
        raise RuntimeError(f"Shopify: {str(j['errors'])[:300]}")
    return j["data"]


def fetch_shopify(asof, save):
    """One bulk export of the orders the windows need; returns the JSONL path."""
    W = windows(asof)
    recent = W["PM"][0]
    ly0, ly1 = W["LYM"][0], W["NXT"][1]
    search = (f"(created_at:>='{recent}' AND created_at:<='{asof + dt.timedelta(days=1)}') OR "
              f"(created_at:>='{ly0}' AND created_at:<='{ly1 + dt.timedelta(days=1)}')")
    inner = ('{ orders(query: "%s") { edges { node { id createdAt test cancelledAt '
             'currentSubtotalPriceSet { shopMoney { amount } } '
             'totalDiscountsSet { shopMoney { amount } } '
             'lineItems { edges { node { title quantity sku '
             'discountedTotalSet { shopMoney { amount } } } } } } } } }') % search.replace('"', '\\"')
    m = shopify_gql('mutation($q: String!) { bulkOperationRunQuery(query: $q) { '
                    'bulkOperation { id status } userErrors { field message } } }', {"q": inner})
    res = m["bulkOperationRunQuery"]
    if res["userErrors"]:
        raise RuntimeError(f"Shopify bulk: {res['userErrors']}")
    op_id = res["bulkOperation"]["id"]
    for _ in range(120):  # up to ~20 minutes
        time.sleep(10)
        st = shopify_gql('query($id: ID!) { node(id: $id) { ... on BulkOperation '
                         '{ status errorCode objectCount url } } }', {"id": op_id})["node"]
        if st["status"] == "COMPLETED":
            if not st.get("url"):  # no orders matched
                open(save, "w").close()
                return save
            with open(save, "w") as f:
                f.write(curl(["-L", st["url"]]))
            return save
        if st["status"] in ("FAILED", "CANCELED", "EXPIRED"):
            raise RuntimeError(f"Shopify bulk {st['status']} {st.get('errorCode')}")
    raise RuntimeError("Shopify bulk export timed out")


def shopify_series(path):
    """JSONL -> (daily series, line items by day and title)."""
    out = collections.defaultdict(lambda: collections.defaultdict(float))
    items = collections.defaultdict(lambda: collections.defaultdict(float))
    order_day, skip = {}, set()
    with open(path) as f:
        for line in f:
            if not line.strip():
                continue
            o = json.loads(line)
            if "__parentId" in o:
                p = o["__parentId"]
                if p in skip or p not in order_day:
                    continue
                d = order_day[p]
                items[(d, o.get("title") or o.get("sku") or "?")]["revenue"] += \
                    float(o["discountedTotalSet"]["shopMoney"]["amount"])
                out[d]["units"] += o.get("quantity") or 0
                continue
            if o.get("test") or o.get("cancelledAt"):
                skip.add(o["id"])
                continue
            d = day(o["createdAt"])
            order_day[o["id"]] = d
            out[d]["revenue"] += float(o["currentSubtotalPriceSet"]["shopMoney"]["amount"])
            out[d]["discounts"] += float(o["totalDiscountsSet"]["shopMoney"]["amount"])
            out[d]["orders"] += 1
    first = min(out) if out else None
    return out, first, items


# ---------- math ----------

def total(series, a, b, key="revenue"):
    s, d = 0.0, a
    while d <= b:
        s += series.get(d, {}).get(key, 0)
        d += dt.timedelta(days=1)
    return s


def pct(cur, prev):
    return None if not prev else (cur - prev) / prev


def covered(first, a, last=None, b=None):
    """True if the channel has data for the whole window."""
    return first is not None and first <= a and (last is None or b is None or last >= b)


def fmt_pct(x):
    return "n/a" if x is None else f"{x:+.0%}".replace("-", "−")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--asof", required=True, help="last full day, YYYY-MM-DD (yesterday)")
    ap.add_argument("--amazon", required=True)
    ap.add_argument("--walmart")
    ap.add_argument("--lowes")
    ap.add_argument("--shopify", help="Shopify bulk JSONL already downloaded")
    ap.add_argument("--fetch-shopify", action="store_true")
    ap.add_argument("--shopify-save", default="shopify_orders.jsonl")
    ap.add_argument("--diverge-pts", type=float, default=0.15)
    ap.add_argument("--min-dollars", type=float, default=500)
    ap.add_argument("--out", required=True)
    ap.add_argument("--slack", required=True, help="shared-channel text (Shopify as % only)")
    ap.add_argument("--slack-private", help="Steven-only text with Shopify dollars")
    a = ap.parse_args()

    asof = day(a.asof)
    W = windows(asof)
    ch, degraded = {}, []
    s, f = h10_series(a.amazon)
    ch["Amazon"] = dict(series=s, first=f, last=asof)
    if a.walmart:
        s, f = h10_series(a.walmart)
        ch["Walmart"] = dict(series=s, first=f, last=asof)
    if a.lowes:
        s, f, l, periods = lowes_series(a.lowes)
        ch["Lowe's"] = dict(series=s, first=f, last=l, periods=periods)
    else:
        degraded.append("Lowe's: no reimbursement periods supplied")
    items = {}
    try:
        path = fetch_shopify(asof, a.shopify_save) if a.fetch_shopify else a.shopify
        if path:
            s, f, items = shopify_series(path)
            ch["Shopify"] = dict(series=s, first=f, last=asof)
        else:
            degraded.append("Shopify: no data supplied")
    except Exception as e:  # report, never invent
        degraded.append(f"Shopify unavailable: {e}")

    table = {}
    for name, c in ch.items():
        row = {}
        for k, (x, y) in W.items():
            ok = covered(c["first"], x, c["last"], y)
            row[k] = round(total(c["series"], x, y), 2) if ok else None
        row["wow"] = pct(row["W"], row["PW"]) if row["W"] is not None else None
        row["mom"] = pct(row["M"], row["PM"]) if row["M"] is not None else None
        row["yoy_w"] = pct(row["W"], row["LYW"]) if row["W"] is not None else None
        row["yoy_m"] = pct(row["M"], row["LYM"]) if row["M"] is not None else None
        if name in ("Amazon", "Walmart") and row["M"]:
            ads = total(c["series"], *W["M"], key="ads")
            if ads:  # Walmart ad spend reads 0 in Helium 10 (2026-10); show TACoS only when present
                row["ads_m"] = round(ads, 2)
                row["tacos_m"] = round(ads / row["M"], 3)
        if name == "Shopify" and row["M"]:
            orders = total(c["series"], *W["M"], key="orders")
            pm_orders = total(c["series"], *W["PM"], key="orders")
            row["orders_m"] = int(orders)
            row["aov_m"] = round(row["M"] / orders, 2) if orders else None
            row["aov_pm"] = round(row["PM"] / pm_orders, 2) if pm_orders and row["PM"] else None
            disc = total(c["series"], *W["M"], key="discounts")
            row["discount_rate_m"] = round(disc / (row["M"] + disc), 3) if row["M"] + disc else None
        if c.get("periods"):  # Lowe's reports in reimbursement periods, ~2 weeks behind
            p = c["periods"]
            row["last_period"] = dict(start=p[-1]["start"], end=p[-1]["end"], revenue=p[-1]["revenue"])
            if len(p) > 1:
                row["last_period"]["vs_prior"] = pct(p[-1]["revenue"], p[-2]["revenue"])
        table[name] = row

    total_m = sum((r["M"] or 0) for r in table.values())
    for r in table.values():
        r["share_m"] = round((r["M"] or 0) / total_m, 3) if total_m else None

    # Divergence vs Shopify: same direction = market, split = channel-specific.
    flags = []
    shop = table.get("Shopify")
    if shop:
        for name, r in table.items():
            if name == "Shopify":
                continue
            for key, label, cur, prev in (("wow", "week over week", "W", "PW"),
                                          ("mom", "month over month", "M", "PM")):
                if r.get(key) is None or shop.get(key) is None:
                    continue
                gap = r[key] - shop[key]
                dollars = abs((r[cur] or 0) - (r[prev] or 0))
                if abs(gap) >= a.diverge_pts and dollars >= a.min_dollars:
                    flags.append(dict(channel=name, window=label, channel_change=round(r[key], 3),
                                      shopify_change=round(shop[key], 3), gap_pts=round(gap, 3),
                                      dollars=round(dollars, 0),
                                      read="lagging Shopify - look at price, stock, ads, rank"
                                      if gap < 0 else "beating Shopify - find what worked and repeat it"))

    # Seasonal guide: what Shopify did over the coming 30 days last year.
    season = None
    if shop and shop.get("NXT") is not None and shop.get("LYM"):
        season = round(pct(shop["NXT"], shop["LYM"]), 3)

    # Shopify product movers (month over month).
    movers = []
    if items:
        cur, prev = collections.defaultdict(float), collections.defaultdict(float)
        for (d, title), v in items.items():
            if W["M"][0] <= d <= W["M"][1]:
                cur[title] += v["revenue"]
            elif W["PM"][0] <= d <= W["PM"][1]:
                prev[title] += v["revenue"]
        for t in set(cur) | set(prev):
            movers.append(dict(title=t, m=round(cur[t], 2), pm=round(prev[t], 2),
                               change=round(cur[t] - prev[t], 2)))
        movers.sort(key=lambda x: -abs(x["change"]))
        movers = movers[:10]

    out = dict(asof=str(asof), windows={k: [str(x), str(y)] for k, (x, y) in W.items()},
               channels=table, divergences=flags, shopify_next30_last_year=season,
               shopify_movers=movers, degraded=degraded,
               notes=["n/a = the channel has no data for that window (Amazon and Walmart "
                      "started selling in 2026, so last-year comparisons are Shopify-only "
                      "until 2027)."])
    with open(a.out, "w") as fh:
        json.dump(out, fh, indent=1)

    def render(private):
        L = ["*:bar_chart: Channels*  ·  last 7 days  |  last 30 days  _(vs prior period · vs last year)_"]
        for name in ("Shopify", "Amazon", "Walmart", "Lowe's"):
            r = table.get(name)
            if not r:
                L.append(f"• *{name}*: no data")
                continue
            if r.get("last_period") and r["M"] is None:
                lp = r["last_period"]
                L.append(f"• *{name}*: ${lp['revenue']:,.0f} for {lp['start'][5:]}–{lp['end'][5:]}  "
                         f"({fmt_pct(lp.get('vs_prior'))} vs prior period; reimbursement data lags)")
                continue
            hide = name == "Shopify" and not private  # Earthwise DTC: % only in the shared channel
            w = "n/a" if r["W"] is None else ("" if hide else f"${r['W']:,.0f} ")
            m = "n/a" if r["M"] is None else ("" if hide else f"${r['M']:,.0f} ")
            extra = ""
            if r.get("tacos_m") is not None:
                extra = f"  ·  TACoS {r['tacos_m']:.0%}"
            if r.get("aov_m") and private:
                extra = f"  ·  AOV ${r['aov_m']:.0f}"
            # Shares would let anyone back out Shopify dollars, so they are private.
            share = f"  ·  {r['share_m']:.0%} of sales" if r.get("share_m") and private else ""
            L.append(f"• *{name}*:  {w}({fmt_pct(r['wow'])} · {fmt_pct(r['yoy_w'])} LY)  |  "
                     f"{m}({fmt_pct(r['mom'])} · {fmt_pct(r['yoy_m'])} LY){share}{extra}")
        for x in flags[:3]:
            L.append(f":warning: *{x['channel']}* {x['window']} {fmt_pct(x['channel_change'])} vs Shopify "
                     f"{fmt_pct(x['shopify_change'])} — {x['read']}")
        if season is not None:
            L.append(f"_Season guide: last year Shopify moved {fmt_pct(season)} over the next 30 days._")
        for d in degraded:
            L.append(f":warning: {d}")
        return "\n".join(L) + "\n"

    with open(a.slack, "w") as fh:
        fh.write(render(False))
    if a.slack_private:
        with open(a.slack_private, "w") as fh:
            fh.write(render(True))
    print(f"{len(table)} channels, {len(flags)} divergences, {len(degraded)} degraded -> {a.out}")


if __name__ == "__main__":
    main()
