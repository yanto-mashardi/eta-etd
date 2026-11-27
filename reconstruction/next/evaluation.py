"""Frozen predictions and AIS-reconstructed actuals, per voyage."""
from datetime import timedelta
import json
from events import dt,minutes
from zoneinfo import ZoneInfo
WIB=ZoneInfo("Asia/Jakarta")
def delta(a,b):
    return round(minutes(a,b),3) if a and b else None
def trip_key(m,q):
    if q.get("D0_utc"):return str(m)+"|"+dt(q["D0_utc"]).isoformat()
    return str(m)+"|A|"+dt(q.get("A_utc") or q["ATA"]).isoformat()
def row_start(r):return r.get("D0_utc") or r["ATA"]
def evaluate(m,voyage,predictions,cycle=None):
    d=predictions.get("D0",{});a=predictions.get("A",{})
    origin=voyage.get("D0_utc")
    # Reject mismatched predictions, including stale persisted results.
    if not origin or d.get("issue_utc")!=origin:d={}
    if a.get("issue_utc")!=voyage.get("A_utc"):a={}
    base=d.get("eta_components",{}).get("baseline_min")
    eta_base=(dt(origin)+timedelta(minutes=base)).isoformat() if base is not None else None
    eta=d.get("eta");early=d.get("etd");conv=a.get("etd")
    ata=voyage.get("A_utc")
    real=cycle.get("D1_utc") if cycle else None
    issued=d.get("published_at") if early else None
    arrived=a.get("published_at") if conv else None
    # Only predictions actually published before the observed target qualify.
    early_ok=bool(real and issued and dt(issued)<dt(real))
    conv_ok=bool(real and arrived and dt(arrived)<dt(real))
    comparable=bool(issued and arrived and dt(issued)<=dt(arrived))
    return {"mmsi":m,"origin_port":voyage["origin_port"],"destination_port":voyage["destination_port"],
        "trip_id":trip_key(m,voyage),"D0_utc":origin,"ATA":ata,"eta_base":eta_base,"eta_corrected":eta,
        "eta_correction_min":delta(eta_base,eta),"vtt_early_base_min":d.get("vtt_components",{}).get("baseline_min"),"vtt_conventional_base_min":a.get("vtt_components",{}).get("baseline_min"),"vtt_early_min":d.get("vtt_components",{}).get("duration_min"),"etd_early":early,"etd_arrival":conv,"etd_real":real,
        "early_error_min":delta(real,early) if early_ok else None,
        "arrival_error_min":delta(real,conv) if conv_ok else None,
        "early_abs_error_min":abs(delta(real,early)) if early_ok else None,
        "arrival_abs_error_min":abs(delta(real,conv)) if conv_ok else None,
        "early_published_at":issued,"arrival_published_at":arrived,
        "lead_advantage_min":delta(issued,arrived) if comparable else None,
        "lead_to_departure_min":delta(issued,real) if early_ok else None,
        "release_early":d.get("release"),"release_arrival":a.get("release"),
        "prediction_status_early":d.get("status"),"prediction_status_arrival":a.get("status"),
        "prediction_error_early":d.get("error"),"prediction_error_arrival":a.get("error"),
        "status":"COMPLETED_QC_PASS" if cycle else "ONGOING"}

def berth_of(v):
    s=v.get("stop") or {}
    votes=s.get("votes") or {}
    return max(votes,key=votes.get) if s.get("confirmed") and votes and s.get("n") and max(votes.values())/s["n"]>=.8 else None

def record_trip(state,m,v,cycle=None,status=None,observed_exit=None):
    q=v.get("voyage")
    if not q:return
    row=evaluate(m,q,v.get("predictions",{}),cycle)
    key=row["trip_id"]
    journal=state.setdefault("trip_monitor",{})
    previous=journal.get(key,{})
    if previous.get("status") in ("COMPLETED_QC_PASS","COMPLETED_QC_FAIL"):return
    last=v.get("last") or {}
    s=v.get("stop") or {}
    if q.get("A_utc") and s.get("port")==q["destination_port"]:
        confirmed=berth_of(v)
        fix=s.get("last") or last
        nearest=fix.get("berth") if fix.get("candidate") and fix.get("port")==q["destination_port"] and fix.get("berth") else None
        b=nearest or confirmed
        if b:
            row["arrival_berth"]=b
            row["berth_quality"]="CONFIRMED" if b==confirmed else "NEAREST"
    row["departure_berth"]=row.get("arrival_berth") or previous.get("arrival_berth") or previous.get("departure_berth")
    row["shipname"]=v.get("shipname") or previous.get("shipname") or m
    row["sog"]=last.get("sog")
    row["last_fix_utc"]=last.get("ts")
    if observed_exit:row["etd_real"]=observed_exit
    row["event_quality"]="QC_PASS" if cycle else "QC_FAIL" if observed_exit else "ARRIVAL_ONLY" if not q.get("D0_utc") else "PENDING"
    row["event_qc_flags"]="|".join(q.get("qc_flags",[]))
    row["publication_protocol"]=q.get("publication_protocol","LEGACY_CONFIRMATION")
    if not q.get("D0_utc"):row["record_type"]="ARRIVAL_ONLY"
    if q.get("event_evidence"):
        proof=json.loads(previous.get("event_evidence_json") or "{}")
        proof.update(q["event_evidence"])
        row["event_evidence_json"]=json.dumps(proof,sort_keys=True,allow_nan=False)
    for phase,suffix in (("D0","early"),("A","arrival")):
        pred=v.get("predictions",{}).get(phase,{})
        if pred.get("features") is not None:
            row["features_"+suffix+"_json"]=json.dumps(pred["features"],sort_keys=True,allow_nan=False)
    row["last_source_fix_utc"]=last.get("source_fix_utc",last.get("ts"))
    row["last_clock_basis"]=last.get("clock_basis","AIS_UPDATE")
    row["status"]=status or ("COMPLETED_QC_PASS" if cycle else v.get("status","ONGOING"))
    # Never erase already published values or confirmed berth evidence with a missing field.
    merged={**previous,**{k:x for k,x in row.items() if x is not None}}
    if not q.get("D0_utc"):merged["D0_utc"]=None
    # Compute after merging frozen predictions and observed D1, including recovered trips.
    journal[key]=with_vtt(merged)

def timing_comparison(actual,estimate,published):
    if not (actual and estimate and published) or dt(published)>=dt(actual):return None
    return (dt(estimate)-dt(actual)).total_seconds()/60

def with_vtt(row):
    out=dict(row)
    out['eta_error_min']=timing_comparison(row.get('ATA'),row.get('eta_corrected'),row.get('early_published_at'))
    status=row.get("status","")
    real=row.get("etd_real") if status in ("COMPLETED_QC_PASS","COMPLETED_QC_FAIL") else None
    ata=row.get("ATA")
    # An observed departure before its arrival cannot be evaluated as a turnaround.
    invalid=bool(real and ata and dt(real)<dt(ata))
    if invalid:real=None
    early_pub=row.get("early_published_at") if row.get("etd_early") else None
    conv_pub=row.get("arrival_published_at") if row.get("etd_arrival") else None
    for prefix,estimate,published in (("early",row.get("etd_early"),early_pub),("arrival",row.get("etd_arrival"),conv_pub)):
        error=timing_comparison(real,estimate,published)
        out[prefix+"_error_min"]=round(error,3) if error is not None else None
        out[prefix+"_abs_error_min"]=round(abs(error),3) if error is not None else None
    out["lead_advantage_min"]=delta(early_pub,conv_pub) if early_pub and conv_pub and dt(early_pub)<=dt(conv_pub) else None
    out["lead_to_departure_min"]=delta(early_pub,real) if early_pub and real and dt(early_pub)<dt(real) else None
    out["evaluation_scope"]="INVALID_ACTUAL" if invalid else "RESEARCH_QC_PASS" if real and status=="COMPLETED_QC_PASS" and row.get("D0_utc") and ata else "OPERATIONAL_QC_FAIL" if status=="COMPLETED_QC_FAIL" else "ARRIVAL_ONLY" if row.get("record_type")=="ARRIVAL_ONLY" else "INCOMPLETE" if status.startswith("INCOMPLETE_") else "PENDING"
    if not out.get("departure_berth") and out.get("arrival_berth"):out["departure_berth"]=out["arrival_berth"]
    if out.get("arrival_berth") and not out.get("berth_quality"):out["berth_quality"]="CONFIRMED"
    out['vtt_conventional_min']=delta(ata,row.get('etd_arrival'))
    out['vtt_real_min']=delta(ata,real)
    for phase in ('early','conventional'):
        base=out.get('vtt_'+phase+'_base_min'); corrected=out.get('vtt_'+phase+'_min')
        out['vtt_'+phase+'_correction_min']=round(corrected-base,3) if base is not None and corrected is not None else None
    return out

def daily_rows(state,day):
    rows=list(state.get("trip_monitor",{}).values())
    def included(r):
        start=dt(row_start(r)).astimezone(WIB).date()
        end=dt(r.get("etd_real") or r.get("last_fix_utc") or row_start(r)).astimezone(WIB).date()
        return start<=day<=end
    return sorted((with_vtt(r) for r in rows if included(r)),key=lambda r:(dt(row_start(r)),r["mmsi"]))

def active_trip_rows(state):
    """Public projection of the same stored rows used by daily monitoring."""
    journal=state.get("trip_monitor",{})
    result={}
    for m,v in state.get("vessels",{}).items():
        q=v.get("voyage")
        if not q:continue
        key=trip_key(m,q)
        row=journal.get(key)
        if row and row["status"] in ("SAILING","ARRIVAL_CANDIDATE","BERTHED","DEPARTURE_PENDING","BERTH_MANEUVER"):
            result[m]=with_vtt(row)
    return result

def operational_boards(rows,active,states):
    """One active voyage per vessel. History remains exclusively in Inspection.
    D0 is observed departure; matching preceding D1 supplies comparison errors.
    A is observed arrival, not a new prediction.
    """
    previous={}
    for r in rows:
        if r.get("etd_real") and r.get("status") in ("COMPLETED_QC_PASS","COMPLETED_QC_FAIL"):
            previous[(str(r["mmsi"]),r["destination_port"],dt(r["etd_real"]))]=r
    arrivals=[];departures=[]
    def item(r,port,other,value,kind,color,status,berth=None,quality="FRESH"):
        return dict(mmsi=r["mmsi"],shipname=r.get("shipname") or r["mmsi"],trip_id=r["trip_id"],board_port=port,other_port=other,board_time=value,board_kind=kind,board_color=color,board_status=status,board_berth=berth,ais_quality=quality)
    for m,r in active.items():
        state=states.get(m,{})
        stale=state.get("status")=="STALE"
        quality="STALE" if stale else "FRESH"
        origin,dest=r["origin_port"],r["destination_port"]
        if r.get("ATA"):
            ata=r["ATA"]
            error=with_vtt(r)["eta_error_min"]
            color=("late" if error<0 else "actual") if error is not None else "unknown"
            berth=r.get("departure_berth") or state.get("berth") or state.get("nearest_berth")
            arrivals.append(item(r,dest,origin,ata,"REAL",color,"TIBA",berth,quality))
            departures.append(item(r,dest,origin,r.get("etd_arrival"),"ESTIMATE","berthed","SANDAR",berth,quality))
        elif r["status"] in ("SAILING","ARRIVAL_CANDIDATE"):
            prior=previous.get((str(m),origin,dt(r["D0_utc"])),{})
            errors=[timing_comparison(prior.get("etd_real"),prior.get(k),prior.get(p)) for k,p in (("etd_early","early_published_at"),("etd_arrival","arrival_published_at"))]
            errors=[e for e in errors if e is not None]
            color="late" if any(e<0 for e in errors) else "actual" if errors else "unknown"
            departures.append(item(r,origin,dest,r["D0_utc"],"REAL",color,"BERANGKAT",prior.get("departure_berth"),quality))
            arrivals.append(item(r,dest,origin,r.get("eta_corrected"),"ESTIMATE","incoming","BERLAYAR",quality=quality))
            departures.append(item(r,dest,origin,r.get("etd_early"),"ESTIMATE","incoming","MENUJU TERMINAL",quality=quality))
    def sort_key(r):
        return (r["board_port"],r["board_kind"]=="REAL",dt(r["board_time"]).timestamp() if r["board_time"] else float("inf"),str(r["mmsi"]))
    return {"arrivals":sorted(arrivals,key=sort_key),"departures":sorted(departures,key=sort_key)}

from events import classify,dt,nm,PORTS

def publish(ais_rows,ais_status,now,journal,active,states,classified=None):
    effective={m:dict(s,status=s.get("last_status",s.get("status"))) if s.get("status")=="STALE" else s for m,s in states.items()}
    base=operational_boards(journal,active,effective)
    result={"arrivals":[],"departures":[],"vessels":{},"issues":[]}
    observed={str(r.get("mmsi","")).strip():r for r in ais_rows if str(r.get("mmsi","")).strip()}
    for m in sorted(set(observed)|set(states)):
        s=effective.get(m,{})
        raw=observed.get(m,{"mmsi":m,"shipname":s.get("shipname") or m})
        r=active.get(m,{})
        v={"status":"AIS_TIDAK_VALID","berth":None,"port":None,"distances":{},"quality":raw.get("live_ais_quality"),"sync":None}
        result["vessels"][m]=v
        def issue(reason):
            v["sync"]=reason
            result["issues"].append({"mmsi":m,"shipname":raw.get("shipname") or m,"reason":reason})
        stale=ais_status!="AVAILABLE" or raw.get("live_ais_quality")!="FRESH"
        if stale:
            # Use the last accepted observation; never classify stale data as a new event.
            p=s.get("last_observation")
            if not p:continue
            v["quality"]="STALE"
            issue("AIS_LAST_KNOWN")
        else:
            if classified is not None:
                p=classified.get(m)
                if not p:continue
            else:
                try:p=classify(raw,now)
                except (ValueError,KeyError,TypeError,OverflowError):continue
        lat,lon=(p.get("latitude"),p.get("longitude")) if stale else (float(raw["latitude"]),float(raw["longitude"]))
        distances={port:min(nm(lat,lon,*xy) for xy in bs.values()) for port,bs in PORTS.items()} if lat is not None and lon is not None else {}
        v.update(sog=p["sog"],fix_utc=p.get("source_fix_utc",p["ts"]),distances=distances)
        if p["candidate"]:
            v.update(status="DI AREA DERMAGA",port=p["port"],berth=p["berth"])
        else:
            v["status"]="BERGERAK" if p["sog"]>.8 else "BERHENTI DI LUAR DERMAGA"
        same=bool(s.get("source_fix_utc",s.get("last_fix_utc")) and dt(s.get("source_fix_utc",s.get("last_fix_utc")))==dt(p["ts"]))
        if not stale and same and s.get("last_sog") is not None and (abs(s["last_sog"]-p["sog"])>1e-6 or abs(s.get("last_distance_nm",p["distance"])-p["distance"])>1e-6 or s.get("last_latitude") is not None and (abs(s["last_latitude"]-lat)>1e-7 or abs(s["last_longitude"]-lon)>1e-7)):
            issue("AIS_TIMESTAMP_CONFLICT")
        elif not stale and not same:
            issue("EVENT_FIX_PENDING")
        rows={k:[dict(x) for x in base[k] if str(x["mmsi"])==m] for k in ("arrivals","departures")}
        def pending(port,status):
            other=next(x for x in PORTS if x!=port)
            result["departures"].append(dict(mmsi=m,shipname=raw.get("shipname") or m,trip_id=r.get("trip_id"),board_port=port,other_port=other,board_time=None,board_kind="ESTIMATE",board_color="unknown",board_status=status,board_berth=v["berth"] if v["port"]==port else None,ais_quality="STALE" if stale else "FRESH"))
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
                    issue("ARRIVAL_NOT_OBSERVED" if s.get("status")=="BERTHED" else "NO_ACTIVE_TRIP")
                pending(p["port"],v["status"])
                continue
        elif r.get("ATA") and s.get("status")=="BERTH_MANEUVER" and p["port"]==r["destination_port"] and p["distance"]<=.15:
            # The same journal record remains active until an actual berth-area exit.
            v["status"]="MANUVER DERMAGA"
            for x in rows["departures"]:x["board_status"]=v["status"]
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
        for k in rows:
            for x in rows[k]:x["ais_quality"]="STALE" if stale else "FRESH"
            result[k].extend(rows[k])
    return result
