"""Bounded read-only recovery of a berth arrival from existing raw AIS.
Only called once per unlinked berth stay; no cache, file writes, or polling.
"""
import json
from datetime import timedelta
from trajectories import messages,normalize,WIB
from events import dt,minutes
MAX_BYTES=4*1024*1024
MAX_LOOKBACK_MIN=180

def find_arrival(ais,p):
    now=dt(p["ts"]);m=p["mmsi"];port=p["port"]
    points={};conflicts=set()
    for day in {now.date(),(now-timedelta(minutes=MAX_LOOKBACK_MIN)).date()}:
        path=ais.parent/"raw"/("ais_api_raw_"+day.strftime("%Y%m%d")+".jsonl")
        try:
            with path.open("rb") as f:
                size=f.seek(0,2);start=max(0,size-MAX_BYTES);f.seek(start)
                if start:f.readline()
                for line in f:
                    try:
                        e=json.loads(line)
                        if not isinstance(e,dict):continue
                        rx=e.get("received_at")
                        for r in messages(e.get("payload")):
                            if not isinstance(r,dict) or str(r.get("mmsi",r.get("immsi",""))).strip()!=m:continue
                            stamp=dt(r["timestamp"])
                            if not 0<=minutes(stamp,now)<=MAX_LOOKBACK_MIN:continue
                            x=normalize(r,rx,stamp.astimezone(WIB).date())
                            if not x:continue
                            try:cog=float(r.get("course",r.get("cog")))
                            except (ValueError,TypeError):cog=None
                            x["cog"]=cog if cog is not None and 0<=cog<360 else None
                            key=x["ts"];old=points.get(key)
                            if old and any(old[k]!=x[k] for k in ("lat","lon","sog")):conflicts.add(key)
                            else:points[key]=x
                    except (ValueError,TypeError,KeyError,OverflowError):continue
        except OSError:continue
    ordered=sorted((x for k,x in points.items() if k not in conflicts),key=lambda x:dt(x["ts"]))
    return first_stationary(ordered,p)

def first_stationary(ordered,p):
    # The latest observed berth run must connect to the live berth fix.
    last=p;first=None
    for x in reversed(ordered):
        gap=minutes(x["ts"],last["ts"])
        if gap<0:continue
        if x["candidate"] and x["port"]==p["port"]:
            if gap>12:return None
            first=x;last=x;continue
        # Require a preceding nonstationary observation, not another berth.
        if first and not x["candidate"] and x["sog"]>.8 and 0<gap<=10:
            return first
        return None
    return None
