#!/usr/bin/env python3
"""
sync_royalty_basis.py — compute OUR royalty basis from ServiceMinder invoices.

This fills the `ours` third of `royalty_periods` (migration 018). The `hfc`
third needs the monthly workbook parsed; the `bank` third needs the Monday
reconciliation. All three are required, because reconciling HFC's workbook to
the bank debit only verifies HFC against HFC — if their revenue basis is wrong,
invoice and debit agree and the error is invisible.

WHAT IT DELIBERATELY DOES NOT DECIDE

  * **Invoiced vs collected.** Stored separately, never blended. For KTU
    Jan–Aug 2026 they differ by $392,637, which at 5% is ~$19,600 of royalty.
    Which one the franchise agreement uses is a question for the agreement, not
    for this script, and a variance computed against the wrong one is noise
    wearing the costume of a finding.
  * **The licence split.** KTU bills under 688 and 824 on different schedules;
    ServiceMinder invoices carry no licence. Rows are therefore written at
    brand level with `license='ALL'` and `license_split` saying so.
  * **The rate.** `franchise_fees` says KTU 5% + NAF 2%; moola.md records KTU 688
    stepping 7.0% → 5.5% → 4.0% through 2026 as volume grew. Those disagree, so
    `--rate` is explicit and `our_rate` records what was used. Nothing is
    written under an assumed rate without saying which.

Usage:
  python3 intranet/scripts/sync_royalty_basis.py                    # dry run
  python3 intranet/scripts/sync_royalty_basis.py --apply
  python3 intranet/scripts/sync_royalty_basis.py --apply --rate 0.055 --naf 0.02
"""
import json, os, subprocess, sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SB = os.path.join(ROOT, "mcp-servers", "sb.sh")
SM = os.path.join(ROOT, "mcp-servers", "sm.sh")
APPLY = "--apply" in sys.argv
def _arg(flag, default):
    return float(sys.argv[sys.argv.index(flag) + 1]) if flag in sys.argv else default
RATE = _arg("--rate", 0.05)   # KTU headline per franchise_fees; BTU is tiered
NAF  = _arg("--naf", 0.02)
FROM = "2026-01-01"; THROUGH = "2026-08-31"


def sb(sql):
    out = subprocess.run(["bash", SB], input=sql, capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f"sb.sh failed: {out.stderr.strip()}")
    data = json.loads(out.stdout)
    if isinstance(data, dict) and "message" in data and "ok" not in data:
        raise RuntimeError(f"SQL error: {data['message']}")
    return data


def sm(brand, endpoint, body):
    out = subprocess.run(["bash", SM, brand, endpoint, json.dumps(body)],
                         capture_output=True, text=True, timeout=180)
    try:
        return json.loads(out.stdout)
    except json.JSONDecodeError:
        return {}


def month_of(v):
    """ServiceMinder dates are US M/D/YYYY, not ISO — see sync_proposal_engagement."""
    if not v:
        return None
    part = str(v).split(" ")[0]
    try:
        m, _d, y = (int(x) for x in part.split("/"))
        return f"{y:04d}-{m:02d}"
    except (ValueError, TypeError):
        return part[:7] if part[:4].isdigit() else None


def q(v):
    return "null" if v in (None, "") else "'" + str(v).replace("'", "''") + "'"


def n(v):
    return "null" if v is None else f"{v:.2f}"


def main():
    print(f"rate {RATE:.3%} · NAF {NAF:.3%} · {FROM}..{THROUGH}"
          f"{'' if APPLY else '   [DRY RUN]'}\n")
    grand = {}
    for brand in ("KTU", "BTU"):
        res = sm(brand, "invoice/query",
                 {"FromDate": FROM, "ThroughDate": THROUGH, "Take": 1000})
        inv = res.get("Invoices") or []
        if not inv:
            print(f"{brand}: no invoices returned — skipping rather than writing zeroes")
            continue
        months = defaultdict(lambda: {"n": 0, "inv": 0.0, "col": 0.0})
        for i in inv:
            k = month_of(i.get("Date"))
            if not k:
                continue
            g = months[k]
            g["n"] += 1
            g["inv"] += float(i.get("Subtotal") or 0)
            g["col"] += float(i.get("Total") or 0) - float(i.get("BalanceDue") or 0)
        print(f"{brand}: {len(inv)} invoices across {len(months)} months")
        tot_i = tot_c = 0.0
        for k in sorted(months):
            g = months[k]
            tot_i += g["inv"]; tot_c += g["col"]
            roy = g["inv"] * RATE
            naf = g["inv"] * NAF
            print(f"   {k}  {g['n']:>3} inv   invoiced {g['inv']:>12,.2f}   "
                  f"collected {g['col']:>12,.2f}   royalty {roy:>10,.2f}   NAF {naf:>9,.2f}")
            if APPLY:
                sb(f"""
                  insert into royalty_periods
                    (brand, period, license, license_split, our_invoiced, our_collected,
                     our_invoice_count, our_rate, our_royalty, our_naf, recon_status, notes)
                  values ({q(brand)}, {q(k)}, 'ALL',
                    'brand total — ServiceMinder invoices carry no licence, so this is not split across {"688/824" if brand=="KTU" else "BTU199/BTU200"}',
                    {n(g['inv'])}, {n(g['col'])}, {g['n']}, {RATE}, {n(roy)}, {n(naf)},
                    'no_workbook',
                    'Ours only. HFC workbook not yet parsed, no bank debit matched. Royalty computed on INVOICED subtotal (tax excluded) at the rate shown — the agreement may use collected instead.')
                  on conflict (brand, period, license) do update set
                    our_invoiced=excluded.our_invoiced, our_collected=excluded.our_collected,
                    our_invoice_count=excluded.our_invoice_count, our_rate=excluded.our_rate,
                    our_royalty=excluded.our_royalty, our_naf=excluded.our_naf,
                    synced_at=now()
                """)
        grand[brand] = (tot_i, tot_c, len(inv))
        gap = tot_i - tot_c
        print(f"   YTD invoiced {tot_i:,.2f} · collected {tot_c:,.2f} · "
              f"uncollected {gap:,.2f}")
        print(f"   royalty {tot_i*RATE:,.2f} on invoiced  vs  {tot_c*RATE:,.2f} on collected "
              f"— a {abs(tot_i-tot_c)*RATE:,.2f} swing on which basis the agreement uses\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
