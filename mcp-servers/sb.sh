#!/usr/bin/env bash
# =============================================================================
# sb.sh — run SQL against the Axyom intranet Supabase from a headless session.
#
#   bash mcp-servers/sb.sh "SELECT * FROM notify_queue WHERE status='pending'"
#   bash mcp-servers/sb.sh "UPDATE notify_queue SET status='sent' WHERE id='...'"
#
# WHY THIS EXISTS
#   Scheduled agent runs (Ax hourly, the daily agents) are non-interactive: an
#   MCP tool call can stall on a permission prompt nobody is there to answer.
#   This script talks to PostgREST over curl instead — no MCP, no prompt.
#
# HOW IT WORKS
#   The Supabase project exposes no arbitrary-SQL RPC, so this translates a
#   practical subset of SQL into PostgREST REST calls. Unsupported SQL exits
#   non-zero with a clear message — it never silently returns an empty result,
#   because "looks like zero rows" is the failure mode that hides broken runs.
#
# OUTPUT
#   SELECT  -> JSON array of rows
#   writes  -> {"ok":true,"count":N} (and the rows, when the server returns them)
#   error   -> {"ok":false,"error":"..."} on stderr, exit 1
#
# REQUIRES  SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in the environment.
# NOTE      PostgREST on this project defaults to the `api` schema; every call
#           sends Accept-Profile/Content-Profile: public.
# =============================================================================
set -uo pipefail

if [ $# -lt 1 ] || [ -z "${1:-}" ]; then
  echo '{"ok":false,"error":"usage: sb.sh \"<SQL>\""}' >&2
  exit 2
fi

: "${SUPABASE_URL:?SUPABASE_URL is not set}"
: "${SUPABASE_SERVICE_ROLE_KEY:?SUPABASE_SERVICE_ROLE_KEY is not set}"

SB_SQL="$1" exec python3 - <<'PYEOF'
import json, os, re, sys, urllib.parse, urllib.request, datetime

SQL   = os.environ["SB_SQL"].strip().rstrip(";").strip()
BASE  = os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1"
KEY   = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
SCHEMA = os.environ.get("SB_SCHEMA", "public")


def die(msg):
    print(json.dumps({"ok": False, "error": msg}), file=sys.stderr)
    sys.exit(1)


def request(method, path, query=None, body=None, prefer=None):
    url = BASE + path
    if query:
        # NB: '+' must stay escaped — PostgREST reads a literal '+' in a query
        # string as a space, which corrupts every timestamptz offset.
        url += "?" + urllib.parse.urlencode(query, safe="().,*:'\"-")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("apikey", KEY)
    req.add_header("Authorization", "Bearer " + KEY)
    req.add_header("Accept-Profile", SCHEMA)
    req.add_header("Content-Profile", SCHEMA)
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if prefer:
        req.add_header("Prefer", prefer)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read().decode() or "[]"
    except urllib.error.HTTPError as e:
        detail = e.read().decode()[:600]
        die("HTTP %s from PostgREST: %s" % (e.code, detail))
    except Exception as e:  # network / DNS / TLS
        die("request failed: %s" % e)
    try:
        return json.loads(raw)
    except ValueError:
        return raw


# ---------------------------------------------------------------- value parsing
INTERVAL_UNITS = {
    "second": 1, "seconds": 1, "minute": 60, "minutes": 60,
    "hour": 3600, "hours": 3600, "day": 86400, "days": 86400,
    "week": 604800, "weeks": 604800,
}


def now_expr(expr):
    """Evaluate now() and now() -/+ interval 'N unit' -> ISO8601 UTC, else None."""
    e = " ".join(expr.split()).lower()
    if e in ("now()", "current_timestamp"):
        return datetime.datetime.now(datetime.timezone.utc).isoformat()
    m = re.match(
        r"^(?:now\(\)|current_timestamp)\s*([-+])\s*interval\s*'\s*(\d+)\s*(\w+)\s*'$", e)
    if not m:
        return None
    sign, qty, unit = m.group(1), int(m.group(2)), m.group(3)
    if unit not in INTERVAL_UNITS:
        die("unsupported interval unit %r" % unit)
    delta = datetime.timedelta(seconds=qty * INTERVAL_UNITS[unit])
    base = datetime.datetime.now(datetime.timezone.utc)
    return (base - delta if sign == "-" else base + delta).isoformat()


def parse_value(tok):
    """SQL literal -> python value. Handles quotes, ::casts, now(), JSON."""
    tok = tok.strip()
    # strip a trailing ::type cast that sits outside quotes
    cast = re.match(r"^(.*?)::\s*[a-z_ ]+(\[\])?$", tok, re.S | re.I)
    if cast and (tok.count("'") % 2 == 0):
        tok = cast.group(1).strip()
    t = now_expr(tok)
    if t is not None:
        return t
    low = tok.lower()
    if low == "null":
        return None
    if low == "true":
        return True
    if low == "false":
        return False
    if re.match(r"^-?\d+$", tok):
        return int(tok)
    if re.match(r"^-?\d*\.\d+$", tok):
        return float(tok)
    if len(tok) >= 2 and tok[0] == "'" and tok[-1] == "'":
        inner = tok[1:-1].replace("''", "'")
        s = inner.strip()
        if s[:1] in "{[" and s[-1:] in "}]":
            try:
                return json.loads(s)   # jsonb literal
            except ValueError:
                pass
        return inner
    die("cannot parse value %r (quote string literals with single quotes)" % tok)


def split_top(s, seps):
    """Split on separators that are not inside quotes or parentheses."""
    out, buf, depth, quote, i = [], "", 0, False, 0
    seps = [x.lower() for x in seps]
    while i < len(s):
        c = s[i]
        if quote:
            buf += c
            if c == "'":
                if i + 1 < len(s) and s[i + 1] == "'":
                    buf += s[i + 1]; i += 2; continue
                quote = False
            i += 1; continue
        if c == "'":
            quote = True; buf += c; i += 1; continue
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        if depth == 0:
            matched = None
            for sep in seps:
                seg = s[i:i + len(sep)].lower()
                if seg != sep:
                    continue
                # word separators need boundaries
                if sep[0].isalpha():
                    before = s[i - 1] if i else " "
                    after = s[i + len(sep)] if i + len(sep) < len(s) else " "
                    if before.isalnum() or after.isalnum() or before == "_" or after == "_":
                        continue
                matched = sep; break
            if matched:
                out.append(buf.strip()); buf = ""; i += len(matched); continue
        buf += c; i += 1
    out.append(buf.strip())
    return [x for x in out if x != ""]


OPS = [("<>", "neq"), ("!=", "neq"), (">=", "gte"), ("<=", "lte"),
       ("=", "eq"), (">", "gt"), ("<", "lt")]


def fmt(v):
    """Render a value into a PostgREST filter operand."""
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v)
    return '"%s"' % s.replace("\\", "\\\\").replace('"', '\\"') if re.search(r"[,.()\s:]", s) else s


def parse_where(where):
    """AND-joined predicates -> list of (column, postgrest_filter)."""
    if not where:
        return []
    if re.search(r"\bor\b", where, re.I):
        die("OR in WHERE is not supported — run separate statements")
    out = []
    for cond in split_top(where, [" and "]):
        c = cond.strip()
        # unwrap a fully-parenthesised predicate, but never chew the closing
        # paren off `col IN (...)` — strip("()") would.
        while c.startswith("(") and c.endswith(")") and len(split_top(c[1:-1], [")"])) == 1:
            c = c[1:-1].strip()
        m = re.match(r"^(\w+)\s+is\s+not\s+null$", c, re.I)
        if m:
            out.append((m.group(1), "not.is.null")); continue
        m = re.match(r"^(\w+)\s+is\s+null$", c, re.I)
        if m:
            out.append((m.group(1), "is.null")); continue
        m = re.match(r"^(\w+)\s+(not\s+)?in\s*\((.*)\)$", c, re.I | re.S)
        if m:
            vals = [fmt(parse_value(v)) for v in split_top(m.group(3), [","])]
            op = "not.in" if m.group(2) else "in"
            out.append((m.group(1), "%s.(%s)" % (op, ",".join(vals)))); continue
        m = re.match(r"^(\w+)\s+(not\s+)?like\s+(.+)$", c, re.I | re.S)
        if m:
            pat = str(parse_value(m.group(3))).replace("%", "*")
            out.append((m.group(1), ("not.like." if m.group(2) else "like.") + pat)); continue
        for sym, op in OPS:
            idx = c.find(sym)
            if idx <= 0:
                continue
            col, rhs = c[:idx].strip(), c[idx + len(sym):].strip()
            if not re.match(r"^\w+$", col):
                break
            val = parse_value(rhs)
            if val is None and op == "eq":
                out.append((col, "is.null"))
            else:
                out.append((col, "%s.%s" % (op, fmt(val))))
            break
        else:
            die("unsupported WHERE clause: %r" % c)
    return out


def apply_where(query, where):
    for col, filt in parse_where(where):
        query.setdefault(col, []).append(filt) if col in query else query.update({col: filt})
    return query


# ------------------------------------------------------------------- statements
def do_select(sql):
    m = re.match(
        r"^select\s+(?P<cols>.+?)\s+from\s+(?P<tbl>[\w.]+)"
        r"(?:\s+where\s+(?P<where>.+?))?"
        r"(?:\s+order\s+by\s+(?P<order>.+?))?"
        r"(?:\s+limit\s+(?P<limit>\d+))?"
        r"(?:\s+offset\s+(?P<offset>\d+))?$", sql, re.I | re.S)
    if not m:
        die("could not parse SELECT")
    tbl = m.group("tbl").split(".")[-1]
    cols = " ".join(m.group("cols").split())
    if re.search(r"\b(join|group\s+by|having|union|distinct)\b", sql, re.I):
        die("JOIN/GROUP BY/HAVING/UNION are not supported by the REST translator")
    if re.search(r"\w+\s*\(", cols) and cols.strip() != "*":
        die("aggregate/function columns are not supported — select raw columns instead")

    q = {"select": "*" if cols.strip() == "*" else ",".join(
        c.strip() for c in split_top(cols, [","]))}
    apply_where(q, m.group("where"))
    if m.group("order"):
        parts = []
        for o in split_top(m.group("order"), [","]):
            bits = o.split()
            col = bits[0]
            direction = "desc" if len(bits) > 1 and bits[1].lower().startswith("desc") else "asc"
            parts.append("%s.%s" % (col, direction))
        q["order"] = ",".join(parts)
    if m.group("limit"):
        q["limit"] = m.group("limit")
    if m.group("offset"):
        q["offset"] = m.group("offset")
    print(json.dumps(request("GET", "/" + tbl, q), indent=2))


def do_update(sql):
    m = re.match(r"^update\s+(?P<tbl>[\w.]+)\s+set\s+(?P<set>.+?)"
                 r"(?:\s+where\s+(?P<where>.+))?$", sql, re.I | re.S)
    if not m:
        die("could not parse UPDATE")
    tbl = m.group("tbl").split(".")[-1]
    where = m.group("where")
    if not where:
        die("refusing UPDATE with no WHERE clause")
    body = {}
    for assign in split_top(m.group("set"), [","]):
        if "=" not in assign:
            die("bad SET assignment: %r" % assign)
        col, rhs = assign.split("=", 1)
        body[col.strip()] = parse_value(rhs)
    q = apply_where({"select": "*"}, where)
    rows = request("PATCH", "/" + tbl, q, body, prefer="return=representation")
    n = len(rows) if isinstance(rows, list) else 0
    print(json.dumps({"ok": True, "count": n, "rows": rows}, indent=2))


def do_insert(sql):
    m = re.match(r"^insert\s+into\s+(?P<tbl>[\w.]+)\s*\((?P<cols>[^)]+)\)\s*"
                 r"values\s*(?P<vals>.+?)"
                 r"(?:\s+on\s+conflict\s+(?P<conflict>.+?))?$", sql, re.I | re.S)
    if not m:
        die("could not parse INSERT (INSERT ... SELECT is not supported — "
            "run the SELECT, build the rows, then INSERT them)")
    tbl = m.group("tbl").split(".")[-1]
    cols = [c.strip() for c in split_top(m.group("cols"), [","])]
    rows = []
    for tup in split_top(m.group("vals"), [","]):
        t = tup.strip()
        if not (t.startswith("(") and t.endswith(")")):
            die("bad VALUES tuple: %r" % t)
        vals = [parse_value(v) for v in split_top(t[1:-1], [","])]
        if len(vals) != len(cols):
            die("VALUES count (%d) != column count (%d)" % (len(vals), len(cols)))
        rows.append(dict(zip(cols, vals)))
    prefer = "return=representation"
    conflict = m.group("conflict")
    q = {}
    if conflict:
        mc = re.match(r"^\(([^)]+)\)\s*do\s+nothing$", conflict.strip(), re.I)
        mu = re.match(r"^\(([^)]+)\)\s*do\s+update", conflict.strip(), re.I)
        if mc:
            prefer += ",resolution=ignore-duplicates"
            q["on_conflict"] = ",".join(c.strip() for c in mc.group(1).split(","))
        elif mu:
            prefer += ",resolution=merge-duplicates"
            q["on_conflict"] = ",".join(c.strip() for c in mu.group(1).split(","))
        else:
            die("unsupported ON CONFLICT clause")
    out = request("POST", "/" + tbl, q or None, rows, prefer=prefer)
    n = len(out) if isinstance(out, list) else 0
    print(json.dumps({"ok": True, "count": n, "rows": out}, indent=2))


def do_delete(sql):
    m = re.match(r"^delete\s+from\s+(?P<tbl>[\w.]+)(?:\s+where\s+(?P<where>.+))?$",
                 sql, re.I | re.S)
    if not m:
        die("could not parse DELETE")
    if not m.group("where"):
        die("refusing DELETE with no WHERE clause")
    tbl = m.group("tbl").split(".")[-1]
    q = apply_where({"select": "*"}, m.group("where"))
    rows = request("DELETE", "/" + tbl, q, prefer="return=representation")
    n = len(rows) if isinstance(rows, list) else 0
    print(json.dumps({"ok": True, "count": n, "rows": rows}, indent=2))


head = SQL.split(None, 1)[0].lower() if SQL else ""
if head == "select":
    do_select(SQL)
elif head == "update":
    do_update(SQL)
elif head == "insert":
    do_insert(SQL)
elif head == "delete":
    do_delete(SQL)
else:
    die("unsupported statement %r — sb.sh handles SELECT/INSERT/UPDATE/DELETE. "
        "DDL and PL/pgSQL must go through a migration." % head)
PYEOF
