# Closebot → HighLevel AI Suite migration

**Status:** extraction complete, build not started.
**Extracted:** 2026-09-19. **Source:** Closebot agency `agn_TDG3VN71BCI35XN7` ("Kitchen & Bath Tune-Up").

Raw artifacts live in [`closebot-migration/`](closebot-migration/). They are the **only copy**
of this configuration outside Closebot's own database — nothing in this repo or in
HighLevel held it before today.

---

## 1. How the extraction was done (repeatable)

The wired MCP server (`mcp-servers/closebot/server.py`) exposes 14 read endpoints, all
telemetry — bots, metrics, leads, billing. **None of them return a bot's prompt or flow.**

Two undocumented endpoints carry the actual configuration:

| Endpoint | Returns |
|---|---|
| `GET /persona` and `/persona/{id}` | The shared persona: tone, hard rules, service area, humanization settings |
| `GET /bot/{id}/export` | `{id, kdl, version}` — the **complete flow graph** in Closebot's KDL definition language |

```bash
curl -H "X-CB-KEY: $CLOSEBOT_API_KEY" https://api.closebot.com/bot/{id}/export
```

Neither is in the swagger spec the MCP server was built from. `/bot/{id}/export` is the
one that matters — it is a full, lossless dump. Anything claiming Closebot config can't
be pulled programmatically is wrong; it just isn't documented.

**These endpoints should be added to the MCP server** so the config is snapshotted on a
schedule rather than pulled by hand. Not done yet.

---

## 2. What exists in the account

Four bots, **all sharing a single persona** (`pers_2NWYK8F7YCDST2PC`, "Andy"):

| Bot | ID | Category | HL location | KDL |
|---|---|---|---|---|
| Kitchen Tune-Up Booking Bot | `bot_SRQO2QVP9AVZ8SQ4` | GHLS | KTU `nHLCxHPidnhV1NFzRtZZ` | 427 lines |
| Bath Tune-Up Booking Bot | `bot_O8XUQA6CTBLEILUV` | GHLS | BTU `0uWA8M5BzHrrcJftuaDe` | 410 lines |
| SMS Campaign | `bot_CBHGI91ODANAAOLB` | GHLS | KTU, tag-gated `smscampaign` | 181 lines |
| LinqBlueIntegration | `bot_1DKPS7TNL4OLVE7Q` | webhook | — | 118 lines |

KTU is at version 0.0.182 after **182 revisions**; BTU at 0.0.31 after 31. That ratio is
itself a finding — BTU has received roughly one-sixth the tuning attention, and section 4
shows where that shows up.

**Channels.** BTU runs on GMB, Live Chat, SMS, FB, IG, WhatsApp. KTU's source is tag-gated
(`ai start`). Both are `GHLS` category — they already read and write HighLevel directly.

---

## 3. The architecture, in three layers

**Layer 1 — Persona ("Andy"), shared by all four bots.** Tone, message-length rule
(1–2 sentences), the NEVER-DO list (no pricing over chat, no design review over chat, never
ask twice), the service-area whitelist, homeowners-only, and the budget-question redirect.
Also humanization: `typoPercent 5`, `breakupLargeMessagePercent 10`, `responseDelay 1`.
Model preference order: anthropic → gemini → grok → openai → deepseek.

**Layer 2 — Per-bot `__CONFIG__`.** `conversationReason` (the brand-specific mission and
the core-services rule), `businessInformation`, `prohibitedWords`, and the follow-up state
machine.

**Layer 3 — The flow graph.** Typed nodes wired by handle. Node types in use:

| KDL node | What it does |
|---|---|
| `MultiObjective` | Capture a field — name, address, email, phone, project scope. Has `MaxAttempts`, `Sensitivity`, `SkipIfNotBlank` |
| `AISwitch` | LLM-judged branch on named cases ("Interested in remodel" / "Not interested") |
| `Comparator` | AI-evaluated gate — the service-area check |
| `Booking` | Offer slots and book into a named `CalendarId`; tags `FailedTag` on failure |
| `ModifyTags` | Add/remove HL tags |
| `SetField` | Write back to HL contact fields, optionally AI-validated |
| `SaveConversation` | Summarize into `contact.last_message` |
| `Conversation` | Free-form closing turn |
| `Statement` / `Delay` / `End` | Speak, wait, terminate |
| `ScenarioCustom` / `ScenarioAggression` | **Priority-ranked global interrupts** that can fire from anywhere in the conversation |

The `Scenario*` nodes are the architecturally important ones — see section 5.

**Knowledge lives in HighLevel already.** `businessInformation` on both bots is a
concatenation of HL custom values:

```
{{custom_values.ktu_playbook}}
{{custom_values.objections_toolkit_shape_up_your_sales_approach_handling_objections}}
{{custom_values.bath_tuneup_refacing_manual_2023_v6}}
{{custom_values.core_services_guide_623_us}}
{{custom_values.kitchen_website}} / {{custom_values.bathroom_website}}
```

This is the single biggest piece of good news in the migration: the playbook, objection
toolkit, refacing manual and core-services guide **do not need to move.** They are already
HL custom values and will resolve identically inside a HighLevel agent.

---

## 4. Defects found in the live bots

These are pre-existing, in production today, and independent of the migration. Listed
worst-first.

### 4.1 — BTU's booking is misrouted. Both paths. (critical)

The BTU bot has two `Booking` nodes:

| Node | `CalendarId` | Reality |
|---|---|---|
| `ba6fe8ee…` | `IezEuyUywqr1OL7tjHEk` | **This is KTU's Consultation Calendar.** Not present in BTU's location at all. |
| `bcda4208…` | `kEW9PFmXRzujFf6rQUPp` | **Not present in BTU's location either.** Origin unverified. |

Verified against `get-calendars` for BTU location `0uWA8M5BzHrrcJftuaDe`: BTU's only active
consultation calendar is **`k6bokOz0oIicKYu93zhW`** ("Consultation Calendar",
`service_booking`, 2-hour slots, 48-hour lead time, 30-day window, `isActive: true`).
Neither ID the bot uses appears in that location's calendar list.

Consequence: BTU bookings either land on KTU's calendar or fail to `FailedTag`
"AI Appointment error". **This should be fixed in Closebot now regardless of migration
timing** — it is not worth waiting for the HL rebuild.

### 4.2 — BTU tags its bookings as kitchen

`ModifyTags 3f8f5ec3…` in the BTU flow adds the tag **`AI Booked Kitchen`**. The same node
ID and the same tag appear in the KTU flow. This is a copy-paste of the KTU graph that was
never re-pointed — which also explains 4.1. A second BTU path (`54f437df…`) correctly adds
`AI Booked bath`, so BTU's booking attribution is split between two tags, one of them wrong.

Anything counting bookings by tag is currently overstating KTU and understating BTU.

### 4.3 — BTU has almost no guardrails

| | KTU | BTU |
|---|---|---|
| `prohibitedWords` | ~40 terms: all pricing language (`pricing`, `quote`, `estimate`, `cost`, `invoice`, `proposal`, `discount`…), all design-review language (`photos`, `plans`, `drawings`, `blueprint`, `measurements`), and the out-of-area geos (`manhattan`, `brooklyn`, `queens`, `bronx`, `staten`, `newark`, `hudson`) | **3 entries: `Cheap`, `cheapest`, `-`** |

BTU has no word-level block on quoting price over chat and no geo block. The persona still
forbids it in prose, but the hard filter KTU relies on is absent.

### 4.4 — BTU barely follows up

| | KTU | BTU |
|---|---|---|
| `smart` | true | false |
| `repeat` | true | false |
| Sequence | 1 day → 72 hours → 30 days | **single touch at 3 weeks** |
| `extraPrompt` | Written follow-up message with booking link | **empty** |

A BTU lead who doesn't book gets one generic nudge 21 days later. KTU gets three, the first
next-day, with copy. This is very likely a measurable BTU conversion gap and is worth
quantifying against the booking data before the rebuild.

### 4.5 — Smaller items

- **KTU `CalendarName "other-use-calendarid"`** — a placeholder string left in the name
  field. The `CalendarId` beneath it is correct (`IezEuyUywqr1OL7tjHEk` = KTU), so it works,
  but it is confusing.
- **BTU loads `{{custom_values.ktu_playbook}}`** — may be deliberate (shared playbook) or
  another copy-paste artifact. Needs a decision, not a guess.
- **KTU project-scope capture has `MaxAttempts 1`** — one shot at the single most valuable
  qualification field in the flow.
- **Two `SetField` nodes carry a wrong `AiDescription`**: the phone-field node
  (`…1778381754069`) says "Validate and update `{{contact.email}}` field". Copy-paste.
- **KTU's address `SetField` expression** is `{{nodes.166b4528….result[0]}}{{contact.address}}`
  — string-concatenating a captured value onto the existing address rather than replacing it.

---

## 5. Mapping to HighLevel AI Suite

HighLevel offers two relevant surfaces. **Agent Studio** (under AI Employee Plus, billed
pay-per-use) is the right target — it is a visual canvas with typed nodes and deploys to
Conversation AI channels (SMS, chat, social). Plain Conversation AI is a prompt-and-goals
box with no graph and cannot express this flow.

| Closebot | Agent Studio equivalent | Confidence |
|---|---|---|
| Persona `howToRespond` | LLM/Prompt node — system prompt | Direct |
| `__CONFIG__.conversationReason` | Folded into the same system prompt | Direct |
| `businessInformation` custom values | Knowledge Base node, or keep as `{{custom_values.*}}` in the prompt | Direct — values already exist in HL |
| `MultiObjective` | Capture node (text/choice/date/number) | Direct |
| `AISwitch` | Conditional Routing on conversation context | Direct |
| `Comparator` (service area) | Conditional Routing | Direct |
| `Booking` + `CalendarId` | Appointment Booking action | Direct |
| `ModifyTags` | Tool node → HL API / workflow | Direct |
| `SetField` | Update Contact Field action | Direct |
| `SaveConversation` | Conversation summary | Direct |
| **`ScenarioCustom` / `ScenarioAggression`** | **No equivalent** | **GAP — see below** |
| `Delay` node | Workflow wait step, outside the agent | Partial |
| `prohibitedWords` | Prompt instruction only | **Degraded** — no hard filter |
| `typoPercent`, `breakupLargeMessagePercent`, `responseDelay` | Not available | **Lost** |
| Follow-up state machine | HL Workflow, outside the agent | Partial — rebuild as workflow |
| Model preference chain | Single model selection | **Lost** — no automatic failover |

### The one real architectural gap

Closebot's `Scenario*` nodes are **priority-ranked interrupts with a confidence threshold**
that can fire at any point in the conversation and jump the flow. KTU runs six of them:

| Priority | Trigger |
|---|---|
| 90 | Contact is aggressive or angry → end |
| 50 | "I'll get back to you later" → acknowledge, delay, resume |
| 50 | "Not interested" → end |
| 50 | "Someone already reached out to me" → end |
| 50 | Contact tags contain `AI Stop` → end |
| 50 | Appointment already exists → end |

Agent Studio's conditional routing evaluates **at a node**, not continuously across the
conversation. There is no documented equivalent to a global, priority-ranked, threshold-gated
interrupt listener.

**This is the thing most likely to make an HL rebuild feel worse than Closebot.** Without it,
an angry contact or someone who says "your rep already called me" keeps getting walked
through the qualification script. Mitigation is a combination of (a) instructing the exit
conditions in the system prompt, and (b) HL Workflow triggers on inbound message content and
tags that pause the agent externally. That is a workaround, not parity, and it needs
explicit testing before cutover.

---

## 6. Build sequence

1. **Fix 4.1 and 4.2 in Closebot now.** Misrouted bookings are costing real appointments
   today; do not let them ride until cutover.
2. Confirm the disposition of 4.3/4.4 — is BTU's weakness deliberate or neglect? The rebuild
   should not faithfully port a defect.
3. Pull KTU + BTU conversation transcripts via `/botMetric/messages` as the regression corpus.
   **Not yet done.**
4. Build the KTU agent in Agent Studio from the mapping above. KTU first — it is the more
   mature graph and will surface the gaps.
5. Test against the regression corpus, paying specific attention to the six interrupt
   scenarios.
6. Shadow-run alongside Closebot on a traffic slice. Do not hard-cut.
7. Port to BTU with correct calendar, correct tags, KTU's guardrail set, and KTU's follow-up
   cadence.

## 7. Open items

- `kEW9PFmXRzujFf6rQUPp` — which location does it belong to? Not BTU.
- Is `{{custom_values.ktu_playbook}}` in the BTU bot intentional?
- Transcript pull for the regression corpus.
- Add `/persona` and `/bot/{id}/export` to `mcp-servers/closebot/server.py` for scheduled
  config snapshots.
- Confirm AI Employee Plus is enabled on both sub-accounts and understand the per-use
  billing before building.
