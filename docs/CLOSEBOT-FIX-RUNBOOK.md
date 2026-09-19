# Closebot + HighLevel fix runbook — exact steps, by business

**Date:** 2026-09-19. Companion to [`CLOSEBOT-OPTIMIZATION-AUDIT.md`](CLOSEBOT-OPTIMIZATION-AUDIT.md).

Every value below was read from the live config. Each step says **which system**, **the exact
screen**, and **the exact value**.

---

## ⚠ Two corrections to the earlier audit — read before acting

**1. Do NOT raise `appointmentPerSlot`.** The earlier runbook said to set it to 3. That was wrong.
HighLevel's API documents the field as *"Maximum bookings per slot **(per user)**"* — so `1` with
three round-robin designers already permits three concurrent bookings. Setting it to 3 would permit
**three per designer, nine concurrent**, and would overbook.

**2. The real constraint was never `appointmentPerSlot` — it was that only one designer had any
availability.** All 13 historical KTU appointments were assigned to the same user
(`x5CvqPWifa1XXfvSIdCX`). The reason: until 2026-09-18 he was the only designer with a schedule on
that calendar. Two more schedules were added 2026-09-18, so this is **already partly fixed** —
not by anything in this runbook.

Current KTU designer availability:

| Designer | Availability on the KTU calendar | Schedule created |
|---|---|---|
| `x5CvqPWifa1XXfvSIdCX` | Wed/Thu/Fri 10:00–18:00, Sat 10:00–14:00 — **no Mon, no Tue** | 2025-09-08 |
| `t1T6fPu4eFzW86t6AhdK` | Mon–Fri 10:00–16:00, Sat 10:00–14:00 | 2026-09-18 |
| `t5pqL2s7OHc2CbTGkcBY` | Thu 10:00–16:00, Fri 10:00–14:00 | 2026-09-18 |

**The remaining blocker is the calendar's own open hours.** HighLevel books only where *calendar
open hours* AND *designer availability* overlap. The KTU calendar has **no Monday entry**, so even
though `t1T6f…` is now available Monday 10:00–16:00, **Monday still yields zero bookable slots**.
That is step K1 below and it is the single highest-value change remaining.

---

## ⚠ Three traps

1. **The persona is shared.** Both bots use `pers_2NWYK8F7YCDST2PC` ("Andy") at 100%. Any persona
   edit changes both. Persona steps are in Part 5.
2. **Someone was editing the KTU calendar at 16:10 UTC on 2026-09-19** (all three schedules show
   that update time). Confirm nobody else is mid-change before you start, or you will overwrite
   each other.
3. **Do B1 before any other BTU work.** Until it's done, every BTU improvement books into a
   calendar nobody looks at.

---

# PART 1 — HighLevel · Kitchen Tune-Up calendar

**Navigate:** HighLevel → switch to sub-account **Kitchen Tune-Up** → **Calendars** → **Calendar
Settings** → **Consultation Calendar** (`IezEuyUywqr1OL7tjHEk`) → **Availability** tab.

### K1 — Add Monday and extend Tuesday ⬅ do this one first
The calendar's open hours today are Tue–Sat only, and Tuesday is afternoons only.

| Day | Now | Set to |
|---|---|---|
| **Monday** | **not listed** | **10:00 – 18:00** |
| Tuesday | 14:00 – 18:00 | **10:00 – 18:00** |
| Wednesday | 10:00 – 18:00 | leave |
| Thursday | 10:00 – 18:00 | leave |
| Friday | 10:00 – 18:00 | leave |
| Saturday | 10:00 – 14:00 | leave |

**How:** in the Availability tab, toggle Monday on and set 10:00–18:00; change Tuesday's start from
2:00 PM to 10:00 AM. Save.

This unlocks Monday all-day and Tuesday mornings for `t1T6f…`, who is already available then.

### K2 — Reduce the minimum booking notice
**Screen:** same calendar → **Advanced / Scheduling Notice**

| Setting | Now | Set to |
|---|---|---|
| Minimum Scheduling Notice | **24 hours** | **12 hours** |

A lead texting at 6pm currently cannot be offered anything the next morning.

### K3 — Leave these alone
- **`appointmentPerSlot` / "Maximum bookings per slot": leave at 1.** See correction 1 above.
- **`slotInterval`: leave at 120 minutes.** Dropping it to 60 while slots are 2 hours long can
  create overlapping bookings that exceed designer count. Revisit only after K1 has run a few weeks.

### K4 — Ask the two new designers to widen their own availability (optional, highest upside)
`t5pqL…` is available only Thursday and Friday; `x5Cvq…` has no Monday or Tuesday. Their personal
availability now caps the calendar more than the calendar caps them. Each designer sets this under
**Settings → My Profile → Availability**, or you set it under **Settings → Team → [user] →
Availability**.

---

# PART 2 — HighLevel · Bath Tune-Up calendar

**Navigate:** HighLevel → sub-account **Bath Tune-Up** → **Calendars** → **Calendar Settings** →
**Consultation Calendar** (`k6bokOz0oIicKYu93zhW`).

### B-HL1 — Reduce the minimum booking notice
| Setting | Now | Set to |
|---|---|---|
| Minimum Scheduling Notice | **48 hours** | **12 hours** |

Twice KTU's, on the brand with less demand. Two full days before anyone can book.

### B-HL2 — Add designers to the bath calendar ⬅ the real BTU capacity fix
This calendar has **one** team member (`t5pqL2s7OHc2CbTGkcBY`) whose availability is Wed 10:30–14:00
+ 16:00–18:00, Thu 10:30–14:00 + 16:00–18:00, Fri 10:00–14:00 — roughly **13 hours a week**, no
Monday, Tuesday or Saturday. The calendar's open hours say Mon–Fri 09:00–17:00 and Sat 09:00–15:00,
so most of that window has nobody behind it.

**How:** calendar → **Team Members** → add the designers who actually run bath consultations, then
set each one's availability. **Leave `appointmentPerSlot` at 1** — it is per-user.

If only one person runs bath consults, that is the honest ceiling and no setting changes it. Say so
rather than widening the calendar's open hours, which would advertise slots nobody can staff.

### B-HL3 — Don't change `appointmentPerSlot` here either
Same reason as K3.

---

# PART 3 — Closebot · Bath Tune-Up bot

**Navigate:** Closebot → **Agents** → **Job Flows** → `Bath Tune-Up Booking Bot`
(`bot_O8XUQA6CTBLEILUV`). Changes take effect when you **publish** a new version.

### B1 — Point booking at BTU's actual calendar ⬅ first
**Node:** Booking `bcda4208-2523-4e0f-99de-6c989e362671` (click it on the canvas)

| Field | Now | Set to |
|---|---|---|
| Calendar ID | `kEW9PFmXRzujFf6rQUPp` | **`k6bokOz0oIicKYu93zhW`** |
| Calendar name | `Consultation Calendar` | `Consultation Calendar` (unchanged) |

The current calendar sits in the **Kitchen Tune-Up** sub-account and has held **zero appointments
ever**. Your team's real bath consults are on `k6bokOz0oIicKYu93zhW`.

### B2 — Stop writing the email into the phone field
**Node:** Set Field targeting `contact.phone`

| Field | Now | Set to |
|---|---|---|
| Field value expression | `{{contact.email}}` | **`{{contact.phone}}`** |

AI is off on this node, so nothing corrects it. Then repair the damage: **Contacts → filter Phone
contains `@` → export → restore from ServiceMinder or the original form submissions.** Do the
repair *after* the fix or it re-corrupts.

### B3 — Book at the customer's home
**Node:** Booking `bcda4208…` → Description

| Now | Set to |
|---|---|
| `Book a 2 hour appointment at {{location.full_address}} with the contact.` | `Book a 2 hour appointment at {{contact.address}} with the contact {{contact.name}}` |

`{{location.full_address}}` is 1285 Broad Street — your own office — on an in-home consultation.

### B4 — Add an entry-tag gate
**Navigate:** Closebot → **Settings → Sources** → `src_16VMHVU5CCOHPAC7` ("Bath Tune-Up") → tag filter

Currently empty, so the bot engages **every** inbound conversation on GMB, Live Chat, SMS, Facebook,
Instagram and WhatsApp. Add a tag rule matching KTU's: operator `and`, rule tag **`ai start`**,
condition `is`.

### B5 — Fix the booking prompt
**Node:** Booking `bcda4208…` → Prompt. Replace the final sentence with the text in **Part 5 / S0**.

### B6 — Enable the three bot-level tools
**Navigate:** bot → **Settings** → Tools. BTU's list is empty; KTU has all three. Enable:
`SummarizeConversation`, `TranscribeConversation`, `SmartFollowUp`.

### B7 — Replace the follow-up sequence
**Navigate:** bot → **Follow-up**

| Setting | Now | Set to |
|---|---|---|
| Smart follow-up | false | **true** |
| Repeat | false | **true**, capped at 4 total touches |
| Steps | one at **3 weeks** | **1 day → 72 hours → 30 days** |
| Extra prompt | empty | text below |

```
Hey {{contact.first_name}}! Just wanted to check back in. Life gets busy — totally understand.
If you are still thinking about updating your bathroom, we would love to help. The consultation
is completely free and there is no obligation. You can grab a time that works for you here:
www.bathtuneupbloomfield.com/schedule — or just reply here and I can get you set up!
```

### B8 — Copy KTU's prohibited-words list
**Navigate:** bot → **Settings → Prohibited Words**. BTU has three entries (`Cheap`, `cheapest`, `-`).
Paste KTU's 37, with `addordable` corrected to `affordable`:

```
Cheap, cheapest, pricing, quote, estimate, cost, breakdown, invoice, proposal, rates, fee, fees,
charge, charges, affordable, cheaper, discount, discounts, deal, deals, review, send, email, photos,
plans, design, drawings, blueprint, measurements, specs, specifications, manhattan, brooklyn,
queens, bronx, staten, newark, hudson
```

### B9 — Fix the wrong prompt on the name objective
**Node:** "Get Full name" objective → Prompt

| Now | Set to |
|---|---|
| `Ensure email address is valid format.` | `Get contact's last name to ensure you have their full name.` |

### B10 — Fix two Set Field expressions carrying prose
**Nodes:** Set Field → `contact.name`, and Set Field → `contact.address`. Both have the **value
expression** set to the sentence `Update {{contact.first_name}} {{contact.last_name}} and
{{contact.name}} fields with collected information`. Set them to `{{contact.name}}` and
`{{contact.address}}` respectively.

### B11 — Delete the orphan branch, restore the AI-stop gate
**On the canvas.** Delete the unreachable branch: Booking `ba6fe8ee` → ModifyTags (`AI Booked
Kitchen`) → SaveConversation → Conversation `228127fd`. Nothing routes into it.

**Then re-attach `If tags contain AI stop`** (`02967243`), also currently unreachable. Without it,
tagging a BTU contact `ai stop` does nothing. KTU has a working equivalent.

---

# PART 4 — Closebot · Kitchen Tune-Up bot

**Navigate:** Closebot → **Agents → Job Flows** → `Kitchen Tune-Up Booking Bot`
(`bot_SRQO2QVP9AVZ8SQ4`).

### K-CB1 — Fix the booking prompt
**Node:** Booking `ba6fe8ee-545d-41d1-a127-a1b667796f1c` → Prompt. Replace the final sentence with
**Part 5 / S0**.

### K-CB2 — Cap the follow-up
**Navigate:** bot → **Follow-up**. `followUpRepeat` is on with the 30-day step repeating and **no
attempt cap** — contacts are messaged every 30 days forever. Cap at **4 total touches**.

### K-CB3 — Fix the name field's value expression
**Node:** Set Field → `contact.name`

| Now | Set to |
|---|---|
| `{{nodes.166b4528-b656-44f5-b156-d48a02e1fea5.result[0]}}{{contact.address}}` | `{{contact.name}}` |

It currently points at the address node's output.

### K-CB4 — Remove the disconnected source
**Navigate:** Settings → Sources. `src_X6UYDWSPPFPH2M9O` is **disconnected but still attached and
enabled**. Detach it. The live source is `src_L620TCZJBOL15MOG`.

### K-CB5 — Cosmetic: the calendar name field
**Node:** Booking → Calendar name reads `other-use-calendarid`, a placeholder. Set to
`Consultation Calendar`. The ID beneath it is already correct.

### K-CB6 — Fix the prohibited-words typo
**Navigate:** bot → Settings → Prohibited Words. `addordable` → `affordable`.

---

# PART 5 — Closebot · shared (affects BOTH bots)

### S0 — The booking-prompt replacement text
Used by **B5** and **K-CB1**. Replace this sentence:

```
When a contact responds with "Yes" or "OK" to a slot offer, the bot should book them immediately.
```

with:

```
Book immediately on ANY affirmative response to a slot offer — this includes naming a day, naming a
time, "that works", "sure", "let's do it", "pencil me in", "book it", or repeating a slot back to
you. Do not ask a further clarifying question once the contact has indicated a slot. Confirm the
booking in the same reply.
```

**Why:** a lead replied "Let's pencil in Thursday the eighth at 4 o'clock" and was never booked. The
prompt named two literal tokens.

### S1 — Consultation duration: block 2 hours, say 90 minutes
**Navigate:** Closebot → **Agents → Personas → Andy** → *How to Respond* → CONSULTATION block.

| Where | Now | Set to |
|---|---|---|
| Persona CONSULTATION block | `Always free, always in-home, always 60 minutes.` | `Always free, always in-home, and usually about 90 minutes.` |
| Both Booking node prompts | "Consultations take up to 2 hours" | `Consultations usually take about 90 minutes.` |
| Both HighLevel calendars | `slotDuration` 120 min | **leave at 120** |

The calendar keeps blocking a full 2 hours of designer time; only the customer-facing wording
changes. Today the persona says 60 minutes while the bot tells leads 2 hours — the worst of both.

⚠ One caveat, stated once: 90 minutes is still under the 2 hours you actually block, so a designer
running long will overrun what the customer was told. It is a large improvement on "60 minutes"
and a normal way to reduce booking friction — just brief the designers that the customer heard 90.

### S2 — Set reply-hour restrictions
**Navigate:** Closebot → **Settings → Sources** → each source → **Reply Restrictions**.
Both read "No restrictions configured" — the AI replies on every channel 24/7.

Apply to **both** `src_L620TCZJBOL15MOG` (KTU) and `src_16VMHVU5CCOHPAC7` (BTU):

| Days | Hours | Timezone |
|---|---|---|
| Monday – Sunday | **08:00 – 21:00** | `America/New_York` |

Select all channels when applying. This matches KTU's existing *follow-up* window, so the two
settings stop contradicting each other. While you are on that screen, align BTU's **Follow-Up
Restrictions** to the same 7-day 08:00–21:00 (BTU is currently weekdays only, to 17:00).

### S3 — Clean up the knowledge library
**Navigate:** Closebot → **Settings → Knowledge** (Uploads).

11 files, ~100 KB. **Nothing reads them** — no node in either flow references the library, and the
Global Prompt pulls its knowledge from HighLevel custom values instead
(`ktu_playbook`, `objections_toolkit_*`, `bath_tuneup_refacing_manual_*`, `core_services_guide_*`).
Two files show error icons and four are orphaned `Real Wave Scraper` dumps attached to no source.

**Do it in this order — the delete is not reversible:**

1. **Download all 11 first.** Row's ⋮ menu → Download, for each. Closebot has no text preview, so
   this is the only way to see what is in them.
2. **Archive them to Drive**, under `07 Vendors & Products` or a new `Closebot archive` folder.
3. **Delete all 11** from Closebot.
4. **Verify**: run one test conversation per bot and confirm answers about services, pricing
   deflection and scope are unchanged. They should be — the real knowledge is the HighLevel custom
   values and this step does not touch them.

If you would rather not delete, deleting only the four orphaned `Real Wave Scraper` files and the
two erroring files is the safe subset.

---

# Suggested order

| # | Step | System | Business | Effort |
|---|---|---|---|---|
| 1 | B1 — repoint calendar | Closebot | BTU | 1 field |
| 2 | B2 — stop phone corruption | Closebot | BTU | 1 field |
| 3 | B3 — book at customer address | Closebot | BTU | 1 field |
| 4 | K1 — add Monday, extend Tuesday | HighLevel | KTU | 2 min |
| 5 | S0 via K-CB1 + B5 — close on soft yes | Closebot | Both | 1 prompt ×2 |
| 6 | K2 + B-HL1 — booking notice 12h | HighLevel | Both | 2 fields |
| 7 | B4 — BTU entry gate | Closebot | BTU | 1 setting |
| 8 | S1 — 90-minute wording | Closebot | Both | 3 edits |
| 9 | S2 — reply hours | Closebot | Both | 2 screens |
| 10 | B6, B7, B8 — BTU parity | Closebot | BTU | ~30 min |
| 11 | B-HL2 — designers on bath calendar | HighLevel | BTU | staffing call |
| 12 | S3 — knowledge cleanup | Closebot | Both | ~20 min |
| 13 | K-CB2…K-CB6, B9, B10, B11 | Closebot | Both | hygiene |

Steps 1–5 are five single-field edits, one calendar change and one prompt. They address both causes
of the 9% booking-step conversion and the two defects doing daily damage.

---

# After the changes — how to tell if it worked

The number to watch is **booking-step conversion**: bookings divided by conversations that reached
the Booking node. Baseline is **9%** on both bots (KTU 14/155, BTU 4/43).

Re-measure after two weeks with:

```bash
curl -H "X-CB-KEY: $CLOSEBOT_API_KEY" \
  "https://api.closebot.com/botMetric/actions?start=<ISO>&end=<ISO>&maxCount=5000"
```

Count actions on the Booking nodes (`ba6fe8ee…` for KTU, `bcda4208…` for BTU) against actions on the
booked-tag nodes (`3f8f5ec3…` KTU, `54f437df…` BTU). If K1 and S0 land, this should move
substantially. If it doesn't, the cause is deeper in the booking handoff and warrants a fuller
transcript review.

---

# ADDENDUM 2026-09-19 — ServiceMinder reconciliation + an API hazard

## ⚠ Never PUT a partial body to HighLevel `update-calendar`

A partial-body PUT (`{allowBookingAfter, allowBookingAfterUnit}`) against
`IezEuyUywqr1OL7tjHEk` **reset every field not sent to its default**:

| Field | Before | After the partial PUT |
|---|---|---|
| `openHours` | Tue–Sat array | **`{}` — no bookable hours at all** |
| `slotDuration` | 120 mins | 30 mins |
| `slotInterval` | 120 mins | 30 mins |
| `formSubmitType` | `RedirectURL` | `ThankYouMessage` |

Restored within ~2 minutes by sending a complete body, verified by independent read. If you ever
script against this endpoint: **read the calendar, merge your change into the whole object, write
it back, then re-read to verify.** Prefer the UI for one-off changes.

## ServiceMinder vs HighLevel — they disagree, and SM is the system of record

### Kitchen Tune-Up

| Designer | HighLevel | ServiceMinder (Sales category) |
|---|---|---|
| Ben Yabra (`x5Cvq…`) | Wed/Thu/Fri 10:00–18:00, Sat 10:00–14:00 | Wed 10–18, **Thu 09:00–20:00**, **Fri 10:00–20:00**, Sat 10–14 · 33 h/wk |
| `t5pqL…` | Thu 10:00–16:00, Fri 10:00–14:00 | = Amanda Brochardt (61043) — **exact match** · 10 h/wk |
| `t1T6f…` | Mon–Fri 10:00–16:00, Sat 10–14 (created 2026-09-18) | **no matching SM agent** |

- **Do NOT open Monday or Tuesday on the KTU calendar.** No KTU sales agent has Monday or Tuesday
  availability in ServiceMinder. The `t1T6f…` schedule added 2026-09-18 is a generic Mon–Fri 10–16
  default matching no real agent. Opening those days advertises slots nobody can staff.
  **This supersedes step K1.**
- **Existing KTU Tuesday hours (14:00–18:00) are already unstaffed** per ServiceMinder. Worth
  removing, not extending.
- **Unexposed evening capacity:** ServiceMinder has Ben until **20:00 Thursday and Friday** and from
  **09:00 Thursday**. Both the calendar's open hours and Ben's HighLevel schedule stop at 18:00, so
  roughly 5 hours/week of staffed prime-time availability can never be offered by the bot.

### Bath Tune-Up — the opposite problem

| | Sales capacity |
|---|---|
| ServiceMinder | Ben 33 h/wk · Karen Naithe 33.5 h/wk (starts 2026-09-30) · Amanda Brochardt 10 h/wk · Amanda Borchardt 22.5 h/wk |
| HighLevel bath calendar | **one** team member, ~13 h/wk |

BTU is not capacity-constrained. Its HighLevel calendar exposes one person's partial week out of
roughly four agents' worth in ServiceMinder. **This supersedes B-HL2's framing** — the people exist.

### Duplicate agent records in ServiceMinder

| Id | Name | Email | Mobile | Start | Availability |
|---|---|---|---|---|---|
| 61043 | Amanda **Bro**chardt | aborchardt@kitchentuneup.com | 248-422-4554 | 2026-05-04 | Thu 10–16, Fri 10–14 |
| 61712 | Amanda **Bor**chardt | Aborchardt@kitchentuneup.com | 973-521-2698 | 2026-04-01 | Mon/Tue/Wed 10:30–14 + 16–18, Thu 16–18, Fri 10–14 |

Two records for one person, different spellings, phones and availability. This splits round-robin
assignment and any per-agent reporting. Merge or retire one.

Also: **`Steven Livingston` (44444) has no time slots**, and **`Service Agents` (40117)** is a
catch-all in the **Service** category (not Sales) with Sun–Sat 08:00–20:00 — it should not be
reachable for consultations.

---

# ADDENDUM 2 — 2026-09-19 · B1 WITHDRAWN. The BTU booking design is correct.

**Do not repoint BTU's booking calendar.** Step B1 above is wrong and must not be actioned.

BTU's booking node deliberately targets `kEW9PFmXRzujFf6rQUPp` — the "Consultation Calendar - Bath"
that sits in the **Kitchen Tune-Up** sub-account — so that Closebot only has to hold one HighLevel
account connection. A downstream transfer then moves the appointment into Bath Tune-Up's own
calendar. That is intentional, and it works.

**Evidence (matched to the second):**

| Closebot `AI Booked bath` tag fired | Appointment `dateAdded` on BTU `k6bokOz0oIicKYu93zhW` | Event title |
|---|---|---|
| 2026-01-27T15:57:54.96 | 2026-01-27T15:57:54 | "Angela Varachi" |
| 2026-01-28T16:55:24.47 | 2026-01-28T16:55:23 | "Eileen And Jeffrey Riman" |

Bot-originated bookings are titled with the **contact's name**; everything ServiceMinder creates on
the same calendar is titled "Consultation - In-Home". That title difference plus the same-second
`dateAdded` makes the attribution unambiguous.

**Why the earlier finding was wrong.** `kEW9PFmXRzujFf6rQUPp` returns zero events for any window
queried — but that is the *expected* end state of a staging calendar whose appointments are moved
out. The original audit treated an empty staging calendar as a broken one without testing the
transfer hypothesis. Anyone re-running this analysis should verify against the **destination**
calendar, matching on `dateAdded` and event title, not against the staging calendar.

**What does NOT change:** BTU still converts only 4 bookings from 43 booking-node hits (9%), the
same rate as KTU. That is an availability-and-closing problem (steps K1/K2/S0), not a routing one.
Every other BTU step in this runbook stands — the phone/email corruption (B2), the office address on
the booking description (B3), the missing entry-tag gate (B4), the empty tools array (B6), the
follow-up sequence (B7) and the prohibited-words list (B8).
