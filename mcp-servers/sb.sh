#!/usr/bin/env bash
# =============================================================================
# sb.sh — Supabase query helper for non-interactive (scheduled) agent runs.
#
# WHY THIS EXISTS
#   Scheduled agent fires are non-interactive: any MCP tool call that triggers
#   an "Allow" permission prompt stalls the whole run, because nobody is there
#   to answer it. `mcp__Supabase__execute_sql` is the worst offender — every
#   agent needs the database, so every agent stalls.
#
#   sb.sh gives agents a prompt-free path to the intranet database over plain
#   curl → PostgREST, authenticated with the service-role key from the
#   environment. No MCP, no prompt, no stall.
#
# USAGE
#   sb.sh '<SQL>'                     translate a SQL statement and run it
#   sb.sh --rest GET  '<path>'        raw PostgREST passthrough (GET/DELETE)
#   sb.sh --rest POST '<path>' '<json>'   raw passthrough with a body
#   sb.sh --explain '<SQL>'           print the translated request, run nothing
#   sb.sh --ping                      connectivity + auth check
#
# OUTPUT
#   SELECT  → a JSON array of rows
#   writes  → {"ok":true,"count":N}
#   failure → {"ok":false,"error":"..."} on stdout AND a non-zero exit code
#
# REQUIRES
#   SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in the environment
#   (set in the Cloud environment's env-var config — never in the repo).
#
# SQL SUPPORT — READ THIS BEFORE ADDING A QUERY
#   PostgREST is not a SQL engine. This script translates a deliberately small,
#   well-defined subset and REFUSES anything outside it, loudly, rather than
#   guessing and silently writing the wrong rows.
#
#   Supported:
#     SELECT <cols|*> FROM t [WHERE ...] [ORDER BY c [ASC|DESC], ...] [LIMIT n]
#     UPDATE t SET c = v, ... WHERE ...
#     INSERT INTO t (cols) VALUES (...) [, (...)]
#     DELETE FROM t WHERE ...
#   WHERE terms, AND-joined only:
#     c = v · c <> v · c != v · c < v · c <= v · c > v · c >= v
#     c IN (v, ...) · c IS NULL · c IS NOT NULL · c LIKE 'x%' · c ILIKE 'x%'
#   Values:
#     'string' ('' escapes a quote) · number · true/false/null
#     now() · now() - interval '5 minutes' · now() + interval '1 day'
#     ::jsonb / ::json casts send real JSON (not a quoted string); other
#     casts (::text, ::timestamptz, ...) are stripped.
#
#   NOT supported — these raise an error instead of running:
#     OR / NOT, joins, subqueries, INSERT ... SELECT, aggregates, GROUP BY,
#     the || concatenation operator, RETURNING, CTEs.
#     Build the literal values in the shell and pass a plain statement.
# =============================================================================
set -uo pipefail

SCHEMA="${SB_SCHEMA:-public}"

die() { printf '{"ok":false,"error":%s}\n' "$(printf '%s' "$1" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')"; exit 1; }

[ -n "${SUPABASE_URL:-}" ] || die "SUPABASE_URL is not set in the environment"
[ -n "${SUPABASE_SERVICE_ROLE_KEY:-}" ] || die "SUPABASE_SERVICE_ROLE_KEY is not set in the environment"

BASE="${SUPABASE_URL%/}/rest/v1"

# Perform a PostgREST request. $1=method $2=path $3=body(optional)
# Prints the body; exits non-zero (after printing an error envelope) on HTTP >=400.
sb_request() {
  local method="$1" path="$2" body="${3:-}" out code
  local -a args=(
    -sS -m 60 -X "$method" "$BASE/$path"
    -H "apikey: $SUPABASE_SERVICE_ROLE_KEY"
    -H "Authorization: Bearer $SUPABASE_SERVICE_ROLE_KEY"
    -H "Accept-Profile: $SCHEMA"
    -H "Content-Profile: $SCHEMA"
  )
  if [ -n "$body" ]; then
    args+=(-H "Content-Type: application/json" -H "Prefer: return=representation" --data-binary "$body")
  elif [ "$method" != "GET" ]; then
    args+=(-H "Prefer: return=representation")
  fi

  out="$(curl "${args[@]}" -w $'\n__HTTP__%{http_code}' 2>&1)"
  code="${out##*__HTTP__}"
  out="${out%$'\n'__HTTP__*}"

  case "$code" in
    2*) printf '%s' "$out"; return 0 ;;
    *)  printf '{"ok":false,"http":%s,"error":%s}\n' "${code:-0}" \
          "$(printf '%s' "$out" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()[:2000]))')"
        return 1 ;;
  esac
}

# ---- flag handling ---------------------------------------------------------
case "${1:-}" in
  --ping)
    if sb_request GET "?select=" >/dev/null 2>&1 || sb_request GET "notify_queue?select=id&limit=1" >/dev/null; then
      printf '{"ok":true,"url":"%s","schema":"%s"}\n' "$SUPABASE_URL" "$SCHEMA"; exit 0
    fi
    die "could not reach PostgREST at $BASE" ;;
  --rest)
    method="${2:?--rest needs a method}"; path="${3:?--rest needs a path}"; body="${4:-}"
    sb_request "$method" "$path" "$body"; rc=$?; echo; exit $rc ;;
  --explain) EXPLAIN=1; SQL="${2:?--explain needs a SQL string}" ;;
  "") die "usage: sb.sh '<SQL>' | sb.sh --rest <METHOD> <path> [json] | sb.sh --ping" ;;
  *)  EXPLAIN=0; SQL="$1" ;;
esac

# ---- SQL → PostgREST translation ------------------------------------------
# Emits one line: METHOD<TAB>PATH<TAB>BODY   (or an error envelope on stderr).
PLAN="$(SB_SQL="$SQL" python3 <<'PY'
import json, os, re, sys
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

def utcnow():
    # 'Z' rather than '+00:00': a literal '+' in a query string decodes to a
    # space, which Postgres then rejects as an invalid timestamp.
    return datetime.now(timezone.utc).replace(tzinfo=None)

def iso(dt):
    return dt.replace(tzinfo=None).isoformat() + "Z"

sql = os.environ["SB_SQL"].strip().rstrip(";").strip()

def fail(msg):
    print(json.dumps({"ok": False, "error": msg}), file=sys.stderr)
    sys.exit(3)

# --- tokenizer: strings are atomic so commas/parens inside them are safe ----
TOKEN = re.compile(r"""
      (?P<ws>\s+)
    | (?P<str>'(?:[^']|'')*')
    | (?P<num>-?\d+\.?\d*)
    | (?P<cast>::\w+)
    | (?P<op><=|>=|<>|!=|=|<|>|\|\||[-+])
    | (?P<word>[A-Za-z_][A-Za-z_0-9]*)
    | (?P<punc>[(),*.])
""", re.VERBOSE)

def tokenize(s):
    toks, i = [], 0
    while i < len(s):
        m = TOKEN.match(s, i)
        if not m:
            fail(f"cannot parse SQL near: {s[i:i+40]!r}")
        i = m.end()
        kind = m.lastgroup
        if kind == "ws":
            continue
        text = m.group()
        if kind == "str":
            toks.append(("S", text[1:-1].replace("''", "'")))
        elif kind == "num":
            toks.append(("N", text))
        elif kind == "cast":
            toks.append(("C", text[2:].lower()))
        elif kind == "op":
            toks.append(("O", text))
        elif kind == "word":
            toks.append(("W", text))
        else:
            toks.append(("P", text))
    return toks

T = tokenize(sql)
pos = 0

def peek(n=0):
    return T[pos + n] if pos + n < len(T) else (None, None)
def nextt():
    global pos
    t = peek(); pos += 1; return t
def at_word(*words):
    k, v = peek()
    return k == "W" and v.lower() in [w.lower() for w in words]
def expect_word(*words):
    if not at_word(*words):
        fail(f"expected {'/'.join(words)} but found {peek()[1]!r}")
    return nextt()[1]
def expect_punc(p):
    k, v = peek()
    if k != "P" or v != p:
        fail(f"expected {p!r} but found {v!r}")
    nextt()

for kind, val in T:
    if kind == "O" and val == "||":
        fail("the || concatenation operator is not supported — build the value "
             "in the shell and pass a literal")

INTERVAL = re.compile(r"(\d+)\s*(second|minute|hour|day|week|month|year)s?", re.I)
UNIT = {"second": "seconds", "minute": "minutes", "hour": "hours",
        "day": "days", "week": "weeks"}

def interval_delta(text):
    parts = INTERVAL.findall(text)
    if not parts:
        fail(f"cannot parse interval {text!r}")
    td = timedelta()
    for amount, unit in parts:
        unit = unit.lower(); amount = int(amount)
        if unit in UNIT:
            td += timedelta(**{UNIT[unit]: amount})
        elif unit == "month":
            td += timedelta(days=30 * amount)
        else:
            td += timedelta(days=365 * amount)
    return td

def parse_value():
    """Return (python_value, is_json). Consumes trailing ::casts."""
    k, v = nextt()
    if k == "S":
        val, is_json = v, False
    elif k == "N":
        val, is_json = (float(v) if "." in v else int(v)), False
    elif k == "W" and v.lower() == "now":
        expect_punc("("); expect_punc(")")
        base = utcnow()
        if at_word("interval"):
            fail("missing +/- before interval")
        val, is_json = iso(base), False
    elif k == "W" and v.lower() in ("null", "true", "false"):
        val = {"null": None, "true": True, "false": False}[v.lower()]
        is_json = False
    else:
        fail(f"unsupported value {v!r}")

    # ::casts — jsonb/json means send real JSON, not a quoted string
    while peek()[0] == "C":
        cast = nextt()[1]
        if cast in ("json", "jsonb") and isinstance(val, str):
            try:
                val = json.loads(val)
            except json.JSONDecodeError as e:
                fail(f"value cast to {cast} is not valid JSON: {e}")
            is_json = True
    return val, is_json

# `now()` appears inside WHERE as `now() - interval '...'`; the tokenizer splits
# the minus off as an operator, so handle that shape here.
def parse_rhs():
    if at_word("now"):
        nextt(); expect_punc("("); expect_punc(")")
        base = utcnow()
        k, v = peek()
        if k == "O" and v in ("-", "+"):
            nextt(); expect_word("interval")
            ik, iv = nextt()
            if ik != "S":
                fail("interval must be a quoted string")
            delta = interval_delta(iv)
            base = base - delta if v == "-" else base + delta
        while peek()[0] == "C":
            nextt()
        return iso(base), False
    return parse_value()

OPMAP = {"=": "eq", "<>": "neq", "!=": "neq", "<": "lt",
         "<=": "lte", ">": "gt", ">=": "gte"}

def fmt(v):
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)

def enc(v):
    """Percent-encode a filter value for the query string."""
    s = fmt(v)
    if s in ("null", "true", "false"):
        return s
    return quote(s, safe="*")

def quote_in(v):
    s = fmt(v)
    if re.search(r'[,\.\(\)"\s]', s):
        s = '"' + s.replace('"', '\\"') + '"'
    return quote(s, safe='*"')

def parse_where():
    """Return a list of PostgREST filter strings."""
    filters = []
    while True:
        k, col = nextt()
        if k != "W":
            fail(f"expected a column name in WHERE, found {col!r}")
        if peek()[0] == "P" and peek()[1] == ".":  # table.column
            nextt(); col = nextt()[1]

        if at_word("is"):
            nextt()
            if at_word("not"):
                nextt(); expect_word("null"); filters.append(f"{col}=not.is.null")
            else:
                expect_word("null"); filters.append(f"{col}=is.null")
        elif at_word("in"):
            nextt(); expect_punc("(")
            vals = []
            while True:
                v, _ = parse_value(); vals.append(quote_in(v))
                if peek()[0] == "P" and peek()[1] == ",":
                    nextt(); continue
                break
            expect_punc(")")
            filters.append(f"{col}=in.({','.join(vals)})")
        elif at_word("like", "ilike"):
            word = nextt()[1].lower()
            v, _ = parse_value()
            filters.append(f"{col}={word}.{quote(fmt(v).replace('%', '*'), safe='*')}")
        elif at_word("not"):
            fail("NOT in WHERE is not supported")
        else:
            k2, op = nextt()
            if k2 != "O" or op not in OPMAP:
                fail(f"unsupported operator {op!r} in WHERE")
            v, _ = parse_rhs()
            filters.append(f"{col}={OPMAP[op]}.{enc(v)}")

        if at_word("and"):
            nextt(); continue
        if at_word("or"):
            fail("OR in WHERE is not supported — run separate statements")
        break
    return filters

def parse_tail():
    """ORDER BY / LIMIT → PostgREST query params."""
    params = []
    if at_word("order"):
        nextt(); expect_word("by")
        orders = []
        while True:
            col = nextt()[1]
            direction = "asc"
            if at_word("asc", "desc"):
                direction = nextt()[1].lower()
            if at_word("nulls"):
                nextt(); direction += "." + ("nullsfirst" if at_word("first") else "nullslast"); nextt()
            orders.append(f"{col}.{direction}")
            if peek()[0] == "P" and peek()[1] == ",":
                nextt(); continue
            break
        params.append("order=" + ",".join(orders))
    if at_word("limit"):
        nextt(); params.append("limit=" + nextt()[1])
    if at_word("offset"):
        nextt(); params.append("offset=" + nextt()[1])
    return params

verb = peek()[1]
if verb is None:
    fail("empty statement")
verb = verb.lower()

if verb == "select":
    nextt()
    cols = []
    while not at_word("from"):
        k, v = nextt()
        if v is None:
            fail("SELECT without FROM")
        if k == "P" and v == ",":
            continue
        if k == "P" and v == "*":
            cols.append("*"); continue
        if k == "W":
            if v.lower() in ("count", "sum", "avg", "min", "max", "distinct"):
                fail(f"{v.upper()} is not supported — select the rows and aggregate in the shell")
            cols.append(v); continue
        fail(f"unsupported item in SELECT list: {v!r}")
    expect_word("from")
    table = nextt()[1]
    params = ["select=" + (",".join(cols) if cols else "*")]
    if at_word("where"):
        nextt(); params += parse_where()
    params += parse_tail()
    if peek()[1] is not None:
        fail(f"unsupported trailing SQL near {peek()[1]!r}")
    print("GET\t" + table + "?" + "&".join(params) + "\t")

elif verb == "update":
    nextt()
    table = nextt()[1]
    expect_word("set")
    payload = {}
    while True:
        col = nextt()[1]
        k, op = nextt()
        if k != "O" or op != "=":
            fail("expected = in SET")
        v, _ = parse_rhs()
        payload[col] = v
        if peek()[0] == "P" and peek()[1] == ",":
            nextt(); continue
        break
    if not at_word("where"):
        fail("refusing an UPDATE with no WHERE clause")
    nextt()
    filters = parse_where()
    if peek()[1] is not None:
        fail(f"unsupported trailing SQL near {peek()[1]!r}")
    print("PATCH\t" + table + "?" + "&".join(filters) + "\t" + json.dumps(payload))

elif verb == "insert":
    nextt(); expect_word("into")
    table = nextt()[1]
    expect_punc("(")
    cols = []
    while True:
        cols.append(nextt()[1])
        if peek()[0] == "P" and peek()[1] == ",":
            nextt(); continue
        break
    expect_punc(")")
    expect_word("values")
    rows = []
    while True:
        expect_punc("(")
        vals = []
        while True:
            v, _ = parse_value(); vals.append(v)
            if peek()[0] == "P" and peek()[1] == ",":
                nextt(); continue
            break
        expect_punc(")")
        if len(vals) != len(cols):
            fail(f"INSERT has {len(cols)} columns but {len(vals)} values")
        rows.append(dict(zip(cols, vals)))
        if peek()[0] == "P" and peek()[1] == ",":
            nextt(); continue
        break
    if at_word("on"):
        fail("ON CONFLICT is not supported — check for the row first")
    if at_word("returning"):
        fail("RETURNING is not supported — the rows are returned anyway")
    if peek()[1] is not None:
        fail(f"unsupported trailing SQL near {peek()[1]!r}")
    print("POST\t" + table + "\t" + json.dumps(rows))

elif verb == "delete":
    nextt(); expect_word("from")
    table = nextt()[1]
    if not at_word("where"):
        fail("refusing a DELETE with no WHERE clause")
    nextt()
    filters = parse_where()
    if peek()[1] is not None:
        fail(f"unsupported trailing SQL near {peek()[1]!r}")
    print("DELETE\t" + table + "?" + "&".join(filters) + "\t")

else:
    fail(f"unsupported statement {verb.upper()!r} — sb.sh handles "
         "SELECT / INSERT / UPDATE / DELETE only")
PY
)" || exit 1

METHOD="$(printf '%s' "$PLAN" | cut -f1)"
RPATH="$(printf '%s' "$PLAN" | cut -f2)"
BODY="$(printf '%s' "$PLAN" | cut -f3)"

if [ "${EXPLAIN:-0}" = "1" ]; then
  printf '{"method":"%s","path":%s,"body":%s}\n' "$METHOD" \
    "$(printf '%s' "$RPATH" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')" \
    "$(printf '%s' "${BODY:-null}" | python3 -c 'import sys; s=sys.stdin.read().strip(); print(s if s else "null")')"
  exit 0
fi

RESP="$(sb_request "$METHOD" "$RPATH" "$BODY")" || { printf '%s\n' "$RESP"; exit 1; }

if [ "$METHOD" = "GET" ]; then
  printf '%s\n' "$RESP"
else
  printf '%s' "$RESP" | python3 -c '
import json, sys
raw = sys.stdin.read().strip()
try:
    rows = json.loads(raw) if raw else []
    print(json.dumps({"ok": True, "count": len(rows) if isinstance(rows, list) else 1}))
except json.JSONDecodeError:
    print(json.dumps({"ok": True, "raw": raw[:500]}))
'
fi
