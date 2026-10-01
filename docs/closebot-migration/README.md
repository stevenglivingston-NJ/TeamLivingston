# Closebot configuration extraction — 2026-09-19

Raw, unmodified exports from the Closebot API. See
[`../CLOSEBOT-TO-HIGHLEVEL-MIGRATION.md`](../CLOSEBOT-TO-HIGHLEVEL-MIGRATION.md)
for the teardown, defect list and HighLevel mapping.

| File | Source endpoint |
|---|---|
| `ktu.kdl` | `GET /bot/bot_SRQO2QVP9AVZ8SQ4/export` → `.kdl` |
| `btu.kdl` | `GET /bot/bot_O8XUQA6CTBLEILUV/export` → `.kdl` |
| `smscampaign.kdl` | `GET /bot/bot_CBHGI91ODANAAOLB/export` → `.kdl` |
| `linqblue.kdl` | `GET /bot/bot_1DKPS7TNL4OLVE7Q/export` → `.kdl` |
| `persona-andy.json` | `GET /persona` |
| `bots-index.json` | `GET /bot` |

Neither `/persona` nor `/bot/{id}/export` appears in the swagger spec the MCP server
was generated from. `/bot/{id}/export` returns the complete flow graph and is the
only programmatic route to a bot's prompt and logic.

Contains no credentials. Does contain HighLevel location IDs, calendar IDs and
custom-value names, all of which are already in `CLAUDE.md`.
