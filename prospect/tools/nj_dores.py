#!/usr/bin/env python3
"""NJ DORES Business Name Search — free public entity lookup.

Turns an LLC name from a deed index into its state registration: entity ID,
registered city, entity type and formation date. The formation date is the
useful part for Prospect — an SPE formed within ~90 days of a purchase is an
acquisition vehicle, which means a CapEx decision is live right now.

What this does NOT return: registered agent, registered office address, or
members. The free search does not expose them. To get the agent + office
address, order a Status Report ($5.00 + $1.25 online fee) for the entity ID at
https://www.njportal.com/dor/businessrecords/ — see prospect/records-access.md.

Usage:
    python3 nj_dores.py "47 UNION" "28 MORSE" "209 MONTAGUE"
    python3 nj_dores.py --json "RPM DEVELOPMENT" > out.json
    python3 nj_dores.py --file entities.txt

Search tips: drop the LLC/L.L.C./Inc suffix and any punctuation. DORES matches
on a name prefix, so "209 MONTAGUE" finds "209 MONTAGUE, L.L.C." but
"209 MONTAGUE LLC" may not.
"""
import argparse
import html
import http.cookiejar
import json
import re
import sys
import time
import urllib.parse
import urllib.request

BASE = "https://www.njportal.com/DOR/BusinessNameSearch/Search/BusinessName"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36")

_cj = http.cookiejar.CookieJar()
_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_cj))
_opener.addheaders = [("User-Agent", UA)]

# DORES entity type codes worth knowing when reading results.
TYPE_NOTES = {
    "LLC": "domestic LLC",
    "FLC": "foreign LLC",
    "DP": "domestic profit corporation",
    "FP": "foreign profit corporation",
    "LP": "limited partnership",
    "NP": "non-profit",
}


def get_token():
    """Fetch the anti-forgery token the search form requires."""
    with _opener.open(BASE, timeout=30) as r:
        page = r.read().decode("utf-8", "replace")
    m = re.search(r'__RequestVerificationToken" type="hidden" value="([^"]+)"', page)
    return m.group(1) if m else None


def search(name, token):
    """Return [{name, entity_id, city, type, incorporated}] for a name prefix."""
    data = urllib.parse.urlencode({
        "__RequestVerificationToken": token,
        "BusinessName": name,
    }).encode()
    req = urllib.request.Request(BASE, data=data)
    with _opener.open(req, timeout=30) as r:
        page = r.read().decode("utf-8", "replace")
    page = re.sub(r"<script.*?</script>", "", page, flags=re.S)
    out = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", page, flags=re.S):
        cells = [html.unescape(re.sub("<[^>]+>", "", c)).strip()
                 for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, flags=re.S)]
        if len(cells) >= 5 and cells[0] and cells[0] != "Business Name":
            out.append({
                "name": cells[0],
                "entity_id": cells[1],
                "city": cells[2],
                "type": cells[3],
                "incorporated": cells[4],
            })
    return out


def clean(name):
    """Strip suffixes and punctuation that break DORES prefix matching."""
    n = re.sub(r"\s*\(.*?\)", "", name)
    n = re.sub(r"[,.]", " ", n)
    n = re.sub(r"\b(L\s*L\s*C|LLC|INC|CORP|CORPORATION|COMPANY|CO|LP|LTD)\b",
               " ", n, flags=re.I)
    return " ".join(n.split())


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("names", nargs="*", help="entity names to look up")
    ap.add_argument("--file", help="file with one entity name per line")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    ap.add_argument("--raw", action="store_true",
                    help="search names verbatim instead of stripping suffixes")
    ap.add_argument("--delay", type=float, default=1.2,
                    help="seconds between queries (default 1.2 — be polite)")
    args = ap.parse_args()

    names = list(args.names)
    if args.file:
        with open(args.file) as fh:
            names += [ln.strip() for ln in fh if ln.strip()]
    if not names:
        ap.error("give at least one entity name, or --file")

    token = get_token()
    if not token:
        sys.exit("could not obtain the DORES verification token — the form may have changed")

    results = {}
    for i, raw_name in enumerate(names, 1):
        query = raw_name if args.raw else clean(raw_name)
        try:
            hits = search(query, token)
            err = None
        except Exception as exc:
            hits, err = [], str(exc)
        results[raw_name] = {"query": query, "hits": hits, "error": err}

        if not args.json:
            print(f"\n=== {raw_name}   (searched: {query!r}) ===")
            if err:
                print(f"  ERROR: {err}")
            elif not hits:
                print("  no registration found — check spelling, or the entity "
                      "may be registered in another state")
            for h in hits[:8]:
                note = TYPE_NOTES.get(h["type"], h["type"])
                print(f"  {h['name']}")
                print(f"    id {h['entity_id']} · {h['city'] or 'city not listed'} "
                      f"· {note} · formed {h['incorporated']}")

        if i < len(names):
            time.sleep(args.delay)
        if i % 25 == 0:                      # token goes stale on long runs
            token = get_token() or token

    if args.json:
        json.dump(results, sys.stdout, indent=1)
        print()


if __name__ == "__main__":
    main()
