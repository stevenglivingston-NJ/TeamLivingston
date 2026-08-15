#!/usr/bin/env bash
# sb.sh — Supabase PostgREST REST wrapper for Ax / agent hourly runs
# Usage: sb.sh '<SQL>'
# Translates common SQL patterns to PostgREST REST calls.
# Returns JSON rows for SELECT, {"ok":true} for writes.
#
# Required env vars (set in Cloud environment secrets):
#   SUPABASE_URL              https://tguwpswcneywvscxzyef.supabase.co
#   SUPABASE_SERVICE_ROLE_KEY sb_secret_...

set -euo pipefail

SB_URL="${SUPABASE_URL:-}"
SB_KEY="${SUPABASE_SERVICE_ROLE_KEY:-}"

if [[ -z "$SB_URL" || -z "$SB_KEY" ]]; then
  echo '{"error":"SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY not set"}' >&2
  exit 1
fi

SQL="${1:-}"
if [[ -z "$SQL" ]]; then
  echo '{"error":"No SQL provided"}' >&2
  exit 1
fi

# Shared headers for all PostgREST calls
AUTH_HEADERS=(
  -H "apikey: ${SB_KEY}"
  -H "Authorization: Bearer ${SB_KEY}"
  -H "Accept-Profile: public"
  -H "Content-Profile: public"
  -H "Accept: application/json"
)

# Try the execute_sql RPC first (may not exist on all projects)
RPC_RESULT=$(curl -s -w "\n__STATUS__%{http_code}" \
  -X POST \
  "${AUTH_HEADERS[@]}" \
  -H "Content-Type: application/json" \
  "${SB_URL}/rest/v1/rpc/execute_sql" \
  -d "{\"query\": $(python3 -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$SQL")}" 2>/dev/null)

RPC_STATUS=$(echo "$RPC_RESULT" | grep -o '__STATUS__[0-9]*' | grep -o '[0-9]*' || echo "0")
RPC_BODY=$(echo "$RPC_RESULT" | sed 's/__STATUS__[0-9]*$//' | tr -d '\n')

if [[ "$RPC_STATUS" == "200" ]]; then
  echo "$RPC_BODY"
  exit 0
fi

# Fallback: translate simple SQL patterns to PostgREST REST

# ---- SELECT ----
if echo "$SQL" | grep -qi '^\s*SELECT'; then
  TABLE=$(echo "$SQL" | python3 -c "
import sys, re
sql = sys.stdin.read()
m = re.search(r'FROM\s+(\w+)', sql, re.IGNORECASE)
print(m.group(1) if m else '')
")
  if [[ -z "$TABLE" ]]; then
    echo '{"error":"Could not parse table from SELECT"}' >&2; exit 1
  fi

  # Build PostgREST query string from WHERE/ORDER/LIMIT
  QS=$(echo "$SQL" | python3 - <<'PYEOF'
import sys, re

sql = sys.stdin.read()

# Extract ORDER BY
order = ""
m = re.search(r'ORDER\s+BY\s+(\w+)(\s+(ASC|DESC))?', sql, re.IGNORECASE)
if m:
    col = m.group(1)
    dir_ = (m.group(3) or 'ASC').lower()
    order = f"order={col}.{dir_}"

# Extract LIMIT
limit = ""
m = re.search(r'LIMIT\s+(\d+)', sql, re.IGNORECASE)
if m:
    limit = f"limit={m.group(1)}"

# Extract WHERE conditions (simple key=value / key>'value' patterns)
filters = []
where_m = re.search(r'WHERE\s+(.+?)(?:\s+ORDER|\s+LIMIT|$)', sql, re.IGNORECASE | re.DOTALL)
if where_m:
    where_clause = where_m.group(1).strip()
    # Handle: col='val' AND col2<'val2' etc.
    for cond in re.split(r'\s+AND\s+', where_clause, flags=re.IGNORECASE):
        cond = cond.strip()
        # status='pending' -> status=eq.pending
        m2 = re.match(r"(\w+)\s*=\s*'([^']*)'", cond)
        if m2:
            filters.append(f"{m2.group(1)}=eq.{m2.group(2)}")
            continue
        # status IN ('a','b') -> status=in.(a,b)
        m3 = re.match(r"(\w+)\s+IN\s*\(([^)]+)\)", cond, re.IGNORECASE)
        if m3:
            vals = ','.join(v.strip().strip("'") for v in m3.group(2).split(','))
            filters.append(f"{m3.group(1)}=in.({vals})")
            continue
        # created_at < now() - interval '5 minutes' -> approximate with a timestamp
        m4 = re.match(r"(\w+)\s*<\s*now\(\)\s*-\s*interval\s*'(\d+)\s+(\w+)'", cond, re.IGNORECASE)
        if m4:
            import datetime
            col = m4.group(1)
            n = int(m4.group(2))
            unit = m4.group(3).rstrip('s')
            delta = datetime.timedelta(**{unit+'s': n})
            ts = (datetime.datetime.utcnow() - delta).strftime('%Y-%m-%dT%H:%M:%S')
            filters.append(f"{col}=lt.{ts}")
            continue
        # col < 'val'
        m5 = re.match(r"(\w+)\s*<\s*'([^']*)'", cond)
        if m5:
            filters.append(f"{m5.group(1)}=lt.{m5.group(2)}")
            continue
        # id='uuid'
        m6 = re.match(r"(\w+)\s*=\s*'([^']*)'", cond)
        if m6:
            filters.append(f"{m6.group(1)}=eq.{m6.group(2)}")

parts = filters + ([order] if order else []) + ([limit] if limit else [])
print('&'.join(parts))
PYEOF
)

  RESULT=$(curl -s -w "\n__STATUS__%{http_code}" \
    "${AUTH_HEADERS[@]}" \
    "${SB_URL}/rest/v1/${TABLE}?${QS}")
  STATUS=$(echo "$RESULT" | grep -o '__STATUS__[0-9]*' | grep -o '[0-9]*' || echo "0")
  BODY=$(echo "$RESULT" | sed 's/__STATUS__[0-9]*$//')
  echo "$BODY"
  [[ "$STATUS" == "200" ]] && exit 0 || exit 1
fi

# ---- UPDATE / PATCH ----
if echo "$SQL" | grep -qi '^\s*UPDATE'; then
  TABLE=$(echo "$SQL" | python3 -c "
import sys, re
sql = sys.stdin.read()
m = re.search(r'UPDATE\s+(\w+)', sql, re.IGNORECASE)
print(m.group(1) if m else '')
")
  if [[ -z "$TABLE" ]]; then
    echo '{"error":"Could not parse table from UPDATE"}' >&2; exit 1
  fi

  # Parse WHERE clause for ID filter
  WHERE_ID=$(echo "$SQL" | python3 -c "
import sys, re
sql = sys.stdin.read()
m = re.search(r\"WHERE\s+id\s*=\s*'([^']+)'\", sql, re.IGNORECASE)
print(m.group(1) if m else '')
")

  # Parse SET clause into JSON
  SET_JSON=$(echo "$SQL" | python3 - <<'PYEOF'
import sys, re, json

sql = sys.stdin.read()
set_m = re.search(r'SET\s+(.+?)\s+WHERE', sql, re.IGNORECASE | re.DOTALL)
if not set_m:
    print('{}')
    sys.exit(0)

set_clause = set_m.group(1)
obj = {}

# Parse: col=now(), col='val', col='{"json":"val"}'::jsonb
for part in re.split(r',\s*(?=\w+\s*=)', set_clause):
    part = part.strip()
    m = re.match(r"(\w+)\s*=\s*(.*)", part, re.DOTALL)
    if not m:
        continue
    col = m.group(1)
    val = m.group(2).strip().rstrip(',').strip()
    # now()
    if val.lower() in ('now()', 'current_timestamp'):
        import datetime
        obj[col] = datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S') + 'Z'
    # ::jsonb cast
    elif '::jsonb' in val or '::json' in val:
        val = re.sub(r'::(jsonb?|text|varchar).*$', '', val).strip()
        val = val.strip("'")
        try:
            obj[col] = json.loads(val)
        except Exception:
            obj[col] = val
    # quoted string
    elif val.startswith("'") and val.endswith("'"):
        obj[col] = val[1:-1]
    # number
    elif re.match(r'^\d+$', val):
        obj[col] = int(val)
    else:
        obj[col] = val

print(json.dumps(obj))
PYEOF
)

  FILTER="?id=eq.${WHERE_ID}"
  [[ -z "$WHERE_ID" ]] && FILTER=""

  HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
    -X PATCH \
    "${AUTH_HEADERS[@]}" \
    -H "Content-Type: application/json" \
    -H "Prefer: return=minimal" \
    "${SB_URL}/rest/v1/${TABLE}${FILTER}" \
    -d "$SET_JSON")

  if [[ "$HTTP_STATUS" == "204" || "$HTTP_STATUS" == "200" ]]; then
    echo '{"ok":true}'
  else
    echo "{\"error\":\"PATCH returned HTTP $HTTP_STATUS\"}" >&2
    exit 1
  fi
  exit 0
fi

# ---- INSERT ----
if echo "$SQL" | grep -qi '^\s*INSERT'; then
  TABLE=$(echo "$SQL" | python3 -c "
import sys, re
sql = sys.stdin.read()
m = re.search(r'INSERT\s+INTO\s+(\w+)', sql, re.IGNORECASE)
print(m.group(1) if m else '')
")

  # Parse columns and values
  INSERT_JSON=$(echo "$SQL" | python3 - <<'PYEOF'
import sys, re, json

sql = sys.stdin.read()
m = re.search(r'INSERT\s+INTO\s+\w+\s*\(([^)]+)\)\s*VALUES\s*\((.+)\)', sql, re.IGNORECASE | re.DOTALL)
if not m:
    print('{}')
    sys.exit(0)

cols = [c.strip() for c in m.group(1).split(',')]
vals_raw = m.group(2).strip()

# Split values respecting quotes and parens
vals = []
current = ''
depth = 0
in_quote = False
i = 0
while i < len(vals_raw):
    c = vals_raw[i]
    if c == "'" and not in_quote:
        in_quote = True
        current += c
    elif c == "'" and in_quote:
        if i+1 < len(vals_raw) and vals_raw[i+1] == "'":
            current += "''"
            i += 2
            continue
        in_quote = False
        current += c
    elif c == '(' and not in_quote:
        depth += 1
        current += c
    elif c == ')' and not in_quote:
        depth -= 1
        current += c
    elif c == ',' and not in_quote and depth == 0:
        vals.append(current.strip())
        current = ''
        i += 1
        continue
    else:
        current += c
    i += 1
if current.strip():
    vals.append(current.strip())

obj = {}
for col, val in zip(cols, vals):
    val = val.strip()
    if val.lower() in ('now()', 'current_timestamp'):
        import datetime
        obj[col] = datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S') + 'Z'
    elif '::jsonb' in val or '::json' in val:
        val = re.sub(r'::(jsonb?|text|varchar).*$', '', val).strip().strip("'")
        try:
            obj[col] = json.loads(val)
        except Exception:
            obj[col] = val
    elif val.startswith("'") and val.endswith("'"):
        obj[col] = val[1:-1].replace("''", "'")
    elif re.match(r'^-?\d+$', val):
        obj[col] = int(val)
    else:
        obj[col] = val

print(json.dumps(obj))
PYEOF
)

  HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
    -X POST \
    "${AUTH_HEADERS[@]}" \
    -H "Content-Type: application/json" \
    -H "Prefer: return=minimal" \
    "${SB_URL}/rest/v1/${TABLE}" \
    -d "$INSERT_JSON")

  if [[ "$HTTP_STATUS" == "201" || "$HTTP_STATUS" == "200" ]]; then
    echo '{"ok":true}'
  else
    echo "{\"error\":\"INSERT returned HTTP $HTTP_STATUS\"}" >&2
    exit 1
  fi
  exit 0
fi

echo '{"error":"Unsupported SQL pattern — only SELECT/UPDATE/INSERT supported"}' >&2
exit 1
