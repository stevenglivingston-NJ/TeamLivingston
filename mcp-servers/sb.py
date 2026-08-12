#!/usr/bin/env python3
"""
sb.py — run SQL against the Axyom intranet Supabase project without MCP.

Scheduled (non-interactive) agent runs cannot use mcp__Supabase__execute_sql:
the MCP permission prompt has nobody to answer it and the whole cycle stalls.
This translates a practical subset of SQL into PostgREST REST calls made with
curl, so agents can read and write with plain Bash and no permission prompt.

Usage:  sb.sh '<SQL>'            (sb.sh is the wrapper around this file)

Output: SELECT  -> JSON array of rows
        writes  -> {"ok":true,"count":N,"rows":[...]}
        failure -> {"ok":false,"error":"..."} on stdout, exit 1

Supported subset
  SELECT <cols|*|count(*)> FROM t [WHERE ...] [ORDER BY ...] [LIMIT n] [OFFSET n]
  INSERT INTO t (cols) VALUES (...)[,(...)] [ON CONFLICT ... DO NOTHING|DO UPDATE ...]
  UPDATE t SET c = v, ... WHERE ...
  DELETE FROM t WHERE ...

  WHERE supports AND / OR, parenthesised groups, = <> != > >= < <=,
  IS [NOT] NULL, [NOT] IN (...), LIKE / ILIKE, and the expressions
  now(), current_date, and now() +/- interval 'N unit'.

Env: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

# The intranet tables live in `public`; the project's PostgREST default
# schema is `api`, so every request must carry an explicit profile header.
SCHEMA = os.environ.get("SB_SCHEMA", "public")
TIMEOUT = int(os.environ.get("SB_TIMEOUT", "60"))

CMP_OPS = [
    (">=", "gte"), ("<=", "lte"), ("<>", "neq"), ("!=", "neq"),
    ("=", "eq"), (">", "gt"), ("<", "lt"),
]

INTERVAL_UNITS = {
    "second": 1, "seconds": 1, "sec": 1, "secs": 1,
    "minute": 60, "minutes": 60, "min": 60, "mins": 60,
    "hour": 3600, "hours": 3600,
    "day": 86400, "days": 86400,
    "week": 604800, "weeks": 604800,
}


class Unsupported(Exception):
    pass


def utcnow():
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "+00:00")


# --------------------------------------------------------------------------
# tokenizing helpers: everything below operates on "top level" positions,
# meaning outside single-quoted strings and outside parentheses.
# --------------------------------------------------------------------------

def toplevel_mask(s):
    """mask[i] is True when s[i] sits outside quotes and outside parens."""
    out = []
    depth = 0
    inq = False
    i = 0
    while i < len(s):
        c = s[i]
        if inq:
            if c == "'":
                if i + 1 < len(s) and s[i + 1] == "'":  # '' escape
                    out.extend([False, False])
                    i += 2
                    continue
                inq = False
            out.append(False)
            i += 1
            continue
        if c == "'":
            inq = True
            out.append(False)
            i += 1
            continue
        if c == "(":
            out.append(depth == 0)
            depth += 1
            i += 1
            continue
        if c == ")":
            depth -= 1
            out.append(depth == 0)
            i += 1
            continue
        out.append(depth == 0)
        i += 1
    return out


def _kw_pattern(kw):
    return re.compile(r"(?<![\w.])" + r"\s+".join(map(re.escape, kw.split())) + r"(?![\w])", re.I)


def find_kw(s, kw, start=0, mask=None):
    """First top-level occurrence of keyword kw -> (start, end) or None."""
    mask = toplevel_mask(s) if mask is None else mask
    for m in _kw_pattern(kw).finditer(s, start):
        if all(mask[i] for i in range(m.start(), m.end())):
            return m.start(), m.end()
    return None


def split_kw(s, kw):
    """Split s on every top-level occurrence of keyword kw."""
    mask = toplevel_mask(s)
    parts, last = [], 0
    for m in _kw_pattern(kw).finditer(s):
        if all(mask[i] for i in range(m.start(), m.end())):
            parts.append(s[last:m.start()])
            last = m.end()
    parts.append(s[last:])
    return [p.strip() for p in parts if p.strip()]


def split_commas(s):
    mask = toplevel_mask(s)
    parts, last = [], 0
    for i, c in enumerate(s):
        if c == "," and mask[i]:
            parts.append(s[last:i])
            last = i + 1
    parts.append(s[last:])
    return [p.strip() for p in parts if p.strip()]


def strip_parens(s):
    """Remove one layer of wrapping parens if they enclose the whole string."""
    s = s.strip()
    while s.startswith("(") and s.endswith(")"):
        mask = toplevel_mask(s)
        # the wrapping paren encloses everything when no other char is top level
        if any(mask[i] for i in range(1, len(s) - 1)):
            break
        s = s[1:-1].strip()
    return s


# --------------------------------------------------------------------------
# value parsing
# --------------------------------------------------------------------------

def parse_value(raw):
    """SQL literal/expression -> Python value."""
    v = raw.strip()

    cast = None
    m = re.search(r"::\s*([a-zA-Z_][\w]*)\s*(\[\])?\s*$", v)
    if m:
        cast = m.group(1).lower()
        v = v[:m.start()].strip()
    v = strip_parens(v)

    low = v.lower()
    if low == "null":
        return None
    if low == "true":
        return True
    if low == "false":
        return False
    if low in ("now()", "current_timestamp"):
        return iso(utcnow())
    if low == "current_date":
        return utcnow().date().isoformat()

    m = re.match(r"^(?:now\(\)|current_timestamp)\s*([+-])\s*interval\s*'([^']+)'$", v, re.I)
    if m:
        sign = 1 if m.group(1) == "+" else -1
        return iso(utcnow() + sign * timedelta(seconds=parse_interval(m.group(2))))

    m = re.match(r"^current_date\s*([+-])\s*interval\s*'([^']+)'$", v, re.I)
    if m:
        sign = 1 if m.group(1) == "+" else -1
        base = datetime.combine(utcnow().date(), datetime.min.time(), tzinfo=timezone.utc)
        return iso(base + sign * timedelta(seconds=parse_interval(m.group(2))))

    if v.startswith("'") and v.endswith("'") and len(v) >= 2:
        s = v[1:-1].replace("''", "'")
        if cast in ("json", "jsonb"):
            try:
                return json.loads(s)
            except json.JSONDecodeError as e:
                raise Unsupported("invalid JSON literal: %s" % e)
        return s

    if re.match(r"^-?\d+$", v):
        return int(v)
    if re.match(r"^-?\d*\.\d+$", v):
        return float(v)

    raise Unsupported("cannot evaluate expression: %s" % raw.strip())


def parse_interval(text):
    total = 0
    found = False
    for num, unit in re.findall(r"(\d+)\s*([a-zA-Z]+)", text):
        u = unit.lower()
        if u not in INTERVAL_UNITS:
            raise Unsupported("unsupported interval unit: %s" % unit)
        total += int(num) * INTERVAL_UNITS[u]
        found = True
    if not found:
        raise Unsupported("cannot parse interval: %s" % text)
    return total


def qval(v):
    """Render a value for the right-hand side of a PostgREST filter."""
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    s = v if isinstance(v, str) else json.dumps(v)
    if s == "" or re.search(r'[,()"\s]', s):
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return s


def norm_col(col):
    """`fields->>'scan_date'` -> `fields->>scan_date` (PostgREST JSON path form)."""
    col = col.strip()
    col = re.sub(r"->>\s*'([^']*)'", r"->>\1", col)
    col = re.sub(r"->\s*'([^']*)'", r"->\1", col)
    return col.replace(" ", "")


# --------------------------------------------------------------------------
# WHERE -> PostgREST filters
# --------------------------------------------------------------------------

def parse_condition(cond):
    """One comparison -> 'column.op.value' in PostgREST's embedded-filter form."""
    c = strip_parens(cond)

    m = re.match(r"^(.+?)\s+is\s+not\s+null$", c, re.I)
    if m:
        return "%s.not.is.null" % norm_col(m.group(1))
    m = re.match(r"^(.+?)\s+is\s+null$", c, re.I)
    if m:
        return "%s.is.null" % norm_col(m.group(1))

    m = re.match(r"^(.+?)\s+(not\s+)?in\s*\((.*)\)$", c, re.I | re.S)
    if m:
        col, negate, items = norm_col(m.group(1)), bool(m.group(2)), m.group(3)
        vals = [qval(parse_value(x)) for x in split_commas(items)]
        expr = "%s.in.(%s)" % (col, ",".join(vals))
        return ("%s.not.in.(%s)" % (col, ",".join(vals))) if negate else expr

    m = re.match(r"^(.+?)\s+(not\s+)?(i?like)\s+(.+)$", c, re.I | re.S)
    if m:
        col, negate, op = norm_col(m.group(1)), bool(m.group(2)), m.group(3).lower()
        val = qval(parse_value(m.group(4)))
        return "%s.%s%s.%s" % (col, "not." if negate else "", op, val)

    mask = toplevel_mask(c)
    for sym, op in CMP_OPS:
        idx = -1
        for i in range(len(c) - len(sym) + 1):
            if c[i:i + len(sym)] == sym and all(mask[j] for j in range(i, i + len(sym))):
                idx = i
                break
        if idx >= 0:
            col = norm_col(c[:idx])
            val = parse_value(c[idx + len(sym):])
            if val is None:  # `col = NULL` means IS NULL in intent
                return "%s.is.null" % col
            return "%s.%s.%s" % (col, op, qval(val))

    raise Unsupported("cannot parse condition: %s" % cond.strip())


def parse_where(where):
    """WHERE clause -> list of (param, value) query pairs."""
    where = strip_parens(where)
    or_parts = split_kw(where, "OR")
    if len(or_parts) > 1:
        return [("or", "(%s)" % ",".join(build_logic(p) for p in or_parts))]

    params = []
    for cond in split_kw(where, "AND"):
        inner = strip_parens(cond)
        if len(split_kw(inner, "OR")) > 1:
            params.append(("or", "(%s)" % ",".join(
                build_logic(p) for p in split_kw(inner, "OR"))))
            continue
        col_op_val = parse_condition(cond)
        col, rest = col_op_val.split(".", 1)
        params.append((col, rest))
    return params


def build_logic(node):
    """Render a nested AND/OR group in PostgREST's logic-tree syntax."""
    node = strip_parens(node)
    ors = split_kw(node, "OR")
    if len(ors) > 1:
        return "or(%s)" % ",".join(build_logic(p) for p in ors)
    ands = split_kw(node, "AND")
    if len(ands) > 1:
        return "and(%s)" % ",".join(build_logic(p) for p in ands)
    return parse_condition(node)


def parse_order(order):
    out = []
    for item in split_commas(order):
        toks = item.split()
        col = norm_col(toks[0])
        rest = " ".join(toks[1:]).lower()
        parts = [col]
        if "desc" in rest:
            parts.append("desc")
        elif "asc" in rest:
            parts.append("asc")
        if "nulls first" in rest:
            parts.append("nullsfirst")
        elif "nulls last" in rest:
            parts.append("nullslast")
        out.append(".".join(parts))
    return ",".join(out)


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------

def request(method, table, params, body=None, prefer=None):
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not base or not key:
        raise Unsupported("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not set in the environment")

    qs = "&".join("%s=%s" % (quote(k, safe="->"), quote(str(v), safe="().,*:\"-"))
                  for k, v in params)
    url = "%s/rest/v1/%s%s" % (base, table, ("?" + qs) if qs else "")

    cmd = [
        "curl", "-sS", "-m", str(TIMEOUT), "-X", method, url,
        "-w", "\n__HTTP__%{http_code}",
        "-H", "apikey: " + key,
        "-H", "Authorization: Bearer " + key,
        "-H", "Accept-Profile: " + SCHEMA,
        "-H", "Content-Profile: " + SCHEMA,
        "-H", "Accept: application/json",
    ]
    if prefer:
        cmd += ["-H", "Prefer: " + prefer]
    if body is not None:
        cmd += ["-H", "Content-Type: application/json", "--data-binary", json.dumps(body)]
    if method == "HEAD":
        cmd += ["-D", "-"]

    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise Unsupported("curl failed: %s" % (proc.stderr.strip() or proc.returncode))

    raw = proc.stdout
    marker = raw.rfind("\n__HTTP__")
    status = int(raw[marker + 9:].strip()) if marker >= 0 else 0
    payload = raw[:marker] if marker >= 0 else raw
    return status, payload


def fail(msg):
    print(json.dumps({"ok": False, "error": msg}))
    sys.exit(1)


def check(status, payload):
    if status >= 400:
        try:
            detail = json.loads(payload)
        except (json.JSONDecodeError, ValueError):
            detail = payload.strip()
        fail("HTTP %s: %s" % (status, json.dumps(detail) if not isinstance(detail, str) else detail))


# --------------------------------------------------------------------------
# statement handlers
# --------------------------------------------------------------------------

def clean_table(name):
    return name.strip().strip('"').split(".")[-1]


def carve(sql, body_start):
    """Pull the optional trailing WHERE / ORDER BY / LIMIT / OFFSET clauses."""
    mask = toplevel_mask(sql)
    marks = []
    for kw in ("WHERE", "ORDER BY", "LIMIT", "OFFSET"):
        hit = find_kw(sql, kw, body_start, mask)
        if hit:
            marks.append((hit[0], hit[1], kw))
    marks.sort()

    ends = [m[0] for m in marks] + [len(sql)]
    body = sql[body_start:ends[0]].strip()
    clauses = {}
    for i, (_, end, kw) in enumerate(marks):
        clauses[kw] = sql[end:ends[i + 1]].strip()
    return body, clauses


def do_select(sql):
    hit = find_kw(sql, "FROM")
    if not hit:
        raise Unsupported("SELECT without FROM is not supported")
    cols = sql[6:hit[0]].strip()

    tail = sql[hit[1]:].lstrip()
    tbl_match = re.match(r'^([\w".]+)', tail)
    if not tbl_match:
        raise Unsupported("cannot read table name")
    table = clean_table(tbl_match.group(1))

    offset = hit[1] + (len(sql[hit[1]:]) - len(tail)) + tbl_match.end()
    _, clauses = carve(sql, offset)

    params = []
    if "WHERE" in clauses:
        params += parse_where(clauses["WHERE"])

    counting = re.match(r"^count\s*\(\s*\*?\s*\)$", cols.strip(), re.I)
    if counting:
        params.append(("select", "*"))
        params.append(("limit", "1"))
        status, payload = request("HEAD", table, params, prefer="count=exact")
        check(status, payload)
        m = re.search(r"content-range:\s*[\d\-*]+/(\d+|\*)", payload, re.I)
        total = int(m.group(1)) if m and m.group(1) != "*" else None
        print(json.dumps([{"count": total}]))
        return

    params.append(("select", "*" if cols.strip() == "*"
                   else ",".join(norm_col(c) for c in split_commas(cols))))
    if "ORDER BY" in clauses:
        params.append(("order", parse_order(clauses["ORDER BY"])))
    if "LIMIT" in clauses:
        params.append(("limit", clauses["LIMIT"].strip()))
    if "OFFSET" in clauses:
        params.append(("offset", clauses["OFFSET"].strip()))

    status, payload = request("GET", table, params)
    check(status, payload)
    print(payload.strip() or "[]")


def do_update(sql):
    hit = find_kw(sql, "SET")
    if not hit:
        raise Unsupported("UPDATE without SET")
    table = clean_table(sql[6:hit[0]])
    body_text, clauses = carve(sql, hit[1])

    row = {}
    for assign in split_commas(body_text):
        eq = assign.index("=")
        row[norm_col(assign[:eq])] = parse_value(assign[eq + 1:])

    if "WHERE" not in clauses:
        raise Unsupported("refusing UPDATE without WHERE")
    params = parse_where(clauses["WHERE"])

    status, payload = request("PATCH", table, params, body=row,
                              prefer="return=representation")
    check(status, payload)
    rows = json.loads(payload or "[]")
    print(json.dumps({"ok": True, "count": len(rows), "rows": rows}))


def do_delete(sql):
    hit = find_kw(sql, "FROM")
    if not hit:
        raise Unsupported("DELETE without FROM")
    tail = sql[hit[1]:].lstrip()
    tbl_match = re.match(r'^([\w".]+)', tail)
    table = clean_table(tbl_match.group(1))
    offset = hit[1] + (len(sql[hit[1]:]) - len(tail)) + tbl_match.end()
    _, clauses = carve(sql, offset)

    if "WHERE" not in clauses:
        raise Unsupported("refusing DELETE without WHERE")
    params = parse_where(clauses["WHERE"])

    status, payload = request("DELETE", table, params, prefer="return=representation")
    check(status, payload)
    rows = json.loads(payload or "[]")
    print(json.dumps({"ok": True, "count": len(rows), "rows": rows}))


def do_insert(sql):
    m = re.match(r'^insert\s+into\s+([\w".]+)\s*', sql, re.I)
    if not m:
        raise Unsupported("cannot parse INSERT target")
    table = clean_table(m.group(1))
    rest = sql[m.end():].lstrip()

    if not rest.startswith("("):
        raise Unsupported("INSERT requires an explicit column list")
    mask = toplevel_mask(rest)
    close = next(i for i in range(len(rest)) if rest[i] == ")" and mask[i])
    cols = [norm_col(c) for c in split_commas(rest[1:close])]

    rest = rest[close + 1:].lstrip()
    vhit = find_kw(rest, "VALUES")
    if not vhit:
        raise Unsupported("INSERT ... SELECT is not supported; run the SELECT first")

    conflict = find_kw(rest, "ON CONFLICT")
    values_text = rest[vhit[1]:conflict[0] if conflict else len(rest)].strip()

    rows = []
    for group in split_commas(values_text):
        g = group.strip()
        if not (g.startswith("(") and g.endswith(")")):
            raise Unsupported("malformed VALUES tuple: %s" % g)
        vals = [parse_value(v) for v in split_commas(g[1:-1])]
        if len(vals) != len(cols):
            raise Unsupported("column/value count mismatch")
        rows.append(dict(zip(cols, vals)))

    prefer = ["return=representation"]
    if conflict:
        clause = rest[conflict[1]:].strip()
        if re.search(r"do\s+nothing", clause, re.I):
            prefer.append("resolution=ignore-duplicates")
        else:
            prefer.append("resolution=merge-duplicates")

    params = []
    if conflict:
        m2 = re.match(r"^\(([^)]*)\)", rest[conflict[1]:].strip())
        if m2:
            params.append(("on_conflict", ",".join(
                norm_col(c) for c in split_commas(m2.group(1)))))

    status, payload = request("POST", table, params, body=rows, prefer=",".join(prefer))
    check(status, payload)
    out = json.loads(payload or "[]")
    print(json.dumps({"ok": True, "count": len(out), "rows": out}))


def main():
    if len(sys.argv) < 2:
        fail("usage: sb.sh '<SQL>'")

    sql = " ".join(sys.argv[1:]).strip()
    sql = re.sub(r"\s+", " ", sql).strip().rstrip(";").strip()
    if not sql:
        fail("empty statement")

    verb = sql.split(None, 1)[0].lower()
    handlers = {
        "select": do_select,
        "update": do_update,
        "delete": do_delete,
        "insert": do_insert,
    }
    if verb not in handlers:
        fail("unsupported statement type: %s (SELECT/INSERT/UPDATE/DELETE only)" % verb)

    try:
        handlers[verb](sql)
    except Unsupported as e:
        fail(str(e))
    except Exception as e:  # noqa: BLE001 - always emit machine-readable failure
        fail("%s: %s" % (type(e).__name__, e))


if __name__ == "__main__":
    main()
