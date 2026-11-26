"""Frozen predictions and AIS-reconstructed actuals, per voyage."""
from datetime import timedelta
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
        b=berth_of(v)
        if b:row["arrival_berth"]=b
    row["departure_berth"]=row.get("arrival_berth",previous.get("arrival_berth"))
    row["shipname"]=v.get("shipname") or previous.get("shipname") or m
    row["sog"]=last.get("sog")
    row["last_fix_utc"]=last.get("ts")
    if observed_exit:row["etd_real"]=observed_exit
    row["event_quality"]="QC_PASS" if cycle else "QC_FAIL" if observed_exit else "ARRIVAL_ONLY" if not q.get("D0_utc") else "PENDING"
    row["event_qc_flags"]="|".join(q.get("qc_flags",[]))
    row["publication_protocol"]=q.get("publication_protocol","LEGACY_CONFIRMATION")
    if not q.get("D0_utc"):row["record_type"]="ARRIVAL_ONLY"
    row["last_source_fix_utc"]=last.get("source_fix_utc",last.get("ts"))
    row["last_clock_basis"]=last.get("clock_basis","AIS_UPDATE")
    row["status"]=status or ("COMPLETED_QC_PASS" if cycle else v.get("status","ONGOING"))
    # Never erase already published values or confirmed berth evidence with a missing field.
    journal[key]={**previous,**{k:x for k,x in row.items() if x is not None}}

def timing_comparison(actual,estimate,published):
    if not (actual and estimate and published) or dt(published)>=dt(actual):return None
    return (dt(estimate)-dt(actual)).total_seconds()/60

def with_vtt(row):
    out=dict(row)
    out['eta_error_min']=timing_comparison(row.get('ATA'),row.get('eta_corrected'),row.get('early_published_at'))
    out['vtt_conventional_min']=delta(row.get('ATA'),row.get('etd_arrival'))
    out['vtt_real_min']=delta(row.get('ATA'),row.get('etd_real')) if row.get('status') in ('COMPLETED_QC_PASS','COMPLETED_QC_FAIL') else None
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
        if row and row["status"] in ("SAILING","ARRIVAL_CANDIDATE","BERTHED","DEPARTURE_PENDING"):
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
