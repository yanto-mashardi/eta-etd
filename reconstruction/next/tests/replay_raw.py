"""Stream existing raw AIS through the production normalizer and event engine.
No inference, no writes, no new AIS requests. This is a structural replay, not field validation.
"""
import argparse,importlib.util,json
from datetime import datetime,date,time,timedelta,timezone
from pathlib import Path
from collections import Counter
from events import classify,resolve,dt,minutes
from live_events import OperationalTracker
from evaluation import trip_key,record_trip
from copy import deepcopy
from zoneinfo import ZoneInfo
WIB=ZoneInfo("Asia/Jakarta")
def run(root,poller,day):
    spec=importlib.util.spec_from_file_location("candidate_poller",poller)
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    cfg=mod.load_yaml(root/"config/project_config.yaml");ais=cfg["ais"];api=ais["api"]
    centers=mod.terminal_centers(root,cfg);fmap=ais["field_map"];qc=ais.get("quality_control",{})
    buffer=float(ais["corridor_filter"].get("buffer_nm",2.0))
    whitelist={int(x) for x in ais["vessel_filter"]["mmsi_whitelist"]}
    lo=datetime.combine(day,time.min,tzinfo=WIB);hi=lo+timedelta(days=1)
    warm=lo-timedelta(hours=2)
    rawdir=root/api["raw_dir"]
    paths=[rawdir/("ais_api_raw_"+(warm.astimezone(timezone.utc).date()+timedelta(days=n)).strftime("%Y%m%d")+".jsonl") for n in range((hi.astimezone(timezone.utc).date()-warm.astimezone(timezone.utc).date()).days+1)]
    t=OperationalTracker();counts=Counter();flags=Counter();seen=set();complete=[];problems=[]
    for path in paths:
        if not path.is_file():continue
        with path.open(encoding="utf-8") as f:
            for line in f:
                try:env=json.loads(line);rx=dt(env["received_at"])
                except (ValueError,KeyError,TypeError):counts["invalid_envelope"]+=1;continue
                if not warm<=rx<hi:continue
                snapshot={}
                for raw in mod.unwrap_payload(env.get("payload")):
                    try:r=mod.normalize_one(raw,fmap,qc,centers,buffer,whitelist)
                    except (ValueError,KeyError,TypeError):counts["invalid_raw"]+=1;continue
                    if r is None:continue
                    if r.get("provider_observation_basis")=="SERVER_FALLBACK":
                        r["timestamp"]=rx.isoformat()
                        counts["server_fallback"]+=1
                    old=snapshot.get(r["mmsi"])
                    if old is None or dt(r["timestamp"])>=dt(old["timestamp"]):snapshot[r["mmsi"]]=r
                for r in snapshot.values():
                    m=str(r["mmsi"])
                    try:
                        p=classify(r,rx)
                        p=resolve(p,r,t.state["vessels"].get(m,{}).get("last"),rx)
                    except (ValueError,KeyError,TypeError):counts["rejected"]+=1;continue
                    if p is None:counts["duplicate_or_unresolved"]+=1;continue
                    counts["accepted"]+=1
                    old=deepcopy(t.state["vessels"].get(m,{}));n=len(t.state["cycles"])
                    events=t.process(p);v=t.state["vessels"][m];v["shipname"]=r.get("shipname") or m
                    if old.get("voyage") and (not v.get("voyage") or trip_key(m,old["voyage"])!=trip_key(m,v["voyage"])):
                        key=trip_key(m,old["voyage"]);exit=v.get("operational_exit") or {}
                        if exit.get("trip_id")==key:
                            old["voyage"]["event_evidence"]=exit.get("event_evidence",{})
                            old["voyage"]["qc_flags"]=exit.get("qc_flags",[])
                            if len(t.state["cycles"])>n:record_trip(t.state,m,old,t.state["cycles"][-1])
                            else:record_trip(t.state,m,old,status="COMPLETED_QC_FAIL",observed_exit=exit["D1_utc"])
                            q=old["voyage"];d0=q.get("D0_utc");a=q.get("A_utc");d1=exit["D1_utc"]
                            if d0 and a and lo<=dt(d0)<hi and lo<=dt(d1)<hi:
                                if not dt(d0)<dt(a)<dt(d1):problems.append("NONCHRONOLOGICAL:"+key)
                                complete.append(dict(trip_id=key,D0=d0,A=a,D1=d1,sailing_min=round(minutes(d0,a),3),vtt_min=round(minutes(a,d1),3),flags=exit.get("qc_flags",[])))
                                flags.update(exit.get("qc_flags",[]))
                        else:record_trip(t.state,m,old,status="INCOMPLETE_"+v["status"])
                    for x in events:
                        event=(m,x["phase"],x["issue_utc"])
                        if event in seen:problems.append("DUPLICATE:"+str(event))
                        seen.add(event);counts[x["phase"]]+=1
                        if x["phase"]=="D0":
                            if p["candidate"] or p["sog"]<=.8:problems.append("INVALID_EXIT:"+m)
                            if v["voyage"]["origin_port"]==p["port"] and p["distance"]<=.15:problems.append("BERTH_MANOEUVRE:"+m)
                    record_trip(t.state,m,v)
    return dict(day=day.isoformat(),raw_files=[x.name for x in paths if x.is_file()],counts=dict(counts),complete_cycles=len(complete),research_qc_pass=sum(not r["flags"] and 15<=r["sailing_min"]<=120 and 8<=r["vtt_min"]<=180 for r in complete),flags=dict(flags),structural_issues=problems,cycles=complete,status="PASS_STRUCTURAL" if complete and not problems else "INSUFFICIENT_OR_FAIL")
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--root",type=Path,required=True);p.add_argument("--poller",type=Path,required=True);p.add_argument("--day",type=date.fromisoformat,required=True);a=p.parse_args()
    result=run(a.root,a.poller,a.day);print(json.dumps(result,indent=2));raise SystemExit(0 if result["status"]=="PASS_STRUCTURAL" else 1)
