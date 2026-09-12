#!/usr/bin/env bash
# =============================================================================
# verify-google-secret.sh — diagnose a Google OAuth client id/secret/refresh
# token triple over curl, with zero MCP registration and zero permission
# prompts (same rationale as sb.sh / ghl.sh / sm.sh / gmb.sh: Bash isn't
# classifier-gated, so this also works unattended from a scheduled Routine).
# -----------------------------------------------------------------------------
# Why this exists: every Google-backed server in this repo (google-ads, gmb,
# google-analytics, gtm) authenticates with a Desktop OAuth client + a
# long-lived refresh token, and per CLAUDE.md scopes do NOT carry across
# tokens — the GOOGLE_ADS_REFRESH_TOKEN 403s against GA4 and against Tag
# Manager. That produces three different failure shapes that all look the
# same from the outside ("the server won't authenticate"):
#   1. client id/secret wrong or mismatched  -> invalid_client
#   2. refresh token expired/revoked/wrong-client -> invalid_grant
#   3. token mints fine but lacks the scope the API needs -> looks like a
#      403 deep inside the server, days later
# This script mints an access token for one or all of the three credential
# sets and, on success, calls tokeninfo to print the SCOPES actually granted
# — so a scope mismatch shows up here instead of inside a server three hops
# away. bootstrap.sh's "Skipped" list only tells you a var is unset; this
# tells you whether a SET var actually authenticates.
#
# Usage:
#   bash mcp-servers/verify-google-secret.sh                # check ads, ga4, gtm
#   bash mcp-servers/verify-google-secret.sh ads
#   bash mcp-servers/verify-google-secret.sh ga4
#   bash mcp-servers/verify-google-secret.sh gtm
#
# Credential resolution matches .env.example: GA4_CLIENT_ID/SECRET and
# GTM_CLIENT_ID/SECRET fall back to GOOGLE_ADS_CLIENT_ID/SECRET when blank
# (same OAuth app, different token) — GA4_REFRESH_TOKEN / GTM_REFRESH_TOKEN
# always need their own value, minted via tools/get_refresh_token.py.
#
# Exit code: 0 only if every set that was checked minted a token. Prints one
# JSON object per set to stdout either way, so a caller can act on
# "checks[].ok" without re-parsing prose.
# =============================================================================
set -uo pipefail

TOKEN_URL="https://oauth2.googleapis.com/token"
TOKENINFO_URL="https://oauth2.googleapis.com/tokeninfo"

die() { echo "{\"error\":$(python3 -c 'import json,sys;print(json.dumps(sys.argv[1]))' "$1")}" >&2; exit "${2:-1}"; }

# ---- verify_set <name> <client_id_var> <client_secret_var> <refresh_token_var> [fallback_id_var] [fallback_secret_var]
# Prints one JSON object; returns 0 on a successful mint, 1 otherwise.
verify_set() {
  local name="$1" id_var="$2" secret_var="$3" rt_var="$4" fb_id_var="${5:-}" fb_secret_var="${6:-}"

  local cid="${!id_var:-}"
  local csec="${!secret_var:-}"
  local rt="${!rt_var:-}"

  local id_source="$id_var" secret_source="$secret_var"
  if [ -z "$cid" ] && [ -n "$fb_id_var" ]; then cid="${!fb_id_var:-}"; id_source="$fb_id_var (fallback)"; fi
  if [ -z "$csec" ] && [ -n "$fb_secret_var" ]; then csec="${!fb_secret_var:-}"; secret_source="$fb_secret_var (fallback)"; fi

  if [ -z "$cid" ] || [ -z "$csec" ] || [ -z "$rt" ]; then
    local missing=()
    [ -z "$cid" ] && missing+=("$id_var${fb_id_var:+ or $fb_id_var}")
    [ -z "$csec" ] && missing+=("$secret_var${fb_secret_var:+ or $fb_secret_var}")
    [ -z "$rt" ] && missing+=("$rt_var")
    NAME="$name" MISSING="$(printf '%s\n' "${missing[@]}")" python3 <<'PY'
import json, os
print(json.dumps({
    "credential_set": os.environ["NAME"],
    "ok": False,
    "status": "not_configured",
    "missing": [l for l in os.environ["MISSING"].splitlines() if l],
}, indent=1))
PY
    return 1
  fi

  local http_code resp
  resp="$(curl -sS --max-time 60 -w '\n%{http_code}' -X POST "$TOKEN_URL" \
    -d "client_id=$cid" -d "client_secret=$csec" \
    -d "refresh_token=$rt" -d "grant_type=refresh_token" 2>/dev/null)" \
    || { echo "{\"credential_set\":\"$name\",\"ok\":false,\"status\":\"network_error\",\"detail\":\"curl failed reaching oauth2.googleapis.com\"}"; return 1; }
  http_code="${resp##*$'\n'}"
  local body="${resp%$'\n'*}"

  NAME="$name" HTTP_CODE="$http_code" BODY="$body" \
  ID_SRC="$id_source" SECRET_SRC="$secret_source" RT_VAR="$rt_var" \
  TOKENINFO_URL="$TOKENINFO_URL" python3 <<'PY'
import json, os, urllib.request, urllib.error, urllib.parse

name = os.environ["NAME"]
code = os.environ["HTTP_CODE"]
body_raw = os.environ["BODY"]
id_src = os.environ["ID_SRC"]
secret_src = os.environ["SECRET_SRC"]
rt_var = os.environ["RT_VAR"]

try:
    body = json.loads(body_raw)
except json.JSONDecodeError:
    body = {"raw": body_raw}

out = {"credential_set": name, "http_status": int(code) if code.isdigit() else code,
       "client_id_source": id_src, "client_secret_source": secret_src,
       "refresh_token_var": rt_var}

if code == "200" and "access_token" in body:
    out["ok"] = True
    out["status"] = "authenticated"
    out["expires_in_seconds"] = body.get("expires_in")
    token = body["access_token"]
    # tokeninfo tells us the SCOPES actually granted — the thing that bites
    # days later as a 403 deep inside a server, per CLAUDE.md's repeated
    # "scopes don't carry across tokens" lesson.
    try:
        url = os.environ["TOKENINFO_URL"] + "?" + urllib.parse.urlencode({"access_token": token})
        with urllib.request.urlopen(url, timeout=30) as r:
            info = json.loads(r.read().decode())
        out["scopes"] = sorted((info.get("scope") or "").split())
        out["scope_expires_in_seconds"] = info.get("expires_in")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
        out["scopes_lookup_error"] = str(e)
else:
    out["ok"] = False
    err = body.get("error", "unknown_error")
    err_desc = body.get("error_description", "")
    out["error"] = err
    out["error_description"] = err_desc
    if err == "invalid_client":
        out["status"] = "bad_client_id_or_secret"
        out["diagnosis"] = (f"{id_src} / {secret_src} do not form a valid OAuth "
                             f"client, or don't match the client that issued {rt_var}. "
                             "Re-check both values in Cloud Console > APIs & Services > "
                             "Credentials.")
    elif err == "invalid_grant":
        out["status"] = "bad_or_expired_refresh_token"
        out["diagnosis"] = (f"{rt_var} is expired, revoked, or was minted by a "
                             f"different OAuth client than {id_src}/{secret_src}. "
                             "Re-mint with tools/get_refresh_token.py.")
    else:
        out["status"] = "unexpected_error"

print(json.dumps(out, indent=1))
raise SystemExit(0 if out["ok"] else 1)
PY
}

TARGET="${1:-all}"
overall_ok=0

check_ads() {
  verify_set "google-ads" GOOGLE_ADS_CLIENT_ID GOOGLE_ADS_CLIENT_SECRET GOOGLE_ADS_REFRESH_TOKEN
}
check_ga4() {
  verify_set "ga4" GA4_CLIENT_ID GA4_CLIENT_SECRET GA4_REFRESH_TOKEN GOOGLE_ADS_CLIENT_ID GOOGLE_ADS_CLIENT_SECRET
}
check_gtm() {
  verify_set "gtm" GTM_CLIENT_ID GTM_CLIENT_SECRET GTM_REFRESH_TOKEN GOOGLE_ADS_CLIENT_ID GOOGLE_ADS_CLIENT_SECRET
}

case "$TARGET" in
  ads)  check_ads  || overall_ok=1 ;;
  ga4)  check_ga4  || overall_ok=1 ;;
  gtm)  check_gtm  || overall_ok=1 ;;
  all)
    check_ads || overall_ok=1
    check_ga4 || overall_ok=1
    check_gtm || overall_ok=1
    ;;
  *) die "usage: verify-google-secret.sh [ads|ga4|gtm|all]" 2 ;;
esac

exit "$overall_ok"
