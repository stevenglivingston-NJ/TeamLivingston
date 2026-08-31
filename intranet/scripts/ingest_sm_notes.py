#!/usr/bin/env python3
"""
ingest_sm_notes.py — fill `sm_notes` from both directions.

TWO SOURCES, ONE TABLE

  liquid : ServiceMinder notification emails land in `inbox_emails` with an
           `SM-` subject prefix and a JSON envelope in the body. This is the
           ONLY way appointment notes can reach us — the Open API is blind to
           them (verified 2026-08-29 on KTU appt 51051472: appointments/find
           returns Notes:null, appointments/query has no note field, and the org
           download has no Notes column, while the SM UI shows a rep note that
           IS the cancellation reason).

  api    : contact notes (contacts/locate -> Matches[].Notes[]) and proposal
           notes (proposal/details -> Notes[]) are readable directly, so we
           backfill those on a schedule instead of waiting for a notification
           to fire. This is what makes historical rows work — the Liquid feed
           only ever covers events from its install date forward.

Identity is (brand, source, sm_note_id), so re-delivery and re-runs upsert
rather than duplicate.

KNOWN LIMIT OF THE API PATH: contacts/locate returns notes as {Id, Title, Body,
Private} only — no CreatedBy, no CreatedOn. So api-sourced rows land with
authored_by and authored_at NULL. That is the API's limit, not a bug here, and
it is why the Liquid feed is worth installing even for contact notes: only
Liquid carries attribution and timestamps. Readers must render a missing author
or date gracefully rather than treating it as suspicious.

Usage:
    python3 intranet/scripts/ingest_sm_notes.py --liquid          # drain inbox_emails
    python3 intranet/scripts/ingest_sm_notes.py --api-contacts    # backfill contact notes
    python3 intranet/scripts/ingest_sm_notes.py --api-proposals   # backfill proposal notes
    python3 intranet/scripts/ingest_sm_notes.py --all
    ... add --dry-run to any of the above.
"""
import argparse, json, os, re, subprocess, sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SB = os.path.join(REPO, "mcp-servers", "sb.sh")
SM = os.path.join(REPO, "mcp-servers", "sm.sh")

BEGIN = "---SM-NOTES-JSON-BEGIN---"
END = "---SM-NOTES-JSON-END---"

# Free-text blocks, carried OUTSIDE the JSON. See TEXT BLOCKS in the module
# docstring: ServiceMinder's notification body is shortcode substitution, not
# Liquid, so there is no filter to escape a value with. A note body pasted
# inside a JSON string breaks the JSON on the first straight quote or newline
# the rep typed — which is every long note worth capturing. Outside the JSON,
# nothing needs escaping at all.
TEXT_OPEN = re.compile(r"^---SM-TEXT:([a-z_]+)---$", re.M)
TEXT_CLOSE = "---SM-TEXT-END---"

# Mail gateways rewrite quotes and wrap long lines. Both corrupt JSON, and both
# are cheap to undo before parsing.
SMART_QUOTES = {"“": '"', "”": '"', "‘": "'", "’": "'"}


def sql_lit(s):
    if s is None:
        return "NULL"
    return "'" + str(s).replace("'", "''") + "'"


def sb(sql):
    r = subprocess.run(["bash", SB, sql], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"sb.sh failed: {r.stderr[:400]}")
    out = (r.stdout or "").strip()
    if not out:
        return []
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        raise RuntimeError(f"sb.sh returned non-JSON: {out[:300]}")
    # PostgREST reports failures as an OBJECT, not a list. Returning it as-is
    # meant callers iterated a dict and got its KEYS — so a missing table
    # surfaced as `'str' object has no attribute 'get'` several frames later
    # instead of saying what was actually wrong. Fail here, loudly.
    if isinstance(data, dict):
        if "error" in data or "message" in data:
            raise RuntimeError(f"SQL failed: {json.dumps(data)[:400]}")
        return [data]
    return data


def sm(location, endpoint, body):
    r = subprocess.run(["bash", SM, location, endpoint, json.dumps(body)],
                       capture_output=True, text=True)
    try:
        return json.loads(r.stdout or "{}")
    except json.JSONDecodeError:
        return {}


def normalise_brand(raw):
    """SM sends the organization NAME, which is not 'KTU'/'BTU'.

    Match on the distinguishing word rather than the full string — the org names
    have been written several ways over the years ("Kitchen Tune-Up Bloomfield",
    "Kitchen Tune Up - Bloomfield NJ") and an exact-match table would rot.
    """
    s = (raw or "").lower()
    if "bath" in s:
        return "BTU"
    if "kitchen" in s:
        return "KTU"
    if s.strip().upper() in ("KTU", "BTU"):
        return s.strip().upper()
    return None


def extract_envelope(body):
    """Slice the JSON out of a notification email and parse it.

    ORDER MATTERS. Parse the chunk AS-IS first, and only attempt repairs if
    that fails. The earlier version repaired first, which broke the exact case
    this whole feature exists for: curly quotes inside a note body are valid
    JSON (just Unicode), and blanket-replacing them with straight quotes turns
    a legitimate body into a syntax error. Ben Yabra's cancellation note —
    Client wrote "I tried to write in..." — contains three of them, so the
    repair-first version failed on the very note we are trying to capture.

    Repairs are therefore a fallback for genuinely mangled mail (a client that
    smart-quoted the STRUCTURAL quotes, or quoted-printable soft line breaks),
    tried one at a time from least to most destructive.
    """
    if not body or BEGIN not in body:
        return None
    chunk = body.split(BEGIN, 1)[1].split(END, 1)[0]
    texts = extract_text_blocks(body)

    attempts = [
        ("as-is", chunk),
        # Quoted-printable soft line breaks: safe, they are never real content.
        ("unwrap soft line breaks", chunk.replace("=\r\n", "").replace("=\n", "")),
        # Last resort: the mail client smart-quoted the structure itself. This
        # also rewrites curly quotes inside bodies, so only reach for it when
        # nothing else parses.
        ("straighten quotes", _straighten(chunk)),
    ]
    last = None
    for label, candidate in attempts:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError as exc:
            last = (label, exc)
            continue
        if label != "as-is":
            print(f"    envelope parsed after repair: {label}", file=sys.stderr)
        # Text blocks win over any same-named JSON key: the JSON copy is the
        # one that could have been truncated by a stray quote, the text block
        # cannot be.
        if isinstance(parsed, dict):
            parsed.update(texts)
        return parsed
    print(f"    envelope present but unparseable ({last[0]}): {last[1]}", file=sys.stderr)
    return None


def extract_text_blocks(body):
    """Pull `---SM-TEXT:key---` ... `---SM-TEXT-END---` blocks out of the body.

    Values are returned verbatim apart from surrounding whitespace — no quote
    repair, no escaping, no JSON. That is the whole point: this is where a
    multi-line note with the rep's own quotation marks in it can travel safely.
    """
    out = {}
    for m in TEXT_OPEN.finditer(body or ""):
        key = m.group(1)
        rest = body[m.end():]
        if TEXT_CLOSE not in rest:
            print(f"    text block {key!r} has no closing sentinel — skipped",
                  file=sys.stderr)
            continue
        val = rest.split(TEXT_CLOSE, 1)[0].strip()
        # An unfilled shortcode arrives as the literal shortcode text. Treat it
        # as empty rather than storing "{appointment.notes_summary}" as a note.
        if val.startswith("{") and val.endswith("}") and " " not in val:
            continue
        if val:
            out[key] = val
    return out


def synthesize_notes(env):
    """Build a note list when the feed could only send a flattened string.

    ServiceMinder's shortcode templating has no loop construct, so a
    notification cannot iterate `appointment.notes` into an array the way the
    Liquid-based drafts assumed. What it CAN send is a single flattened
    summary. One synthetic note is better than none — the prose is the value
    here, and the alternative is an empty Appointment Recovery tab.

    The synthetic id is the NEGATED appointment/proposal id. Real ServiceMinder
    note ids are positive, so a negative id cannot collide with one, and it is
    stable across re-delivery so `(brand, source, sm_note_id)` still upserts
    instead of duplicating. If the real per-note array ever becomes available,
    those rows land alongside under their own positive ids.
    """
    if env.get("notes"):
        return env["notes"]
    text = (env.get("notes_summary") or env.get("note_body") or "").strip()
    if not text:
        return []
    anchor_id = env.get("appointment_id") or env.get("proposal_id")
    try:
        anchor_id = int(str(anchor_id).strip())
    except (TypeError, ValueError):
        return []
    return [{
        "id": -abs(anchor_id),
        "title": "Notes (flattened feed)",
        "body": text,
        "private": False,
        "created_by": env.get("owner"),
        "created_at": env.get("cancelled_at") or env.get("scheduled"),
    }]


def _straighten(text):
    for bad, good in SMART_QUOTES.items():
        text = text.replace(bad, good)
    return text


def upsert_note(brand, source, note, *, contact_id=None, appointment_id=None,
                proposal_id=None, via="api", dry=False):
    """Returns True when a row was written (or would be)."""
    sm_note_id = note.get("id") or note.get("Id")
    body = (note.get("body") or note.get("Body") or "").strip()
    if not sm_note_id or not body:
        return False  # a note with no id can't be deduped; with no body, nothing to show
    title = note.get("title") or note.get("Title")
    private = bool(note.get("private") or note.get("Private") or False)
    author = note.get("created_by") or note.get("CreatedBy")
    if isinstance(author, dict):
        author = author.get("Name") or author.get("name")
    authored = note.get("created_at") or note.get("CreatedAt") or note.get("CreatedOn")

    if dry:
        return True

    sb(f"""
        insert into sm_notes
          (brand, source, sm_note_id, contact_id, appointment_id, proposal_id,
           title, body, private, authored_by, authored_at, ingested_via)
        values
          ({sql_lit(brand)}, {sql_lit(source)}, {int(sm_note_id)},
           {contact_id or 'NULL'}, {appointment_id or 'NULL'}, {proposal_id or 'NULL'},
           {sql_lit(title)}, {sql_lit(body)}, {str(private).lower()},
           {sql_lit(author)}, {sql_lit(authored) + '::timestamptz' if authored else 'NULL'},
           {sql_lit(via)})
        on conflict (brand, source, sm_note_id) do update set
          body           = excluded.body,
          title          = excluded.title,
          private        = excluded.private,
          authored_by    = coalesce(excluded.authored_by, sm_notes.authored_by),
          authored_at    = coalesce(excluded.authored_at, sm_notes.authored_at),
          -- never let a later API backfill downgrade a Liquid-sourced row: the
          -- Liquid feed is the only one that can see appointment notes at all.
          ingested_via   = case when sm_notes.ingested_via = 'liquid'
                                then 'liquid' else excluded.ingested_via end,
          contact_id     = coalesce(excluded.contact_id, sm_notes.contact_id),
          appointment_id = coalesce(excluded.appointment_id, sm_notes.appointment_id),
          proposal_id    = coalesce(excluded.proposal_id, sm_notes.proposal_id),
          updated_at     = now()
    """)
    return True


def run_liquid(dry):
    rows = sb("select id, subject, body from inbox_emails "
              "where coalesce(processed,false) = false and subject like 'SM-%' "
              "order by received_at asc limit 500")
    print(f"[liquid] {len(rows)} unprocessed SM-* emails")
    written = skipped = 0
    for row in rows:
        env = extract_envelope(row.get("body"))
        if not env:
            print(f"  {row.get('subject')}: no parseable envelope — leaving unprocessed")
            skipped += 1
            continue
        brand = normalise_brand(env.get("brand"))
        if not brand:
            print(f"  {row.get('subject')}: brand {env.get('brand')!r} unrecognised — leaving unprocessed")
            skipped += 1
            continue
        ids = dict(contact_id=env.get("contact_id"),
                   appointment_id=env.get("appointment_id"),
                   proposal_id=env.get("proposal_id"))
        src = env.get("source") or "appointment"
        n = 0
        for note in synthesize_notes(env):
            n += upsert_note(brand, src, note, via="liquid", dry=dry, **ids)
        # The cancellation template also ships the contact's notes; store them
        # under their own source so a contact view picks them up too.
        for note in env.get("contact_notes") or []:
            n += upsert_note(brand, "contact", note, via="liquid", dry=dry,
                             contact_id=env.get("contact_id"))
        written += n
        print(f"  {row.get('subject')}: {n} notes ({src}, {brand})")
        if not dry:
            sb(f"update inbox_emails set processed = true where id = {sql_lit(row['id'])}::uuid")
    print(f"[liquid] {written} notes upserted, {skipped} emails left unprocessed")


# Sections whose notes actually drive a decision, most valuable first. A full
# sweep is 3,164 distinct contacts at roughly one API call each — ~50 minutes,
# far too slow for a daily agent run. So the backfill is PRIORITISED and CAPPED:
# each run tops up the follow-up surfaces first and stops at --limit, and the
# `not exists` guard means the next run picks up where this one left off.
# Passing --limit 0 does the full sweep when you genuinely want it.
PRIORITY_SECTIONS = (
    "appt_followups",     # cancellations — the reason this whole path exists
    "proposals",
    "proposals_lost",
    "appt_upcoming",
    "appt_completed",
    "pipeline_revival",
)


def run_from_file(path, dry):
    """Parse ONE raw ServiceMinder notification email saved to a file.

    Why this exists: `ingest-email` is an HTTP webhook, not a mailbox, and
    ServiceMinder notifications send EMAIL. The live inbound-mail path in this
    org is the Gmail pull that Goldeneye already runs against
    firstgentalent@gmail.com (via the Zapier Gmail connection). So the practical
    wiring is: SM notification -> firstgentalent -> Goldeneye's existing sweep
    picks up `subject:SM-` -> it writes each body_plain to a temp file and calls
    this. No new plumbing, no webhook SM may not support.

    (If ServiceMinder does turn out to support webhook delivery, point it at
    the ingest-email function with the dispatch_config ingest_secret token and
    use --liquid instead; both end up in the same table.)
    """
    with open(path, encoding="utf-8", errors="replace") as fh:
        body = fh.read()
    env = extract_envelope(body)
    if not env:
        print(f"[from-file] {path}: no parseable SM-NOTES envelope", file=sys.stderr)
        return 1
    brand = normalise_brand(env.get("brand"))
    if not brand:
        print(f"[from-file] {path}: brand {env.get('brand')!r} unrecognised", file=sys.stderr)
        return 1
    ids = dict(contact_id=env.get("contact_id"),
               appointment_id=env.get("appointment_id"),
               proposal_id=env.get("proposal_id"))
    src = env.get("source") or "appointment"
    n = 0
    for note in synthesize_notes(env):
        n += upsert_note(brand, src, note, via="liquid", dry=dry, **ids)
    for note in env.get("contact_notes") or []:
        n += upsert_note(brand, "contact", note, via="liquid", dry=dry,
                         contact_id=env.get("contact_id"))
    print(f"[from-file] {n} notes upserted ({src}, {brand}, appt "
          f"{env.get('appointment_id')})")
    return 0


def run_api_contacts(dry, limit=400, sections=None):
    """Backfill contact notes, newest and most decision-relevant first.

    Skips contacts already mirrored unless --refresh is passed: a contact note
    in ServiceMinder is effectively append-only, so re-fetching 3,000 unchanged
    contacts every night buys nothing.
    """
    secs = sections or PRIORITY_SECTIONS
    in_list = ", ".join(sql_lit(x) for x in secs)
    cap = f"limit {int(limit)}" if limit else ""
    rows = sb(f"""
        select distinct on (fields->>'contact_id')
               coalesce(fields->>'brand','KTU') as brand,
               fields->>'contact_id' as contact_id,
               section
        from intranet_records r
        where section in ({in_list})
          and coalesce(fields->>'contact_id','') <> ''
          and not exists (
                select 1 from sm_notes n
                 where n.source = 'contact'
                   and n.contact_id = (r.fields->>'contact_id')::bigint)
        order by fields->>'contact_id', updated_at desc
        {cap}
    """)
    print(f"[api/contacts] {len(rows)} contacts to backfill "
          f"(priority sections, not yet mirrored{', capped at ' + str(limit) if limit else ''})")
    written = 0
    for row in rows:
        brand = normalise_brand(row.get("brand")) or "KTU"
        cid = row.get("contact_id")
        d = sm(brand, "contacts/locate", {"IdSearch": str(cid)})
        for m in d.get("Matches") or []:
            for note in m.get("Notes") or []:
                written += upsert_note(brand, "contact", note,
                                       contact_id=int(cid), via="api", dry=dry)
    print(f"[api/contacts] {written} notes upserted")


def run_api_proposals(dry):
    rows = sb("""
        select distinct
               coalesce(fields->>'brand','KTU') as brand,
               fields->>'sm_id' as proposal_id,
               fields->>'contact_id' as contact_id
        from intranet_records
        where section in ('proposals','proposals_lost')
          and coalesce(fields->>'sm_id','') <> ''
    """)
    print(f"[api/proposals] {len(rows)} proposals referenced by intranet rows")
    written = 0
    for row in rows:
        brand = normalise_brand(row.get("brand")) or "KTU"
        pid = row.get("proposal_id")
        d = sm(brand, "proposal/details", {"ProposalId": int(pid)})
        # The keys are ProposalNotes / CustomerNotes, NOT "Notes" — an earlier
        # version of this looked for "Notes" and would have silently found
        # nothing even where notes existed. Verified 2026-08-29: both come back
        # null on every proposal sampled (12 of 12), so proposal notes look as
        # API-invisible as appointment notes and realistically depend on the
        # Liquid feed too. Kept anyway: it costs nothing and starts working the
        # day ServiceMinder populates them.
        notes = d.get("ProposalNotes") or d.get("CustomerNotes") or []
        if isinstance(notes, str):          # a single free-text blob, not a list
            notes = [{"Id": int(pid), "Title": "Proposal note", "Body": notes}]
        for note in notes:
            written += upsert_note(
                brand, "proposal", note, proposal_id=int(pid),
                contact_id=int(row["contact_id"]) if row.get("contact_id") else None,
                via="api", dry=dry)
    print(f"[api/proposals] {written} notes upserted")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--liquid", action="store_true")
    ap.add_argument("--api-contacts", action="store_true")
    ap.add_argument("--api-proposals", action="store_true")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--from-file", metavar="PATH",
                    help="parse one raw SM notification email saved to a file")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=400,
                    help="max contacts to backfill per run (0 = no cap, ~50 min)")
    a = ap.parse_args()
    if a.from_file:
        sys.exit(run_from_file(a.from_file, a.dry_run))
    if not any((a.liquid, a.api_contacts, a.api_proposals, a.all)):
        ap.error("pick at least one of --liquid / --api-contacts / --api-proposals / --all / --from-file")
    if a.dry_run:
        print("(dry run — nothing written)\n")
    if a.liquid or a.all:
        run_liquid(a.dry_run)
    if a.api_contacts or a.all:
        run_api_contacts(a.dry_run, limit=a.limit)
    if a.api_proposals or a.all:
        run_api_proposals(a.dry_run)


if __name__ == "__main__":
    main()
