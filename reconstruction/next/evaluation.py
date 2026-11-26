"""Frozen predictions and AIS-reconstructed actuals, per voyage."""
from datetime import timedelta
from events import dt,minutes
from zoneinfo import ZoneInfo
WIB=ZoneInfo("Asia/Jakarta")
def delta(a,b):
    return round(minutes(a,b),3) if a and b else None
def evaluate(m,voyage,predictions,cycle=None):
    d=predictions.get("D0",{});a=predictions.get("A",{})
    origin=voyage["D0_utc"]
    # Reject mismatched predictions, including stale persisted results.
    if d.get("issue_utc")!=origin:d={}
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
        "trip_id":str(m)+"|"+dt(origin).isoformat(),"D0_utc":origin,"ATA":ata,"eta_base":eta_base,"eta_corrected":eta,
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

def record_trip(state,m,v,cycle=None,status=None):
    q=v.get("voyage")
    if not q:return
    row=evaluate(m,q,v.get("predictions",{}),cycle)
    key=row["trip_id"]
    journal=state.setdefault("trip_monitor",{})
    previous=journal.get(key,{})
    if previous.get("status")=="COMPLETED_QC_PASS":return
    last=v.get("last") or {}
    s=v.get("stop") or {}
    if q.get("A_utc") and s.get("port")==q["destination_port"]:
        b=berth_of(v)
        if b:row["arrival_berth"]=b
    row["departure_berth"]=row.get("arrival_berth",previous.get("arrival_berth"))
    row["shipname"]=v.get("shipname") or previous.get("shipname") or m
    row["sog"]=last.get("sog")
    row["last_fix_utc"]=last.get("ts")
    row["status"]=status or ("COMPLETED_QC_PASS" if cycle else v.get("status","ONGOING"))
    # Never erase already published values or confirmed berth evidence with a missing field.
    journal[key]={**previous,**{k:x for k,x in row.items() if x is not None}}

def with_vtt(row):
    out=dict(row)
    out['vtt_conventional_min']=delta(row.get('ATA'),row.get('etd_arrival'))
    out['vtt_real_min']=delta(row.get('ATA'),row.get('etd_real')) if row.get('status')=='COMPLETED_QC_PASS' else None
    for phase in ('early','conventional'):
        base=out.get('vtt_'+phase+'_base_min'); corrected=out.get('vtt_'+phase+'_min')
        out['vtt_'+phase+'_correction_min']=round(corrected-base,3) if base is not None and corrected is not None else None
    return out

def daily_rows(state,day):
    rows=list(state.get("trip_monitor",{}).values())
    def included(r):
        start=dt(r["D0_utc"]).astimezone(WIB).date()
        end=dt(r.get("etd_real") or r.get("last_fix_utc") or r["D0_utc"]).astimezone(WIB).date()
        return start<=day<=end
    return sorted((with_vtt(r) for r in rows if included(r)),key=lambda r:(dt(r["D0_utc"]),r["mmsi"]))

def active_trip_rows(state):
    """Public projection of the same stored rows used by daily monitoring."""
    journal=state.get("trip_monitor",{})
    result={}
    for m,v in state.get("vessels",{}).items():
        q=v.get("voyage")
        if not q:continue
        key=str(m)+"|"+dt(q["D0_utc"]).isoformat()
        row=journal.get(key)
        if row and row["status"] in ("SAILING","ARRIVAL_CANDIDATE","BERTHED"):
            result[m]=with_vtt(row)
    return result
