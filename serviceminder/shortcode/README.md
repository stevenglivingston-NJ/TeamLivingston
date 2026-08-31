# ServiceMinder notification templates (shortcode, NOT Liquid)

**Use these, not `../liquid/`.** The notification/trigger body in ServiceMinder
is shortcode substitution — single braces, `{contact.id}` — confirmed
2026-08-31 from a working trigger in the KTU org:

```
{ "ContactId": "{contact.id}", "Phone": "{contact.phone}", ... }
```

Two things follow, and the second is the one that bites quietly:

1. **No loops.** There is no `{% for %}`, so a notification cannot iterate
   `appointment.notes` into an array. The `../liquid/` drafts assumed it could.
   Notes have to arrive as one flattened string, which is why
   `ingest_sm_notes.py` synthesizes a single note row (see `synthesize_notes`).

2. **No filters, so no way to escape a value.** Every value is hand-quoted in
   the template: `"Phone": "{contact.phone}"`. Fine for a phone number. For a
   note body it is broken by construction — the first straight quote or line
   break the rep typed ends the JSON string, and those appear in exactly the
   long notes worth capturing. Ben Yabra's cancellation note contains both.

So **free text travels outside the JSON**, in its own sentinel block:

```
---SM-TEXT:notes_summary---
Client wrote "I tried to write in..." and then I
both called with no answer and also texted him
---SM-TEXT-END---
```

Nothing inside a text block needs escaping. The parser slices between the
sentinels and takes the value verbatim.

## The shortcode names for notes are a guess — deliberately a safe one

A working trigger gave us the shortcode names for contacts, appointments,
proposals and invoices. It did **not** show one for notes. So each template
below emits SEVERAL candidate shortcodes into the same `notes_summary` block.

This is safe because an unfilled shortcode arrives as its own literal text
(`{appointment.notes_summary}`), and `extract_text_blocks()` discards any value
that looks like a bare unresolved shortcode. Whichever candidate ServiceMinder
actually supports fills in; the rest are dropped. A wrong guess degrades to
"no note", never to a garbage note.

Once the first real notification arrives, check which one resolved:

```sql
select source, sm_note_id, authored_by, left(body,120)
from sm_notes where ingested_via='liquid' order by created_at desc limit 5;
```

then trim the losers out of the template so the email stops carrying dead
blocks.

## Install (SM UI — cannot be done through the API)

Once per brand (KTU and BTU — notifications are per-organization):

| template | event | subject |
|---|---|---|
| `cancellation.txt` | Appointment Cancelled | `SM-CANCEL {appointment.id}` |
| `appointment.txt` | Appointment Completed | `SM-APPT {appointment.id}` |
| `proposal.txt` | Proposal Sent (repeat for Accepted / Declined) | `SM-PROP {proposal.id}` |

- Deliver to **firstgentalent@gmail.com** — the inbox Goldeneye already sweeps.
  Not `ingest-email`; that is an HTTP webhook and SM notifications send email.
- Body format **plain text**. HTML entity-escapes the JSON and breaks it.
- Paste the file contents as the body, nothing else.
