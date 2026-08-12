#!/usr/bin/env bash
# sb.sh — run SQL against the Axyom intranet Supabase project with no MCP prompt.
#
#   bash mcp-servers/sb.sh "SELECT * FROM notify_queue WHERE status='pending' LIMIT 5"
#
# Scheduled agent runs are non-interactive: an MCP call (mcp__Supabase__execute_sql)
# blocks on an "Allow" prompt nobody can answer and the run stalls. This wrapper goes
# straight to PostgREST over curl instead. See sb.py for the supported SQL subset.
#
# Requires SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in the environment.
set -euo pipefail
exec python3 "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/sb.py" "$@"
