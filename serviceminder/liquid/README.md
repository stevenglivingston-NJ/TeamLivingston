# ServiceMinder Liquid feeds

These templates exist for one reason: **the ServiceMinder Open API cannot see
appointment notes.** Verified 2026-08-29 against KTU appointment `51051472`
(Garret Starr, cancelled 8/20):

| path | result |
|---|---|
| `appointments/find` | `Notes: null`, `UpdateNote: null` |
| `appointments/query` | no note field at all; `CancelReasonId: null` |
| `contacts/locate` | one note — the *intake* blurb, not the cancellation |
| download `kind=appointments` | no `Notes` column |

Meanwhile the SM UI shows a note the rep wrote the evening of the cancellation:

> *"Client wrote 'I tried to write in and tell them I wanted it last week. Not
> this week' and then I both called client with no answer and also texted him
> advising that we can reschedule if he'd still like. No reply back"*

That note **is** the cancellation reason, and the record of what has already
been tried. No API path can reach it. Liquid can.

## What each template is for

| template | install at | fills |
|---|---|---|
| `cancellation_notes.liquid` | Notifications → **Appointment Cancelled** | appointment notes + cancel reason for Appointment Recovery |
| `appointment_notes.liquid` | Notifications → **Appointment Completed** (and any other appointment event you want mirrored) | appointment notes on completed/rescheduled visits |
| `proposal_notes.liquid` | Notifications → **Proposal Sent / Accepted / Declined** | proposal notes for the Proposals tabs |

All three emit the same envelope, so one parser handles them:

```
---SM-NOTES-JSON-BEGIN---
{ ...one JSON object... }
---SM-NOTES-JSON-END---
```

The sentinels are not decoration. Mail gateways append footers and
disclaimers, so the parser slices between the markers rather than trusting the
whole body to be JSON.

## Installing (SM UI — cannot be done through the API)

For each template, **once per brand** (KTU and BTU — notifications are
per-organization):

1. Control Panel → Notifications → pick the event from the table above.
2. Add a delivery to the intranet ingest address.
3. Paste the template as the **body**.
4. Set the body format to **plain text**. An HTML body entity-escapes the JSON
   and breaks the parser.
5. Set the subject to exactly the `SUBJECT:` line given in the template header.

## What consumes them

`intranet/scripts/ingest_sm_notes.py` reads unprocessed `inbox_emails` rows
whose subject starts with `SM-`, parses the envelope, and upserts into
`sm_notes` (identity: `brand, source, sm_note_id`). Re-delivery is therefore
idempotent.

## A note on `cancel_reason.name`

`appointment.cancel_reason` is an `IdName`, so Liquid is the only place the
reason **label** is visible at runtime. There is no cancel-reason lookup
endpoint — `cancelreasons`, `settings/cancelreasons`, `lookups/cancelreasons`
and `appointmentcancelreasons` all answer HTTP 200 with an empty body. The
id→label map was recovered by joining `appointments/query` against the org
download and is recorded in `intranet/scripts/repair_appt_followups.py`; these
templates make it unnecessary going forward.
