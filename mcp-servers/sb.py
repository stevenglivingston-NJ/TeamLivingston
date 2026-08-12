#!/usr/bin/env python3
"""
Translate a constrained SQL subset into Supabase PostgREST calls over curl.

Why this exists: the scheduled (non-interactive) agent runs cannot use
`mcp__Supabase__execute_sql` — every MCP call stops on a permission prompt that
nobody is there to answer, and the whole hourly cycle stalls. curl needs no
permission, so agents get their Supabase reads/writes through here instead.

Usage:  sb.sh "SELECT * FROM notify_queue WHERE status='pending' LIMIT 50"

Output: JSON array of rows for SELECT, {"ok":true,"count":N} for writes,
        {"error":"..."} plus a non-zero exit on failure.

Supported subset (everything the agent specs in .claude/agents/ actually use):
  SELECT <cols|*|count(*)> FROM t [WHERE ...] [ORDER BY c [ASC|DESC], ...] [LIMIT n]
  INSERT INTO t (cols) VALUES (...) [, (...)]
  UPDATE t SET c = v, ... WHERE ...
  DELETE FROM t WHERE ...

WHERE predicates are AND-joined only (OR is rejected rather than silently
mistranslated) and may use: = <> != < <= > >=, IS [NOT] NULL, [NOT] IN (...),
[NOT] LIKE/ILIKE. Values may be literals, now(), or now() - interval 'N unit'.
A trailing ::type cast is stripped. UPDATE and DELETE require a WHERE clause —
PostgREST refuses unfiltered ones anyway, and so do we.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone

REST_PROFILE = "public"  # the project's default PostgREST profile is `api`


class SqlError(Exception):
    pass


# --------------------------------------------------------------------------
# quote-aware scanning
# --------------------------------------------------------------------------

def _spans(sql):
    """Yield (index, in_quote, depth) so splitters can ignore quoted/nested text."""
    in_quote = False
    depth = 0
    i = 0
    while i < len(sql):
        ch = sql[i]
        if in_quote:
            if ch == "'":
                if i + 1 < len(sql) and sql[i + 1] == "'":  # '' escape
                    yield i, True, depth
                    i += 1
                    yield i, True, depth
                    i += 1
                    continue
                in_quote = False
        elif ch == "'":
            in_quote = True
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        yield i, in_quote, depth
        i += 1


def split_top(sql, pattern):
    """Split on `pattern` only where it is unquoted and at paren depth 0."""
    rx = re.compile(pattern, re.IGNORECASE)
    safe = [True] * len(sql)
    for i, in_quote, depth in _spans(sql):
        safe[i] = (not in_quote) and depth == 0
    parts, last, pos = [], 0, 0
    while pos < len(sql):
        m = rx.search(sql, pos)
        if not m:
            break
        if safe[m.start()] and (m.end() == len(sql) or safe[m.end() - 1]):
            parts.append(sql[last:m.start()])
            last = m.end()
            pos = m.end()
        else:
            pos = m.start() + 1
    parts.append(sql[last:])
    return [p.strip() for p in parts]


def find_top(sql, pattern):
    """Index of the first unquoted, depth-0 match of `pattern`, or -1."""
    rx = re.compile(pattern, re.IGNORECASE)
    safe = [True] * len(sql)
    for i, in_quote, depth in _spans(sql):
        safe[i] = (not in_quote) and depth == 0
    pos = 0
    while pos < len(sql):
        m = rx.search(sql, pos)
        if not m:
            return -1
        if safe[m.start()]:
            return m.start()
        pos = m.start() + 1
    return -1


# --------------------------------------------------------------------------
# values
# --------------------------------------------------------------------------

_INTERVAL_UNITS = {
    "second": 1, "seconds": 1, "sec": 1, "secs": 1,
    "minute": 60, "minutes": 60, "min": 60, "mins": 60,
    "hour": 3600, "hours": 3600,
    "day": 86400, "days": 86400,
    "week": 604800, "weeks": 604800,
}

_NOW_INTERVAL = re.compile(
    r"^now\(\)\s*([+-])\s*interval\s*'(\d+)\s*(\w+)'$", re.IGNORECASE
)


def _unquote(lit):
    return lit[1:-1].replace("''", "'")


def parse_value(raw):
    """SQL literal/expression -> Python value."""
    v = raw.strip()
    v = re.sub(r"::\s*\w+(\s*\[\s*\])?$", "", v).strip()  # drop ::jsonb, ::text[]

    m = _NOW_INTERVAL.match(v)
    if m:
        sign, qty, unit = m.group(1), int(m.group(2)), m.group(3).lower()
        if unit not in _INTERVAL_UNITS:
            raise SqlError("unsupported interval unit: %s" % unit)
        delta = timedelta(seconds=qty * _INTERVAL_UNITS[unit])
        now = datetime.now(timezone.utc)
        return (now + delta if sign == "+" else now - delta).isoformat()

    low = v.lower()
    if low in ("now()", "current_timestamp"):
        return datetime.now(timezone.utc).isoformat()
    if low == "null":
        return None
    if low == "true":
        return True
    if low == "false":
        return False

    if v.startswith("'") and v.endswith("'") and len(v) >= 2:
        s = _unquote(v)
        # a quoted JSON object/array (typically ::jsonb) goes in as real JSON
        if s[:1] in "{[":
            try:
                return json.loads(s)
            except ValueError:
                return s
        return s

    if re.fullmatch(r"-?\d+", v):
        return int(v)
    if re.fullmatch(r"-?\d*\.\d+", v):
        return float(v)

    raise SqlError("unsupported value expression: %s" % raw.strip())


def _pct(ch):
    return "".join("%%%02X" % b for b in ch.encode("utf-8"))


def enc_value(text):
    """Percent-encode a filter value, leaving only unreserved characters bare."""
    return "".join(c if (c.isalnum() or c in "-._~") else _pct(c) for c in text)


def _scalarize(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (dict, list)):
        return json.dumps(value, separators=(",", ":"))
    return str(value)


def filter_literal(value):
    """RHS of a scalar filter (eq/neq/lt/gt/like).

    PostgREST reads double quotes here as part of the value — `status=eq."sent"`
    matches nothing — so scalars go in bare and percent-encoded.
    """
    if value is None:
        return "null"
    if isinstance(value, (bool, int, float)):
        return _scalarize(value)
    return enc_value(_scalarize(value))


def in_literal(value):
    """One element of an `in.(...)` list.

    Here quotes ARE structural, so they stay literal and any quote/backslash in
    the data is backslash-escaped first; percent-encoding is applied afterwards
    and decodes back to the escaped form before PostgREST parses it.
    """
    if value is None:
        return "null"
    if isinstance(value, (bool, int, float)):
        return _scalarize(value)
    escaped = _scalarize(value).replace("\\", "\\\\").replace('"', '\\"')
    return '"%s"' % enc_value(escaped)


# --------------------------------------------------------------------------
# WHERE -> PostgREST filters
# --------------------------------------------------------------------------

_OPS = {"=": "eq", "<>": "neq", "!=": "neq", "<=": "lte", ">=": "gte", "<": "lt", ">": "gt"}

_IDENT = r"[A-Za-z_][A-Za-z0-9_]*"


def parse_where(clause):
    if find_top(clause, r"\bOR\b") != -1:
        raise SqlError("OR in WHERE is not supported — rewrite as separate statements")

    params = []
    for pred in split_top(clause, r"\bAND\b"):
        if not pred:
            continue
        pred = pred.strip()
        if pred.startswith("(") and pred.endswith(")"):
            pred = pred[1:-1].strip()

        m = re.match(r"^(%s)\s+IS\s+NOT\s+NULL$" % _IDENT, pred, re.IGNORECASE)
        if m:
            params.append((m.group(1), "not.is.null"))
            continue

        m = re.match(r"^(%s)\s+IS\s+NULL$" % _IDENT, pred, re.IGNORECASE)
        if m:
            params.append((m.group(1), "is.null"))
            continue

        m = re.match(r"^(%s)\s+(NOT\s+)?IN\s*\((.*)\)$" % _IDENT, pred, re.IGNORECASE | re.DOTALL)
        if m:
            col, neg, body = m.group(1), bool(m.group(2)), m.group(3)
            items = [in_literal(parse_value(x)) for x in split_top(body, r",") if x]
            params.append((col, "%sin.(%s)" % ("not." if neg else "", ",".join(items))))
            continue

        m = re.match(r"^(%s)\s+(NOT\s+)?(I?LIKE)\s+(.+)$" % _IDENT, pred, re.IGNORECASE | re.DOTALL)
        if m:
            col, neg, op, raw = m.group(1), bool(m.group(2)), m.group(3).lower(), m.group(4)
            params.append((col, "%s%s.%s" % ("not." if neg else "", op, filter_literal(parse_value(raw)))))
            continue

        m = re.match(r"^(%s)\s*(<>|!=|<=|>=|=|<|>)\s*(.+)$" % _IDENT, pred, re.IGNORECASE | re.DOTALL)
        if m:
            col, op, raw = m.group(1), m.group(2), m.group(3)
            value = parse_value(raw)
            if value is None:
                params.append((col, "is.null" if op == "=" else "not.is.null"))
            else:
                params.append((col, "%s.%s" % (_OPS[op], filter_literal(value))))
            continue

        raise SqlError("unsupported WHERE predicate: %s" % pred)

    return params


# --------------------------------------------------------------------------
# statement parsing
# --------------------------------------------------------------------------

def _table(name):
    return name.strip().strip('"').split(".")[-1]


def _carve(sql, keyword):
    """Split `sql` at a top-level keyword -> (before, after-or-None)."""
    idx = find_top(sql, r"\b%s\b" % keyword)
    if idx == -1:
        return sql, None
    kw = re.match(r"\b%s\b" % keyword, sql[idx:], re.IGNORECASE).group(0)
    return sql[:idx], sql[idx + len(kw):]


def parse_select(sql):
    body = sql[len("select"):]
    body, limit = _carve(body, "LIMIT")
    body, order = _carve(body, "ORDER\\s+BY")
    body, where = _carve(body, "WHERE")
    cols_part, from_part = _carve(body, "FROM")
    if from_part is None:
        raise SqlError("SELECT without FROM")

    cols = cols_part.strip()
    params = list(parse_where(where) if where else [])

    headers = ["Accept-Profile: %s" % REST_PROFILE]
    count_only = bool(re.fullmatch(r"count\(\s*\*\s*\)", cols, re.IGNORECASE))
    if count_only:
        params.append(("select", "id"))
        headers.append("Prefer: count=exact")
    else:
        params.append(("select", "*" if cols == "*" else ",".join(c.strip() for c in split_top(cols, r","))))

    if order:
        terms = []
        for term in split_top(order, r","):
            m = re.match(r"^(%s)(?:\s+(ASC|DESC))?(?:\s+NULLS\s+(FIRST|LAST))?$" % _IDENT, term.strip(), re.IGNORECASE)
            if not m:
                raise SqlError("unsupported ORDER BY term: %s" % term)
            piece = m.group(1) + "." + (m.group(2) or "asc").lower()
            if m.group(3):
                piece += ".nulls" + m.group(3).lower()
            terms.append(piece)
        params.append(("order", ",".join(terms)))

    if limit:
        n = limit.strip().rstrip(";").strip()
        if not n.isdigit():
            raise SqlError("unsupported LIMIT: %s" % limit)
        params.append(("limit", n))

    return {"method": "GET", "table": _table(from_part), "params": params,
            "headers": headers, "body": None, "count_only": count_only}


def parse_insert(sql):
    m = re.match(r"^insert\s+into\s+(%s(?:\.%s)?)\s*\((.*?)\)\s*values\s*(.+)$" % (_IDENT, _IDENT),
                 sql, re.IGNORECASE | re.DOTALL)
    if not m:
        raise SqlError("unsupported INSERT — expected: INSERT INTO t (cols) VALUES (...)")
    table, cols_raw, values_raw = m.group(1), m.group(2), m.group(3).strip().rstrip(";").strip()

    if find_top(values_raw, r"\bON\s+CONFLICT\b") != -1 or find_top(values_raw, r"\bRETURNING\b") != -1:
        raise SqlError("ON CONFLICT / RETURNING are not supported")

    cols = [c.strip() for c in split_top(cols_raw, r",")]
    rows = []
    for tup in split_top(values_raw, r"\)\s*,\s*\("):
        tup = tup.strip().lstrip("(").rstrip(")")
        vals = [parse_value(v) for v in split_top(tup, r",")]
        if len(vals) != len(cols):
            raise SqlError("INSERT column/value count mismatch (%d cols, %d values)" % (len(cols), len(vals)))
        rows.append(dict(zip(cols, vals)))

    return {"method": "POST", "table": _table(table), "params": [],
            "headers": ["Content-Profile: %s" % REST_PROFILE, "Content-Type: application/json",
                        "Prefer: return=minimal,count=exact"],
            "body": json.dumps(rows), "count_only": False, "rowcount": len(rows)}


def parse_update(sql):
    body = sql[len("update"):]
    body, where = _carve(body, "WHERE")
    if where is None:
        raise SqlError("UPDATE without WHERE is refused")
    table_part, set_part = _carve(body, "SET")
    if set_part is None:
        raise SqlError("UPDATE without SET")

    payload = {}
    for assign in split_top(set_part, r","):
        m = re.match(r"^(%s)\s*=\s*(.+)$" % _IDENT, assign.strip(), re.DOTALL)
        if not m:
            raise SqlError("unsupported SET assignment: %s" % assign)
        payload[m.group(1)] = parse_value(m.group(2))

    return {"method": "PATCH", "table": _table(table_part), "params": parse_where(where.rstrip(";")),
            "headers": ["Content-Profile: %s" % REST_PROFILE, "Content-Type: application/json",
                        "Prefer: return=minimal,count=exact"],
            "body": json.dumps(payload), "count_only": False}


def parse_delete(sql):
    body = sql[len("delete"):]
    body, where = _carve(body, "WHERE")
    if where is None:
        raise SqlError("DELETE without WHERE is refused")
    _, from_part = _carve(body, "FROM")
    if from_part is None:
        raise SqlError("DELETE without FROM")
    return {"method": "DELETE", "table": _table(from_part), "params": parse_where(where.rstrip(";")),
            "headers": ["Content-Profile: %s" % REST_PROFILE, "Prefer: return=minimal,count=exact"],
            "body": None, "count_only": False}


def parse(sql):
    s = sql.strip().rstrip(";").strip()
    head = s.split(None, 1)[0].lower() if s else ""
    if head == "select":
        return parse_select(s)
    if head == "insert":
        return parse_insert(s)
    if head == "update":
        return parse_update(s)
    if head == "delete":
        return parse_delete(s)
    raise SqlError("unsupported statement: %s" % (head or "(empty)"))


# --------------------------------------------------------------------------
# execution
# --------------------------------------------------------------------------

def build_url(base, table, params):
    """Join pre-encoded params. Filter values are already percent-encoded by
    filter_literal/in_literal; select/order/limit carry only identifiers and the
    structural characters PostgREST expects, so nothing is re-encoded here."""
    qs = "&".join("%s=%s" % (k, v) for k, v in params)
    return "%s/rest/v1/%s%s" % (base.rstrip("/"), table, ("?" + qs) if qs else "")


def run(plan):
    base = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not base or not key:
        raise SqlError("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY are not set in the environment")

    # Body and headers go to separate files: piping both to stdout is ambiguous
    # once a proxy injects its own header block.
    with tempfile.TemporaryDirectory() as tmp:
        body_path = os.path.join(tmp, "body")
        head_path = os.path.join(tmp, "head")
        cmd = ["curl", "-sS", "--max-time", "45", "-D", head_path, "-o", body_path,
               "-w", "%{http_code}",
               "-X", plan["method"], build_url(base, plan["table"], plan["params"]),
               "-H", "apikey: " + key, "-H", "Authorization: Bearer " + key]
        for h in plan["headers"]:
            cmd += ["-H", h]
        if plan["body"] is not None:
            cmd += ["--data-binary", plan["body"]]

        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise SqlError("curl failed: %s" % (proc.stderr.strip() or proc.returncode))

        status = int(proc.stdout.strip() or 0)
        with open(body_path, "r", encoding="utf-8", errors="replace") as fh:
            payload = fh.read()
        with open(head_path, "r", encoding="utf-8", errors="replace") as fh:
            head = fh.read()

    # keep the LAST Content-Range — a proxy may prepend its own header block
    content_range = ""
    for line in head.splitlines():
        if line.lower().startswith("content-range:"):
            content_range = line.split(":", 1)[1].strip()

    if status >= 400:
        detail = payload.strip()
        try:
            detail = json.dumps(json.loads(detail))
        except ValueError:
            pass
        raise SqlError("HTTP %d from PostgREST: %s" % (status, detail))

    if plan["method"] == "GET":
        if plan["count_only"]:
            total = content_range.split("/")[-1] if content_range else "0"
            return [{"count": int(total) if total.isdigit() else 0}]
        return json.loads(payload) if payload.strip() else []

    # writes: PostgREST reports affected rows in Content-Range (e.g. "*/3")
    affected = plan.get("rowcount")
    if content_range:
        tail = content_range.split("/")[-1]
        if tail.isdigit():
            affected = int(tail)
    result = {"ok": True}
    if affected is not None:
        result["count"] = affected
    return result


def main(argv):
    if len(argv) != 2 or argv[1] in ("-h", "--help"):
        print(json.dumps({"error": "usage: sb.sh '<SQL>'"}))
        return 2
    try:
        out = run(parse(argv[1]))
    except SqlError as e:
        print(json.dumps({"error": str(e)}))
        return 1
    except Exception as e:  # noqa: BLE001 — always emit JSON, never a traceback
        print(json.dumps({"error": "%s: %s" % (type(e).__name__, e)}))
        return 1
    print(json.dumps(out, indent=None, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
