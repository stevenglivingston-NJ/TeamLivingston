# Playbook — playbook.ktubtu.com

The team's operating standards, published as a static site (Cloudflare Pages project
`ktu-playbook`). This folder is the source of truth; the site is a copy.

| Page | File | Document |
|---|---|---|
| `/` | `index.html` | **Library** — the home page: every document as a card (title, description, audience, version), search, quick answers, links to the daily tools |
| `/lead-to-last-nail/` | `lead-to-last-nail/index.html` | Lead to Last Nail — the 15-stage operating standard (v1.2) |
| `/btu-handover-sop/` | `btu-handover-sop/index.html` | BTU-OPS-001 Sales-to-Production Handover SOP (v1.1) |
| `/ktu-handover-standard/` | `ktu-handover-standard/index.html` | KTU Sales→PM Handover Standard V2 — verbatim signed text |
| `/selections-and-ordering/` | `selections-and-ordering/index.html` | Selections & Order Sheet standard (v2.6) + orders.ktubtu.com (Job Tracker sheet retired) |
| `/systems/` | `systems/index.html` | Systems & Where Things Live: which software is for what, where each record lives, how a job moves between systems (v1.0) |

Publish (from any Claude cloud session; `CLOUDFLARE_API_TOKEN` is in the environment):

```
cd playbook && npx wrangler pages deploy . --project-name ktu-playbook --branch main --commit-dirty=true
```

Every document page loads `assets/fold.css` + `assets/fold.js`: each `<h2>` section folds to its title and the one-line description in its `data-desc` attribute, Lead to Last Nail stages fold to title + lead paragraph, a Contents bar with Expand all / Collapse all is added, links to an id inside a fold open it, and printing opens everything. **A new section needs a `data-desc`.** A new document needs a card on the Library page.

Rules: edit here, then publish — never hand-edit the live site. Signed documents (the KTU
standard) are reproduced verbatim; a change needs a new signed version. Every SOP carries a
change log. The intranet links here from its Playbook tab.
