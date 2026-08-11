#!/usr/bin/env bash
# Supabase PostgREST helper for non-interactive agent runs (Ax, etc).
# Usage: sb.sh '<SQL-like PostgREST path or raw SELECT ...>'
# Simplified: this wraps curl to PostgREST. For SELECTs, pass a resource path
# query string (e.g. "notify_queue?select=*&status=eq.pending&order=created_at&limit=50").
# For writes, prefix with METHOD (PATCH/POST) and pass path + JSON body via env BODY.
#
# Examples:
#   sb.sh "notify_queue?select=*&status=eq.pending&created_at=lt.$(date -u -d '-5 min' +%Y-%m-%dT%H:%M:%S)&order=created_at&limit=50"
#   METHOD=PATCH BODY='{"status":"sent","sent_at":"now()"}' sb.sh "notify_queue?id=eq.<uuid>"
#
# Requires SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in the environment.

set -euo pipefail

if [[ -z "${SUPABASE_URL:-}" || -z "${SUPABASE_SERVICE_ROLE_KEY:-}" ]]; then
  echo '{"error":"SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY not set"}' >&2
  exit 1
fi

PATH_QUERY="${1:?usage: sb.sh '<postgrest-path-and-query>'}"
METHOD="${METHOD:-GET}"
SB_URL="${SUPABASE_URL%/}"

ARGS=(-sS -X "$METHOD"
  "${SB_URL}/rest/v1/${PATH_QUERY}"
  -H "apikey: ${SUPABASE_SERVICE_ROLE_KEY}"
  -H "Authorization: Bearer ${SUPABASE_SERVICE_ROLE_KEY}"
  -H "Accept-Profile: public"
  -H "Content-Profile: public"
  -H "Content-Type: application/json"
)

if [[ "$METHOD" != "GET" ]]; then
  ARGS+=(-H "Prefer: return=representation")
  if [[ -n "${BODY:-}" ]]; then
    ARGS+=(-d "$BODY")
  fi
fi

curl "${ARGS[@]}"
