#!/usr/bin/env python3
"""Headless Shopify price + unit-cost feed for the Jatalia / Earthwise sweep.

Replaces the old session-only path (the claude.ai Shopify MCP + Coupler.io push),
which could not run in a scheduled Cloud Routine. This pulls every product variant
from the Shopify Admin GraphQL API — retail `price` AND `inventoryItem.unitCost`
(the COGS field the storefront connector blocks) — and writes `shopify_costs.json`
in the shape the billing/exception code already consumes.

Auth (set in the Cloud environment's env-var config — see mcp-servers/.env.example):
  SHOPIFY_ADMIN_TOKEN    Admin API access token (shpat_...), scopes read_products + read_inventory
  SHOPIFY_SHOP_DOMAIN    e.g. earthwiseseed.myshopify.com   (default below)
Optional:
  SHOPIFY_API_VERSION    default 2024-10
  SHOPIFY_COSTS_OUT      output path (default ./data/shopify_costs.json next to this file)

HTTP goes through `curl`, NOT python-urllib: the Cloud session egress proxy 403s
urllib and would silently return zero rows (same reason lead-sweep.py / sb.sh use
curl). See TeamLivingston/CLAUDE.md.

SKU-collision rule: some EW SKUs are reused across an ACTIVE product and a DRAFT one
(e.g. EW00103 Microclover ACTIVE $12.95 vs Wild Sunshine DRAFT $35). We keep the
ACTIVE product's variant — the real seller — matching the resolution validated by
hand on 2026-07-06.
"""
import json
import os
import subprocess
import sys

SHOP = os.environ.get("SHOPIFY_SHOP_DOMAIN", "earthwiseseed.myshopify.com").strip()
TOKEN = os.environ.get("SHOPIFY_ADMIN_TOKEN", "").strip()
API_VERSION = os.environ.get("SHOPIFY_API_VERSION", "2024-10").strip()
_here = os.path.dirname(os.path.abspath(__file__))
OUT = os.environ.get("SHOPIFY_COSTS_OUT", os.path.join(_here, "data", "shopify_costs.json"))

ENDPOINT = f"https://{SHOP}/admin/api/{API_VERSION}/graphql.json"

QUERY = """
query($cursor: String) {
  products(first: 50, after: $cursor) {
    edges {
      node {
        title
        status
        variants(first: 100) {
          edges {
            node {
              sku
              title
              price
              inventoryItem { unitCost { amount } }
            }
          }
        }
      }
    }
    pageInfo { hasNextPage endCursor }
  }
}
"""


def gql(cursor=None):
    """POST the GraphQL query via curl; return the parsed `data` object."""
    body = json.dumps({"query": QUERY, "variables": {"cursor": cursor}})
    proc = subprocess.run(
        [
            "curl", "-sS", "--fail-with-body", "--max-time", "60",
            "-X", "POST", ENDPOINT,
            "-H", f"X-Shopify-Access-Token: {TOKEN}",
            "-H", "Content-Type: application/json",
            "-d", body,
        ],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"curl failed (rc={proc.returncode}): {proc.stderr.strip()} {proc.stdout.strip()[:400]}")
    payload = json.loads(proc.stdout)
    if payload.get("errors"):
        raise RuntimeError(f"Shopify GraphQL errors: {json.dumps(payload['errors'])[:600]}")
    return payload["data"]


def flatten_page(data, seen):
    """Merge a page's variants into `seen` (sku -> record), ACTIVE beating DRAFT."""
    for pe in data["products"]["edges"]:
        n = pe["node"]
        ptitle, pstatus = n["title"], n["status"]
        for ve in n["variants"]["edges"]:
            v = ve["node"]
            sku = (v.get("sku") or "").strip()
            if not sku:
                continue
            cost = ((v.get("inventoryItem") or {}).get("unitCost") or {}).get("amount")
            rec = {
                "sku": sku,
                "title": v.get("title", ""),
                "price": str(v.get("price", "") or ""),
                "product_title": ptitle,
                "product_status": pstatus,
                "inventoryItem_unitCost_amount": ("" if cost is None else str(cost)),
            }
            prev = seen.get(sku)
            # ACTIVE wins over any non-ACTIVE; within same status, last write wins.
            if prev and prev["product_status"] == "ACTIVE" and pstatus != "ACTIVE":
                continue
            seen[sku] = rec


def main():
    if not TOKEN:
        sys.stderr.write("SHOPIFY_ADMIN_TOKEN not set — cannot pull Shopify feed.\n")
        return 2

    seen = {}
    cursor = None
    pages = 0
    while True:
        data = gql(cursor)
        flatten_page(data, seen)
        pages += 1
        pi = data["products"]["pageInfo"]
        if not pi["hasNextPage"]:
            break
        cursor = pi["endCursor"]
        if pages > 200:  # safety backstop against a pagination loop
            sys.stderr.write("Stopped after 200 pages (unexpected).\n")
            break

    results = [{"hasNextPage": False, "edges": rec} for rec in seen.values()]
    with_cost = sum(1 for r in seen.values() if r["inventoryItem_unitCost_amount"])
    from datetime import date  # local import so the module imports even if date is frozen elsewhere
    stamp = os.environ.get("SWEEP_TODAY") or date.today().isoformat()

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(
            {"results": results, "feedbackUrl": f"admin-api-pull-{stamp}", "execution": "shopify-admin-api"},
            fh, indent=1,
        )

    sys.stderr.write(
        f"shopify_costs: {len(results)} SKUs ({with_cost} with unit cost) "
        f"from {pages} page(s) -> {OUT}\n"
    )
    # Emit a compact summary on stdout so a caller (the sweep / a Routine) can log it.
    print(json.dumps({"skus": len(results), "with_cost": with_cost, "pages": pages, "out": OUT}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
