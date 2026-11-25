"""Read-only daily trajectory inspection, independent of live ML and stock ledger."""
import csv,json,math,threading,time,logging,os
from pathlib import Path
from datetime import datetime,date,timedelta,timezone
from zoneinfo import ZoneInfo
from collections import defaultdict
from events import MMSI,PORTS,dt,nm,Tracker,minutes
WIB=ZoneInfo("Asia/Jakarta")
MAX_GAP=10
_lock=threading.Lock()
_cache={}
def messages(payload):
    if isinstance(payload,list):return payload
    if isinstance(payload,dict):
        for k in ("data","results","ships","vessels","items"):
            if isinstance(payload.get(k),list):return payload[k]
        return [payload]
    return []
def records(ais,day):
    # Fix date, not reception date, defines the requested WIB day.
    archive=Path(os.getenv("BIMA2_TRAJECTORY_CACHE","/opt/BIMA2_NEXT/data/trajectory_cache"))
    raw=ais.parent/"raw"
    paths=[raw/("ais_api_raw_"+(day+timedelta(days=i)).strftime("%Y%m%d")+".jsonl") for i in (-1,0,1)]
    paths=[p for p in paths if p.is_file()]
    # Include archived reception dates for late fixes; deduplication follows.
    archives=[archive/("AIS_RAW_"+(day+timedelta(days=i)).isoformat()+".csv") for i in (0,1)]
    archives=[p for p in archives if p.is_file()]
    for p in archives:
        try: f=p.open(encoding="utf-8-sig",newline="")
        except OSError:
            logging.warning("Trajectory cache unreadable: %s",p.name);continue
        with f:
            for r in csv.DictReader(f):yield r,r.get("received_at_original")
    for p in paths:
        try: f=p.open(encoding="utf-8")
        except OSError:
            logging.warning("Trajectory source unreadable: %s",p.name);continue
        with f:
            for line in f:
                try:e=json.loads(line)
                except ValueError:continue # concurrent partial last line
                if not isinstance(e,dict):continue
                for r in messages(e.get("payload")):
                    if isinstance(r,dict):yield r,e.get("received_at")
def normalize(r,received,day):
    try:
        m=str(r.get("mmsi",r.get("immsi",""))).strip()
        if m not in MMSI:return None
        raw=json.loads(r.get("raw_json") or "{}")
        if not isinstance(raw,dict):return None
        value=r.get("update_at") or r.get("ais_update_at") or raw.get("update_at")
        if not value:return None
        stamp=datetime.fromisoformat(str(value).replace("Z","+00:00"))
        # Provider's naive update_at is WIB, as shown by offset-aware timestamp and live receiver.
        if stamp.tzinfo is None:stamp=stamp.replace(tzinfo=WIB)
        stamp=stamp.astimezone(timezone.utc)
        rx=dt(received)
        if stamp.astimezone(WIB).date()!=day or stamp>rx:return None
        lat=float(r.get("lat",r.get("latitude")));lon=float(r.get("lon",r.get("longitude")));sog=float(r.get("sog") if r.get("sog") not in ("",None) else r.get("speed") if r.get("speed") not in ("",None) else raw.get("speed"))
        if not (1.2<=lat<=1.6 and 101.95<=lon<=102.4 and 0<=sog<=40):return None
        ds=sorted((nm(lat,lon,*xy),p,b) for p,bs in PORTS.items() for b,xy in bs.items())
        dist,p,b=ds[0]
        return dict(mmsi=m,shipname=str(r.get("shipname") or m),ts=stamp.isoformat(),received=rx.isoformat(),lat=lat,lon=lon,sog=sog,cog=None,distance=dist,port=p,berth=b,candidate=sog<=.8 and dist<=.15,ambiguous=ds[1][0]<=.15 or (ds[1][0]-dist)*1852<50)
    except (ValueError,TypeError,KeyError,OverflowError):return None
def split_trips(points):
    # Use research stop confirmation to identify D0/A; never connect over gaps.
    tracker=Tracker()
    out=[];leg=[];origin=None;dest=None
    def finish(status):
        nonlocal leg,origin,dest
        if leg:
            first,last=leg[0],leg[-1]
            out.append(dict(trip_id=first["mmsi"]+"_"+str(len(out)+1),mmsi=first["mmsi"],shipname=last["shipname"],origin_port=origin,destination_port=dest,start_time=first["ts"],end_time=last["ts"],point_count=len(leg),duration_min=round(minutes(first["ts"],last["ts"]),2),status=status,points=[dict(ts=p["ts"],lat=p["lat"],lon=p["lon"],sog=p["sog"]) for p in leg]))
        leg=[];origin=None;dest=None
    prev=None
    for p in points:
        if prev and minutes(prev["ts"],p["ts"])> (12 if prev["candidate"] and p["candidate"] and prev["port"]==p["port"] else MAX_GAP):
            finish("AIS_GAP")
        events=tracker.process(p)
        for e in events:
            if e["phase"]=="D0":
                finish("PARTIAL")
                origin=e["features"]["origin_port"];dest=e["features"]["destination_port"]
            elif e["phase"]=="A":
                # Cut at first arrival fix, not at confirmation time.
                arrival=e["issue_utc"]
                leg=[x for x in leg if dt(x["ts"])<=dt(arrival)]
                if origin and dest:finish("COMPLETE")
        # A moving fragment without known D0 is still useful, not a validated trip.
        if origin or not p["candidate"] or leg:
            leg.append(p)
        prev=p
    finish("IN_PROGRESS" if origin else "PARTIAL")
    return out
def daily(ais,day):
    key=(str(ais),day.isoformat())
    with _lock:
        now=time.monotonic()
        if key in _cache and now-_cache[key][0]<60:return _cache[key][1]
        groups=defaultdict(dict);conflicts=set()
        for r,rx in records(ais,day):
            p=normalize(r,rx,day)
            if not p:continue
            k=(p["mmsi"],p["ts"])
            old=groups[p["mmsi"]].get(p["ts"])
            if old and (old["lat"],old["lon"],old["sog"])!=(p["lat"],p["lon"],p["sog"]):
                conflicts.add(k)
            elif not old or p["received"]<old["received"]:
                groups[p["mmsi"]][p["ts"]]=p
        trips=[];count=0
        for m,group in sorted(groups.items()):
            pts=sorted((p for ts,p in group.items() if (m,ts) not in conflicts),key=lambda x:dt(x["ts"]))
            count+=len(pts);trips.extend(split_trips(pts))
        result={"date":day.isoformat(),"timezone":"Asia/Jakarta","point_count":count,"conflicting_fixes_excluded":len(conflicts),"trips":trips,"status":"AVAILABLE" if count else "NO_LOCAL_AIS","generated_at":datetime.now(timezone.utc).isoformat()}
        _cache.clear();_cache[key]=(now,result)
        return result
