#!/bin/bash
# sb.sh — Supabase SQL helper via PostgREST REST API
# Usage: bash sb.sh '<SQL>'
# Handles common SELECT/UPDATE/INSERT/DELETE patterns against the Supabase project.
# Returns JSON rows for SELECT, {"ok":true} for writes.
# Requires: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in environment.

SQL="${1:-}"
if [ -z "$SQL" ]; then
  echo '{"error":"no SQL provided"}' >&2
  exit 1
fi

URL="${SUPABASE_URL:-https://tguwpswcneywvscxzyef.supabase.co}"
KEY="${SUPABASE_SERVICE_ROLE_KEY:-}"

if [ -z "$KEY" ]; then
  echo '{"error":"SUPABASE_SERVICE_ROLE_KEY not set"}' >&2
  exit 1
fi

# Python handles SQL → PostgREST translation
python3 - "$SQL" "$URL" "$KEY" <<'PYEOF'
import sys
import json
import re
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timezone, timedelta

sql = sys.argv[1].strip()
base_url = sys.argv[2].rstrip('/')
key = sys.argv[3]

HEADERS = {
    "apikey": key,
    "Authorization": f"Bearer {key}",
    "Content-Type": "application/json",
    "Accept-Profile": "public",
    "Content-Profile": "public",
}

def rest_get(table, params=None, select_cols="*"):
    qs = f"select={urllib.parse.quote(select_cols)}"
    if params:
        qs += "&" + "&".join(f"{k}={urllib.parse.quote(str(v))}" for k, v in params.items())
    url = f"{base_url}/rest/v1/{table}?{qs}"
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"error": e.read().decode()}

def rest_patch(table, where_params, data):
    qs = "&".join(f"{k}={urllib.parse.quote(str(v))}" for k, v in where_params.items())
    url = f"{base_url}/rest/v1/{table}?{qs}"
    body = json.dumps(data).encode()
    req = urllib.request.Request(url, data=body, method="PATCH",
                                  headers={**HEADERS, "Prefer": "return=minimal", "Accept-Profile": "public", "Content-Profile": "public"})
    try:
        with urllib.request.urlopen(req) as r:
            return {"ok": True}
    except urllib.error.HTTPError as e:
        return {"error": e.read().decode()}

def rest_post(table, data):
    url = f"{base_url}/rest/v1/{table}"
    body = json.dumps(data).encode()
    req = urllib.request.Request(url, data=body, method="POST",
                                  headers={**HEADERS, "Prefer": "return=minimal", "Accept-Profile": "public", "Content-Profile": "public"})
    try:
        with urllib.request.urlopen(req) as r:
            return {"ok": True}
    except urllib.error.HTTPError as e:
        return {"error": e.read().decode()}

def rest_delete(table, where_params):
    qs = "&".join(f"{k}={urllib.parse.quote(str(v))}" for k, v in where_params.items())
    url = f"{base_url}/rest/v1/{table}?{qs}"
    req = urllib.request.Request(url, method="DELETE",
                                  headers={**HEADERS, "Prefer": "return=minimal", "Accept-Profile": "public", "Content-Profile": "public"})
    try:
        with urllib.request.urlopen(req) as r:
            return {"ok": True}
    except urllib.error.HTTPError as e:
        return {"error": e.read().decode()}

def now_iso():
    return datetime.now(timezone.utc).isoformat()

def minutes_ago(n):
    return (datetime.now(timezone.utc) - timedelta(minutes=n)).isoformat()

# ── SQL pattern dispatcher ──────────────────────────────────────────────────

sql_upper = sql.upper().strip()

# ── SELECT patterns ─────────────────────────────────────────────────────────

if sql_upper.startswith("SELECT"):
    # Extract table name
    m = re.search(r'FROM\s+(\w+)', sql, re.IGNORECASE)
    if not m:
        print(json.dumps({"error": "could not parse table from SQL"}))
        sys.exit(1)
    table = m.group(1)

    # SELECT fields
    sel_m = re.match(r'SELECT\s+(.*?)\s+FROM', sql, re.IGNORECASE | re.DOTALL)
    sel_cols = "*"
    if sel_m:
        cols = sel_m.group(1).strip()
        if cols != "*":
            sel_cols = cols

    params = {}

    # WHERE status='pending'
    m = re.search(r"status\s*=\s*['\"](\w+)['\"]", sql, re.IGNORECASE)
    if m:
        params["status"] = f"eq.{m.group(1)}"

    # WHERE status IN ('open','in_progress')
    m = re.search(r"status\s+IN\s*\(([^)]+)\)", sql, re.IGNORECASE)
    if m:
        vals = re.findall(r"'(\w+)'", m.group(1))
        params["status"] = f"in.({',' .join(vals)})"

    # WHERE created_at < now() - interval '5 minutes'
    if re.search(r"created_at\s*<\s*now\(\)\s*-\s*interval\s*['\"]5 minutes['\"]", sql, re.IGNORECASE):
        params["created_at"] = f"lt.{minutes_ago(5)}"

    # WHERE created_at < now() - interval '24 hours'
    if re.search(r"created_at\s*<\s*now\(\)\s*-\s*interval\s*['\"]24 hours['\"]", sql, re.IGNORECASE):
        params["created_at"] = f"lt.{minutes_ago(24*60)}"

    # WHERE section='ax_state'
    m = re.search(r"section\s*=\s*'([^']+)'", sql, re.IGNORECASE)
    if m:
        params["section"] = f"eq.{m.group(1)}"

    # WHERE due_date = 'today' or current date
    m = re.search(r"due_date\s*=\s*(?:current_date|'([^']+)')", sql, re.IGNORECASE)
    if m:
        date_str = m.group(1) if m.group(1) else datetime.now(timezone.utc).strftime('%Y-%m-%d')
        params["due_date"] = f"eq.{date_str}"

    # WHERE due_date < current_date
    if re.search(r"due_date\s*<\s*(?:current_date|today)", sql, re.IGNORECASE):
        today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        params["due_date"] = f"lt.{today}"

    # WHERE id='...'
    m = re.search(r"\bid\s*=\s*'([^']+)'", sql, re.IGNORECASE)
    if m:
        params["id"] = f"eq.{m.group(1)}"

    # WHERE source='...'
    m = re.search(r"source\s*=\s*'([^']+)'", sql, re.IGNORECASE)
    if m:
        params["source"] = f"eq.{m.group(1)}"

    # WHERE kind='...'
    m = re.search(r"\bkind\s*=\s*'([^']+)'", sql, re.IGNORECASE)
    if m:
        params["kind"] = f"eq.{m.group(1)}"

    # ORDER BY
    m = re.search(r'ORDER BY\s+(\w+)(?:\s+(ASC|DESC))?', sql, re.IGNORECASE)
    if m:
        col = m.group(1)
        direction = (m.group(2) or "asc").lower()
        params["order"] = f"{col}.{direction}"

    # LIMIT
    m = re.search(r'LIMIT\s+(\d+)', sql, re.IGNORECASE)
    if m:
        params["limit"] = m.group(1)

    result = rest_get(table, params if params else None, sel_cols)
    print(json.dumps(result))

# ── UPDATE patterns ─────────────────────────────────────────────────────────

elif sql_upper.startswith("UPDATE"):
    m = re.match(r'UPDATE\s+(\w+)\s+SET\s+(.+?)\s+WHERE\s+(.+?)(?:;?\s*)$', sql, re.IGNORECASE | re.DOTALL)
    if not m:
        print(json.dumps({"error": "could not parse UPDATE"}))
        sys.exit(1)

    table = m.group(1)
    set_clause = m.group(2).strip()
    where_clause = m.group(3).strip()

    # Parse SET pairs — handle ::jsonb casts and quoted values
    data = {}
    # Split on commas not inside quotes/braces
    set_parts = re.split(r",\s*(?=[a-zA-Z_])", set_clause)
    for part in set_parts:
        part = part.strip()
        kv = re.match(r"(\w+)\s*=\s*(.+)", part, re.DOTALL)
        if not kv:
            continue
        col = kv.group(1)
        val_raw = kv.group(2).strip().rstrip(";")

        # Strip ::jsonb / ::text casts
        val_raw = re.sub(r"::[\w]+$", "", val_raw.strip()).strip()

        if val_raw.lower() == "now()":
            data[col] = now_iso()
        elif val_raw.startswith("'") and val_raw.endswith("'"):
            data[col] = val_raw[1:-1]
        elif val_raw.startswith("{") or val_raw.startswith("["):
            try:
                data[col] = json.loads(val_raw)
            except Exception:
                data[col] = val_raw
        elif re.match(r'^-?\d+\.?\d*$', val_raw):
            data[col] = float(val_raw) if '.' in val_raw else int(val_raw)
        else:
            data[col] = val_raw

    # Parse WHERE → PostgREST params
    where_params = {}
    # id='...'
    id_m = re.search(r"\bid\s*=\s*'([^']+)'", where_clause)
    if id_m:
        where_params["id"] = f"eq.{id_m.group(1)}"
    # status='...'
    st_m = re.search(r"status\s*=\s*'([^']+)'", where_clause)
    if st_m:
        where_params["status"] = f"eq.{st_m.group(1)}"
    # source='...'
    src_m = re.search(r"source\s*=\s*'([^']+)'", where_clause)
    if src_m:
        where_params["source"] = f"eq.{src_m.group(1)}"

    if not where_params:
        print(json.dumps({"error": "could not parse WHERE clause for UPDATE"}))
        sys.exit(1)

    result = rest_patch(table, where_params, data)
    print(json.dumps(result))

# ── INSERT patterns ─────────────────────────────────────────────────────────

elif sql_upper.startswith("INSERT"):
    m = re.match(r'INSERT\s+INTO\s+(\w+)\s*\(([^)]+)\)\s+VALUES\s*\((.+)\)', sql, re.IGNORECASE | re.DOTALL)
    if not m:
        print(json.dumps({"error": "could not parse INSERT"}))
        sys.exit(1)

    table = m.group(1)
    cols = [c.strip() for c in m.group(2).split(",")]
    # Parse values — simple split on top-level commas
    vals_str = m.group(3).strip()
    vals = []
    depth = 0
    cur = ""
    in_q = False
    q_char = None
    for ch in vals_str:
        if in_q:
            cur += ch
            if ch == q_char:
                in_q = False
        elif ch in ("'", '"'):
            in_q = True
            q_char = ch
            cur += ch
        elif ch in ("(", "{", "["):
            depth += 1
            cur += ch
        elif ch in (")", "}", "]"):
            depth -= 1
            cur += ch
        elif ch == "," and depth == 0:
            vals.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur:
        vals.append(cur.strip())

    data = {}
    for col, val_raw in zip(cols, vals):
        val_raw = val_raw.strip().rstrip(";")
        val_raw = re.sub(r"::[\w]+$", "", val_raw.strip()).strip()
        if val_raw.lower() in ("now()", "current_timestamp"):
            data[col] = now_iso()
        elif val_raw.lower() == "current_date":
            data[col] = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        elif val_raw.startswith("'") and val_raw.endswith("'"):
            data[col] = val_raw[1:-1]
        elif val_raw.startswith("{") or val_raw.startswith("["):
            try:
                data[col] = json.loads(val_raw)
            except Exception:
                data[col] = val_raw
        elif re.match(r'^-?\d+\.?\d*$', val_raw):
            data[col] = float(val_raw) if '.' in val_raw else int(val_raw)
        else:
            data[col] = val_raw

    result = rest_post(table, data)
    print(json.dumps(result))

# ── DELETE patterns ─────────────────────────────────────────────────────────

elif sql_upper.startswith("DELETE"):
    m = re.match(r'DELETE\s+FROM\s+(\w+)\s+WHERE\s+(.+)', sql, re.IGNORECASE | re.DOTALL)
    if not m:
        print(json.dumps({"error": "could not parse DELETE"}))
        sys.exit(1)

    table = m.group(1)
    where_clause = m.group(2).strip()
    where_params = {}
    id_m = re.search(r"\bid\s*=\s*'([^']+)'", where_clause)
    if id_m:
        where_params["id"] = f"eq.{id_m.group(1)}"
    st_m = re.search(r"status\s*=\s*'([^']+)'", where_clause)
    if st_m:
        where_params["status"] = f"eq.{st_m.group(1)}"

    if not where_params:
        print(json.dumps({"error": "could not parse WHERE for DELETE"}))
        sys.exit(1)

    result = rest_delete(table, where_params)
    print(json.dumps(result))

else:
    print(json.dumps({"error": f"unsupported SQL statement type: {sql_upper[:20]}"}))
    sys.exit(1)
PYEOF
