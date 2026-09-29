# Playbook — playbook.ktubtu.com

The team's operating standards, published as a static site (Cloudflare Pages project
`ktu-playbook`). This folder is the source of truth; the site is a copy.

| Page | File | Document |
|---|---|---|
| `/` | `index.html` | Lead to Last Nail — the 15-stage operating standard (v1.2) |
| `/btu-handover-sop/` | `btu-handover-sop/index.html` | BTU-OPS-001 Sales-to-Production Handover SOP (v1.1) |
| `/ktu-handover-standard/` | `ktu-handover-standard/index.html` | KTU Sales→PM Handover Standard V2 — verbatim signed text |
| `/selections-and-ordering/` | `selections-and-ordering/index.html` | Selections & Order Sheet standard (v2.0) + Job Tracker |

Publish (from any Claude cloud session; `CLOUDFLARE_API_TOKEN` is in the environment):

```
cd playbook && npx wrangler pages deploy . --project-name ktu-playbook --branch main --commit-dirty=true
```

Rules: edit here, then publish — never hand-edit the live site. Signed documents (the KTU
standard) are reproduced verbatim; a change needs a new signed version. Every SOP carries a
change log. The intranet links here from its Playbook tab.
