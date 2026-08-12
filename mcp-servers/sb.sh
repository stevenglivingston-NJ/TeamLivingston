#!/usr/bin/env bash
# sb.sh — run SQL against the Axyom Supabase project without an MCP permission prompt.
#
#   bash mcp-servers/sb.sh "SELECT * FROM notify_queue WHERE status='pending' LIMIT 50"
#
# Prints a JSON array of rows for SELECT, {"ok":true,"count":N} for writes, and
# {"error":"..."} with a non-zero exit on failure. Reads SUPABASE_URL and
# SUPABASE_SERVICE_ROLE_KEY from the environment. See sb.py for the supported
# SQL subset — it is deliberately narrow, and rejects anything it cannot
# translate faithfully rather than guessing.
set -euo pipefail
exec python3 "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/sb.py" "$@"
