#!/usr/bin/env python3
"""amazon-sp/ping.py — one successful SP-API call to keep the Developer account alive.

Amazon suspends SP-API access if a Developer account makes no successful API call
for 60 days. This makes exactly one successful call (LWA token → GET
/sellers/v1/marketplaceParticipations), which resets that clock and validates the
credentials. Run it monthly (or wire it to a tiny Routine) so the lapse never recurs.

HTTP via curl (no python deps; also dodges the Cloud egress-proxy 403 that hits
urllib — see TeamLivingston/CLAUDE.md).

Required env (same as the amazon-sp MCP server):
  AMAZON_SP_CLIENT_ID  AMAZON_SP_CLIENT_SECRET  AMAZON_SP_REFRESH_TOKEN

Usage:
  export AMAZON_SP_CLIENT_ID=... AMAZON_SP_CLIENT_SECRET=... AMAZON_SP_REFRESH_TOKEN=...
  python3 mcp-servers/amazon-sp/ping.py
"""
import json
import os
import subprocess
import sys

LWA_TOKEN_URL = "https://api.amazon.com/auth/o2/token"
SP_API_BASE = "https://sellingpartnerapi-na.amazon.com"


def curl(args):
    p = subprocess.run(["curl", "-sS", "--max-time", "40", *args], capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"curl rc={p.returncode}: {p.stderr.strip()} {p.stdout.strip()[:300]}")
    return p.stdout


def main():
    cid = os.environ.get("AMAZON_SP_CLIENT_ID", "").strip()
    sec = os.environ.get("AMAZON_SP_CLIENT_SECRET", "").strip()
    rt = os.environ.get("AMAZON_SP_REFRESH_TOKEN", "").strip()
    if not all([cid, sec, rt]):
        sys.stderr.write("Missing AMAZON_SP_CLIENT_ID / _CLIENT_SECRET / _REFRESH_TOKEN in env.\n")
        return 2

    # 1) LWA access token
    tok = json.loads(curl([
        "-X", "POST", LWA_TOKEN_URL,
        "-H", "Content-Type: application/x-www-form-urlencoded",
        "--data-urlencode", "grant_type=refresh_token",
        "--data-urlencode", f"refresh_token={rt}",
        "--data-urlencode", f"client_id={cid}",
        "--data-urlencode", f"client_secret={sec}",
    ]))
    if "access_token" not in tok:
        sys.stderr.write("LWA token exchange failed: " + json.dumps(tok)[:300] + "\n")
        return 1
    access = tok["access_token"]

    # 2) one successful SP-API GET
    out = curl([
        "-w", "\n%{http_code}",
        f"{SP_API_BASE}/sellers/v1/marketplaceParticipations",
        "-H", f"x-amz-access-token: {access}",
        "-H", "Content-Type: application/json",
    ])
    body, _, code = out.rpartition("\n")
    code = code.strip()
    if code.startswith("2"):
        try:
            n = len(json.loads(body).get("payload", []))
        except ValueError:
            n = "?"
        print(f"✅ SP-API call OK (HTTP {code}) — {n} marketplace participation(s). 60-day clock reset.")
        return 0
    sys.stderr.write(f"✗ SP-API returned HTTP {code}: {body[:400]}\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
