"""Single backend publication projection, using latest AIS and the Inspection journal.
No inference, persistent state, or additional polling in this module.
"""
from events import classify,dt,nm,PORTS
from evaluation import operational_boards

def publish(ais_rows,ais_status,now,journal,active,states):
    base=operational_boards(journal,active,states)
    result={"arrivals":[],"departures":[],"vessels":{},"issues":[]}
    for raw in ais_rows:
        m=str(raw.get("mmsi","")).strip()
        if not m:continue
        s=states.get(m,{})
        r=active.get(m,{})
        v={"status":"AIS_TIDAK_VALID","berth":None,"port":None,"distances":{},"quality":raw.get("live_ais_quality"),"sync":None}
        result["vessels"][m]=v
        def issue(reason):
            v["sync"]=reason
            result["issues"].append({"mmsi":m,"shipname":raw.get("shipname") or m,"reason":reason})
        try:
            if ais_status!="AVAILABLE" or raw.get("live_ais_quality")!="FRESH":continue
            p=classify(raw,now)
        except (ValueError,KeyError,TypeError,OverflowError):continue
        lat,lon=float(raw["latitude"]),float(raw["longitude"])
        v.update(sog=p["sog"],fix_utc=p["ts"],distances={port:min(nm(lat,lon,*xy) for xy in bs.values()) for port,bs in PORTS.items()})
        if p["candidate"]:
            v.update(status="DI AREA DERMAGA",port=p["port"],berth=p["berth"])
        else:
            v["status"]="BERGERAK" if p["sog"]>.8 else "BERHENTI DI LUAR DERMAGA"
        same=bool(s.get("source_fix_utc",s.get("last_fix_utc")) and dt(s.get("source_fix_utc",s.get("last_fix_utc")))==dt(p["ts"]))
        if same and s.get("last_sog") is not None and (abs(s["last_sog"]-p["sog"])>1e-6 or abs(s.get("last_distance_nm",p["distance"])-p["distance"])>1e-6 or s.get("last_latitude") is not None and (abs(s["last_latitude"]-lat)>1e-7 or abs(s["last_longitude"]-lon)>1e-7)):
            issue("AIS_TIMESTAMP_CONFLICT")
        elif not same:
            issue("EVENT_FIX_PENDING")
        rows={k:[dict(x) for x in base[k] if str(x["mmsi"])==m] for k in ("arrivals","departures")}
        def pending(port,status):
            other=next(x for x in PORTS if x!=port)
            result["departures"].append(dict(mmsi=m,shipname=raw.get("shipname") or m,trip_id=r.get("trip_id"),board_port=port,other_port=other,board_time=None,board_kind="ESTIMATE",board_color="unknown",board_status=status,board_berth=v["berth"] if v["port"]==port else None,ais_quality="FRESH"))
        if p["candidate"]:
            if r.get("ATA") and r.get("destination_port")==p["port"] and s.get("status")=="BERTHED" :
                v["status"]="SANDAR"
                for x in rows["departures"]:x["board_berth"]=v["berth"]
            elif r and not r.get("ATA") and r.get("destination_port")==p["port"] and v["sync"]!="AIS_TIMESTAMP_CONFLICT":
                v["status"]="MENUNGGU KONFIRMASI TIBA"
                for x in rows["arrivals"]:x["board_status"]=v["status"]
            else:
                if r:issue("AIS_EVENT_PHASE_CONFLICT")
                else:
                    if s.get("status")=="BERTHED" and s.get("port")==p["port"]:v["status"]="SANDAR"
                    issue("NO_ACTIVE_TRIP")
                pending(p["port"],v["status"])
                continue
        elif r.get("ATA"):
            issue("AIS_DEPARTURE_PENDING")
            pending(r["destination_port"],"MENUNGGU EVENT BERANGKAT")
            continue
        elif not r:
            issue("NO_ACTIVE_TRIP")
            continue
        elif p["sog"]<=.8:
            for x in rows["arrivals"]:x["board_status"]=v["status"]
            for x in rows["departures"]:
                if x["board_kind"]=="ESTIMATE":x["board_status"]=v["status"]
                else:x["board_status"]="BERANGKAT · BERHENTI"
            # Stationary outside a berth cannot establish destination arrival.
            # If still near the recorded origin, suspend destination estimates.
            if p["port"]==r["origin_port"] and p["distance"]<=.5:
                issue("STOPPED_NEAR_ORIGIN")
                rows["arrivals"]=[]
                rows["departures"]=[x for x in rows["departures"] if x["board_port"]==r["origin_port"]]
                for x in rows["departures"]:x["board_status"]=v["status"]
        for k in rows:result[k].extend(rows[k])
    return result
