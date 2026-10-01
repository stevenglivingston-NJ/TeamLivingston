# Change log

Every change to a tool, flow, integration or deploy — **who / what / when / where**. Newest first.
Add an entry with every change; the **Tekki** agent mirrors this to the intranet Change Log
(Tech Stack tab). Format: `YYYY-MM-DD · who · WHERE (repo/system) · WHAT — detail [link]`.

## 2026-10-01
- **2026-10-01 · Claude Code (for Steven) · Playbook + CLAUDE.md · Job Tracker sheet is a read-only copy** — Selections & Order Sheet v2.5 §7 rewritten (why it stopped being two-way, what it is for, mid-October review); CLAUDE.md orders row says the same. Code in ktu-pricing-build `sheets.js`. [#pending]
- **2026-10-01 · Claude Code (for Steven) · TeamLivingston playbook · Four gaps closed from a re-audit** — Lead to Last Nail no longer claims to be "the one copy" (it is one page of six; the Library is the source of truth); Selections & Order Sheet v2.4 adds "The selection appointment" ahead of §1 (lookbook tier ladder, delta pricing, Track A single-visit rule) with every existing anchor untouched; the Library gains a card for the Lead-to-Handover Acceptance Test, which had zero mentions across all six pages. The KTU Handover Standard carries **three** conflicting reface durations (5–7 wks end-to-end, 7–9 wks "excluding client time", 7–10 wks from design approval) — flagged in an editorial note outside the signed text, since correcting it needs a new signed version. **Owner's ruling pending.** [#243]
- **2026-10-01 · Claude Code (for Steven) · TeamLivingston · CLAUDE.md: Supabase function deploys work again** — `SUPABASE_ACCESS_TOKEN` in ktu-pricing-build now holds a personal access token; the 401 note is gone. [#pending]

## 2026-09-30
- **2026-09-30 · Claude Code (for Steven) · Supabase + Playbook · Orders → JobTread write-back; "After the signature" runbook** — migration `20260930e_orders_jobtread_writeback.sql` (applied): `ord_lines.jt_*` columns, `ord_jt_pending/mark`, `ord_jt_jobs_due/job_mark`, `ord_jt_job_state`; `jt_pushed` hidden from people without cost access. Playbook Selections & Order Sheet v2.3 §9 (each step from signed sheet to start date: owner, deadline, where, what updates itself); BTU-OPS-001 §9.2–9.3 point at orders.ktubtu.com; home FAQ updated. [#pending]
- **2026-09-30 · Claude Code (for Steven) · Playbook · One client-facing install number** — Lead to Last Nail stage 11 and BTU-OPS-001 §3 (v1.2) now say "install typically 60–90 days after the signed design and selections", the same line the new automatic welcome email (ktu-pricing-build `portal/email/build.py`) sends on deposit; stage 11 lists that email next to the 24-hour welcome call. [#pending]
- **2026-09-30 · Claude Code (for Steven) · ktu-pricing-build + Supabase · Client selection link: stages, change log, notes, research tasks, change orders, batched alerts; signature before any order** — approval is a pre-order review; the order sheet reads Awaiting signed sheet until the JobTread Selection Sheet is signed; one round of changes then change-order requests; cron `*/5` replaces `45 */2`. [ktu-pricing-build#29]
- **2026-09-30 · Claude Code (for Steven) · Supabase + orders.ktubtu.com · Workbook enforces the signature rule** — `jc_jobs.selections_signed` (from JobTread, or a named "Signed (paper)" tick for jobs with no JobTread job); `ord_save_line` refuses placing an order on an unsigned job; lines already ordered stay editable. Migration `20260930d_orders_signature_rule.sql`. [#234]
- **2026-09-30 · Claude Code (for Steven) · TeamLivingston playbook · Selections & Order Sheet: signature rule and the selection-link stages** [#234]
- **2026-09-30 · Claude Code (for Steven) · TeamLivingston · Require-CHANGELOG check + PR template** — CI nudge to keep this log current. [#pending]
- **2026-09-30 · Claude Code (for Steven) · TeamLivingston · Tekki owns the change log; Playbook "Tools & How-To" page** — Tekki mirrors each repo's CHANGELOG.md to the intranet and flags undocumented changes; new playbook page with flow diagram + how-tos, deployed to playbook.ktubtu.com. [#233]

<!-- Add new entries above this line, newest first. -->
