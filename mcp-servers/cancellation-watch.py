#!/usr/bin/env python3
"""
cancellation-watch.py — weekly KTU in-home consultation cancellation report.

Measures cancellations against the agreed ceiling: only client-requested,
out-of-territory, non-cabinet-scope and repair-only cancellations are allowed,
and together they should be no more than ALLOWED_CEILING of booked consults.
Anything above that line has to be replaced with paid lead generation, so the
report prices the overage at the real cost per acquired lead.

Writes two things and sends nothing itself:
  report_snapshots.cancel_watch   subject + body the scheduler mails out
  intranet_records/cancel_watch   the rows the intranet Reports tab renders

Delivery is the scheduler's job (public.enqueue_due_reports, hourly pg_cron),
driven by report_schedules — so frequency and recipients are edited on the
intranet, never here.

WHAT THIS CAN AND CANNOT SEE — read before trusting a "no reason" count.
The free-text appointment note that carries most real cancellation reasons is
NOT reachable from any API: appointments/find returns Notes:null, the Org
Download API's appointments dataset has no Notes column, and appointments/query
never had one. Only the ServiceMinder UI export has it. So this report
classifies from what IS reachable — the CancelReasonId picklist and the
contact's Notes[] activity log — and counts everything else as "no reason
captured", which is deliberate: an unlogged cancellation is indistinguishable
from a preventable one, so it counts against the ceiling. The fix is the
picklist: it is currently set on ~20% of cancellations and 90% of those say
"Other", which classifies nothing.

All HTTP goes through the curl helpers on purpose. Scheduled Routines run in
Auto mode, where an mcp__* call stalls forever waiting for a permission prompt
nobody can answer (see CLAUDE.md). Bash is not gated.

Usage:
  python3 mcp-servers/cancellation-watch.py                  # last full week
  python3 mcp-servers/cancellation-watch.py --days 30
  python3 mcp-servers/cancellation-watch.py --dry-run        # print, write nothing
"""
from __future__ import annotations
import argparse, datetime as dt, json, re, subprocess, sys, os
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
SM = os.path.join(HERE, "sm.sh")
SB = os.path.join(HERE, "sb.sh")

LOCATION = "KTU"
SERVICE = "Consultation - In-Home"
REPORT_KEY = "cancel_watch"

# The agreed standard. 24% is what the allowed reasons actually came to across
# Jan-Aug 2026 (73 of 308 booked consults), so it is an observed rate held as a
# ceiling, not an invented target.
ALLOWED_CEILING = 0.24
# KTU Google Ads YTD: $24,939 spend / 119 conversions (paid_brief, 2026-08-30).
COST_PER_LEAD = 210

STATUS = {0: "Tentative", 1: "Scheduled", 3: "Completed", 4: "Cancelled"}

# --- classification -------------------------------------------------------
# A contact's Notes[] array is mostly BOOKING context — the Perceptionist call
# that made the appointment, the web form, the stated budget range. None of that
# says why the appointment was later cancelled, and reading it as if it did
# produces confident nonsense ("Budget: $30,000-$40,000" scored as a price
# objection when it is the customer's stated budget at booking).
#
# So classification is two-stage: find note fragments that actually carry
# cancellation intent, and only classify those. A contact with rich booking
# notes and nothing about the cancellation is "No reason captured" — which is
# the honest answer and the one that drives the behaviour we want.
CANCEL_INTENT = re.compile(
    r"cancel|reschedul|re-?book|postpon|push(ed)? (it )?(back|out)|not ready|"
    r"call(ing)? back when|no longer|changed (their|his|her) mind|"
    r"went with|another contractor|competitor|"
    r"out(side)? (of )?(our |the )?(service )?(area|territory)|not (in )?our territory|"
    r"do(es)? not service|don'?t service|transferred to|"
    r"too (high|expensive|much)|over (his|her|their) budget|not in (his|her|their) budget|"
    r"budget is (nowhere|not|too)|can'?t afford|cannot afford|"
    r"no ?show|did not (answer|respond)|never responded|unreachable|"
    r"duplicate|double ?book|"
    r"not off?ered|does not fit our model|no cabinet|repair only",
    re.I)

# Ordered, most specific first. Applied ONLY to cancellation-intent fragments.
RULES: list[tuple[re.Pattern, str, bool]] = [
    (re.compile(r"out(side)? (of )?(our |the )?(service )?(area|territory)|not (in )?our territory|"
                r"do(es)? not service|don'?t service|wrong territory|transferred to (other|another)",
                re.I), "Out of territory", True),
    (re.compile(r"no cabinet|not cabinet|counter ?tops? only|appliance only|"
                r"service (desired )?not off?ered|does not fit our model|not our (model|scope)",
                re.I), "Non-cabinet scope", True),
    (re.compile(r"\brepair(s| only)?\b|handyman|touch ?up only|single door|one door", re.I),
     "Repair only", True),
    (re.compile(r"reschedul|re-?book|call(ing)? back when|will call back|another (time|date)|"
                r"push(ed)? (it )?(back|out)|postpon|not ready|next (year|spring|summer|fall)",
                re.I), "Client requested — reschedule or postpone", True),
    (re.compile(r"cancel|changed (their|his|her) mind|no longer interested|"
                r"went a different direction", re.I),
     "Client requested — cancelled", True),
    (re.compile(r"too (high|expensive|much)|over (his|her|their) budget|"
                r"not in (his|her|their) budget|budget is (nowhere|not|too)|"
                r"can'?t afford|cannot afford", re.I), "Price above budget", False),
    (re.compile(r"another contractor|went with|competitor|chose someone", re.I),
     "Lost to a competitor", False),
    (re.compile(r"duplicate|double ?book|booked twice|same slot", re.I),
     "Duplicate or booking error", False),
    (re.compile(r"no ?show|did not (answer|respond)|unreachable|never responded|"
                r"could not (reach|contact)", re.I), "Unreachable / no-show", False),
]

def run(cmd: list[str]) -> str:
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if p.returncode != 0:
        raise RuntimeError(f"{cmd[1]} failed: {p.stderr[:300]}")
    return p.stdout


def sm(path: str, payload: dict) -> dict:
    out = run(["bash", SM, LOCATION, path, json.dumps(payload)])
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        raise RuntimeError(f"{path} returned non-JSON: {out[:200]}")


def sb(sql: str):
    out = run(["bash", SB, sql])
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        raise RuntimeError(f"supabase returned non-JSON: {out[:300]}")


def q(s) -> str:
    """Single-quote a value for inline SQL."""
    return "'" + str(s if s is not None else "").replace("'", "''") + "'"


JUNK = re.compile(r"\btest\w*\b|testing|^z+ |demo|do not use|sample|asdf|qwerty|holding time slot", re.I)
JUNK_PHONE = re.compile(r"^(\d)\1{6,}$|^123456|^555")


def is_junk(name: str, phone: str, city: str, api_key: str, created_by: str) -> bool:
    blob = f"{name} {city}"
    if JUNK.search(blob):
        return True
    if JUNK_PHONE.match(re.sub(r"\D", "", phone or "")):
        return True
    if (api_key or "").strip() == "KTUApp" or (created_by or "").strip() == "Support":
        return True
    return False


def cancel_fragments(text: str) -> str:
    """Only the parts of the note that actually talk about the cancellation."""
    keep = [seg.strip() for seg in re.split(r"\s*\|+\s*|(?<=[.!?])\s+", text or "")
            if seg.strip() and CANCEL_INTENT.search(seg)]
    return " | ".join(keep)


def classify(text: str) -> tuple[str, bool, str]:
    """-> (category, allowed, the fragment the call was made on)."""
    frag = cancel_fragments(text)
    if not frag:
        return "No reason captured", False, ""
    for rx, cat, allowed in RULES:
        if rx.search(frag):
            return cat, allowed, frag
    return "Reason logged but unclassified", False, frag


def strip_html(t: str) -> str:
    t = re.sub(r"<[^>]+>", " ", t or "")
    t = re.sub(r"https?://\S+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def contact_notes(cid: int) -> str:
    """Every note on the contact, newest last. '' when the contact has none."""
    try:
        d = sm("contacts/locate", {"IdSearch": str(cid)})
    except Exception:
        return ""
    for m in d.get("Matches") or []:
        if str(m.get("Id")) != str(cid):
            continue
        parts = []
        for n in sorted(m.get("Notes") or [], key=lambda x: x.get("Id") or 0):
            b = strip_html(n.get("Body") or "")
            if b and b.lower() not in ("undefined", "null", "n/a", "."):
                parts.append(f"{(n.get('Title') or '').strip()}: {b}".strip(": "))
        return " | ".join(parts)
    return ""


def fetch(frm: str, thr: str) -> list[dict]:
    d = sm("appointments/query", {"FromDate": frm, "ThroughDate": thr,
                                  "Take": 500, "IncludeContact": True})
    out = []
    for a in d.get("Appointments") or []:
        if a.get("ServiceName") != SERVICE:
            continue
        c = a.get("Contact") or {}
        out.append({
            "id": a.get("AppointmentId"), "contact_id": a.get("ContactId"),
            "when": a.get("DateTime"), "status": a.get("Status"),
            "cancel_reason_id": a.get("CancelReasonId"),
            "agent": a.get("ServiceAgentName") or "",
            "name": (c.get("Name") or "").strip(), "city": (c.get("City") or "").strip(),
            "phone": c.get("Phone") or "", "email": c.get("Email") or "",
            "addr": c.get("Address1") or "", "zip": c.get("Zip") or "",
            "channel": c.get("Channel") or "", "campaign": c.get("Campaign") or "",
            "api_key": a.get("ApiKey") or "", "created_by": "",
        })
    return out


def build(days: int, frm: str, thr: str) -> tuple[dict, list[dict]]:
    rows = fetch(frm, thr)
    kept, seen = [], set()
    for r in rows:
        if is_junk(r["name"], r["phone"], r["city"], r["api_key"], r["created_by"]):
            continue
        k = (r["contact_id"], str(r["when"]), r["status"])
        if k in seen:
            continue
        seen.add(k)
        kept.append(r)
    real, junk_n = kept, len(rows) - len(kept)

    cancelled = [r for r in real if r["status"] == 4]
    attended = [r for r in real if r["status"] == 3]

    detail = []
    for r in cancelled:
        note = contact_notes(r["contact_id"])
        cat, allowed, frag = classify(note)
        # An explicit picklist value that is not the catch-all still counts as logged.
        rid = r.get("cancel_reason_id")
        if cat == "No reason captured" and rid and int(rid) not in (0, 3523):
            cat, allowed = f"Picklist reason {rid}", True
        r = {**r, "note": note, "evidence": frag, "category": cat, "allowed": allowed}
        detail.append(r)

    booked = len(real)
    n_can = len(cancelled)
    allowed = [r for r in detail if r["allowed"]]
    breaches = [r for r in detail if not r["allowed"]]
    unlogged = [r for r in detail if r["category"] == "No reason captured"]

    ceiling_n = round(booked * ALLOWED_CEILING)
    over = max(0, n_can - ceiling_n)

    m = {
        "window_days": days, "from": frm, "through": thr,
        "booked": booked, "attended": len(attended), "cancelled": n_can,
        "junk_excluded": junk_n,
        "cancel_rate": round(n_can / booked, 4) if booked else None,
        "allowed": len(allowed),
        "allowed_rate_of_booked": round(len(allowed) / booked, 4) if booked else None,
        "breaches": len(breaches), "unlogged": len(unlogged),
        "ceiling": ALLOWED_CEILING, "ceiling_count": ceiling_n,
        "over_ceiling": over, "spend_impact": over * COST_PER_LEAD,
        "cost_per_lead": COST_PER_LEAD,
        "in_ceiling": n_can <= ceiling_n,
        "categories": dict(Counter(r["category"] for r in detail)),
    }
    return m, detail


def render(m: dict, detail: list[dict]) -> tuple[str, str]:
    pct = lambda x: "—" if x is None else f"{x*100:.0f}%"
    verdict = "WITHIN CEILING" if m["in_ceiling"] else "OVER CEILING"
    subject = (f"[KTU] Cancellation Watch {m['from']} → {m['through']} — "
               f"{m['cancelled']}/{m['booked']} cancelled ({pct(m['cancel_rate'])}), {verdict}")

    L = []
    L.append(f"KTU in-home consultations · {m['from']} to {m['through']}")
    L.append("=" * 64)
    L.append("")
    L.append(f"  Booked                {m['booked']}")
    L.append(f"  Attended              {m['attended']}")
    L.append(f"  Cancelled             {m['cancelled']}  ({pct(m['cancel_rate'])} of booked)")
    L.append("")
    L.append(f"  Allowed reasons       {m['allowed']}  ({pct(m['allowed_rate_of_booked'])} of booked)")
    L.append(f"  Ceiling               {int(m['ceiling']*100)}% of booked = {m['ceiling_count']} cancellations")
    L.append(f"  STATUS                {verdict}")
    if m["over_ceiling"]:
        L.append(f"  Over by               {m['over_ceiling']} consults")
        L.append(f"  Replacement cost      ${m['spend_impact']:,} "
                 f"({m['over_ceiling']} × ${m['cost_per_lead']}/lead)")
    L.append("")
    L.append("Allowed = client-requested, out of territory, non-cabinet scope, or repair only.")
    L.append("")
    L.append("Cancellations by reason")
    L.append("-" * 64)
    for cat, n in sorted(m["categories"].items(), key=lambda kv: -kv[1]):
        mark = "ok " if any(r["allowed"] for r in detail if r["category"] == cat) else "OUT"
        L.append(f"  {mark}  {n:3d}  {cat}")
    L.append("")

    if m["unlogged"]:
        L.append(f"NO REASON CAPTURED — {m['unlogged']} of {m['cancelled']}")
        L.append("-" * 64)
        L.append("These count against the ceiling. Set a real cancel reason on the")
        L.append("appointment (not \"Other\") and they classify automatically.")
        for r in [x for x in detail if x["category"] == "No reason captured"]:
            L.append(f"  · {r['name'] or '(no name)'} — {r['city']} — "
                     f"{str(r['when'])[:10]} — {r['phone']}")
        L.append("")

    outs = [r for r in detail if not r["allowed"] and r["category"] != "No reason captured"]
    if outs:
        L.append(f"OUTSIDE THE ALLOWED REASONS — {len(outs)}")
        L.append("-" * 64)
        for r in outs:
            L.append(f"  · {r['name'] or '(no name)'} — {r['city']} — {r['category']}")
            if r.get("evidence"):
                L.append(f"      {r['evidence'][:220]}")
        L.append("")

    if m["junk_excluded"]:
        L.append(f"({m['junk_excluded']} test/system record(s) excluded from every figure above.)")
    L.append("How this is measured")
    L.append("-" * 64)
    L.append("Counts come from ServiceMinder appointments; reasons come from the cancel-")
    L.append("reason picklist and the contact's note log. The free-text note typed on the")
    L.append("appointment itself is NOT readable by any API — only by the manual UI export —")
    L.append("so a reason written only there shows here as \"no reason captured\". That is a")
    L.append("tooling limit, not a judgement: the way to close it is the cancel-reason")
    L.append("picklist on the appointment, which is currently set on about a fifth of")
    L.append("cancellations and reads \"Other\" nine times in ten. Picklist set = classified")
    L.append("automatically, here and everywhere else.")
    L.append("")
    L.append("Full detail, history and the recovery list: https://dash.goaxyom.com → Reports")
    L.append("Change this report's frequency or recipients on that same tab.")
    return subject, "\n".join(L)


def publish(m: dict, detail: list[dict], subject: str, body: str) -> None:
    sb(f"""insert into report_snapshots(report_key, generated_at, subject, body, metrics)
           values ({q(REPORT_KEY)}, now(), {q(subject)}, {q(body)}, {q(json.dumps(m))}::jsonb)
           on conflict (report_key) do update
             set generated_at = now(), subject = excluded.subject,
                 body = excluded.body, metrics = excluded.metrics;""")

    scan = dt.date.today().isoformat()
    rows = []

    def rec(sort, fields):
        fields = {**fields, "scan_date": scan, "report_key": REPORT_KEY}
        rows.append(f"('cancel_watch','KTU',{sort},{q(json.dumps(fields))}::jsonb)")

    rec(0, {"kind": "headline",
            "severity": "ok" if m["in_ceiling"] else "urgent",
            "title": (f"{m['cancelled']} of {m['booked']} consults cancelled "
                      f"({m['cancel_rate']*100:.0f}%) — "
                      + ("within the 24% allowed ceiling" if m["in_ceiling"]
                         else f"{m['over_ceiling']} over the ceiling, "
                              f"${m['spend_impact']:,} to replace")),
            "detail": (f"{m['allowed']} cancellations were for allowed reasons "
                       f"({m['allowed_rate_of_booked']*100:.0f}% of booked). "
                       f"{m['unlogged']} had no reason captured and count against the ceiling."),
            "window": f"{m['from']} to {m['through']}",
            "source": "ServiceMinder appointments/query + contacts/locate"})
    for i, (cat, n) in enumerate(sorted(m["categories"].items(), key=lambda kv: -kv[1]), 1):
        allowed = any(r["allowed"] for r in detail if r["category"] == cat)
        rec(i, {"kind": "reason", "reason": cat, "count": n,
                "allowed": "Allowed" if allowed else "Counts against ceiling",
                "severity": "ok" if allowed else "warn"})
    for j, r in enumerate([x for x in detail if not x["allowed"]], 1):
        rec(100 + j, {"kind": "breach", "customer": r["name"], "city": r["city"],
                      "phone": r["phone"], "email": r["email"],
                      "when": str(r["when"])[:16], "reason": r["category"],
                      "note": (r.get("evidence") or "")[:500],
                      "full_note": (r["note"] or "")[:900], "channel": r["channel"],
                      "campaign": r["campaign"], "severity": "warn"})

    sb("delete from intranet_records where section='cancel_watch';")
    for i in range(0, len(rows), 40):
        sb("insert into intranet_records(section,brand,sort_order,fields) values "
           + ",".join(rows[i:i + 40]) + ";")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=0,
                    help="trailing window; default is the last full Mon-Sun week")
    ap.add_argument("--from", dest="frm"), ap.add_argument("--through", dest="thr")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    if a.frm and a.thr:
        frm, thr = a.frm, a.thr
        days = (dt.date.fromisoformat(thr) - dt.date.fromisoformat(frm)).days + 1
    elif a.days:
        today = dt.date.today()
        frm, thr, days = (today - dt.timedelta(days=a.days)).isoformat(), today.isoformat(), a.days
    else:
        today = dt.date.today()
        last_sun = today - dt.timedelta(days=(today.weekday() + 1) % 7 or 7)
        frm, thr, days = (last_sun - dt.timedelta(days=6)).isoformat(), last_sun.isoformat(), 7

    m, detail = build(days, frm, thr)
    subject, body = render(m, detail)
    print(subject); print(); print(body)
    if a.dry_run:
        print("\n[dry-run] nothing written")
        return 0
    publish(m, detail, subject, body)
    print(f"\npublished report_snapshots.{REPORT_KEY} and intranet_records/cancel_watch")
    return 0


if __name__ == "__main__":
    sys.exit(main())
