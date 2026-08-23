# `mcp-servers/tools/`

Operator scripts. Not MCP servers — these are run by hand, usually once.

## `get_refresh_token.py`

Mints a Google OAuth refresh token for one of the Google-backed servers.

`google-ads/server.py` has told operators to run `python get_refresh_token.py`
since the repo was created; the script never existed. This is it.

```bash
pip install google-auth-oauthlib

# Preferred — hand it Google's own download, no secret typed by hand.
# Cloud Console > APIs & Services > Credentials > your Desktop client >
# download icon > client_secret_*.json
python3 mcp-servers/tools/get_refresh_token.py --preset tagmanager \
  --client-secrets-file ~/Downloads/client_secret_XXX.json

# Or, if the env vars are already set on this machine:
python3 mcp-servers/tools/get_refresh_token.py --preset tagmanager
```

The downloaded JSON contains the client secret — delete it once the token is
minted, and never commit it.

It opens a consent screen on localhost, so run it on a machine with a browser —
not in a Cloud session. Sign in as the account that already holds the access you
are granting. Paste the printed token into the Cloud environment's env-var
config under the name the script prints. Never commit it.

### Scopes do not carry across tokens

Each Google API needs its own token. Verified, not assumed:

| Token | Scope | Against another API |
|---|---|---|
| `GOOGLE_ADS_REFRESH_TOKEN` | `adwords` | 403 on GA4 Data API, 403 on Tag Manager (2026-08-23) |
| `GA4_REFRESH_TOKEN` | `analytics.readonly` | scoped to GA4 only |
| `GTM_REFRESH_TOKEN` | `tagmanager.*` | scoped to Tag Manager only |

### Choosing a Tag Manager preset

- **`tagmanager`** — read plus edit containers. An agent can stage a change as a
  container version; a human still clicks Publish in the GTM UI before it is
  live on the sites. **Prefer this.**
- **`tagmanager-publish`** — adds publish rights, so an agent can ship a
  container live with no human step. Only grant this if you specifically want
  unattended publishing.

Either grant lets the holder change what fires on the production sites —
analytics, pixels, conversion tracking. It is a materially wider grant than the
read-only tokens the other servers use. Declining it and keeping Tag Manager
edits manual is a reasonable choice.
