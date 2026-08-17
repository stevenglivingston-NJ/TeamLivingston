#!/usr/bin/env bash
# sb.sh - Supabase SQL helper via PostgREST REST API
# Usage: sb.sh '<SQL query>'
SQL="$1"
if [ -z "${SUPABASE_URL:-}" ] || [ -z "${SUPABASE_SERVICE_ROLE_KEY:-}" ]; then
  echo '{"error":"SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY not set"}' >&2; exit 1
fi
python3 - "$SQL" <<'PYEOF'
import sys,re,json,urllib.request,urllib.parse,os,datetime
sql=sys.argv[1].strip().rstrip(';')
base=os.environ['SUPABASE_URL']+'/rest/v1'
key=os.environ['SUPABASE_SERVICE_ROLE_KEY']
bh={'Authorization':f'Bearer {key}','apikey':key,'Accept-Profile':'public','Content-Profile':'public','Content-Type':'application/json'}
def now_minus(m): return (datetime.datetime.utcnow()-datetime.timedelta(minutes=m)).strftime('%Y-%m-%dT%H:%M:%S')
def utcnow(): return datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
def http(method,url,body=None,minimal=False):
    h=dict(bh); h['Prefer']='return=minimal' if minimal else 'return=representation'
    data=json.dumps(body).encode() if body is not None else None
    req=urllib.request.Request(url,data=data,headers=h,method=method)
    try:
        with urllib.request.urlopen(req) as r: t=r.read().decode(); return t if t else '{"ok":true}'
    except urllib.error.HTTPError as e: return e.read().decode()
def parse_where(w):
    p={}
    for c in re.split(r'\s+AND\s+',w.strip(),flags=re.I):
        c=c.strip()
        m=re.match(r"(\w+)\s*=\s*'([^']*)'",c)
        if m: p[m.group(1)]=f'eq.{m.group(2)}'; continue
        m=re.match(r"(\w+)\s*<\s*now\(\)\s*-\s*interval\s*'(\d+)\s*minutes?'",c,re.I)
        if m: p[m.group(1)]=f'lt.{now_minus(int(m.group(2)))}'; continue
        m=re.match(r"(\w+)\s*<\s*'([^']*)'",c)
        if m: p[m.group(1)]=f'lt.{m.group(2)}'; continue
        m=re.match(r"(\w+)\s*>=\s*'([^']*)'",c)
        if m: p[m.group(1)]=f'gte.{m.group(2)}'; continue
        m=re.match(r"(\w+)\s*=\s*(\S+)",c)
        if m: p[m.group(1)]=f'eq.{m.group(2)}'
    return p
# SELECT
m=re.match(r"SELECT\s+(.*?)\s+FROM\s+(\w+)(.*)",sql,re.I|re.S)
if m:
    cols,table,rest=m.groups(); params={}
    wm=re.search(r"WHERE\s+(.*?)(?:\s+ORDER BY|\s+LIMIT|$)",rest,re.I|re.S)
    if wm: params.update(parse_where(wm.group(1)))
    om=re.search(r"ORDER BY\s+(\w+)(?:\s+(ASC|DESC))?",rest,re.I)
    if om: params['order']=f"{om.group(1)}.{(om.group(2) or 'ASC').lower()}"
    lm=re.search(r"LIMIT\s+(\d+)",rest,re.I)
    if lm: params['limit']=lm.group(1)
    if cols.strip()!='*': params['select']=re.sub(r'\s+','',cols)
    qs='&'.join(f'{k}={urllib.parse.quote(str(v))}' for k,v in params.items())
    print(http('GET',f"{base}/{table}"+(f'?{qs}' if qs else ''))); sys.exit(0)
# UPDATE
m=re.match(r"UPDATE\s+(\w+)\s+SET\s+(.*?)\s+WHERE\s+(.*)",sql,re.I|re.S)
if m:
    table,sc,where=m.groups(); body={}
    for part in re.split(r",\s*(?=\w+\s*=)",sc.strip()):
        part=part.strip()
        e=re.match(r"(\w+)\s*=\s*'([^']*)'",part)
        if e: body[e.group(1)]=e.group(2); continue
        e=re.match(r"(\w+)\s*=\s*now\(\)",part,re.I)
        if e: body[e.group(1)]=utcnow(); continue
        e=re.match(r"(\w+)\s*=\s*'(.+?)'::(jsonb|json)",part,re.S)
        if e:
            try: body[e.group(1)]=json.loads(e.group(2))
            except: body[e.group(1)]=e.group(2)
            continue
        e=re.match(r"(\w+)\s*=\s*(.+)",part)
        if e: body[e.group(1)]=e.group(2).strip()
    params=parse_where(where)
    qs='&'.join(f'{k}={urllib.parse.quote(str(v))}' for k,v in params.items())
    print(http('PATCH',f"{base}/{table}"+(f'?{qs}' if qs else ''),body,minimal=True)); sys.exit(0)
# INSERT
m=re.match(r"INSERT INTO\s+(\w+)\s*\(([^)]+)\)\s+VALUES\s*\((.+)\)",sql,re.I|re.S)
if m:
    table=m.group(1); cols=[c.strip() for c in m.group(2).split(',')]
    vals=[g1 if g1 is not None else g2 for g1,g2 in re.findall(r"'((?:[^'\\]|\\.)*)'|(\w+)",m.group(3))]
    print(http('POST',f"{base}/{table}",dict(zip(cols,vals)))); sys.exit(0)
print(json.dumps({"error":f"Unsupported SQL: {sql[:100]}"})); sys.exit(1)
PYEOF
