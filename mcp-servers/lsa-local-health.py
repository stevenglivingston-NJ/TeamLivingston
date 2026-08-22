#!/usr/bin/env python3
"""Seed the intranet organic_lsa card: WTD/MTD/YTD + YoY per brand, plus the two
alerts that caused the 2026 outage — LSA verification expiry and call-path health.

Run from the repo root:  python3 mcp-servers/lsa-local-health.py
Idempotent: deletes today's rows before inserting, then prunes older scan_dates.
Organic runs this daily; see .claude/agents/organic.md sections 12-16.
"""
import importlib.util, json, subprocess, logging, datetime
logging.disable(logging.INFO)
spec=importlib.util.spec_from_file_location("s","mcp-servers/google-ads/server.py"); spec.loader.exec_module(m:=importlib.util.module_from_spec(spec))
ga=m._ads_client().get_service("GoogleAdsService")
today=datetime.date.today(); tstr=today.isoformat()

VQ='''SELECT local_services_verification_artifact.artifact_type,
 local_services_verification_artifact.status,
 local_services_verification_artifact.insurance_verification_artifact.expiration_date_time,
 local_services_verification_artifact.license_verification_artifact.expiration_date_time
 FROM local_services_verification_artifact'''
CQ='''SELECT local_services_lead_conversation.event_date_time,
 local_services_lead_conversation.conversation_channel,
 local_services_lead_conversation.phone_call_details.call_duration_millis
 FROM local_services_lead_conversation
 ORDER BY local_services_lead_conversation.event_date_time DESC LIMIT 15'''

vals=[]
for order,(brand,cid) in enumerate([("KTU","2579406186"),("BTU","4668735878")],1):
    r=m.query_lsa_periods(brand); P=r["periods"]; acct=r.get("account",{})
    alerts=[]
    # verification
    best={}
    for row in ga.search(customer_id=cid, query=VQ):
        a=row.local_services_verification_artifact; t=a.artifact_type.name
        exp=(a.insurance_verification_artifact.expiration_date_time if t=="INSURANCE"
             else a.license_verification_artifact.expiration_date_time if t=="LICENSE" else "")
        if a.status.name=="PASSED" and exp:
            if t not in best or exp>best[t]: best[t]=exp
    for t,exp in sorted(best.items()):
        d=(datetime.date.fromisoformat(exp[:10])-today).days
        lvl="urgent" if d<30 else ("warn" if d<60 else "info")
        alerts.append({"level":lvl,"text":f"{t.title()} valid to {exp[:10]} ({d} days). Renew 60 days out — a lapse suspended KTU LSA for 16 days in 2026."})
    # call path
    convs=[(c.local_services_lead_conversation.event_date_time,
            c.local_services_lead_conversation.conversation_channel.name,
            c.local_services_lead_conversation.phone_call_details.call_duration_millis or 0)
           for c in ga.search(customer_id=cid, query=CQ)]
    calls=[c for c in convs if c[1]=="PHONE_CALL"]
    if calls:
        last=calls[0]
        zeros=0
        for c in calls:
            if c[2]==0: zeros+=1
            else: break
        age=(today-datetime.date.fromisoformat(last[0][:10])).days
        if zeros>=2 and age<=7:
            alerts.append({"level":"urgent","text":f"{zeros} consecutive 0-second calls in the last {age}d — phone path broken, not unanswered. Test-call the LSA number."})
        elif zeros>=2:
            alerts.append({"level":"warn","text":f"Routing repaired 2026-08-22. Last {zeros} calls on record are 0-second (newest {last[0][:10]}, {age}d ago) — awaiting the first real inbound call to confirm the fix in Google's data."})
        else:
            alerts.append({"level":"info","text":f"Last call {last[0][:10]}, {last[2]//1000}s — call path answering."})
    else:
        alerts.append({"level":"warn","text":"No PHONE_CALL conversations in the recent window — verify the LSA number rings through."})

    resp=acct.get("phone_responsiveness"); py=P.get("prior_year_YTD",{}); ytd,wtd,mtd=P["YTD"],P["WTD"],P["MTD"]
    sev="urgent" if any(a["level"]=="urgent" for a in alerts) else ("warn" if any(a["level"]=="warn" for a in alerts) else "info")
    if py.get("leads") and not py.get("coverage_note"):
        d=round((ytd["leads"]-py["leads"])/py["leads"]*100)
        headline=f"{ytd['leads']} leads YTD vs {py['leads']} last year ({'+' if d>=0 else ''}{d}% YoY) · {wtd['leads']} WTD · {mtd['leads']} MTD"
    else:
        headline=f"{ytd['leads']} leads YTD · {mtd['leads']} MTD · {wtd['leads']} WTD"
    detail=(f"Answer rate {round(resp*100)}%. " if resp is not None else "")+ \
           f"{ytd['charged']} of {ytd['leads']} YTD leads charged."
    fields={"severity":sev,"headline":headline,"detail":detail,
            "account":{"rating":acct.get("rating"),"reviews":acct.get("reviews"),
                       "weekly_budget":acct.get("weekly_budget"),"responsiveness":resp},
            "periods":P,"alerts":alerts,"scan_date":tstr}
    vals.append(f"('organic_lsa','{brand}',{order},'"+json.dumps(fields).replace("'","''")+"'::jsonb)")

subprocess.run(["bash","mcp-servers/sb.sh",f"DELETE FROM intranet_records WHERE section='organic_lsa' AND fields->>'scan_date' = '{tstr}';"],capture_output=True,text=True)
sql="INSERT INTO intranet_records (section, brand, sort_order, fields) VALUES "+", ".join(vals)+";"
print(subprocess.run(["bash","mcp-servers/sb.sh",sql],capture_output=True,text=True).stdout[:200])
print(subprocess.run(["bash","mcp-servers/sb.sh",f"DELETE FROM intranet_records WHERE section='organic_lsa' AND fields->>'scan_date' <> '{tstr}';"],capture_output=True,text=True).stdout[:200])
