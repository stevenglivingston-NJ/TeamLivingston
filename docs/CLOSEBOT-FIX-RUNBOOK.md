# Closebot fix runbook — exact steps, by business

**Date:** 2026-09-19. Companion to [`CLOSEBOT-OPTIMIZATION-AUDIT.md`](CLOSEBOT-OPTIMIZATION-AUDIT.md).

Every item below was verified against the live config. Each says **where** to make the change
(Closebot vs HighLevel), the **exact node or field**, and the **exact value**.

---

## ⚠ Read first — three things that will bite you

**1. The persona is shared.** Both bots use persona `pers_2NWYK8F7YCDST2PC` ("Andy") at 100%
weight. **Any persona edit changes both bots.** Persona changes are in their own section at the
end — do not make them while thinking you're editing one brand.

**2. KTU and BTU have opposite calendar problems.** KTU has three designers throttled to one
booking per slot. BTU has one designer and a 48-hour booking lead time. **Do not apply KTU's
capacity fix to BTU** — it would create double-bookings against a single designer.

**3. BTU's booking currently goes nowhere.** Fix B1 before anything else on BTU. Until it's done,
every other BTU improvement just produces more bookings into a calendar nobody looks at.

---

# KITCHEN TUNE-UP

Bot `bot_SRQO2QVP9AVZ8SQ4` · HL location `nHLCxHPidnhV1NFzRtZZ` · Calendar `IezEuyUywqr1OL7tjHEk`

**Audit result:** KTU is the healthier of the two. Correct calendar, correct entry gate, full
guardrail list, working follow-up, all three bot tools enabled. Its problem is capacity and
closing — 155 booking attempts produced 14 bookings.

### K1 — Raise booking capacity ⬅ highest impact
**Where:** HighLevel → Calendars → Consultation Calendar (`IezEuyUywqr1OL7tjHEk`)

| Setting | Now | Change to | Why |
|---|---|---|---|
| `appointmentPerSlot` | **1** | **match your concurrent designer count (calendar has 3 members)** | Three designers assigned, one booking allowed per slot |
| Monday | **closed** | 10:00–18:00 | A full working day is unbookable |
| Tuesday | 14:00–18:00 | 10:00–18:00 | No Tuesday mornings today |
| `allowBookingAfter` | 24 hours | 4–12 hours | Same-day and next-morning are impossible today |
| `slotInterval` | 120 min | 60 min (keep `slotDuration` 120) | Staggered starts roughly double offer density |

⚠ **Do not change `appointmentPerSlot` until you confirm the designer count** — see Open Questions.
Current theoretical capacity is 16 slots/week; leads were being offered 1–2, a week out.

### K2 — Make the bot close on a soft yes
**Where:** Closebot → KTU flow → Booking node `ba6fe8ee-545d-41d1-a127-a1b667796f1c` → Prompt

Current text ends with:
```
When a contact responds with "Yes" or "OK" to a slot offer, the bot should book them immediately.
```
Replace that sentence with:
```
Book immediately on ANY affirmative response to a slot offer — this includes naming a day, naming
a time, "that works", "sure", "let's do it", "pencil me in", "book it", or repeating a slot back to
you. Do not ask a further clarifying question once the contact has indicated a slot. Confirm the
booking in the same reply.
```
**Evidence:** a lead replied "Let's pencil in Thursday the eighth at 4 o'clock" and was never booked.

### K3 — Cap the follow-up sequence
**Where:** Closebot → KTU flow → Follow-up settings

`followUpRepeat: true` with the 30-day step set to repeat and **no attempt cap** — contacts are
messaged every 30 days indefinitely. Set a cap of 3–5 total touches, then stop.

### K4 — Fix the name field's value expression
**Where:** Closebot → KTU flow → SetField node targeting `contact.name`

| | Value |
|---|---|
| Now | `{{nodes.166b4528-b656-44f5-b156-d48a02e1fea5.result[0]}}{{contact.address}}` |
| Change to | `{{contact.name}}` |

It currently points at the **address** node's output. AI is on so it likely self-corrects, but it's wrong.

### K5 — Remove the disconnected source
**Where:** Closebot → Settings → Sources

`src_X6UYDWSPPFPH2M9O` is **disconnected but still attached and enabled** on the KTU bot. Remove it.
The live source is `src_L620TCZJBOL15MOG`.

### K6 — Cosmetic: calendar name field
**Where:** Closebot → KTU flow → Booking node → CalendarName

Reads `other-use-calendarid`, a placeholder. The CalendarId beneath it is correct. Set to
`Consultation Calendar` so the next person reading it isn't misled.

### K7 — Fix the typo in the prohibited-words list
**Where:** Closebot → KTU flow → Settings → Prohibited Words

`addordable` → `affordable`. The intended word is currently not being blocked.

---

# BATH TUNE-UP

Bot `bot_O8XUQA6CTBLEILUV` · HL location `0uWA8M5BzHrrcJftuaDe`

**Audit result:** BTU is materially broken, not merely under-tuned. It is at revision 31 against
KTU's 182. Its bookings land nowhere, it corrupts CRM data on every contact it touches, it has no
entry gate, no guardrails, no follow-up worth the name, and none of its bot tools enabled.

### B1 — Point booking at BTU's actual calendar ⬅ do this first
**Where:** Closebot → BTU flow → Booking node `bcda4208-2523-4e0f-99de-6c989e362671` → CalendarId

| | Value |
|---|---|
| Now | `kEW9PFmXRzujFf6rQUPp` — "Consultation Calendar - Bath", **sits in the KTU sub-account**, **0 appointments ever** |
| Change to | `k6bokOz0oIicKYu93zhW` — "Consultation Calendar", in BTU's location, holds your team's real bath consults |

**Verified:** `kEW9PFmXRzujFf6rQUPp` has held zero appointments from June 2025 to Feb 2027, from any
source. Your team's actual bath work — "full bathroom remodel, leak issues", "new tub and shower
wall" — is on `k6bokOz0oIicKYu93zhW`. Also update CalendarName to `Consultation Calendar`.

### B2 — Stop writing the email address into the phone field ⬅ active data corruption
**Where:** Closebot → BTU flow → SetField node targeting `contact.phone`

| | Value |
|---|---|
| Now | `{{contact.email}}` |
| Change to | `{{contact.phone}}` |

AI is **off** on this node, so nothing catches it. Every BTU contact the bot processes has its phone
field overwritten with an email address, and has for months.

**Then repair the damage:** export BTU contacts, filter phone fields containing `@`, and restore
from the original source. Do this after the fix, not before, or it re-corrupts.

### B3 — Book at the customer's home, not your office
**Where:** Closebot → BTU flow → Booking node `bcda4208…` → Description

| | Value |
|---|---|
| Now | `Book a 2 hour appointment at {{location.full_address}} with the contact.` |
| Change to | `Book a 2 hour appointment at {{contact.address}} with the contact {{contact.name}}` |

`{{location.full_address}}` is 1285 Broad Street — your own office — going onto every in-home
bath consultation. KTU already does this correctly.

### B4 — Add an entry-tag gate
**Where:** Closebot → Settings → Sources → `src_16VMHVU5CCOHPAC7` → tag filter

BTU has `tags: []` and an empty `tagFilterConfig`. It engages **every inbound conversation** across
GMB, Live Chat, SMS, Facebook, Instagram and WhatsApp — existing customers, vendors, wrong numbers,
job follow-ups. KTU requires the tag `ai start`.

Add the same gate. Expect BTU's engaged-conversation count to fall and its conversion rate to rise;
that is the intent. It also means BTU's "242 conversations" figure has never been 242 leads.

### B5 — Fix the booking prompt (same as K2)
**Where:** Closebot → BTU flow → Booking node `bcda4208…` → Prompt

Apply the identical replacement text from **K2**. Both bots have the "Yes"/"OK" literal-token problem.

### B6 — Enable the three bot-level tools
**Where:** Closebot → BTU flow → Settings

BTU's `tools` array is **empty**. Enable all three, matching KTU:
- `SummarizeConversation`
- `TranscribeConversation`
- `SmartFollowUp`

### B7 — Replace the follow-up sequence
**Where:** Closebot → BTU flow → Follow-up settings

| | Now (BTU) | Change to (match KTU) |
|---|---|---|
| `smartFollowUp` | false | **true** |
| `followUpRepeat` | false | **true**, capped at 3–5 touches |
| Sequence | one touch at **3 weeks** | **1 day → 72 hours → 30 days** |
| Custom copy | **empty** | written, with the BTU booking link |
| Window | weekdays only, to 17:00 | 7 days, to 21:00 |

Suggested copy (bath-adapted from KTU's, which is demonstrably working — a follow-up revived a
lead dormant for three weeks):
```
Hey {{contact.first_name}}! Just wanted to check back in. Life gets busy — totally understand.
If you are still thinking about updating your bathroom, we would love to help. The consultation
is completely free and there is no obligation. You can grab a time that works for you here:
www.bathtuneupbloomfield.com/schedule — or just reply here and I can get you set up!
```

### B8 — Copy KTU's prohibited-words list
**Where:** Closebot → BTU flow → Settings → Prohibited Words

BTU currently has **three** entries: `Cheap`, `cheapest`, `-` (a literal hyphen). KTU has 37,
covering all pricing language, all design-review language, and the out-of-area geographies.

Copy KTU's list verbatim (with `addordable` → `affordable`). Your first operating rule is never to
quote price over chat, and BTU has no hard filter enforcing it today.

### B9 — Fix the wrong prompt on the name field
**Where:** Closebot → BTU flow → "Get Full name" objective → Prompt

| | Value |
|---|---|
| Now | `Ensure email address is valid format.` |
| Change to | `Get contact's last name to ensure you have their full name.` |

### B10 — Fix the two SetField expressions carrying prose
**Where:** Closebot → BTU flow → SetField nodes targeting `contact.name` and `contact.address`

Both have the **value expression** set to the literal sentence
`Update {{contact.first_name}} {{contact.last_name}} and {{contact.name}} fields with collected
information` — that's instruction text sitting in a value field. Set to `{{contact.name}}` and
`{{contact.address}}` respectively.

### B11 — Delete the orphan branch, restore the AI-stop gate
**Where:** Closebot → BTU flow canvas

Eight nodes were never reached in 12 months. Delete the orphan Booking branch — Booking
`ba6fe8ee` (points at KTU's calendar) → ModifyTags (`AI Booked Kitchen`) → SaveConversation →
Conversation `228127fd`.

**But re-attach `If tags contain AI stop`** (`02967243`), which is also currently unreachable. BTU
has no working tag-based kill switch; KTU does. Without it, tagging a BTU contact `ai stop` does
nothing.

### B12 — Widen BTU's booking window
**Where:** HighLevel → BTU → Calendars → Consultation Calendar (`k6bokOz0oIicKYu93zhW`)

| Setting | Now | Change to |
|---|---|---|
| `allowBookingAfter` | **48 hours** | 4–12 hours |

**Leave `appointmentPerSlot` at 1** — this calendar has one team member. Raising it would
double-book a single designer. This is the opposite of K1.

Its hours (Mon–Fri 09:00–17:00, Sat 09:00–15:00) and `slotInterval` (60 min, staggered) are
already better than KTU's. The 48-hour lead time is the constraint.

### B13 — Install the tracking pixel
**Where:** bathtuneupbloomfield.com

The Closebot pixel is **not detected** on the BTU site; KTU's is live. BTU has no web-chat or
visitor-intelligence coverage.

### B14 — Remove the orphan sources
**Where:** Closebot → Settings → Sources

Four BTU sources with zero job flows attached: `src_24WVSJQXITOFM74O`, `src_K33N5LIO2QBMW3PN`,
`src_L3IGFL677FXL3N5D`, `src_QB34844K4VMV14RK`. Three are set to timezone `America/Cancun`.

---

# SHARED — affects BOTH bots

⚠ **These change KTU and BTU simultaneously.** Persona `pers_2NWYK8F7YCDST2PC`.

### S1 — Fix the consultation duration
**Where:** Closebot → Personas → Andy → How to Respond → CONSULTATION block

| Source | Says |
|---|---|
| Persona | "always **60 minutes**" |
| Both booking nodes | "up to **2 hours**" |
| Both HL calendars | `slotDuration` **120 min** |

The persona is the outlier. Change `always 60 minutes` → `always 2 hours`. The bot is already
telling leads 2 hours in live conversations, so the persona is simply wrong and risks a customer
blocking one hour for a two-hour visit.

### S2 — Set reply-hour restrictions
**Where:** Closebot → Settings → Sources → each source → Reply Restrictions

Both sources read "No restrictions configured" — the AI replies on every channel 24/7. Only
follow-ups are time-boxed. Set live-reply hours, or decide deliberately to keep 24/7.

### S3 — Clean up the knowledge library
**Where:** Closebot → Settings → Knowledge

11 files, 100KB, **referenced by nothing** — no node in either flow reads the library, and the real
knowledge is the four HighLevel custom values in the Global Prompt. Two files carry error icons.
Delete them, or wire them up deliberately.

---

# Open questions — answer these before K1 and B2

1. **How many designers can genuinely run a KTU consultation at the same time?** The calendar has
   three members assigned. If that reflects real concurrent capacity, K1 roughly triples bookable
   supply. If the `1` was deliberate because only one designer works a slot, K1 is not a fix and
   KTU's ceiling is a staffing decision, not a settings one. **This is the single most consequential
   unknown in the whole audit.**
2. **Should the bath calendar live in BTU's sub-account permanently?** B1 repoints the bot at
   BTU's existing calendar, which is the right call. If you instead want the KTU-located
   "Consultation Calendar - Bath" to be the system of record, that's a deliberate move and the
   thank-you redirect needs fixing too.
3. **Do you have a clean source to restore corrupted BTU phone numbers from?** (B2) ServiceMinder
   or the original form submissions are the likely candidates.

---

# Suggested order

| # | Item | Business | Where | Effort |
|---|---|---|---|---|
| 1 | B1 — repoint calendar | BTU | Closebot | 1 field |
| 2 | B2 — stop phone corruption | BTU | Closebot | 1 field |
| 3 | B3 — book at customer address | BTU | Closebot | 1 field |
| 4 | K2 + B5 — close on soft yes | Both | Closebot | 1 prompt ×2 |
| 5 | K1 — raise KTU capacity | KTU | HighLevel | after Q1 |
| 6 | B12 — widen BTU lead time | BTU | HighLevel | 1 field |
| 7 | B4 — BTU entry gate | BTU | Closebot | 1 setting |
| 8 | B6, B7, B8 — BTU parity | BTU | Closebot | ~30 min |
| 9 | S1 — duration | Both | Closebot | 1 line |
| 10 | Everything else | — | — | hygiene |

Items 1–4 are five single-field edits and one prompt. They address the two causes of the 9%
booking-step conversion and the two defects doing daily damage. Everything after that is
improvement rather than repair.
