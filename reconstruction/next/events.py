"""Causal online adaptation of research Stage2/3/4. No writes to legacy AIS."""
from datetime import datetime, timezone
from statistics import median
from collections import Counter
import math, csv, json, os, tempfile
from pathlib import Path
from zoneinfo import ZoneInfo

PORTS={"BENGKALIS":{"BKL-01":(1.449921,102.136747),"BKL-02":(1.449491,102.138242)},
       "PAKNING":{"PKN-01":(1.380001,102.148561),"PKN-02":(1.37879,102.149836)}}
MMSI={"525002060","525002121","525003298","525015047","525100240"}
def dt(s):
    t=datetime.fromisoformat(str(s).replace("Z","+00:00"))
    if t.tzinfo is None: raise ValueError("AIS timestamp must include UTC offset")
    return t.astimezone(timezone.utc)
def minutes(a,b): return (dt(b)-dt(a)).total_seconds()/60
def nm(lat,lon,x,y):
    a,b,c,d=map(math.radians,(lat,lon,x,y))
    z=math.sin((c-a)/2)**2+math.cos(a)*math.cos(c)*math.sin((d-b)/2)**2
    return 3440.065*2*math.asin(math.sqrt(min(1,max(0,z))))
def classify(row,now,field="ais_update_at"):
    if str(row.get("inference_allowed","")).lower() not in ("true","1"): raise ValueError("AIS inference not permitted")
    m=str(row["mmsi"]).strip()
    if m not in MMSI: raise ValueError("Vessel outside research scope")
    stamp=dt(row[field])
    if not 0<=(now-stamp).total_seconds()<=300: raise ValueError("Stale or future AIS fix")
    lat,lon,sog=map(float,(row["latitude"],row["longitude"],row["sog"]))
    if not (1.2<=lat<=1.6 and 101.95<=lon<=102.4 and 0<=sog<=40): raise ValueError("AIS outside QC limits")
    try: cog=float(row.get("cog",""))
    except (TypeError,ValueError): cog=None
    if cog is not None and not (0<=cog<360): cog=None
    distances=sorted((nm(lat,lon,*xy),p,b) for p,bs in PORTS.items() for b,xy in bs.items())
    dist,p,b=distances[0]; second=distances[1][0]
    candidate=sog<=.8 and dist<=.15
    return {"mmsi":m,"ts":stamp.isoformat(),"received":now.isoformat(),"sog":sog,"cog":cog,"latitude":lat,"longitude":lon,
            "distance":dist,"port":p,"berth":b,"candidate":candidate,
            "ambiguous":candidate and (second<=.15 or (second-dist)*1852<50)}
def cycle_key(c): return (str(c["mmsi"]),dt(c["D0_utc"]).isoformat(),dt(c["A_utc"]).isoformat(),dt(c["D1_utc"]).isoformat())
def clean_cycle(c):
    key=cycle_key(c); d0,a,d1=key[1:]
    s,v=round(minutes(d0,a),5),round(minutes(a,d1),5)
    if not (15<=s<=120 and 8<=v<=180): raise ValueError("Cycle duration outside research QC")
    if c["origin_port"] not in PORTS or c["destination_port"] not in PORTS or c["origin_port"]==c["destination_port"]: raise ValueError("Invalid ports")
    return {"mmsi":key[0],"origin_port":c["origin_port"],"destination_port":c["destination_port"],"D0_utc":d0,"A_utc":a,"D1_utc":d1,"sailing":s,"vtt":v,"known_at":c.get("known_at",d1),"cycle_id":c.get("cycle_id","|".join(key))}
def read_seed(path):
    with Path(path).open(encoding="utf-8-sig",newline="") as f:
        rows=list(csv.DictReader(f))
    result=[]
    for c in rows:
        if c.get("qc_status")=="PASS" and c.get("event_quality")=="AIS_HIGH_CONFIDENCE":
            result.append(clean_cycle(c))
    if not result: raise ValueError("No accepted historical cycles")
    if len({cycle_key(c) for c in result})!=len(result): raise ValueError("Duplicate historical cycles")
    return result
def features(history,fix,origin,dest):
    issue=fix["ts"]; m=fix["mmsi"]; t=dt(issue).astimezone(ZoneInfo("Asia/Jakarta"))
    # Same last-30 grouping as Stage4; also exclude live labels not yet observed.
    observed=sorted((r for r in history if dt(r["D1_utc"])<dt(issue) and dt(r["known_at"])<=dt(fix["received"])),key=lambda r:(dt(r["D1_utc"]),r["cycle_id"]))
    groups={"pair":[r for r in observed if r["mmsi"]==m and r["destination_port"]==dest][-30:],
            "vessel":[r for r in observed if r["mmsi"]==m][-30:],
            "port":[r for r in observed if r["destination_port"]==dest][-30:],"global":observed[-30:]}
    f={"mmsi":m,"origin_port":origin,"destination_port":dest,"issue_hour_local":t.hour,"issue_dow_local":t.weekday(),
       "ais_fix_age_min":0.0,"sog_at_issue_kn":fix["sog"],"cog_at_issue_deg":fix["cog"],
       "distance_to_nearest_berth_nm":fix["distance"],"historical_completed_count":len(observed)}
    for g,rows in groups.items():
        if g!="global": f["hist_"+g+"_n"]=len(rows)
        for kind in ("sailing","vtt"): f["hist_"+g+"_"+kind+"_median_min"]=round(median(r[kind] for r in rows),6) if rows else None
    return f
def atomic_json(path,obj):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(dir=path.parent,prefix=".state-")
    try:
        with os.fdopen(fd,"w") as out:
            json.dump(obj,out,allow_nan=False);out.flush();os.fsync(out.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)

class Tracker:
    def __init__(self,state=None,seed=(),require_moving_exit=False):
        self.require_moving_exit=require_moving_exit
        self.state=state or {"vessels":{},"cycles":[]}
        all_cycles={cycle_key(c):c for c in seed}
        all_cycles.update({cycle_key(c):c for c in self.state["cycles"]})
        self.history=list(all_cycles.values())
        self.seed_count=len(seed)
    def process(self,p):
        v=self.state["vessels"].setdefault(p["mmsi"],{"last":None,"stop":None,"voyage":None,"status":"WAITING_ORIGIN","predictions":{}})
        prev=v["last"]
        if prev and dt(p["ts"])<=dt(prev["ts"]): return []
        events=[]
        # Never infer exit from missing observations or from a direct jump to another berth.
        if prev and minutes(prev["ts"],p["ts"])>(12 if prev["candidate"] and p["candidate"] and prev["port"]==p["port"] else 10):
            v.update(stop=None,voyage=None,status="AIS_GAP",predictions={})
            prev=None
        s=v["stop"]
        if p["candidate"]:
            if s and p["port"]!=s["port"]:
                v.update(stop=None,voyage=None,status="PORT_JUMP",predictions={});s=None;prev=None
            if not s:
                s={"port":p["port"],"first":p,"last":p,"n":0,"votes":{},"bracket":prev["ts"] if prev and not prev["candidate"] else None,"confirmed":False}
                v["stop"]=s
                q=v["voyage"]
                if q and q["destination_port"]==p["port"] and 15<=minutes(q["D0_utc"],p["ts"])<=120 and s["bracket"]:
                    s["arrival_features"]=features(self.history,p,q["origin_port"],q["destination_port"])
            s["n"]+=1;s["last"]=p
            if not p["ambiguous"]: s["votes"][p["berth"]]=s["votes"].get(p["berth"],0)+1
            if not s["confirmed"] and s["n"]>=3 and minutes(s["first"]["ts"],p["ts"])>=4 and (not s["bracket"] or minutes(s["bracket"],s["first"]["ts"])<=10):
                s["confirmed"]=True;v["status"]="BERTHED"
                # A stationary observation window establishes origin occupancy, not an actual arrival.
                s["arrival_observed"]=bool(s["bracket"])
                q=v["voyage"]
                if q and "arrival_features" in s and q["destination_port"]==p["port"]:
                    q["A_utc"]=s["first"]["ts"]
                    q["A_confirmed_at"]=p["received"]
                    events.append({"phase":"A","issue_utc":q["A_utc"],"published_at":p["received"],"features":s["arrival_features"]})
                elif q:
                    v["voyage"]=None;v["predictions"]={}
            elif not s["confirmed"]: v["status"]="ARRIVAL_CANDIDATE"
        else:
            if s:
                if self.require_moving_exit and s["confirmed"] and p["sog"]<=.8:
                    # A stationary fix outside the berth radius is not proof of departure.
                    v["status"]="DEPARTURE_PENDING";v["last"]=p
                    return events
                if s["confirmed"] and minutes(s["last"]["ts"],p["ts"])<=10:
                    q=v["voyage"]
                    if q and q.get("A_utc")==s["first"]["ts"] and q["destination_port"]==s["port"]:
                        try:
                            c=clean_cycle(dict(q,mmsi=p["mmsi"],D1_utc=p["ts"],known_at=p["received"]))
                            if cycle_key(c) not in {cycle_key(x) for x in self.history}:
                                self.history.append(c);self.state["cycles"].append(c)
                            v["last_completed_cycle"]=c
                        except ValueError: v["last_cycle_status"]="EXCLUDED_DURATION_QC"
                    origin=s["port"];dest=next(k for k in PORTS if k!=origin)
                    v["voyage"]={"origin_port":origin,"destination_port":dest,"D0_utc":p["ts"]}
                    v["predictions"]={};v["status"]="SAILING"
                    events.append({"phase":"D0","issue_utc":p["ts"],"published_at":p["received"],"features":features(self.history,p,origin,dest)})
                else:
                    v.update(voyage=None,predictions={},status="UNCONFIRMED_STOP_EXIT")
                v["stop"]=None
            elif v["voyage"] and minutes(v["voyage"]["D0_utc"],p["ts"])>120:
                v.update(voyage=None,predictions={},status="VOYAGE_EXPIRED")
            elif not v["voyage"]: v["status"]="WAITING_ORIGIN"
        v["last"]=p
        return events
    def snapshot(self,now):
        out={}
        for m,v in self.state["vessels"].items():
            last=v["last"];s=v["stop"];votes=s["votes"] if s else {}
            berth=max(votes,key=votes.get) if votes and max(votes.values())/s["n"]>=.8 else None
            stale=not last or (now-dt(last["ts"])).total_seconds()>300
            out[m]={"status":"STALE" if stale else v["status"],"port":s["port"] if s else None,"berth":berth,"voyage":v["voyage"],"predictions":v["predictions"],"last_fix_utc":last["ts"] if last else None,"last_sog":last.get("sog") if last else None,"last_distance_nm":last.get("distance") if last else None,"last_latitude":last.get("latitude") if last else None,"last_longitude":last.get("longitude") if last else None,"stop_observations":s["n"] if s else 0,"stop_span_min":round(minutes(s["first"]["ts"],s["last"]["ts"]),2) if s else None,"arrival_bracket":s["bracket"] if s else None,"nearest_berth":last["berth"] if last and last["candidate"] and not stale else None,"berth_confidence":"CONFIRMED" if berth and s and s["confirmed"] and not stale else "NEAREST_ONLY" if last and last["candidate"] and not stale else "UNKNOWN"}
        return out
