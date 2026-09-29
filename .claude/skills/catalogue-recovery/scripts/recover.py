#!/usr/bin/env python3
"""
catalogue-recovery helper — rebuild one clean, client-facing "Finalized" selections
document for a KTU/BTU JobTread job, and audit why selection edits went missing.

Self-contained: talks to the JobTread Pave API with JOBTREAD_GRANT_KEY. No MCP, no
other repo needed, so it also runs from a scheduled/non-interactive session.

  python3 recover.py sweep  <jobId> [--out DIR] [--account]   # everything on the job (+ sibling jobs)
  python3 recover.py photos <jobId> <docNumber> [--out DIR]   # download a document's line photos to view
  python3 recover.py build  <spec.json>                       # create the Finalized document from a spec
  python3 recover.py verify <documentId>                      # lines, photos, leftover internal wording

READ SKILL.md FIRST. build writes to a live job; sweep/photos/verify only read.
"""
import argparse, collections, datetime, json, os, re, subprocess, sys, urllib.error, urllib.request

API = "https://api.jobtread.com/pave"
ORG_ID = "22PB4XPxGZHK"            # Kitchen Tune-Up Bloomfield (KTU + BTU share one org)
TZ = "America/New_York"            # JobTread timestamps are UTC; the business runs on Eastern
INTERNAL_WORDS = ("OPEN", "CONFIRM", "WHERE THIS COMES FROM", "parameter", "job budget",
                  "IMG_", "Amanda", "Steven", "INTERNAL", "TODO")


def _key():
    k = os.environ.get("JOBTREAD_GRANT_KEY", "").strip()
    if not k:
        sys.exit("JOBTREAD_GRANT_KEY is not set (env vars load at session start).")
    return k


def pave(query):
    body = json.dumps({"query": {"$": {"grantKey": _key()}, **query}}).encode()
    req = urllib.request.Request(API, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Pave {e.code}: {e.read().decode('utf-8', 'replace')[:800]}") from None


def local(ts):
    """UTC ISO -> 'MM/DD h:mm AM' Eastern."""
    if not ts:
        return ""
    from zoneinfo import ZoneInfo
    d = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(ZoneInfo(TZ))
    return d.strftime("%m/%d %I:%M:%S %p").lstrip("0")


def paged(root, field, args, nodes, size=25):
    """All nodes of a connection, following nextPage. Keep size small: big pages 413."""
    out, page = [], None
    while True:
        a = {"size": size, **args}
        if page:
            a["page"] = page
        d = pave({root[0]: {"$": root[1], field: {"$": a, "nextPage": {}, "nodes": nodes}}})
        c = d[root[0]][field]
        out += c["nodes"]
        page = c.get("nextPage")
        if not page:
            return out


LINE = {"id": {}, "name": {}, "description": {}, "quantity": {}, "quantityFormula": {}, "createdAt": {},
        "isSelected": {}, "unit": {"id": {}, "name": {}}, "costCode": {"id": {}, "name": {}},
        "costType": {"id": {}, "name": {}}, "costGroup": {"name": {}},
        "document": {"id": {}, "number": {}, "name": {}, "subject": {}, "status": {}, "isSimpleSelection": {}},
        "jobCostItem": {"id": {}}, "files": {"nodes": {"name": {}, "url": {}}}}


# --------------------------------------------------------------------------- sweep
def sweep(job_id, out, account=False):
    os.makedirs(out, exist_ok=True)
    job = pave({"job": {"$": {"id": job_id}, "id": {}, "name": {}, "number": {}, "parameters": {},
                        "description": {}, "location": {"address": {}, "account": {"id": {}, "name": {}}},
                        "customFieldValues": {"nodes": {"value": {}, "customField": {"name": {}}}},
                        "documents": {"nodes": {"id": {}, "number": {}, "name": {}, "subject": {}, "status": {},
                                                "isSimpleSelection": {}, "includeInBudget": {}, "createdAt": {},
                                                "costItems": {"count": {}}}}}})["job"]
    lines = paged(("job", {"id": job_id}), "costItems", {}, LINE)
    events = paged(("job", {"id": job_id}), "events", {"sortBy": [{"field": "createdAt", "order": "asc"}]},
                   {"createdAt": {}, "type": {}, "createdByUser": {"name": {}}, "createdByUserAgent": {},
                    "createdByGrantName": {}, "data": {},
                    "document": {"_on_document": {"number": {}}, "_on_deletedDocument": {"id": {}}}}, size=20)
    json.dump({"job": job, "lines": lines, "events": events}, open(f"{out}/sweep_{job_id}.json", "w"), indent=1)

    acct = (job.get("location") or {}).get("account") or {}
    print(f"== {job['name']} ({job['number']}) · {acct.get('name')} · {job['location'].get('address')}")
    print("\nDOCUMENTS  (simple selection → Selections tab; others → Documents tab)")
    for d in job["documents"]["nodes"]:
        tab = "Selections tab" if d["isSimpleSelection"] else "Documents"
        print(f"  #{d['number']:<3} {d['name']:<11} {str(d['subject'] or ''):<28} {d['status']:<9} "
              f"{d['costItems']['count']:>3} lines  {tab}  created {local(d['createdAt'])}")

    budget = [l for l in lines if not l.get("document")]
    tpl_cut = min((l["createdAt"] for l in budget), default="")[:10]
    print(f"\nBUDGET: {len(budget)} lines. Hand-added (after template load {tpl_cut}):")
    for l in sorted(budget, key=lambda x: x["createdAt"]):
        if l["createdAt"][:10] > tpl_cut:
            print(f"  {local(l['createdAt'])} | {l['name'][:48]:<48} | qty {l['quantity']} | photos "
                  f"{len(l['files']['nodes'])} | {(l['description'] or '')[:70]!r}")
    print("\nBUDGET QUANTITIES > 0 (formula-driven from parameters):")
    for l in budget:
        if (l["quantity"] or 0) > 0 and "QA CHECK" not in (l["costGroup"] or {}).get("name", ""):
            print(f"  {l['quantity']:>8} {(l['unit'] or {}).get('name', ''):<12} {l['name'][:60]}")
    print("\nPARAMETERS WITH A VALUE:")
    for p in job["parameters"]:
        v = p.get("value")
        if v not in (None, "", 0, "0", "None", "N/A", "No"):
            print(f"  {p['name']}: {v}")
    links = [l for l in lines if "http" in (l["description"] or "")]
    print(f"\nLINES WITH A LINK: {len(links)}")
    for l in links:
        where = f"doc #{l['document']['number']}" if l.get("document") else "budget"
        url = re.search(r"https?://\S+", l["description"]).group(0)[:90]
        print(f"  [{where}] {l['name'][:50]} → {url}")

    print("\nSTATUS TIMELINE (Eastern). Pending/approved = LOCKED, edits refused:")
    for e in events:
        if e["type"] in ("documentCreated", "documentUpdated", "documentDeleted"):
            dn = (e.get("document") or {}).get("number", "deleted")
            nxt = ((e.get("data") or {}).get("next") or {})
            st = nxt.get("status", "")
            dev = "iPhone" if "iPhone" in (e.get("createdByUserAgent") or "") else \
                  "Mac" if "Macintosh" in (e.get("createdByUserAgent") or "") else (e.get("createdByGrantName") or "")
            if e["type"] != "documentUpdated" or st:
                print(f"  {local(e['createdAt']):<22} #{dn:<4} {e['type']:<16} {st:<9} "
                      f"{(e.get('createdByUser') or {}).get('name', ''):<18} {dev}")

    if account and acct.get("id"):
        sib = pave({"account": {"$": {"id": acct["id"]}, "jobs": {"nodes": {"id": {}, "name": {}}}}})["account"]["jobs"]["nodes"]
        mine = {f["name"]: l["name"] for l in lines for f in l["files"]["nodes"]}
        print(f"\nSIBLING JOBS ON {acct['name']}: matching this job's photo filenames")
        for j in sib:
            if j["id"] == job_id:
                continue
            other = paged(("job", {"id": j["id"]}), "costItems", {}, LINE)
            json.dump(other, open(f"{out}/sweep_{j['id']}.json", "w"), indent=1)
            hits = [(f["name"], l["name"], (l["description"] or "")[:90]) for l in other
                    for f in l["files"]["nodes"] if f["name"] in mine and f["name"].startswith("IMG_")]
            print(f"  {j['name']}: {len(other)} lines, {len(hits)} photo matches")
            for fn, nm, ds in hits:
                print(f"     {fn}  ({mine[fn]})  →  {nm[:50]} | {ds!r}")
    print(f"\nFull dump: {out}/sweep_{job_id}.json")


# -------------------------------------------------------------------------- photos
def photos(job_id, doc_number, out):
    os.makedirs(f"{out}/img", exist_ok=True)
    lines = paged(("job", {"id": job_id}), "costItems", {}, LINE)
    idx = {}
    for l in lines:
        if (l.get("document") or {}).get("number") == int(doc_number):
            for f in l["files"]["nodes"]:
                idx.setdefault(f["name"], (l["name"], f["url"]))
    for fn, (item, url) in idx.items():
        subprocess.run(["curl", "-sS", "-m", "60", "-L", "-o", f"{out}/img/{fn}", url], check=False)
        print(f"  {fn:<28} {item}")
    json.dump({k: v[0] for k, v in idx.items()}, open(f"{out}/img/index.json", "w"), indent=1)
    print(f"{len(idx)} photos in {out}/img — view each one (Read tool) to identify the product.")


# --------------------------------------------------------------------------- build
def _upload(path_or_url, name):
    if re.match(r"https?://", path_or_url):
        blob = subprocess.run(["curl", "-sS", "-m", "60", "-L", path_or_url], capture_output=True, check=True).stdout
    else:
        blob = open(path_or_url, "rb").read()
    ctype = "image/png" if name.lower().endswith(".png") else "image/jpeg"
    up = pave({"createUploadRequest": {"$": {"organizationId": ORG_ID, "size": len(blob), "type": ctype},
                                       "createdUploadRequest": {"id": {}, "url": {}}}})["createUploadRequest"]["createdUploadRequest"]
    subprocess.run(["curl", "-sS", "-X", "PUT", up["url"], "-H", f"content-type: {ctype}",
                    "-H", f"x-goog-content-length-range: {len(blob)},{len(blob)}", "--data-binary", "@-"],
                   input=blob, check=True, capture_output=True)
    return {"name": name, "uploadRequestId": up["id"]}


def build(spec_path):
    s = json.load(open(spec_path))
    tpl = {}
    if s.get("copySenderFromDocId"):
        tpl = pave({"document": {"$": {"id": s["copySenderFromDocId"]}, **{k: {} for k in (
            "toName", "toEmailAddress", "toAddress", "fromName", "fromEmailAddress", "fromPhoneNumber", "fromAddress",
            "fromOrganizationName", "signatureDisclaimer", "emailMessage", "jobLocationName", "jobLocationAddress")}}})["document"]
    items = []
    for ln in s["lines"]:
        it = {"_type": "costItem", "name": ln["name"], "description": ln["description"],
              "costCodeId": ln["costCodeId"], "costTypeId": ln["costTypeId"], "unitCost": 0, "unitPrice": 0}
        if ln.get("quantity") is not None:
            it["quantity"] = ln["quantity"]
        if ln.get("unitId"):
            it["unitId"] = ln["unitId"]
        items.append(it)
    payload = {"jobId": s["jobId"], "name": s.get("name", "Selections"), "type": "customerOrder",
               "subject": s["subject"], "description": s["description"], "taxRate": 0, "dueDays": 7,
               "includeInBudget": False, "showCostItemFiles": True, "showQuantity": True, "requireSignature": True,
               **{k: v for k, v in tpl.items() if v},
               "lineItems": [{"_type": "costGroup", "name": s.get("groupName", "Selections"), "lineItems": items}]}
    doc = pave({"createDocument": {"$": payload, "createdDocument": {"id": {}, "number": {}, "costItems": {
        "$": {"size": 50}, "nodes": {"id": {}, "name": {}}}}}})["createDocument"]["createdDocument"]
    print(f"created document #{doc['number']} {doc['id']} (draft)")
    byname = {n["name"]: n["id"] for n in doc["costItems"]["nodes"]}
    for ln in s["lines"]:
        ph = ln.get("photos") or []
        if ph:   # ONE update per line with ALL files — a second updateCostItem(files) replaces the first
            files = [_upload(p, os.path.basename(p.split("?")[0])) for p in ph]
            cid = byname[ln["name"]]
            pave({"updateCostItem": {"$": {"id": cid, "files": files}, "costItem": {"$": {"id": cid}, "id": {}}}})
    for c in s.get("internalComments", []):   # team-only notes: never visible to the client or vendors
        pave({"createComment": {"$": {"targetType": "document", "targetId": doc["id"], "name": c["name"],
                                      "message": c["message"][:4096], "isPinned": True, "isVisibleToAll": False,
                                      "isVisibleToCustomerRoles": False, "isVisibleToVendorRoles": False,
                                      "isVisibleToInternalRoles": True}, "createdComment": {"id": {}}}})
    verify(doc["id"])


# -------------------------------------------------------------------------- verify
def verify(doc_id):
    d = pave({"document": {"$": {"id": doc_id}, "name": {}, "number": {}, "subject": {}, "status": {},
                           "isSimpleSelection": {}, "includeInBudget": {}, "description": {},
                           "comments": {"nodes": {"name": {}, "isVisibleToCustomerRoles": {}}},
                           "costItems": {"$": {"size": 50}, "nodes": {"name": {}, "quantity": {}, "description": {},
                                                                     "files": {"count": {}}}}}})["document"]
    n = d["costItems"]["nodes"]
    text = (d["description"] or "") + " ".join((i["name"] or "") + " " + (i["description"] or "") for i in n)
    left = sorted({w for w in INTERNAL_WORDS if w in text})
    print(f"{d['name']} #{d['number']} · {d['subject']} · {d['status']} · "
          f"{'Selections tab' if d['isSimpleSelection'] else 'Documents'} · inBudget={d['includeInBudget']}")
    print(f"  lines {len(n)} · photos {sum(i['files']['count'] for i in n)} · header chars {len(d['description'] or '')}")
    print(f"  lines with no photo: {[i['name'][:40] for i in n if not i['files']['count']]}")
    print(f"  lines with no quantity: {[i['name'][:40] for i in n if i['quantity'] is None]}")
    print(f"  internal wording left in client text: {left or 'none'}")
    print(f"  comments: {[(c['name'], 'CLIENT-VISIBLE' if c['isVisibleToCustomerRoles'] else 'team only') for c in d['comments']['nodes']]}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    a = sp.add_parser("sweep"); a.add_argument("job"); a.add_argument("--out", default="recovery"); a.add_argument("--account", action="store_true")
    b = sp.add_parser("photos"); b.add_argument("job"); b.add_argument("doc"); b.add_argument("--out", default="recovery")
    c = sp.add_parser("build"); c.add_argument("spec")
    v = sp.add_parser("verify"); v.add_argument("doc")
    x = ap.parse_args()
    if x.cmd == "sweep":
        sweep(x.job, x.out, x.account)
    elif x.cmd == "photos":
        photos(x.job, x.doc, x.out)
    elif x.cmd == "build":
        build(x.spec)
    else:
        verify(x.doc)
