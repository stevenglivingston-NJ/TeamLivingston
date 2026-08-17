#!/usr/bin/env bash
# Supabase SQL helper — run a SQL query against the public schema via PostgREST RPC.
# Usage: sb.sh '<SQL>'
# Returns JSON rows for SELECT, {"ok":true} for DML.
# Reads SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY from the environment.

set -euo pipefail

SQL="${1:-}"
if [ -z "$SQL" ]; then
  echo '{"error":"Usage: sb.sh '\''<SQL>'\''"}' >&2
  exit 1
fi

SB="${SUPABASE_URL:-https://tguwpswcneywvscxzyef.supabase.co}"
KEY="${SUPABASE_SERVICE_ROLE_KEY:-}"

if [ -z "$KEY" ]; then
  echo '{"error":"SUPABASE_SERVICE_ROLE_KEY not set"}' >&2
  exit 1
fi

# Use the Supabase Management API SQL endpoint (service role key required).
# Falls back to a known-hardcoded project ref if SUPABASE_URL doesn't have it embedded.
PROJECT_REF="${SUPABASE_PROJECT_REF:-tguwpswcneywvscxzyef}"

RESPONSE=$(curl -sf \
  -X POST \
  -H "Authorization: Bearer $KEY" \
  -H "apikey: $KEY" \
  -H "Content-Type: application/json" \
  -H "Accept-Profile: public" \
  -H "Content-Profile: public" \
  -H "Prefer: return=representation" \
  -d "{\"query\": $(echo "$SQL" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')}" \
  "https://api.supabase.com/v1/projects/${PROJECT_REF}/database/query" 2>/dev/null) || true

# If management API fails (no management token), try RPC exec_sql function
if [ -z "$RESPONSE" ]; then
  RESPONSE=$(curl -sf \
    -X POST \
    -H "Authorization: Bearer $KEY" \
    -H "apikey: $KEY" \
    -H "Content-Type: application/json" \
    -H "Accept-Profile: public" \
    -H "Prefer: return=representation" \
    -d "{\"sql\": $(echo "$SQL" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')}" \
    "${SB}/rest/v1/rpc/exec_sql" 2>/dev/null) || true
fi

if [ -n "$RESPONSE" ]; then
  echo "$RESPONSE"
else
  echo '{"error":"Both management API and exec_sql RPC failed — check SUPABASE_SERVICE_ROLE_KEY and ensure exec_sql function exists in public schema"}'
  exit 1
fi
