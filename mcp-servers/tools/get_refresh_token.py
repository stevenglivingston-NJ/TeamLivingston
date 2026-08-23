#!/usr/bin/env python3
"""Mint a Google OAuth refresh token for one of the KTU/BTU MCP servers.

Every Google-backed server here (google-ads, gmb, google-analytics, and now
Tag Manager) authenticates the same way: a Desktop OAuth client plus a
long-lived refresh token held in an environment variable. Scopes do NOT carry
across tokens — the google-ads token 403s against the Analytics API, and it
403s against Tag Manager too (verified 2026-08-23). Each API needs its own
token minted with its own scopes.

`server.py` in google-ads has referenced this script for months without it
existing in the repo. This is that script.

Run it on a machine with a browser — it opens a consent screen on localhost.

    python3 mcp-servers/tools/get_refresh_token.py --preset tagmanager

Then copy the printed refresh token into the Cloud environment's env-var config
under the name it tells you. Never commit the value.

Presets:
  tagmanager       read + edit containers. Stages changes as a container
                   version; a human still clicks Publish in the GTM UI.
  tagmanager-publish
                   the above plus publish rights — an agent can ship a
                   container live with no human step. Prefer `tagmanager`.
  analytics        GA4 Data API (matches the existing GA4_REFRESH_TOKEN).
  ads              Google Ads API (matches GOOGLE_ADS_REFRESH_TOKEN).
"""
import argparse
import os
import sys

PRESETS: dict[str, tuple[str, list[str]]] = {
    "tagmanager": (
        "GTM_REFRESH_TOKEN",
        [
            "https://www.googleapis.com/auth/tagmanager.readonly",
            "https://www.googleapis.com/auth/tagmanager.edit.containers",
        ],
    ),
    "tagmanager-publish": (
        "GTM_REFRESH_TOKEN",
        [
            "https://www.googleapis.com/auth/tagmanager.readonly",
            "https://www.googleapis.com/auth/tagmanager.edit.containers",
            "https://www.googleapis.com/auth/tagmanager.publish",
        ],
    ),
    "analytics": (
        "GA4_REFRESH_TOKEN",
        ["https://www.googleapis.com/auth/analytics.readonly"],
    ),
    "ads": (
        "GOOGLE_ADS_REFRESH_TOKEN",
        ["https://www.googleapis.com/auth/adwords"],
    ),
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--preset", choices=sorted(PRESETS), required=True)
    ap.add_argument("--client-secrets-file", metavar="PATH",
                    help="Path to the client_secret_*.json downloaded from Cloud "
                         "Console > Credentials. Preferred — avoids handling the "
                         "secret by hand.")
    ap.add_argument("--client-id", default=os.environ.get("GOOGLE_ADS_CLIENT_ID"),
                    help="Desktop OAuth client ID. Defaults to GOOGLE_ADS_CLIENT_ID.")
    ap.add_argument("--client-secret", default=os.environ.get("GOOGLE_ADS_CLIENT_SECRET"),
                    help="Desktop OAuth client secret. Defaults to GOOGLE_ADS_CLIENT_SECRET.")
    ap.add_argument("--port", type=int, default=0,
                    help="Loopback port for the consent redirect. 0 picks a free one.")
    args = ap.parse_args()

    if not args.client_secrets_file and not (args.client_id and args.client_secret):
        print("ERROR: need OAuth client credentials. Either:\n"
              "         --client-secrets-file client_secret_XXX.json   (preferred)\n"
              "       or --client-id / --client-secret\n"
              "       or export GOOGLE_ADS_CLIENT_ID and GOOGLE_ADS_CLIENT_SECRET.\n\n"
              "       Download the JSON from Cloud Console > APIs & Services >\n"
              "       Credentials > your Desktop client > the download icon.",
              file=sys.stderr)
        return 2

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("ERROR: pip install google-auth-oauthlib", file=sys.stderr)
        return 2

    env_var, scopes = PRESETS[args.preset]

    if args.client_secrets_file:
        import json
        with open(args.client_secrets_file) as fh:
            client_config = json.load(fh)
        if "installed" not in client_config:
            kind = next(iter(client_config), "unknown")
            print(f"ERROR: {args.client_secrets_file} is a '{kind}' client, not a "
                  f"Desktop app.\n       The loopback consent flow needs an "
                  f"'installed' (Desktop) client.", file=sys.stderr)
            return 2
    else:
        client_config = {
            "installed": {
                "client_id": args.client_id,
                "client_secret": args.client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": ["http://localhost"],
            }
        }

    print(f"Preset : {args.preset}")
    print(f"Scopes : {' '.join(scopes)}")
    print("\nSign in as the account that already has access to what you are "
          "granting —\nfor Tag Manager, the account with edit rights on BOTH "
          "containers.\n")

    flow = InstalledAppFlow.from_client_config(client_config, scopes=scopes)
    # access_type=offline + prompt=consent forces a refresh token even when this
    # account has authorised this client before; without prompt=consent Google
    # returns an access token only and the run is silently useless.
    creds = flow.run_local_server(port=args.port, access_type="offline",
                                  prompt="consent")

    if not creds.refresh_token:
        print("\nERROR: no refresh token returned. Revoke this client for the "
              "account at\n       https://myaccount.google.com/permissions and "
              "run again.", file=sys.stderr)
        return 1

    # A refresh token can only be redeemed by the client that issued it. The
    # environment already holds a DIFFERENT client under GOOGLE_ADS_CLIENT_ID,
    # so printing the token alone gets you "unauthorized_client" at the first
    # API call. Print the client alongside it and name all three vars.
    prefix = env_var.rsplit("_REFRESH_TOKEN", 1)[0]
    id_var, secret_var = f"{prefix}_CLIENT_ID", f"{prefix}_CLIENT_SECRET"
    conf = client_config["installed"]

    print("\n" + "=" * 72)
    print("Set ALL THREE of these in the Cloud environment's env-var config.")
    print("The token is only redeemable by the client that issued it, so the")
    print("client id and secret have to travel with it.\n")
    print(f"{id_var}={conf['client_id']}")
    print(f"{secret_var}=<the client secret from "
          f"{args.client_secrets_file or 'the client you just used'}>")
    print(f"{env_var}={creds.refresh_token}")
    print("=" * 72)
    print("\nThe token and the secret are credentials. Do not commit them, "
          "paste them\ninto a ticket, or send them over chat. Delete the "
          "client_secret JSON once\nboth values are stored.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
