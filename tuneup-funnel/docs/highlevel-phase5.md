# Phase 5 — HighLevel Fan-Out & Conversion Tracking

How the funnel talks to HighLevel and the ad platforms, and what must be
configured on each side. The **repo owns the push** (contact upsert + tags +
conversion events); **HighLevel owns the reaction** (notify Sonya/office,
pipeline moves, nurture) so the team can retune notifications without a
code deploy.

## What the Worker pushes (built)

| Funnel moment | HighLevel | Meta CAPI | GA4 MP |
|---|---|---|---|
| Lead captured (contact gate) | upsert + tag `tuneup-lead` | `Lead` (content_name `tuneup-lead`) | `generate_lead` |
| Callback requested | upsert + tag `tuneup-callback` (+ best time) | `Lead` (content_name `tuneup-callback`) | `generate_lead` |
| Deposit started | — | `InitiateCheckout` | `begin_checkout` (browser) |
| Deposit paid + SM booked | upsert + tag `tuneup-booked` + job custom fields | `Purchase` (value = deposit collected) | `purchase` |

- All pushes are **best-effort and deferred** (`ctx.waitUntil`): the customer's
  response never waits on HL/Meta/GA, and outcomes are logged to D1
  `funnel_events` as `fanout_lead` / `fanout_checkout` / `fanout_booking` —
  check there when something doesn't arrive in HL.
- **Dedup**: the SPA fires the browser pixel with an `eventID` and forwards the
  same id to the Worker, which fires the matching CAPI event. Meta dedupes the
  pair; ad blockers only kill the browser half.
- Purchase **value = deposit actually collected** (not the full quote). The
  full quote rides along in HL custom fields and GA4 `quote_value`.

## HighLevel configuration needed (owner/one-time)

1. **Custom fields** (Settings → Custom Fields, Contact type — create with
   these exact keys):
   `tuneup_session_id`, `tuneup_quote`, `tuneup_deposit`, `tuneup_openings`,
   `tuneup_level`, `tuneup_appointment`, `tuneup_best_time`,
   `tuneup_sm_appointment_id`, `tuneup_sm_contact_id`
2. **Secrets/vars** (Cloudflare): `HIGHLEVEL_API_KEY` secret = KTU Private
   Integration Token (location `nHLCxHPidnhV1NFzRtZZ`, already a wrangler var).
   PIT scopes needed: **Contacts write** (plus payments per Phase 4).
3. **Workflows** — build in the HighLevel AI builder (prompt below): the
   notification/reaction side stays in HL on purpose.

## HighLevel AI-builder prompt (paste into HL)

> Build three workflows for the Kitchen Tune-Up location:
>
> **1. "Tune-Up — Booked (notify office)"** — Trigger: contact tag added
> `tuneup-booked`. Actions: (a) send an internal notification email AND SMS to
> Sonya at the office with: contact name, phone, email, address, custom fields
> Tune-Up Quote, Tune-Up Deposit, Tune-Up Openings, Tune-Up Level, and Tune-Up
> Appointment (the appointment date/time); (b) create/update an opportunity in
> the Tune-Up pipeline and move it to stage "Booked" with the monetary value set
> from the Tune-Up Quote field; (c) send the customer a branded booking
> confirmation email recapping their appointment date, quote, deposit paid, and
> our phone number (973) 521-1182.
>
> **2. "Tune-Up — Callback requested (notify office)"** — Trigger: contact tag
> added `tuneup-callback`. Actions: (a) internal notification SMS + email to
> Sonya: name, phone, and the Tune-Up Best Time field, marked "CALL BACK
> REQUEST — respond within 15 minutes"; (b) create a task assigned to Sonya due
> in 1 hour; (c) add the contact to the Tune-Up pipeline at stage "Callback".
>
> **3. "Tune-Up — New lead (speed to lead)"** — Trigger: contact tag added
> `tuneup-lead`. Actions: (a) internal notification email to the office inbox
> with name/phone/email and Tune-Up Quote if present; (b) if no `tuneup-booked`
> tag is added within 2 hours, send the contact a friendly SMS + email nudge:
> their instant quote is saved and they can finish booking online or call
> (973) 521-1182; (c) stop the nudge sequence immediately if `tuneup-booked` or
> `tuneup-callback` is added.
>
> Do not send any automated SMS before checking our SMS consent settings; use
> the location's approved sending number.

## Ad-platform configuration needed (owner/one-time)

- **Meta**: Events Manager → pixel `109034988941656` → Settings → Conversions
  API → *Generate access token* → `wrangler secret put META_CAPI_TOKEN`.
- **GA4**: create the property for ktubloomfield.com → copy `G-XXXX` id into
  `wrangler.toml` (`GA4_MEASUREMENT_ID`) **and** the Pages build env
  (`VITE_GA4_ID`) → Admin → Data Streams → Measurement Protocol API secrets →
  `wrangler secret put GA4_API_SECRET`.
- Until each is configured the Worker records `skipped: "no_config"` in
  `funnel_events` and the funnel behaves normally.

## Deliberately NOT in HighLevel

Conversion tracking (Pixel/CAPI/GA4) stays in the repo, not HL's native
integrations: ad-spend optimization depends on correct dedup (shared
event_id) and correct values (deposit collected), which HL's coarse
tag-based firing can't guarantee. Keep HL workflows to notifications,
pipeline, and nurture.
