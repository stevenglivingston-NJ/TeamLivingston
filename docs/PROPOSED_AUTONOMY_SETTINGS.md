# Proposed `.claude/settings.json` — for Steven to apply on `main`

**Status: proposed, not applied.** I could not write this file myself — every attempt to
edit `.claude/settings.json` (via Bash, via Edit, even `git show` of it) was blocked by the
Auto-mode classifier as *Self-Modification*. That block is correct: an agent should not be
able to grant itself permissions. So the JSON below is here for you to paste.

Two things about *where* you paste it:

1. **It must land on `main`.** `mcp-servers/setup.sh` hard-resets every fresh session to
   `origin/main`. A settings change sitting on a `claude/*` branch is invisible to every
   scheduled Routine fire.
2. **Do it yourself, in the repo or the Cloud console.** Not through an agent session.

---

## Read this before you decide it's worth doing

**This is the second line of defence, not the fix.** The fix already shipped
(PR [#213](https://github.com/stevenglivingston-NJ/TeamLivingston/pull/213)): the two
stalled agents now reach Google Ads and CompanyCam through `gads.sh` / `companycam.sh`
instead of `mcp__*` tools. That change is verified against live data.

Be skeptical of the settings block on its own, for one specific reason: **`permissions.defaultMode:
bypassPermissions` was already set the entire time both agents were stalling, and it did not
help.** The Organic stall (9 days) and the Foreman stall (4 days) both happened with that key
in place. Whatever gates `mcp__*` calls in a scheduled Routine fire is *not* reading the repo's
`defaultMode`. There is no strong reason to assume it will read `permissions.allow` either.

So: **apply this if you want belt-and-braces, not because it closes the hole.** The measured
evidence says the transport change is what closed it. If you apply this and a *new* agent
stalls anyway, that is confirmation the account-level classifier is the real gate and the
answer is another curl helper, not more JSON.

Confidence, stated honestly:

| Key | Confidence it does what I claim |
|---|---|
| `permissions.allow` | High — documented, standard Claude Code settings shape |
| `permissions.deny` | High — same |
| `autoMode` | **Low.** I have not verified this key is read in a scheduled CCR fire. Treat it as a guess. If Claude Code rejects the file on load, delete the `autoMode` block first and re-test. |

---

## The JSON

Replace the whole contents of `.claude/settings.json` with this. The existing
`SessionStart` hook is preserved verbatim — do not drop it, it is what runs `setup.sh`.

```json
{
  "permissions": {
    "defaultMode": "bypassPermissions",
    "allow": [
      "mcp__serviceminder",
      "mcp__ServiceMinder",
      "mcp__ghl-ktu",
      "mcp__ghl-btu",
      "mcp__High_Level",
      "mcp__google-ads",
      "mcp__google-analytics",
      "mcp__gmb",
      "mcp__gtm",
      "mcp__closebot",
      "mcp__companycam",
      "mcp__CompanyCam",
      "mcp__clarity-live",
      "mcp__clarity-ktu-export",
      "mcp__clarity-btu-export",
      "mcp__cloudflare",
      "mcp__Cloudflare_Developer_Platform",
      "mcp__shipstation",
      "mcp__amazon-sp",
      "mcp__amazon-ads",
      "mcp__walmart-ads",
      "mcp__Shopify",
      "mcp__Helium10",
      "mcp__Supabase",
      "mcp__ClickUp",
      "mcp__JobTread",
      "mcp__Intuit_QuickBooks",
      "mcp__Bank_Connection_Truthifi",
      "mcp__Gusto",
      "mcp__Gmail",
      "mcp__Google_Drive",
      "mcp__Google_Calendar",
      "mcp__Slack",
      "mcp__Zapier",
      "mcp__Facebook_Ads",
      "mcp__Semrush",
      "mcp__Clay",
      "mcp__Canva",
      "mcp__GoDaddy",
      "mcp__Coupler_io",
      "mcp__github",
      "Read",
      "Glob",
      "Grep",
      "Bash(bash mcp-servers/sb.sh:*)",
      "Bash(bash mcp-servers/sm.sh:*)",
      "Bash(bash mcp-servers/ghl.sh:*)",
      "Bash(bash mcp-servers/gmb.sh:*)",
      "Bash(bash mcp-servers/gads.sh:*)",
      "Bash(bash mcp-servers/companycam.sh:*)",
      "Bash(bash mcp-servers/clickup.sh:*)",
      "Bash(bash mcp-servers/agent-freshness-check.sh:*)",
      "Bash(python3 mcp-servers/lead-sweep.py:*)",
      "Bash(python3 mcp-servers/tracking-audit.py:*)",
      "Bash(python3 mcp-servers/jc-labor-sync.py:*)",
      "Bash(cat:*)",
      "Bash(head:*)",
      "Bash(tail:*)",
      "Bash(sed -n:*)",
      "Bash(grep:*)",
      "Bash(ls:*)",
      "Bash(date:*)",
      "Bash(jq:*)",
      "Bash(mkdir -p:*)"
    ],
    "deny": [
      "Bash(rm -rf /*)",
      "Bash(rm -rf ~*)",
      "Bash(rm -rf $HOME*)",
      "Bash(git push --force*)",
      "Bash(git push -f*)",
      "Bash(curl * | bash)",
      "Bash(curl * | sh)"
    ]
  },
  "autoMode": {
    "allow": [
      "$defaults",
      "mcp__serviceminder",
      "mcp__ghl-ktu",
      "mcp__ghl-btu",
      "mcp__High_Level",
      "mcp__google-ads",
      "mcp__google-analytics",
      "mcp__gmb",
      "mcp__companycam",
      "mcp__CompanyCam",
      "mcp__clarity-live",
      "mcp__Supabase",
      "mcp__Slack",
      "mcp__Gmail",
      "mcp__Google_Drive"
    ],
    "soft_deny": [
      "$defaults"
    ],
    "environment": "$defaults"
  },
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "for d in /home/user/TeamLivingston /workspace/TeamLivingston \"$HOME/TeamLivingston\"; do [ -f \"$d/mcp-servers/setup.sh\" ] && { bash \"$d/mcp-servers/setup.sh\"; break; }; done; exit 0"
          }
        ]
      }
    ]
  }
}
```

---

## Why the `deny` list exists at all

The Foreman stall was **not** an `mcp__*` call. Its `pending_action` was a plain
`Bash` call: `rm -f $SD/*_insert_*.sql`. That contradicted what `CLAUDE.md` asserted
(since corrected) — `bypassPermissions` covers ordinary Bash but **not** destructive
commands, which get classified separately no matter what the mode says.

No agent spec contains an `rm`. Foreman improvised the cleanup. So the durable fix was the
one already in PR #213: `.claude/agents/foreman.md` now tells the agent to write scratch
files to a timestamped directory and **never clean up**. The `deny` list above is only
there so that if another agent improvises something destructive, it fails loudly and
immediately rather than hanging in `REQUIRES_ACTION` for nine days.

That is the real lesson from the outage and it is worth stating plainly: **a stall is
silent.** The Routine fires, the session hangs waiting for an approval nobody can give,
the board renders yesterday's rows because every agent writes-then-prunes by `scan_date`,
and nothing anywhere is marked failed. A hard deny is better than a hang.

---

## How to verify it took

After merging to `main`, wait for the next fire of any agent and run:

```bash
bash mcp-servers/agent-freshness-check.sh
```

(That script ships in PR #213. Until that PR merges it is not on `main` — the morning
Routine falls back to inline SQL through `sb.sh`, which is already there.)

It prints one line per agent section with the last `scan_date`, how many days late it is
against its own cron slot, and a RAG verdict. Green across the board over two consecutive
days is the only evidence that counts. A single green day proves nothing — the 09:00–11:20
UTC dead zone documented in `CLAUDE.md` produced several of those.
