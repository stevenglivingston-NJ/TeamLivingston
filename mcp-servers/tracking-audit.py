#!/usr/bin/env python3
"""
tracking-audit.py — daily paid-marketing tracking-health sweep for KTU + BTU.

Why this exists
---------------
On 2026-08-23 a full manual audit found that ~$1,250/month of Google Ads spend
was being optimised against almost no conversion signal. None of the causes were
exotic; every one was a config drift that had been silently true for months:

  * a thank-you trigger bound to a domain that had since been redirected away
  * a conversion tag left paused, pointing at a REMOVED conversion action
  * a Google Ads conversion-goal category that was not biddable, so the one
    action that actually fired never informed Smart Bidding
  * landing pages loading the *other* brand's GTM container
  * pixels and gtag blocks belonging to accounts nobody here owns

None of that raises an alarm on its own. Tags keep loading, dashboards keep
rendering, and the number that matters — conversions reaching the bidder —
quietly sits near zero. This script re-checks all of it every morning so the
next drift is caught in a day instead of a quarter.

It is deliberately DETERMINISTIC: the agent that runs it does not re-derive the
analysis, it just publishes the findings. Every check is a real API call or a
real page fetch; nothing is inferred.

Usage
-----
  python3 mcp-servers/tracking-audit.py
  python3 mcp-servers/tracking-audit.py --out /tmp/tracking-audit.json
  python3 mcp-servers/tracking-audit.py --brand KTU

Requires env (Cloud environment secrets):
  GTM_REFRESH_TOKEN + (GTM_CLIENT_ID/SECRET or GOOGLE_ADS_CLIENT_ID/SECRET)
  GA4_REFRESH_TOKEN
  GOOGLE_ADS_DEVELOPER_TOKEN / CLIENT_ID / CLIENT_SECRET / REFRESH_TOKEN
  GHL_PIT_KTU / GHL_PIT_BTU
  CLARITY_KTU_TOKEN / CLARITY_BTU_TOKEN   (optional)

Transport note: HTTP goes through `curl`, matching lead-sweep.py. The session
egress proxy is honoured by curl but NOT by python-urllib, which returns 403 and
would make every check silently "pass" with zero data.

Output contract
---------------
{
  "scan_date": "...", "generated_at": "...",
  "status": "GREEN|AMBER|RED",
  "findings": [ {id, severity, brand, area, title, detail, fix} ],
  "metrics": {...},
  "degradations": [ "..." ]      # a pipe that could not be checked
}

An empty findings list next to a non-empty `degradations` list is UNVERIFIED,
not clean. Any consumer must say so rather than reporting all-clear.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone

ET = timezone(timedelta(hours=-4))

# ----------------------------------------------------------------- constants

CONTAINERS = {
    "KTU": {"account": "6139458547", "container": "137178727", "public": "GTM-KLT6WSH4"},
    "BTU": {"account": "6293468865", "container": "219120991", "public": "GTM-PK4HC6SR"},
}
GA4_PROPERTY = {"KTU": "453600017", "BTU": "487870392"}
GA4_MEASUREMENT = {"KTU": "G-44L97WQQXY", "BTU": "G-JE6291J8GY"}
ADS_ACCOUNT = {"KTU": "2579406186", "BTU": "4477036900"}
ADS_CONVERSION_ID = {"KTU": "568518580", "BTU": "17046712909"}
META_PIXEL = {"KTU": "109034988941656", "BTU": "1133512425499466"}
GHL_LOCATION = {"KTU": "nHLCxHPidnhV1NFzRtZZ", "BTU": "0uWA8M5BzHrrcJftuaDe"}

# Hostnames that must load their OWN brand's container, checked live.
BRAND_HOSTS = {
    "KTU": ["https://core.ktubloomfield.com", "https://lp.ktubloomfield.com"],
    "BTU": ["https://bathtuneupbloomfield.com"],
}

# Every Google/Meta/Bing id we knowingly run. Anything else found on a live page
# is reported — that is how the foreign AW- and pixel ids were caught.
KNOWN_IDS = {
    "GTM-KLT6WSH4", "GTM-PK4HC6SR",
    "G-44L97WQQXY", "G-JE6291J8GY", "GT-M6QBNDV3",
    "AW-568518580", "AW-17046712909",
    "109034988941656", "1133512425499466",
}

# Legacy trackers that should no longer appear in HighLevel funnel code.
LEGACY_TRACKERS = [
    (r"anytrack", "AnyTrack"),
    (r"AW-10831800845", "legacy gtag AW-10831800845"),
    (r"AW-17539791406", "legacy gtag AW-17539791406"),
    (r"tag\.simpli\.fi", "Simpli.fi"),
    (r"ms1\.consolidata\.ai", "Consolidata"),
    (r"877584890925563", "foreign Meta pixel 877584890925563"),
    (r"1213355723529903", "retired Meta pixel 1213355723529903"),
]

SEVERITY_RANK = {"critical": 3, "high": 2, "low": 1}


# ------------------------------------------------------------------- plumbing

class Audit:
    def __init__(self) -> None:
        self.findings: list[dict] = []
        self.degradations: list[str] = []
        self.metrics: dict = {}

    def finding(self, fid, severity, brand, area, title, detail, fix) -> None:
        self.findings.append({
            "id": fid, "severity": severity, "brand": brand, "area": area,
            "title": title, "detail": detail, "fix": fix,
        })

    def degrade(self, pipe: str, err: object) -> None:
        self.degradations.append(f"{pipe}: {str(err)[:200]}")

    @property
    def status(self) -> str:
        if any(f["severity"] == "critical" for f in self.findings):
            return "RED"
        if self.findings or self.degradations:
            return "AMBER"
        return "GREEN"


def curl(url: str, headers: dict | None = None, timeout: int = 30) -> str:
    cmd = ["curl", "-sSL", "--max-time", str(timeout)]
    ca = "/root/.ccr/ca-bundle.crt"
    if os.path.exists(ca):
        cmd += ["--cacert", ca]
    for k, v in (headers or {}).items():
        cmd += ["-H", f"{k}: {v}"]
    cmd.append(url)
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"curl {res.returncode}: {res.stderr[:160]}")
    return res.stdout


def google_token(refresh_env: str, client_pairs: list[tuple[str, str]]) -> str:
    """Exchange a refresh token, trying each client pair.

    A refresh token is only redeemable by the client that minted it, and these
    environments have carried a GTM_CLIENT_ID belonging to a different client
    than the token's — so a single-pair attempt returns unauthorized_client.
    """
    last = ""
    for cid, secret in client_pairs:
        if not (cid and secret):
            continue
        out = subprocess.run(
            ["curl", "-sS", "--max-time", "30",
             *(["--cacert", "/root/.ccr/ca-bundle.crt"]
               if os.path.exists("/root/.ccr/ca-bundle.crt") else []),
             "-X", "POST", "https://oauth2.googleapis.com/token",
             "-d", f"client_id={cid}", "-d", f"client_secret={secret}",
             "-d", f"refresh_token={os.environ[refresh_env]}",
             "-d", "grant_type=refresh_token"],
            capture_output=True, text=True).stdout
        try:
            data = json.loads(out)
        except json.JSONDecodeError:
            last = out[:160]
            continue
        if "access_token" in data:
            return data["access_token"]
        last = data.get("error_description") or data.get("error") or out[:160]
    raise RuntimeError(f"token exchange failed: {last}")


def _google_clients(prefix: str) -> list[tuple[str, str]]:
    return [
        (os.environ.get(f"{prefix}_CLIENT_ID", ""), os.environ.get(f"{prefix}_CLIENT_SECRET", "")),
        (os.environ.get("GOOGLE_ADS_CLIENT_ID", ""), os.environ.get("GOOGLE_ADS_CLIENT_SECRET", "")),
    ]


# --------------------------------------------------------------------- checks

def check_gtm(a: Audit, brands: list[str]) -> None:
    """Conversion tags live and unpaused; Clarity scoped; no orphan triggers."""
    try:
        token = google_token("GTM_REFRESH_TOKEN", _google_clients("GTM"))
    except Exception as exc:
        a.degrade("gtm", exc)
        return
    hdr = {"Authorization": f"Bearer {token}"}
    base = "https://tagmanager.googleapis.com/tagmanager/v2"

    for brand in brands:
        c = CONTAINERS[brand]
        path = f"accounts/{c['account']}/containers/{c['container']}"
        try:
            live = json.loads(curl(f"{base}/{path}/versions:live", hdr))
        except Exception as exc:
            a.degrade(f"gtm:{brand}", exc)
            continue

        tags = live.get("tag", [])
        triggers = {t["triggerId"]: t for t in live.get("trigger", [])}
        a.metrics[f"gtm_{brand}_live_version"] = live.get("containerVersionId")
        a.metrics[f"gtm_{brand}_tags"] = len(tags)

        # Conversion tags must not be paused. A paused lead tag is exactly how
        # KTU lost web lead tracking.
        for t in tags:
            is_conv = t.get("type") in ("awct", "awcc") or (
                t.get("type") == "gaawe"
                and "lead" in t.get("name", "").lower())
            if is_conv and t.get("paused"):
                a.finding(
                    "GTM-PAUSED-CONV", "critical", brand, "gtm",
                    f"Conversion tag paused: {t['name']}",
                    f"Tag {t['tagId']} ({t['type']}) is paused, so this conversion "
                    f"never reaches the ad platform.",
                    "Unpause it in GTM, or delete it if genuinely retired.")

        # Every firing trigger must exist (a deleted trigger orphans its tag).
        builtin = {"2147479553", "2147479573"}
        for t in tags:
            if t.get("paused"):
                continue
            for tid in t.get("firingTriggerId", []):
                if tid not in triggers and tid not in builtin:
                    a.finding(
                        "GTM-DANGLING-TRIGGER", "high", brand, "gtm",
                        f"Tag '{t['name']}' references missing trigger {tid}",
                        "The tag is live but its trigger no longer exists.",
                        "Repoint the tag at a valid trigger.")

        # Clarity must be hostname-scoped or it records builder-preview traffic.
        for t in tags:
            if "clarity" not in t.get("name", "").lower():
                continue
            fires = t.get("firingTriggerId", [])
            if any(f in builtin for f in fires):
                a.finding(
                    "CLARITY-UNSCOPED", "high", brand, "clarity",
                    "Clarity fires on All Pages",
                    "Clarity will record builder previews and any other hostname "
                    "served by this container, drowning real sessions.",
                    "Bind it to a Page Hostname regex for this brand's domain.")

        # A Google Tag pointing at an id we do not own sends data off-account.
        for t in tags:
            if t.get("type") != "googtag":
                continue
            tag_id = next((p.get("value") for p in t.get("parameter", [])
                           if p["key"] == "tagId"), None)
            if tag_id and tag_id not in KNOWN_IDS:
                a.finding(
                    "GTM-UNKNOWN-GOOGLE-TAG", "critical", brand, "gtm",
                    f"Google Tag loads unrecognised id {tag_id}",
                    "This id is not in the known-good list, so page data may be "
                    "flowing to an account nobody here controls.",
                    f"Replace with this brand's own id, or add {tag_id} to "
                    f"KNOWN_IDS if it is legitimately ours.")


def check_live_pages(a: Audit, brands: list[str]) -> None:
    """What a browser really loads: right container, and no foreign ids."""
    for brand in brands:
        own = CONTAINERS[brand]["public"]
        other = {v["public"] for k, v in CONTAINERS.items() if k != brand}
        for url in BRAND_HOSTS.get(brand, []):
            try:
                html = curl(url)
            except Exception as exc:
                a.degrade(f"page:{url}", exc)
                continue

            found = set(re.findall(
                r"GTM-[A-Z0-9]{6,}|G-[A-Z0-9]{8,}|AW-[0-9]{6,}|GT-[A-Z0-9]{6,}", html))
            found |= set(re.findall(r"fbq\(\s*['\"]init['\"]\s*,\s*['\"](\d{10,})", html))

            if own not in found:
                a.finding(
                    "PAGE-MISSING-CONTAINER", "critical", brand, "site",
                    f"{url} does not load {own}",
                    f"Found instead: {sorted(found) or 'no tags at all'}.",
                    "Add this brand's GTM container to the page.")
            for wrong in other & found:
                a.finding(
                    "PAGE-WRONG-BRAND-CONTAINER", "critical", brand, "site",
                    f"{url} loads the other brand's container ({wrong})",
                    "All of this page's traffic and conversions report into the "
                    "wrong brand's GA4 property and Ads account.",
                    "Repoint the page/funnel at the correct container in HighLevel.")
            for unknown in sorted(found - KNOWN_IDS - other):
                a.finding(
                    "PAGE-FOREIGN-TAG", "high", brand, "site",
                    f"{url} loads unrecognised tracking id {unknown}",
                    "Not one of ours — data is going to a third party.",
                    f"Remove {unknown} from the page source, or add it to "
                    f"KNOWN_IDS if it is legitimately ours.")


def check_ga4(a: Audit, brands: list[str]) -> None:
    """Cross-brand hostname contamination and unattributed lead events."""
    try:
        token = google_token("GA4_REFRESH_TOKEN", _google_clients("GA4"))
    except Exception as exc:
        a.degrade("ga4", exc)
        return
    hdr = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    for brand in brands:
        pid = GA4_PROPERTY[brand]
        body = {
            "dateRanges": [{"startDate": "7daysAgo", "endDate": "today"}],
            "dimensions": [{"name": "hostName"}],
            "metrics": [{"name": "sessions"}],
            "limit": 50,
        }
        try:
            out = subprocess.run(
                ["curl", "-sS", "--max-time", "30",
                 *(["--cacert", "/root/.ccr/ca-bundle.crt"]
                   if os.path.exists("/root/.ccr/ca-bundle.crt") else []),
                 "-X", "POST", "-H", f"Authorization: Bearer {token}",
                 "-H", "Content-Type: application/json", "-d", json.dumps(body),
                 f"https://analyticsdata.googleapis.com/v1beta/properties/{pid}:runReport"],
                capture_output=True, text=True).stdout
            rows = json.loads(out).get("rows", [])
        except Exception as exc:
            a.degrade(f"ga4:{brand}", exc)
            continue

        wrong_marker = "bathtuneup" if brand == "KTU" else "ktubloomfield"
        total = sum(int(r["metricValues"][0]["value"]) for r in rows) or 1
        bad = 0
        for r in rows:
            host = r["dimensionValues"][0]["value"]
            sess = int(r["metricValues"][0]["value"])
            if wrong_marker in host:
                bad += sess
                a.finding(
                    "GA4-CROSS-BRAND", "high", brand, "ga4",
                    f"{brand} property receiving {host} ({sess} sessions/7d)",
                    "A page on the other brand's hostname is tagged with this "
                    "property's measurement id, so both brands' reporting is wrong.",
                    "Correct the container/measurement id on that hostname.")
            if "vibepreview.com" in host or "leadconnectorhq.com" in host:
                a.finding(
                    "GA4-BUILDER-TRAFFIC", "low", brand, "ga4",
                    f"Builder-preview traffic in analytics: {host} ({sess})",
                    "Page-builder previews are being counted as real sessions.",
                    "Scope tags to real hostnames only.")
        a.metrics[f"ga4_{brand}_cross_brand_session_pct"] = round(100 * bad / total, 1)

        # generate_lead with no hostname = server-side hit with no session join,
        # so the lead cannot be attributed to a channel.
        body2 = {
            "dateRanges": [{"startDate": "30daysAgo", "endDate": "today"}],
            "dimensions": [{"name": "hostName"}],
            "metrics": [{"name": "eventCount"}],
            "dimensionFilter": {"filter": {
                "fieldName": "eventName",
                "stringFilter": {"value": "generate_lead"}}},
            "limit": 30,
        }
        try:
            out = subprocess.run(
                ["curl", "-sS", "--max-time", "30",
                 *(["--cacert", "/root/.ccr/ca-bundle.crt"]
                   if os.path.exists("/root/.ccr/ca-bundle.crt") else []),
                 "-X", "POST", "-H", f"Authorization: Bearer {token}",
                 "-H", "Content-Type: application/json", "-d", json.dumps(body2),
                 f"https://analyticsdata.googleapis.com/v1beta/properties/{pid}:runReport"],
                capture_output=True, text=True).stdout
            rows2 = json.loads(out).get("rows", [])
        except Exception as exc:
            a.degrade(f"ga4-leads:{brand}", exc)
            continue

        tot = sum(int(r["metricValues"][0]["value"]) for r in rows2)
        unattr = sum(int(r["metricValues"][0]["value"]) for r in rows2
                     if r["dimensionValues"][0]["value"] in ("(not set)", ""))
        a.metrics[f"ga4_{brand}_generate_lead_30d"] = tot
        a.metrics[f"ga4_{brand}_generate_lead_unattributed"] = unattr
        if tot and unattr / tot > 0.5:
            a.finding(
                "GA4-LEADS-UNATTRIBUTED", "high", brand, "ga4",
                f"{unattr}/{tot} generate_lead events have no hostname",
                "These arrive server-side with no session join, so no channel, "
                "campaign or source can be credited for the lead.",
                "Fire generate_lead client-side, or pass session_id/client_id "
                "into the Measurement Protocol calls.")


def check_google_ads(a: Audit, brands: list[str]) -> None:
    """Is anything actually reaching the bidder?"""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "gads", os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "google-ads", "server.py"))
        gads = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gads)
        client = gads._ads_client()
        svc = client.get_service("GoogleAdsService")
    except Exception as exc:
        a.degrade("google-ads", exc)
        return

    for brand in brands:
        cid = ADS_ACCOUNT[brand]
        try:
            q = """SELECT conversion_action.name, conversion_action.category,
                   conversion_action.origin, conversion_action.primary_for_goal,
                   metrics.all_conversions FROM conversion_action
                   WHERE conversion_action.status='ENABLED'
                   AND segments.date DURING LAST_30_DAYS"""
            primary_total, primary_zero = 0.0, []
            for row in svc.search(customer_id=cid, query=q):
                ca = row.conversion_action
                if not ca.primary_for_goal:
                    continue
                conv = row.metrics.all_conversions
                primary_total += conv
                if conv == 0 and ca.origin.name != "LOCAL_SERVICES_ADS":
                    primary_zero.append(ca.name)
            a.metrics[f"ads_{brand}_primary_conversions_30d"] = round(primary_total, 1)

            if primary_total < 10:
                a.finding(
                    "ADS-NO-SIGNAL", "critical", brand, "google-ads",
                    f"Only {primary_total:.0f} primary conversions in 30 days",
                    "Smart Bidding needs roughly 15+/month to optimise. Below "
                    "that it is effectively spending blind.",
                    "Verify conversion tags fire, and promote the actions that "
                    "actually record volume to primary.")
            if len(primary_zero) >= 3:
                a.finding(
                    "ADS-DEAD-PRIMARIES", "low", brand, "google-ads",
                    f"{len(primary_zero)} primary actions recorded zero in 30d",
                    "Zero-volume primaries dilute the goal set: " +
                    ", ".join(primary_zero[:6]),
                    "Demote the ones that are duplicates or genuinely retired.")

            # Biddability: a promoted action whose category+origin is not
            # biddable contributes nothing. This is subtle and easy to miss.
            biddable = set()
            for row in svc.search(customer_id=cid, query="""
                    SELECT customer_conversion_goal.category,
                           customer_conversion_goal.origin,
                           customer_conversion_goal.biddable
                    FROM customer_conversion_goal"""):
                cg = row.customer_conversion_goal
                if cg.biddable:
                    biddable.add((cg.category.name, cg.origin.name))
            for row in svc.search(customer_id=cid, query=q):
                ca = row.conversion_action
                if not ca.primary_for_goal or row.metrics.all_conversions == 0:
                    continue
                pair = (ca.category.name, ca.origin.name)
                if pair not in biddable and ca.origin.name != "LOCAL_SERVICES_ADS":
                    a.finding(
                        "ADS-GOAL-NOT-BIDDABLE", "high", brand, "google-ads",
                        f"'{ca.name}' records conversions but its goal is not biddable",
                        f"{pair[0]}/{pair[1]} is switched off in the account's "
                        "conversion goals, so this volume never informs bidding.",
                        "Enable that category/origin in Goals > Settings.")

            # Spend with nothing to show for it.
            q2 = """SELECT campaign.name, campaign.advertising_channel_type,
                    metrics.cost_micros, metrics.clicks, metrics.all_conversions
                    FROM campaign WHERE campaign.status='ENABLED'
                    AND segments.date DURING LAST_30_DAYS"""
            for row in svc.search(customer_id=cid, query=q2):
                spend = row.metrics.cost_micros / 1e6
                if spend >= 100 and row.metrics.all_conversions == 0:
                    a.finding(
                        "ADS-SPEND-NO-CONV", "high", brand, "google-ads",
                        f"'{row.campaign.name}' spent ${spend:,.0f} with 0 conversions",
                        f"{row.metrics.clicks} clicks, nothing recorded in 30 days.",
                        "Confirm tracking is intact for this campaign, then pause "
                        "it if the traffic is genuinely junk.")

            # The container's conversion id must match the account's.
            for row in svc.search(customer_id=cid, query="""
                    SELECT customer.conversion_tracking_setting.conversion_tracking_id
                    FROM customer"""):
                got = str(row.customer.conversion_tracking_setting.conversion_tracking_id)
                if got != ADS_CONVERSION_ID[brand]:
                    a.finding(
                        "ADS-CONV-ID-DRIFT", "critical", brand, "google-ads",
                        f"Conversion tracking id is {got}, expected "
                        f"{ADS_CONVERSION_ID[brand]}",
                        "Tags built against the old id will not register.",
                        "Reconcile the account's conversion tracking id.")
        except Exception as exc:
            a.degrade(f"google-ads:{brand}", exc)


def check_highlevel(a: Audit, brands: list[str]) -> None:
    """PIT validity, and legacy trackers still pasted into funnel code."""
    for brand in brands:
        env = f"GHL_PIT_{brand}"
        token = os.environ.get(env)
        if not token:
            a.degrade(f"highlevel:{brand}", f"{env} not set")
            continue
        hdr = {"Authorization": f"Bearer {token}", "Version": "2021-07-28"}
        loc = GHL_LOCATION[brand]
        try:
            curl(f"https://services.leadconnectorhq.com/locations/{loc}", hdr)
        except Exception as exc:
            a.finding(
                "GHL-TOKEN-DEAD", "critical", brand, "highlevel",
                f"{env} rejected by HighLevel",
                str(exc)[:160],
                "Regenerate the location's Private Integration Token.")
            continue
        try:
            data = json.loads(curl(
                f"https://services.leadconnectorhq.com/funnels/funnel/list?locationId={loc}",
                hdr, timeout=45))
        except Exception as exc:
            a.degrade(f"highlevel-funnels:{brand}", exc)
            continue

        dirty = {}
        for fn in data.get("funnels", []):
            blob = (fn.get("trackingCodeHead") or "") + "\n" + (fn.get("trackingCodeBody") or "")
            hits = [label for pat, label in LEGACY_TRACKERS
                    if re.search(pat, blob, re.I)]
            if hits:
                dirty[fn.get("name", "?")] = hits
        a.metrics[f"ghl_{brand}_funnels_with_legacy_trackers"] = len(dirty)
        if dirty:
            sample = "; ".join(f"{k}: {', '.join(v)}" for k, v in list(dirty.items())[:5])
            a.finding(
                "GHL-LEGACY-TRACKERS", "high", brand, "highlevel",
                f"{len(dirty)} funnels still carry retired tracking code",
                sample + ("; ..." if len(dirty) > 5 else ""),
                "Remove them in Funnel > Settings > Tracking Code.")


def check_meta(a: Audit, brands: list[str]) -> None:
    """Is the canonical pixel still receiving events?"""
    token = os.environ.get("META_ACCESS_TOKEN") or os.environ.get("FB_ACCESS_TOKEN")
    if not token:
        a.degrade("meta", "no META_ACCESS_TOKEN — checked via MCP connector instead")
        return
    for brand in brands:
        pid = META_PIXEL[brand]
        try:
            data = json.loads(curl(
                f"https://graph.facebook.com/v21.0/{pid}"
                f"?fields=name,last_fired_time,server_last_fired_time"
                f"&access_token={token}"))
        except Exception as exc:
            a.degrade(f"meta:{brand}", exc)
            continue
        last = data.get("last_fired_time", "")
        a.metrics[f"meta_{brand}_last_fired"] = last
        if last and last.startswith("1969"):
            a.finding(
                "META-PIXEL-SILENT", "high", brand, "meta",
                f"Canonical pixel {pid} has never fired",
                f"Pixel '{data.get('name')}' shows no browser events.",
                "Confirm the pixel is installed on the live site.")


def check_clarity(a: Audit, brands: list[str]) -> None:
    """Clarity reachable and actually recording sessions."""
    for brand in brands:
        token = os.environ.get(f"CLARITY_{brand}_TOKEN")
        if not token:
            a.degrade(f"clarity:{brand}", f"CLARITY_{brand}_TOKEN not set")
            continue
        try:
            raw = curl(
                "https://www.clarity.ms/export-data/api/v1/project-live-insights"
                "?numOfDays=1",
                {"Authorization": f"Bearer {token}"})
            data = json.loads(raw)
        except Exception as exc:
            a.degrade(f"clarity:{brand}", exc)
            continue
        sessions = 0
        if isinstance(data, list):
            for metric in data:
                for info in metric.get("information", []):
                    try:
                        sessions = max(sessions, int(info.get("sessionsCount") or 0))
                    except (TypeError, ValueError):
                        pass
        a.metrics[f"clarity_{brand}_sessions_24h"] = sessions
        if sessions == 0:
            a.finding(
                "CLARITY-NO-SESSIONS", "high", brand, "clarity",
                f"Clarity recorded 0 sessions in 24h for {brand}",
                "Either the tag stopped firing or its trigger excludes the "
                "hostnames that carry real traffic.",
                "Check the Clarity tag's hostname regex in GTM.")


# ----------------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", help="write JSON here instead of stdout")
    ap.add_argument("--brand", choices=["KTU", "BTU"], help="limit to one brand")
    args = ap.parse_args()
    brands = [args.brand] if args.brand else ["KTU", "BTU"]

    a = Audit()
    for name, fn in [
        ("gtm", check_gtm), ("live pages", check_live_pages), ("ga4", check_ga4),
        ("google ads", check_google_ads), ("highlevel", check_highlevel),
        ("meta", check_meta), ("clarity", check_clarity),
    ]:
        try:
            fn(a, brands)
        except Exception as exc:          # a broken check must not kill the sweep
            a.degrade(name, exc)

    a.findings.sort(key=lambda f: -SEVERITY_RANK.get(f["severity"], 0))
    now = datetime.now(ET)
    doc = {
        "scan_date": now.date().isoformat(),
        "generated_at": now.isoformat(),
        "status": a.status,
        "summary": {
            "critical": sum(1 for f in a.findings if f["severity"] == "critical"),
            "high": sum(1 for f in a.findings if f["severity"] == "high"),
            "low": sum(1 for f in a.findings if f["severity"] == "low"),
            "degradations": len(a.degradations),
        },
        "findings": a.findings,
        "metrics": a.metrics,
        "degradations": a.degradations,
    }
    text = json.dumps(doc, indent=2)
    if args.out:
        with open(args.out, "w") as fh:
            fh.write(text)
        s = doc["summary"]
        print(f"{doc['status']}  critical={s['critical']} high={s['high']} "
              f"low={s['low']} degraded={s['degradations']} -> {args.out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
