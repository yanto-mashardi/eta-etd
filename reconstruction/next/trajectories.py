"""Read-only daily trajectory inspection, independent of live ML and stock ledger."""
import csv,json,math,threading,time,logging,os
from pathlib import Path
from datetime import datetime,date,timedelta,timezone
from zoneinfo import ZoneInfo
from collections import defaultdict,Counter
from events import MMSI,PORTS,dt,geometry,minutes,canonical_mmsi
WIB=ZoneInfo("Asia/Jakarta")
MAX_GAP=10
_lock=threading.Lock()
_cache={}
CACHE_TTL=60
CACHE_MAX_POINTS=10000
def expire_cache():
    if not _lock.acquire(blocking=False):return
    try:
        if any(time.monotonic()-entry[0]>=CACHE_TTL for entry in _cache.values()):_cache.clear()
    finally:_lock.release()
def messages(payload):
    if isinstance(payload,list):return payload
    if isinstance(payload,dict):
        for k in ("data","results","ships","vessels","items"):
            if isinstance(payload.get(k),list):return payload[k]
        return [payload]
    return []
def records(ais,day):
    # Observation date, not reception or provider update date, defines WIB day.
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
def normalize(r,received,day,diagnostics=None):
    def reject(reason):
        if diagnostics is not None:diagnostics[reason]+=1
        return None
    try:
        m=canonical_mmsi(r.get("mmsi",r.get("immsi","")))
        if m not in MMSI:return reject('MMSI_OUTSIDE_SCOPE')
        raw=json.loads(r.get("raw_json") or "{}")
        if not isinstance(raw,dict):return reject('RAW_NOT_OBJECT')
        value=r.get("timestamp") or raw.get("timestamp")
        # Observation timestamp is distinct from the provider update/age field.
        # Do not use update_at as observation identity.
        if not value:return reject('MISSING_TIMESTAMP')
        stamp=datetime.fromisoformat(str(value).replace("Z","+00:00"))
        if stamp.tzinfo is None:return reject('NAIVE_TIMESTAMP')
        stamp=stamp.astimezone(timezone.utc)
        rx=dt(received)
        if stamp.astimezone(WIB).date()!=day:return reject('OTHER_OBSERVATION_DAY')
        if stamp>rx:return reject('FUTURE_VS_RECEIPT')
        lat=float(r.get("lat",r.get("latitude")));lon=float(r.get("lon",r.get("longitude")));sog=float(r.get("sog") if r.get("sog") not in ("",None) else r.get("speed") if r.get("speed") not in ("",None) else raw.get("speed"))
        if not (1.2<=lat<=1.6 and 101.95<=lon<=102.4 and 0<=sog<=40):return reject('POSITION_OR_SPEED_QC')
        # Restrict visualization to crossing corridor, excluding unrelated vessel locations.
        if not (1.35<=lat<=1.48 and 102.10<=lon<=102.19):return reject('OUTSIDE_PLOT_CORRIDOR')
        source=r.get("ais_update_at") or r.get("update_at") or raw.get("update_at") or raw.get("ais_update_at")
        try:source=dt(source).isoformat()
        except (ValueError,TypeError):source=None
        return dict(mmsi=m,reported_mmsi=str(r.get("reported_mmsi") or r.get("mmsi",r.get("immsi",""))),shipname=str(r.get("shipname") or m),ts=stamp.isoformat(),received=rx.isoformat(),source_fix_utc=source,observation_utc=stamp.isoformat(),clock_basis="HISTORICAL_OBSERVATION",lat=lat,lon=lon,latitude=lat,longitude=lon,sog=sog,cog=None,**geometry(lat,lon,sog))
    except (ValueError,TypeError,KeyError,OverflowError):return reject('INVALID_FIELD')
def split_trips(points,journal=()):
    """Associate observations with stored journal intervals, never infer a second D0/A/D1."""
    rows=sorted((r for r in journal if r.get("D0_utc") or r.get("ATA")),key=lambda r:dt(r.get("D0_utc") or r["ATA"]))
    out=[];leg=[];current=None;prev=None
    def association(p):
        now=dt(p["ts"]);matches=[]
        for r in rows:
            start=dt(r.get("D0_utc") or r["ATA"])
            end=r.get("etd_real") or (r.get("last_fix_utc") if str(r.get("status","")).startswith("INCOMPLETE_") else None)
            if start<=now and (not end or now<dt(end)):matches.append(r)
        if not matches:return (None,"AT_BERTH" if p["candidate"] else "PARTIAL",None,None)
        r=matches[-1]
        if r.get("ATA") and now>=dt(r["ATA"]):
            return (r["trip_id"],"AT_BERTH" if p["candidate"] else "BERTH_INTERVAL",r.get("destination_port"),None)
        return (r["trip_id"],"JOURNAL_LEG" if r.get("ATA") else "IN_PROGRESS",r.get("origin_port"),r.get("destination_port"))
    def finish(status=None):
        nonlocal leg
        if not leg:return
        first,last=leg[0],leg[-1]
        link,kind,origin,dest=current
        out.append(dict(trip_id=first["mmsi"]+"_"+str(len(out)+1),journal_trip_id=link,mmsi=first["mmsi"],shipname=last["shipname"],origin_port=origin,destination_port=dest,start_time=first["ts"],end_time=last["ts"],point_count=len(leg),duration_min=round(minutes(first["ts"],last["ts"]),2),status=status or kind,points=[dict(ts=z["ts"],lat=z["lat"],lon=z["lon"],sog=z["sog"]) for z in leg]))
        leg=[]
    for p in points:
        key=association(p)
        gap=prev and minutes(prev["ts"],p["ts"])>(12 if prev["candidate"] and p["candidate"] and prev["port"]==p["port"] else MAX_GAP)
        if gap:finish("AIS_GAP")
        elif current is not None and key!=current:finish()
        current=key;leg.append(p);prev=p
    finish()
    return out
def daily(ais,day,journal=()):
    journal=tuple(journal)
    key=(str(ais),day.isoformat(),tuple(sorted((r["trip_id"],r.get("D0_utc"),r.get("ATA"),r.get("etd_real"),r.get("status"),r.get("last_fix_utc") if str(r.get("status","")).startswith("INCOMPLETE_") else None) for r in journal)))
    with _lock:
        now=time.monotonic()
        if key in _cache and now-_cache[key][0]<CACHE_TTL:return _cache[key][1]
        _cache.clear()
        groups=defaultdict(dict);conflicts=set();diagnostics=defaultdict(Counter);seen_names={}
        for r,rx in records(ais,day):
            m=canonical_mmsi(r.get('mmsi',r.get('immsi','')))
            if m not in MMSI:continue
            diagnostics[m]['SOURCE_RECORDS']+=1
            if r.get('shipname'):seen_names[m]=r['shipname']
            p=normalize(r,rx,day,diagnostics[m])
            if not p:continue
            diagnostics[m]['NORMALIZED_RECORDS']+=1
            k=(p["mmsi"],p["ts"])
            old=groups[p["mmsi"]].get(p["ts"])
            if old and (old["lat"],old["lon"],old["sog"])!=(p["lat"],p["lon"],p["sog"]):
                conflicts.add(k)
            elif not old or p["received"]<old["received"]:
                groups[p["mmsi"]][p["ts"]]=p
        trips=[];count=0;vessel_counts=[]
        for m in sorted(MMSI):
            group=groups.get(m,{})
            pts=sorted((p for ts,p in group.items() if (m,ts) not in conflicts),key=lambda x:dt(x["ts"]))
            count+=len(pts);segments=split_trips(pts,[r for r in journal if str(r.get('mmsi'))==m]);trips.extend(segments)
            vessel_counts.append({"mmsi":m,"shipname":pts[-1]["shipname"] if pts else seen_names.get(m,m),"accepted_points":len(pts),"conflicts":sum(1 for k in conflicts if k[0]==m),"segments":len(segments),"diagnostics":dict(diagnostics[m])})
        result={"date":day.isoformat(),"timezone":"Asia/Jakarta","timestamp_basis":"provider_timestamp","segment_basis":"journal_intervals","point_count":count,"vessel_counts":vessel_counts,"conflicting_fixes_excluded":len(conflicts),"trips":trips,"status":"AVAILABLE" if count else "NO_LOCAL_AIS","generated_at":datetime.now(timezone.utc).isoformat()}
        if count<=CACHE_MAX_POINTS:_cache[key]=(time.monotonic(),result)
        return result
