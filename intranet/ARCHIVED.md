# This intranet path is archived — do not deploy from here

**2026-09-13.** `dash.goaxyom.com` is now built and deployed from a different
repository: **github.com/stevenglivingston-NJ/KTUBTU-Intranet**, branch
`claude/intranet-deployment-8p6vy7` as of this date (confirmed live via the
Cloudflare API — the worker's `workers/alias` and `modified_on` timestamp
match that branch's latest commit to the second).

## Why this folder stopped being the source of truth

`ktubtuintranet.html` here and `KTUBTU-Intranet`'s `index.html` are two
independent rebuilds of the same app that both targeted the identical
Cloudflare Worker name (`ktubtuintranet`) and the identical custom domain
(`dash.goaxyom.com`). Whichever one deployed last, won — silently, with no
merge and no warning. `KTUBTU-Intranet` deployed more recently and has since
pulled substantially ahead (431 live functions vs. 302 here as of the last
comparison — this copy is missing entire tabs: Job Costing, Legal entities,
Invoicing reconciliation, the Tools panel, and more).

`RECONCILIATION.md` in this folder documents an earlier round of the same
problem, from 2026-08-18. Read it for history, not for current instructions —
its "treat `ktubtuintranet.html` as the source of truth, deploy only from
here" guidance is what this archive notice supersedes.

## What was done to make this safe

`wrangler.jsonc` no longer names the `ktubtuintranet` worker and no longer
claims the `dash.goaxyom.com` route, so `npm run deploy` here can no longer
silently overwrite production even by accident. The code and its history stay
in the repo — nothing here was deleted.

## If this ever needs to come back

That's a deliberate decision, not a `git revert`. Talk to Steven first, and
re-run the same live-vs-repo function-set comparison this notice is based on
before touching either `wrangler.jsonc`.
