#!/usr/bin/env bash
# Verify the shared Google OAuth credential, and say plainly which of the two
# failure modes you are in. One client secret is used by google-ads, gmb,
# google-analytics, gtm and tracking-audit.py, so this one check covers all five.
#
#   bash mcp-servers/verify-google-secret.sh
#
# Reads GOOGLE_ADS_CLIENT_ID / _CLIENT_SECRET / _REFRESH_TOKEN from the
# environment, falling back to ~/.claude/settings.json (mcpServers.google-ads.env).
set -u

python3 - <<'PY'
import json, os, sys, urllib.request, urllib.parse, urllib.error

def creds():
    e = {k: os.environ.get(k) for k in
         ("GOOGLE_ADS_CLIENT_ID", "GOOGLE_ADS_CLIENT_SECRET", "GOOGLE_ADS_REFRESH_TOKEN")}
    if all(e.values()):
        return e, "environment"
    p = os.path.expanduser("~/.claude/settings.json")
    try:
        env = json.load(open(p))["mcpServers"]["google-ads"]["env"]
        return {k: env.get(k) for k in e}, "~/.claude/settings.json"
    except Exception as ex:
        print(f"could not read credentials: {ex}"); sys.exit(2)

c, src = creds()
missing = [k for k, v in c.items() if not v]
if missing:
    print("MISSING:", ", ".join(missing)); sys.exit(2)

print(f"source     : {src}")
print(f"client_id  : {c['GOOGLE_ADS_CLIENT_ID']}")
print(f"project    : {c['GOOGLE_ADS_CLIENT_ID'].split('-')[0]}")
print()

body = urllib.parse.urlencode({
    "client_id": c["GOOGLE_ADS_CLIENT_ID"],
    "client_secret": c["GOOGLE_ADS_CLIENT_SECRET"],
    "refresh_token": c["GOOGLE_ADS_REFRESH_TOKEN"],
    "grant_type": "refresh_token"}).encode()

try:
    urllib.request.urlopen(
        urllib.request.Request("https://oauth2.googleapis.com/token", data=body), timeout=30)
    print("✅ WORKING — token refresh succeeded.")
    print("   google-ads, gmb, google-analytics, gtm and tracking-audit.py can all authenticate.")
    sys.exit(0)
except urllib.error.HTTPError as e:
    j = json.loads(e.read().decode())
    desc = j.get("error_description", "")
    print(f"❌ FAILED — {j.get('error')}: {desc}")
    print()
    # Google uses two distinct messages, and they mean very different amounts of work.
    if "client was not found" in desc.lower():
        print("   The CLIENT ITSELF is gone (deleted, or the id is wrong).")
        print("   A replacement client means a NEW refresh token too — you must re-consent:")
        print("     python3 mcp-servers/tools/get_refresh_token.py")
    elif "secret" in desc.lower():
        print("   The client EXISTS; only the secret is wrong.")
        print("   The refresh token is still valid — it is bound to the client and the user")
        print("   grant, not the secret. Paste the correct secret and everything resumes.")
        print(f"   https://console.cloud.google.com/apis/credentials?project={c['GOOGLE_ADS_CLIENT_ID'].split('-')[0]}")
    else:
        print("   Unrecognised failure — read the message above before changing anything.")
    sys.exit(1)
PY
