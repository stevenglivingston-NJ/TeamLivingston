---
name: google-drive-cleanup
description: >-
  Audit and reorganize a messy Google Drive (or Shared Drive) into a clean,
  team-friendly structure. Use when the user asks to "clean up", "organize",
  "dedupe", "reorganize", or "declassify/classify" a Drive, or complains about
  duplicate files, duplicate folders, cluttered root, or hard navigation.
  Scans everything, proposes a numbered category taxonomy, then executes the
  moves: files into categories, duplicates + empty files/folders + junk into a
  Trash folder. Reversible (Trash is a normal folder, not permanent deletion).
---

# Google Drive Clean-Up

A repeatable flow for turning a cluttered Drive into a "best-in-class" one.
Proven on the KTU Bloomfield shared drive AND a personal My Drive.

## Step 0 — Identify the drive & account (do this FIRST)
Multiple Google connections may be attached (e.g. one Zapier connection per
account). Before enumerating or moving anything, confirm which account you're
pointed at so you don't reorganize the wrong drive:
`execute_zapier_read_action` → `_zap_raw_request`, GET
`https://www.googleapis.com/drive/v3/about?fields=user,storageQuota`.
Match the returned `displayName`/email to the drive the user asked for. Note the
type: a **Shared Drive** (root id like `0A...`) vs a **personal My Drive**
(root alias `'root'`) — they behave differently for moves (see below).

## Guardrails (read first)
- **Never touch** folders the user names as off-limits (e.g. `.Project Management`,
  `.Archive`). Confirm the exclusion list before moving anything.
- **Business drive:** nothing personal belongs in it — flag personal/owner files
  and ask whether to relocate vs delete. **Personal drive:** the opposite — it
  holds tax returns, credit reports, IDs, wills, PFS, bank statements. Handle as
  sensitive: never share/expose, and gather these under one Finance & Legal
  category rather than scattering them.
- **Scale check.** Personal roots can be huge (this one: 460 root items / ~400
  loose files). Confirm the taxonomy with the user before firing hundreds of
  moves, and warn that a big drive is many operations.
- **Live-sync folders are fragile.** CompanyCam / backup tools sync to a folder;
  reparenting keeps the same folder ID so ID-based syncs survive, but if the
  integration recreates a folder *by name at root* it can split. When unsure,
  leave the synced folder at root and out of the reorg.
- **Reversible, not destructive.** "Trash" here is a real folder you create, not
  Google's system trash. Nothing is permanently deleted.

## Tooling notes (hard-won)
- **Moves go through Zapier**, not the direct Google Drive connector (the Drive
  MCP has no move/delete). Tool: `mcp__Zapier__execute_zapier_write_action`
  with `selected_api:"GoogleDriveCLIAPI"`, `action:"move_file"`,
  `params:{file:<ID>, folder:<DEST_ID>}`. Raw file/folder IDs work directly.
  `status:"SUCCESS"` = done (ignore the cosmetic `results` shape).
- **Create folders** with the Drive MCP `create_file`
  (`mimeType:"application/vnd.google-apps.folder"`, `parentId:<root or dest>`).
  This one CAN target the shared-drive root ID.
- **Shared-drive root is NOT a valid move destination** — `move_file` to the
  drive-root ID fails with `File not found: ___sharedWithMe___`. On a **personal
  My Drive**, the alias `'root'` IS a valid destination, so moving items back to
  root works there.
- **Enumerate via the raw API when the direct MCP is on a different account.**
  `_zap_raw_request` GET `.../drive/v3/files?q='<PARENT_ID>' in parents and
  trashed=false&fields=files(id,name,mimeType,size,modifiedTime),nextPageToken&pageSize=1000`.
  Big listings overflow context — save to a file and parse with python. (Note:
  Google-native Docs/Sheets return `size:null`; fetch size separately only if you
  must distinguish blank ones.)
- **Cheapest move = raw PATCH.** For high-volume reorgs use
  `google_drive_make_api_mutating_request`, method PATCH, url
  `.../drive/v3/files/<ID>`, querystring
  `{addParents:<DEST>, removeParents:<OLD_PARENT_or_'root'>, fields:"id"}` — the
  `fields:"id"` keeps the response tiny (the `move_file` wrapper returns full
  metadata and burns tokens fast at scale). Still throttle to ~4 concurrent.
- **Throttle to ~4 moves per message.** 10+ parallel → "User rate limit
  exceeded"; retry those IDs next batch.
- **Do the moves in the MAIN thread.** The permission classifier blocks
  *spawning a subagent* to run Zapier writes (reads it as routing around a
  Zapier deny rule). Subagents are fine for read-only enumeration.
- **File size caveats:** Google-native files (Docs/Sheets) report a 1024-byte
  minimum even when blank — 1024 ≠ empty. Truly empty binary files show
  `fileSize:"0"` and md5 `d41d8cd98f00b204e9800998ecf8427e`.

## Flow

### 1. Enumerate everything
Recursively list from the root with `mcp__Google_Drive__search_files`
(`query:"parentId = '<ID>'"`, `pageSize:100`, `excludeContentSnippets:true`,
follow `nextPageToken`). Fan out with **read-only subagents** (one per big
subtree) to stay within context; tell each to summarize media-heavy folders as
"N images, M videos" instead of listing every asset, and to flag: duplicate
file names, duplicate folder names, and empty folders.

### 2. Classify → propose taxonomy
Default numbered top-level categories (adjust to the business):
`01 Company & HR · 02 Sales & Pricing · 03 Operations ·
04 Clients & Projects · 05 Marketing & Media · 06 Finance ·
07 Vendors & Products`, plus `Trash`.
Keep genuinely coherent existing hubs intact (e.g. a well-organized brand
folder, an existing resource library) rather than shredding them — place the
whole hub, or distribute its already-category-aligned subfolders.

### 3. Decide routing per item
- Loose root files → the fitting category.
- **Duplicates** → keep one canonical copy (newest / largest / best-named),
  send the rest to **Trash**. Byte-identical = same `fileSize` (and md5).
- **Empty files** (true 0-byte) and **empty folders** → **Trash**.
- **Junk** (broken `.lnk` shortcuts, `.bat`, stray `.html` export artifacts,
  blank "Untitled" 1024-byte Docs/Sheets, temp `~$...` files) → **Trash**.
- Whole well-formed folders → move as a unit into their category.

### 4. Execute
Create the category folders + Trash (Drive MCP `create_file`). Then run the
moves in main-thread batches of ~4 (Zapier `move_file`). Verify a couple with
`get_file_metadata` (check `parentId`) early to confirm the pipeline works.

### 5. Verify + report
List the root again; confirm only category folders + intact hubs + Trash
remain. Report: taxonomy created, counts moved per category, count sent to
Trash, and anything left for the user to decide (personal files, synced
folders, ambiguous items). Tell the user to review Trash, then empty it when
satisfied.
