# Closebot optimization audit

**Date:** 2026-09-19. **Scope:** KTU + BTU booking bots.
**Evidence base:** full KDL flow exports, the shared persona, 4,219 bot actions over 12 months
joined node-by-node to both graphs, live HighLevel calendar configs, and sampled transcripts.

**Decision this supports:** stay on Closebot and fix it. See
[`CLOSEBOT-TO-HIGHLEVEL-MIGRATION.md`](CLOSEBOT-TO-HIGHLEVEL-MIGRATION.md) for why migrating
now would port these defects into a new platform rather than resolve them.

---

## The headline

| | KTU | BTU |
|---|---|---|
| Conversations entered | 310 | 242 |
| Reached the Booking node | 155 | 43 |
| Tagged booked | **14** | **4** |
| Booking-step conversion | **9%** | **9%** |
| End-to-end | **4.5%** | **1.7%** |

Both bots qualify competently — KTU gets 50% of conversations to the booking step. **Both then
convert 9% of booking attempts.** That number, identical across two differently-configured bots,
is where the efficiency is lost. Everything in P0 targets it.

---

## P0 — The booking step. Fix these two first; nothing else comes close.

### P0.1 — There is not enough calendar availability to book into

Sampled transcripts of non-converting leads show the mechanism directly:

> **Lead:** "Is there any chance there is availability for a consult on Friday? We can be available at **any time** that day"
> **Bot:** "Unfortunately Friday the 5th is fully booked. The next available is Wednesday 9/9 at 10:30 AM."
> **Lead:** "No, that won't work." — *lost*

A lead offering total flexibility on a named day was told there was nothing, and the only
alternative was a single slot a week out. That is not a prompt failure. It is a capacity failure.

**KTU Consultation Calendar `IezEuyUywqr1OL7tjHEk` as configured today:**

| Setting | Value | Problem |
|---|---|---|
| Open days | Tue, Wed, Thu, Fri, Sat | **Sunday and Monday entirely closed** |
| Tuesday hours | 14:00–18:00 only | No Tuesday mornings |
| Wed/Thu/Fri | 10:00–18:00 | — |
| Saturday | 10:00–14:00 | — |
| `slotDuration` / `slotInterval` | 120 min / 120 min | No overlap — slots can't stagger |
| `appointmentPerSlot` | **1** | **3 designers assigned, 1 booking per slot** |
| `allowBookingAfter` | 24 hours | Kills same-day and next-morning |

Theoretical capacity is **16 slots per week**. Real offered availability in transcripts was
one to two slots, a week or more out.

**Corrected 2026-09-19 — `appointmentPerSlot` is not the throttle.** HighLevel documents the
field as *"Maximum bookings per slot **(per user)**"*, so `1` across three round-robin designers
already allows three concurrent bookings. Raising it would allow three *per designer*. Do not
change it.

**The actual constraint was that only one designer had availability.** All 13 historical KTU
appointments are assigned to the same user (`x5CvqPWifa1XXfvSIdCX`) because until 2026-09-18 he
was the only designer with a schedule on this calendar. Two more schedules were added that day.
What still blocks new capacity is the **calendar's own open hours**: HighLevel books only where
calendar hours and designer availability overlap, and the calendar has no Monday entry even though
a designer is now available Monday 10:00–16:00. See
[`CLOSEBOT-FIX-RUNBOOK.md`](CLOSEBOT-FIX-RUNBOOK.md) step K1.

**Required:**
1. Open **Monday** 10:00–18:00 on the calendar. A designer is already available then; the calendar is not.
2. Extend **Tuesday** to 10:00–18:00 to match Wed–Fri.
3. Drop `allowBookingAfter` from 24h to 12h so next-morning is reachable.
4. **Leave `appointmentPerSlot` at 1** (per-user — see correction above).
5. **Leave `slotInterval` at 120.** Dropping to 60 against 2-hour slots risks overlapping bookings
   beyond designer count. Revisit after the above has run.
6. Widen the two newly-added designers' own availability — they now cap the calendar more than it caps them.

**BTU is NOT the same fix — corrected 2026-09-19.** BTU's own calendar
(`k6bokOz0oIicKYu93zhW`) has **one** team member, so `appointmentPerSlot: 1` is correct there and
raising it would double-book a single designer. BTU's availability constraint is different: a
**48-hour** `allowBookingAfter`, twice KTU's. Its hours (Mon–Fri 09:00–17:00, Sat 09:00–15:00) and
staggered 60-minute `slotInterval` are already better than KTU's. See
[`CLOSEBOT-FIX-RUNBOOK.md`](CLOSEBOT-FIX-RUNBOOK.md) items K1 and B12.

### P0.2 — The bot does not close on a soft acceptance

> **Bot:** "Early October I have Wednesday 10/7 or Thursday 10/8, both at 10:30am or 4pm. What works best for you?"
> **Lead:** "Let's pencil in **Thursday the eighth at 4 o'clock**"
> *— conversation ends. Never booked.* — *lost*

The lead picked a specific offered slot in plain language and the bot did not book it. The
Booking node's prompt reads:

```
When a contact responds with "Yes" or "OK" to a slot offer, the bot should book them immediately.
```

It enumerates two literal tokens. "Let's pencil in Thursday the eighth at 4" is neither.

**Required:** rewrite the Booking prompt on both bots to treat *any* affirmative slot selection
as a booking instruction — naming a day, naming a time, "that works", "sure", "let's do it",
"pencil me in". Add an explicit instruction to confirm the booking in the same turn rather than
asking a further question.

---

## P1 — BTU is materially misconfigured

BTU is at revision 31 against KTU's 182, and it shows. These are ordered by cost.

### P1.1 — BTU books into the Kitchen Tune-Up sub-account

BTU's live Booking node uses calendar `kEW9PFmXRzujFf6rQUPp`. That calendar is named
"Consultation Calendar - Bath" — but `locationId` is **`nHLCxHPidnhV1NFzRtZZ`, the KTU
sub-account.** Its post-booking redirect is `ktubloomfield.com/thank-you-931953`, and it assigns
to a KTU user.

BTU's own location has `k6bokOz0oIicKYu93zhW` ("Consultation Calendar", active, redirects to
`bathtuneupbloomfield.com/thankyouscheduled`, has a form attached). **The bot never uses it.**

**Verified against live appointment data**, because "a KTU-login calendar that associates back to
BTU" was a reasonable hypothesis and had to be ruled out:

| Calendar | Location | Events, Jun 2025 – Feb 2027 |
|---|---|---|
| `kEW9PFmXRzujFf6rQUPp` — BTU bot's target | KTU | **0** |
| `k6bokOz0oIicKYu93zhW` — BTU's own | BTU | Real bath consults with service notes and assigned designers |
| `IezEuyUywqr1OL7tjHEk` — KTU's | KTU | Real kitchen consults (control, proves the empty result is genuine) |

HighLevel calendars belong to exactly one sub-account; there is no cross-location association.
The calendar BTU's bot books into has never held a single appointment. Meanwhile BTU logged
**43 booking attempts and 4 `AI Booked bath` tags** in the same period — so the tag fires while
nothing lands on the calendar. BTU's booking path does not terminate anywhere real.

Consequences: bath bookings don't appear in BTU's HighLevel location, BTU reporting undercounts
and KTU overcounts, any BTU workflow triggered on "appointment booked" never fires, and bath
customers land on a kitchen thank-you page.

**Required:** decide whether the bath calendar should live in BTU's location (it should) and
repoint the node. If consolidating instead, move it deliberately and fix the redirect.

### P1.2 — BTU has no entry-tag filter

KTU requires the tag `ai start` before engaging. **BTU has `tags: []` and an empty
`tagFilterConfig` — it engages every inbound conversation** on GMB, Live Chat, SMS, FB, IG and
WhatsApp. Existing customers, wrong numbers, vendors, job follow-ups: all get a booking bot.

This is a direct credit burn and a customer-experience risk. It also contaminates the funnel
metrics — BTU's 242 "conversations" are not 242 leads.

**Required:** apply an entry-tag gate to BTU matching KTU's. Expect BTU's engaged volume to drop
and its conversion rate to rise; that is the point.

### P1.3 — BTU writes the email address into the phone field

Verified in the export:

| Target field | Value expression | AI |
|---|---|---|
| `contact.email` | `{{contact.email}}` | off |
| `contact.phone` | **`{{contact.email}}`** | off |

With AI off on that node there is nothing to catch it. Every BTU contact the bot processes gets
its phone field overwritten with an email address. **This is active data corruption in your CRM
and it has been running for months.**

**Required:** change to `{{contact.phone}}`. Then audit BTU contacts for phone fields containing
`@` and repair.

### P1.4 — BTU books the appointment at your own office

BTU's Booking description: `Book a 2 hour appointment at {{location.full_address}}` — the
Bloomfield office. KTU correctly uses `{{contact.address}}`. Every BTU appointment carries the
wrong address for an **in-home** consultation.

**Required:** change to `{{contact.address}}`.

### P1.5 — BTU has no bot-level tools enabled

KTU runs three: `SummarizeConversation`, `TranscribeConversation`, `SmartFollowUp`.
BTU's `tools` array is empty. No conversation summaries, no transcripts, no smart follow-up.

**Required:** enable all three on BTU.

### P1.6 — BTU's follow-up is effectively absent

| | KTU | BTU |
|---|---|---|
| `smartFollowUp` | true | false |
| `followUpRepeat` | true | false |
| Sequence | 1 day → 72 hours → 30 days | **one touch at 3 weeks** |
| Custom copy | written, with booking link | **empty** |
| Follow-up window | 7 days, to 21:00 | weekdays only, to 17:00 |

A BTU lead who doesn't book gets one generic nudge 21 days later, on a weekday, before 5pm.
The transcripts show KTU's follow-up working — a 9/9 follow-up revived a lead dormant since 8/19.

**Required:** port KTU's follow-up sequence, copy and window to BTU, with bath-appropriate text.

### P1.7 — BTU's guardrails are 3 words against KTU's 37

BTU's `prohibitedWords` is `Cheap`, `cheapest`, `-` (a literal hyphen). KTU blocks all pricing
language (`pricing`, `quote`, `estimate`, `cost`, `invoice`, `proposal`, `discount`…), all
design-review language (`photos`, `plans`, `drawings`, `blueprint`, `measurements`), and the
out-of-area geographies (`manhattan`, `brooklyn`, `queens`, `bronx`, `staten`, `newark`, `hudson`).

Your first operating rule is never to quote price over chat. On BTU there is no hard filter
enforcing it.

**Required:** copy KTU's list to BTU. Fix the typo `addordable` → `affordable` while you're there.

### P1.8 — Dead graph

Eight BTU nodes were never reached in 12 months, including an entire orphan Booking branch
(pointing at KTU's calendar, tagging `AI Booked Kitchen`), a `SaveConversation`, an
`If tags contain AI stop` scenario, and a final-confirmation `Conversation` node.

**Required:** delete the orphan branch. Re-attach the `AI stop` tag scenario — BTU currently has
no tag-based kill switch equivalent to KTU's.

---

## P2 — Cross-cutting

### P2.1 — The consultation duration contradicts itself in three places

| Source | Says |
|---|---|
| Persona (shared, both bots) | "always **60 minutes**" |
| Booking node prompt (both) | "up to **2 hours**" |
| HighLevel calendars (both) | `slotDuration` **120 min** |

The bot tells leads 2 hours (observed in transcripts), the persona says 60 minutes. A customer
who reads 60 minutes somewhere and blocks an hour is a no-show risk when the designer needs two.

**Required:** the persona is the outlier — change it to 2 hours.

### P2.2 — KTU's follow-up never stops

`followUpRepeat: true` with the final 30-day step set to `repeatFinal: true` and no attempt cap.
A contact who never books is messaged every 30 days **indefinitely**. That is ongoing credit
spend on dead leads and, eventually, a complaint.

**Required:** cap the sequence — three to five touches, then stop.

### P2.3 — No reply-time restrictions on either bot

Both sources have "No restrictions configured" — the AI replies on every channel 24/7. Follow-ups
are time-boxed but live replies are not. A 3am SMS reads as a bot.

**Required:** set reply restrictions to reasonable hours, or accept deliberately.

### P2.4 — The KTU name field writes the address expression

KTU's `SetField contact.name` uses `{{nodes.166b4528….result[0]}}{{contact.address}}` — the
address node's output. AI is on, so it likely self-corrects, but it is wrong.
BTU's `contact.name` and `contact.address` expressions both contain prose instructions rather
than merge expressions.

**Required:** correct all four to their proper target fields.

### P2.5 — Account hygiene

- **Disconnected source `src_X6UYDWSPPFPH2M9O` still attached and enabled on KTU.** Remove.
- **Four orphan BTU sources**, three set to timezone `America/Cancun`. Remove.
- **11 knowledge files, 100KB, referenced by nothing.** No node in either flow reads the library;
  the real knowledge is the four HighLevel custom values. Two files carry error icons. Delete or
  deliberately wire up.
- **BTU pixel not installed** on `bathtuneupbloomfield.com` (KTU's is live) — BTU has no web-chat
  or visitor-intelligence coverage.
- **Neither bot moves an opportunity or pipeline stage.** Every booking is invisible to HighLevel
  pipeline reporting except via tag.

### P2.6 — 20% of bot actions are unattributed

822 of 4,219 actions carry synthetic node IDs (`99993` ×388, `99998` ×341, `99999` ×75,
`99995` ×13, `99994` ×7) with no `frontendNodeId`. They are presumably follow-up sends, session
boundaries and errors, but Closebot does not document them. Until they are identified, a fifth of
the bot's behaviour is unmeasurable.

**Required:** ask Closebot support what these node IDs mean.

---

## Sequencing

**Week 1 — capacity and closing.** P0.1 and P0.2. These are calendar settings and one prompt
rewrite. Nothing else in this document matters if the bot has no slots to offer and won't close
when a lead accepts one.

**Week 1 — stop the bleeding on BTU.** P1.3 (phone/email corruption) and P1.4 (wrong address)
are one-field changes doing daily damage.

**Week 2 — BTU parity.** P1.1, P1.2, P1.5, P1.6, P1.7, P1.8. Bring BTU up to KTU's standard.

**Week 3 — hygiene and instrumentation.** P2 throughout, plus the unattributed-action question.

**Then re-measure.** Booking-step conversion is the number to watch. 9% is the baseline. If P0
alone doesn't move it substantially, the remaining cause is in the booking handoff itself and
warrants a deeper transcript review.

---

## What this is worth

KTU reached the booking step 155 times in 12 months and booked 14. If P0 moves booking-step
conversion from 9% to even 35% — unremarkable for an AI booking agent with real availability —
that is roughly **54 consultations instead of 14 on KTU alone**, from lead flow you are already
paying to generate. BTU's 43 attempts are additional.

No new leads required. The demand already reached the booking step and was turned away.
