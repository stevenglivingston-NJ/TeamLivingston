---
name: catalogue-recovery
description: >-
  Recover a KTU/BTU client's selections in JobTread and rebuild them as ONE clean,
  client-facing "Finalized" document with every product, item #, store link,
  quantity and photo, plus a team-only audit of why edits went missing. Trigger
  whenever Steven or a designer says selections, links, quantities or details are
  "missing", "lost", "not showing", "didn't save", or asks to "finalize",
  "consolidate", "clean up" or "recover" a job's selections, or asks why someone's
  JobTread updates disappeared — e.g. "selections not showing on job Master2",
  "the designer says she added the links 3 times", "make one finalized selections doc",
  "catalogue recovery on <job>". Covers JobTread selection documents (Selections tab
  and Documents), the job budget and parameters, the client's other jobs, the signed
  ServiceMinder proposal/change order, and product identification from selection
  photos.
---

# Catalogue recovery

Rebuild one final selections document for a job, from everything the rep entered,
and explain why their edits went missing. Proven on a BTU master bath on 2026-09-29:
12 sparse lines with 3 links became 19 fully specified lines with 22 photos.

**Helper:** `scripts/recover.py` (JobTread Pave API over `JOBTREAD_GRANT_KEY`; no MCP,
safe in scheduled runs). Write its output to the session scratchpad (`--out`), never
into a repo: it contains client data. **TeamLivingston is a public repo.** Never commit
client names, addresses, emails or photos.

```
python3 scripts/recover.py sweep  <jobId> --out $SCRATCH/recovery --account
python3 scripts/recover.py photos <jobId> <docNumber> --out $SCRATCH/recovery
python3 scripts/recover.py build  $SCRATCH/recovery/spec.json     # writes to the live job
python3 scripts/recover.py verify <documentId>
```

## JobTread facts this relies on (verified 2026-09-29, sandbox job "ZZ SANDBOX Selections Phase2")

| Behavior | Consequence |
|---|---|
| Line edits on a **pending** or **approved** customer order are refused: `cannot be updated while this Customer Order is approved` | The #1 cause of "I added it and it was lost". Reopen to **draft** first. |
| First approval of a simple selection copies each line into the **budget** | Later edits to the selection **never** update those budget copies, and edits to a budget copy never reach the selection. They drift apart silently. |
| Deleting a selection leaves its budget copies behind | Clean them up by hand |
| A document can only be deleted in **draft** or denied | Set to draft first |
| Simple-selection docs (`isSimpleSelection`) show under the job's **Selections tab**, not Documents. Their name is forced to "Selection", and `description` and `footer` are silently dropped | For a sheet that must show under **Documents** with a header, build a regular customer order |
| Customer-order names are restricted to **Proposal, Selections, Change Order, Bathtune Up Proposal** | Name it "Selections"; put "Finalized — <Room>" in the **subject** |
| Custom fields (Internal Notes, Purchasing Link…) do **not** save on document lines, only on budget lines | Keep internal notes in a **team-only comment** (`isVisibleToCustomerRoles:false`, `isVisibleToVendorRoles:false`, pinned) |
| `updateCostItem(files: …)` **replaces** a line's files | Upload all of a line's photos, then attach them in **one** call |
| Line-level edit history is **not** logged. Events cover document status changes, creation and deletion, with user and device | Absence of evidence is not evidence of a save. Say so. |
| `updateDocument` defaults `notify: true` | Always pass `notify: false` |
| Event timestamps are **UTC** | Convert to Eastern before reporting (the helper does) |

## Procedure

1. **Sweep the job** (`sweep --account`). Read: documents (tab, status, line counts);
   hand-added budget lines (the rep's picks, copied in at approval); **budget quantities**
   (formula-driven from parameters: the real quantities); parameters with values; every line
   with a link; the **status timeline**; and sibling jobs on the same account.
2. **Check the other sources for this job only.** ServiceMinder proposal and change order via
   `mcp-servers/sm.sh <BRAND> proposal/details '{"Id":…}'`. That gives the **signed scope per
   room** (description text), not links. Also the Drive design packet (drawings) and any pricing-app
   order sheet (`ordersheet:<jobId>` in the pricing KV). Record what's there and what isn't.
3. **Pull the photos** from the rep's most complete selection (`photos <jobId> <n>`) and **look
   at every one**. Many are screenshots of the product page, and the name, item # and price are
   readable off them. Note photos attached to the wrong line (e.g. a tile shot on the chandelier line).
4. **Match across jobs by photo filename.** The sweep prints matches. The same `IMG_xxxx` on a
   sibling job's line usually carries the brand, SKU and link the rep typed there.
5. **Verify every link** before writing it: `curl -L -A "Mozilla/5.0" <url>` and check the
   page `<title>`. Test a bogus URL on the same site first, since some sites answer 200 for anything.
   Tile Shop: `https://www.tileshop.com/sitemap.xml` lists every product URL with its item #.
   Joss & Main blocks automated checks (429). Keep the link the rep saved, or give the SKU only.
   Never invent a URL.
6. **Take quantities from the job**, in this order: budget line quantity, then parameter value,
   then the rep's line. If none, write "to be confirmed", never a guess.
7. **Write the spec** (`references/finalized-spec.example.json`) and **show Steven the line list
   before building**. `build` creates a **draft** customer order named "Selections",
   subject "Finalized — <Room>", `includeInBudget:false`, signature required, sender and recipient
   copied from the rep's existing sheet, with photos and the two team-only comments. Then `verify`.
8. **Client-facing check** (`verify` flags leftovers). Line text reads: product name, what it is,
   `Quantity: …`, `Where to buy: <Store> — <link>`. Unknowns read "Exact model to be confirmed
   before ordering" or "Quantity to be confirmed after final measurements". Never OPEN, CONFIRM,
   parameter names, budget talk, IMG filenames or staff names. Header: the room, the address, a
   review-and-sign instruction, "to be confirmed" explained, and "Pricing is carried on your
   approved proposal and change order."
9. **Team-only comments** hold what the client must not see: open items with their quantity
   source, **scope questions** (a line not in the room's signed scope), and where each line came
   from (rep's line + photo + budget line/parameter + sibling job).

## Guardrails

- **Before changing any document's status, check the event log for edits by anyone in the last
  hour.** On 2026-09-29 an approval landed 8 minutes after the designer reopened the sheet to edit
  it, which likely refused her save. If someone is active, ask first.
- Approving, sending, or deleting the rep's own documents needs Steven's explicit go-ahead each time.
  Leave the rep's copies alone until the Finalized sheet is confirmed.
- The Finalized sheet stays **draft** until the open items are filled. Once sent it locks, so tell
  the team to fill gaps on the draft.
- Flag, don't drop, lines outside the signed scope (e.g. a faucet or paint listed only for another room).

## Audit: why the edits were lost

Answer from the sweep's status timeline and the facts table:

1. List every **draft window** (editable) vs **pending/approved** (locked), with durations and the
   device (iPhone vs Mac) per change. Seconds-long reopenings mean the rep tried to edit and relocked.
2. Check for **copies** (several "Selections" docs with the same lines): typing into one never
   updates the others.
3. Compare doc lines' `jobCostItem` links with budget copy `createdAt`. Budget copies newer than the
   first approval mean earlier copies were removed, and anything typed into them went too. Line
   deletions aren't logged, so say that plainly.
4. Rule out automation: every event's `createdByGrantName` / user agent. "JobTread App" means a person;
   "Access for claude.ai" or "Catalogue" (Python) means Claude.
5. If the mechanism is in doubt, **reproduce it on "ZZ SANDBOX Selections Phase2"**: create, approve,
   edit, unapprove, re-approve, compare. Then set to draft, delete the document **and** its leftover
   budget copies.

Report: the most likely cause first, a to-scale timeline, the contributing factors, what it wasn't,
prevention steps for the team, and questions for JobTread support. A printable version renders with
`/opt/pw-browsers/chromium-*/chrome-linux/chrome --headless=new --no-sandbox --no-pdf-header-footer --print-to-pdf=out.pdf file://…`
(force the light theme, `@page{size:Letter}`).

## Prevention (for the team)

1. Set the selection to **Draft** before editing. Edit, **Save**, refresh to confirm, then send or approve.
2. One selection per room. Reopen it rather than copying it.
3. After an approved selection changes, update the matching budget line by hand.
4. Enter long link lists on a computer, not the phone.
