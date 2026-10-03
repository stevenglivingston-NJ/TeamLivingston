#!/usr/bin/env python3
"""Render a price plan (data/price_plan.json) as the Slack approval post + one thread reply
per group, in the team format: margins as %, never profit dollars, product cost or eZdia
terms (the shared channel includes the agency). Dollar detail goes to Steven's DM only.

Usage:
  python3 approval_post.py --plan data/price_plan.json --date "Sat Oct 3" --out post.json
Output JSON: {"parent": "...", "replies": {"E": "...", "A": "...", ...}}
"""
import argparse, json, os, re

HERE = os.path.dirname(os.path.abspath(__file__))
RULE = "━━━━━━━━━━━━━━━━━━━━"


def pct(x, signed=False):
    if x is None:
        return "n/a"
    t = f"{x:+.0%}" if signed else f"{x:.0%}"
    return t.replace("-", "−")


def margin(profit, revenue):
    return profit / revenue if revenue else None


def short(name):
    """'Earthwise Shady Native Wildflower Seed Mix - 1/2 lb, 375 sq ft' -> 'Shady ½ lb'."""
    n = name.replace("Earthwise ", "").replace("Seed Company ", "")
    n = n.replace("1/2", "½").replace("1/4", "¼")
    m = re.search(r"^(.*?)[\s,–-]*((?:\d+(?:\.\d+)?|½|¼)\s*(?:lbs?|oz)\b|(?:½|¼)(?=,))", n)
    base, size = (m.group(1), m.group(2)) if m else (n, "")
    for cut in ("Native Wildflower Seed Mix", "Wildflower Seed Mix", "Native Alternative Lawn Seed",
                "Alternative Lawn Seed", "Alternative Lawn", "Natural Lawn Food", "Lawn Seed",
                "Grass Seed", "Seed Mix", "Wildflower Mix", "Mix", "Seed"):
        base = re.sub(r"\b%s\b(?!-)" % re.escape(cut), "", base)
    base = re.split(r" [–-] |,", base)[0]
    if re.search(r"\bTac", base):
        base = "Seed-Tac"
    base = re.sub(r"[\s,–-]+$", "", re.sub(r"\s+", " ", base)).strip()
    size = re.sub(r"(\d)(lb|oz)", r"\1 \2", size)
    if size and not re.search(r"(lb|oz)", size):
        size += " lb"
    return f"{base} {size}".strip()[:32]


def group_margins(rows):
    rn = sum(r.get("revenue_now") or 0 for r in rows)
    rw = sum(r.get("revenue_new") or 0 for r in rows)
    pn = sum(r.get("profit_now") or 0 for r in rows)
    pw = sum(r.get("profit_new") or 0 for r in rows)
    return margin(pn, rn), margin(pw, rw)


def sku_block(r):
    name = short(r.get("name") or r["sku"])
    mode = r.get("mode", "")
    lines = [f"*{name}*  ·  {mode}{'*' if r.get('mode_note') else ''}  ·  `{r['sku']}`"]
    now = r.get("current_list") or r.get("price_now")
    step, tgt = r.get("step_price"), r.get("target_price")
    price = f"${now:,.2f} → *${step:,.2f}*"
    if tgt and step and tgt > step + 0.5:
        price += f"  _(then ${tgt:,.2f})_"
    bits = [price]
    mn, mw = margin(r.get("profit_now") or 0, r.get("revenue_now")), margin(r.get("profit_new") or 0, r.get("revenue_new"))
    if r.get("margin_new_before_ads") is not None:
        bits.append(f"margin → {pct(r['margin_new_before_ads'])}")
    elif mn is not None and mw is not None:
        bits.append(f"margin {pct(mn)} → *{pct(mw)}*")
    u0, u1 = r.get("units_now"), r.get("units_new")
    if u0 is not None and u1 is not None:
        bits.append(f"sales {u0:.0f} → {u1:.0f}/mo")
    a0, a1 = r.get("ad_spend_now") or 0, r.get("ad_spend_target")
    if a1 is not None and a0 >= 20 and a1 < a0 * 0.95:
        bits.append("ads off" if a1 == 0 else f"ads {pct(a1 / a0 - 1, True)}")
    lines.append("   " + "  ·  ".join(bits))
    return "\n".join(lines)


def render(P, date):
    meta, order = P["group_meta"], P.get("group_order") or list(P["groups"])
    T = P.get("totals", {})
    out = {"replies": {}}
    head = [f":clipboard:  *Price plan — approval needed*  ·  {date}", RULE,
            "*Where we are*  _(last 30 days, Amazon + Walmart)_",
            f">Margin after all costs: *{pct(T.get('margin_now'))}*",
            ">Goal: no SKU at a loss · blended *22–25%* · most profit possible", "",
            "*With this plan*",
            f">Margin *{pct(T.get('margin_now'))} → {pct(T.get('margin_plan'))}*  ·  "
            f"profit *≈{T.get('profit_multiple')}×*  ·  revenue *{pct(T.get('revenue_change'), True)}*",
            ">Revenue dips because we stop paying ads for sales that lose money.",
            ">About half the gain is price, half is ad cuts.", RULE,
            "*The groups*  ·  SKU detail in the thread :thread:", ""]
    for k in order:
        rows = P["groups"].get(k) or []
        if not rows:
            continue
        m = meta[k]
        mn, mw = group_margins(rows)
        tag = "  ·  *urgent*" if m.get("urgent") else ""
        head.append(f"{m['emoji']}  *{k} · {m['title']}*  —  {len(rows)} SKU{'s' if len(rows) > 1 else ''}{tag}")
        head.append(f">{m['blurb']}")
        if mn is not None and mw is not None:
            head.append(f">Margin *{pct(mn)} → {pct(mw)}*")
        head.append("")

        body = [f"{m['emoji']}  *{k} · {m['title']}*  —  {len(rows)} SKU{'s' if len(rows) > 1 else ''}"
                + (f"  ·  margin {pct(mn)} → *{pct(mw)}*" if mn is not None and mw is not None else ""),
                RULE]
        if m.get("caveat"):
            body += [f":warning:  _{m['caveat']}_", ""]
        for r in rows:
            body += [sku_block(r), ""]
            if r.get("reason"):
                body.insert(-1, f"   _{r['reason'].split(';')[0].replace('$', '$')}_")
        body.append("_Margin = after all costs. Sales = units a month, now → expected at the new "
                    "price and ad level. “then” = a second step a week later if sales hold._")
        if any((r.get("ad_spend_target") is not None) for r in rows):
            body.append("_Ad cuts go through the Helium 10 rules (Vinay)._")
        if any(r.get("mode_note") for r in rows):
            body.append("_* was FBA earlier this month; now merchant-fulfilled._")
        if k == "W":
            body.append("_Trish applies approved Walmart prices in Seller Center and replies `done`._")
        out["replies"][k] = "\n".join(body)
    rec = " + ".join(k for k in order if meta.get(k, {}).get("urgent")) or ""
    head += [RULE, "*How to approve*  ·  Steven or Brad, reply in the thread with one line:",
             "`Approve all`   ·   `Approve E+A+D`   ·   `Approve A except U9-RK1E-4E3E`   ·   `Hold`", "",
             f":bulb:  *Recommended:* `Approve {('E+' if rec else '')}A+D` now  →  B and C after a week, "
             "once A and D show sales holding.",
             "_Every change is checked against the Buy Box next run; if we lose it, the price goes back._"]
    out["parent"] = "\n".join(head)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", default=os.path.join(HERE, "data", "price_plan.json"))
    ap.add_argument("--date", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    P = json.load(open(a.plan))
    out = render(P, a.date)
    json.dump(out, open(a.out, "w"), indent=1, ensure_ascii=False)
    print(out["parent"])


if __name__ == "__main__":
    main()
