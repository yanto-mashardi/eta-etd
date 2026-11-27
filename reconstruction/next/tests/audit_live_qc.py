"""Read-only, one-shot audit of live cycles and public projection; no service writes."""
import argparse,json,math
from datetime import datetime,timedelta
from pathlib import Path
from urllib.request import urlopen
from collections import Counter,defaultdict
from events import dt,minutes,canonical_mmsi
from trajectories import records,normalize,WIB

def same(a,b):
    if a is None or b is None:return a is b
    try:return dt(a)==dt(b)
    except (TypeError,ValueError):return False

def fmt(t):
    return dt(t).astimezone(WIB).isoformat(timespec="milliseconds") if t else None

def emit(label,x):
    print(label,json.dumps(x,ensure_ascii=False,sort_keys=True))

def board_checks(e):
    rows={r["trip_id"]:r for r in e.get("prediction_evaluation",[])}
    active=e.get("active_trip_predictions",{})
    prior={(str(r["mmsi"]),r.get("destination_port"),dt(r["etd_real"])):r for r in rows.values() if r.get("etd_real")}
    result=[]
    for m,r in active.items():
        j=rows.get(r["trip_id"])
        fields=("D0_utc","ATA","eta_base","eta_corrected","etd_early","etd_arrival","etd_real","release_early","release_arrival")
        diff=[k for k in fields if j and j.get(k)!=r.get(k)]
        result.append(dict(check="active_vs_inspection",mmsi=m,trip_id=r["trip_id"],result="MATCH" if j and not diff else "MISMATCH" if j else "NOT_IN_SELECTED_DAY",fields=diff))
    for key in ("arrival_board","departure_board"):
        for b in e.get(key,[]):
            r=rows.get(b.get("trip_id"));value=b.get("board_time");port=b.get("board_port")
            field=None
            if r:
                if key=="arrival_board" and port==r["destination_port"]:
                    field="ATA" if b["board_kind"]=="REAL" else "eta_corrected"
                elif key=="departure_board":
                    if b["board_kind"]=="REAL" and port==r["origin_port"]:field="D0_utc"
                    elif b["board_kind"]=="ESTIMATE" and port==r["destination_port"]:field="etd_arrival" if r.get("ATA") else "etd_early"
            expected=r.get(field) if field else None
            status="MATCH" if field and value and same(value,expected) else "MISMATCH" if value else "NOT_PUBLISHED"
            d=dict(check=key,mmsi=b["mmsi"],port=port,kind=b["board_kind"],trip_id=b.get("trip_id"),field=field,board=fmt(value),inspection=fmt(expected),result=status,ais_quality=b.get("ais_quality"))
            if field=="D0_utc" and value:
                prev=prior.get((str(b["mmsi"]),port,dt(value)))
                d["previous_D1"]="MATCH" if prev else "NO_MATCHING_PRIOR_IN_DAY"
                if prev:d["previous_trip_id"]=prev["trip_id"]
            result.append(d)
    return result

def metric_checks(r):
    d0,a,d1=(r.get(k) for k in ("D0_utc","ATA","etd_real"))
    if not d0 or not a or not d1:return None
    s,v=minutes(d0,a),minutes(a,d1)
    required="eta_base eta_corrected eta_correction_min vtt_early_base_min vtt_early_min vtt_early_correction_min etd_early early_published_at release_early arrival_berth vtt_conventional_base_min vtt_conventional_min vtt_conventional_correction_min etd_arrival arrival_published_at release_arrival vtt_real_min eta_error_min early_error_min arrival_error_min lead_advantage_min lead_to_departure_min".split()
    missing=[k for k in required if r.get(k) in (None,"")]
    diffs=[]
    def check(k,value):
        if r.get(k) is not None and abs(float(r[k])-value)>.005:diffs.append(k)
    def diff(k,x,y):
        if x and y:check(k,minutes(x,y))
    diff("eta_correction_min",r.get("eta_base"),r.get("eta_corrected"))
    diff("vtt_early_min",r.get("eta_corrected"),r.get("etd_early"))
    diff("vtt_conventional_min",a,r.get("etd_arrival"))
    check("vtt_real_min",v)
    for phase in ("early","conventional"):
        b=r.get("vtt_"+phase+"_base_min");p=r.get("vtt_"+phase+"_min")
        if b is not None and p is not None:check("vtt_"+phase+"_correction_min",p-b)
    temporal=[]
    ep,cp=r.get("early_published_at"),r.get("arrival_published_at")
    for k,actual,estimate,pub in (("eta_error_min",a,r.get("eta_corrected"),ep),("early_error_min",d1,r.get("etd_early"),ep),("arrival_error_min",d1,r.get("etd_arrival"),cp)):
        if pub and dt(pub)<dt(actual):
            diff(k,actual,estimate)
            if k!="eta_error_min" and estimate:check(k.replace("_error_min","_abs_error_min"),abs(minutes(actual,estimate)))
        else:temporal.append(k+":MISSING_OR_LATE_PUBLICATION")
    if ep and cp:
        if dt(ep)<=dt(cp):diff("lead_advantage_min",ep,cp)
        else:temporal.append("PUBLICATION_ORDER")
    if ep and dt(ep)<dt(d1):diff("lead_to_departure_min",ep,d1)
    if ep and dt(ep)<dt(d0):temporal.append("EARLY_BEFORE_D0")
    if cp and dt(cp)<dt(a):temporal.append("CONV_BEFORE_A")
    return dict(trip_id=r["trip_id"],mmsi=r["mmsi"],shipname=r.get("shipname"),route=r["origin_port"]+"-"+r["destination_port"],D0=fmt(d0),A=fmt(a),D1=fmt(d1),sailing_min=round(s,3),vtt_real_min=round(v,3),duration_qc=15<=s<=120 and 8<=v<=180,status=r["status"],flags=r.get("event_qc_flags"),missing=missing,metric_mismatch=diffs,temporal_issues=temporal,eta=fmt(r.get("eta_corrected")),early_etd=fmt(r.get("etd_early")),conv_etd=fmt(r.get("etd_arrival")),release_early=r.get("release_early"),release_arrival=r.get("release_arrival"),eta_error_min=r.get("eta_error_min"),early_error_min=r.get("early_error_min"),arrival_error_min=r.get("arrival_error_min"),lead_advantage_min=r.get("lead_advantage_min"),lead_to_departure_min=r.get("lead_to_departure_min"))

def raw_source(r):
    raw=json.loads(r.get("raw_json") or "{}")
    value=next((x for d in (r,raw) for k in ("ais_update_at","update_at","updated_at") if (x:=d.get(k))),None)
    if not value:return None,None,"MISSING"
    try:
        x=datetime.fromisoformat(str(value).replace("Z","+00:00"))
        basis="EXPLICIT_OFFSET"
        if x.tzinfo is None:x=x.replace(tzinfo=WIB);basis="ASSUMED_WIB_FROM_POLLER_DEFAULT"
        return x,str(value),basis
    except (TypeError,ValueError):return None,str(value),"INVALID"

def raw_evidence(ais,day,cycles):
    targets=defaultdict(list)
    for r in cycles:
        for phase,k in (("D0","D0_utc"),("A","ATA"),("D1","etd_real")):
            targets[str(r["mmsi"])].append(dict(trip_id=r["trip_id"],phase=phase,target=dt(r[k]),expected_port=r["origin_port"] if phase=="D0" else r["destination_port"],before=None,after=None,source_first=None,source_changed=False,source_count=0,source_best=None))
    if not targets:return
    for row,rx in records(ais,day):
        m=canonical_mmsi(row.get("mmsi",row.get("immsi","")))
        if m not in targets:continue
        p=normalize(row,rx,day)
        if not p:continue
        try:src,src_raw,basis=raw_source(row)
        except (TypeError,ValueError,AttributeError):src,src_raw,basis=None,None,"INVALID"
        obs=dt(p["ts"]);received=dt(p["received"])
        sig=(p["lat"],p["lon"],p["sog"])
        small=dict(observation=fmt(p["ts"]),source_raw=src_raw,source_basis=basis,source_lag_sec=round((obs-src).total_seconds(),3) if src else None,receipt_lag_sec=round((received-obs).total_seconds(),3),lat=p["lat"],lon=p["lon"],sog=p["sog"],port=p["port"],berth=p["berth"],distance_nm=round(p["distance"],5),stationary=p["candidate"])
        for t in targets[m]:
            delta=(obs-t["target"]).total_seconds()
            if -120<=delta<=0 and (t["before"] is None or delta>t["before"]["offset_sec"]):t["before"]={**small,"offset_sec":delta}
            if 0<=delta<=120 and (t["after"] is None or delta<t["after"]["offset_sec"]):t["after"]={**small,"offset_sec":delta}
            if src==t["target"]:
                t["source_count"]+=1
                if t["source_first"] is None:t["source_first"]=sig
                elif sig!=t["source_first"]:t["source_changed"]=True
                # Source timestamp is not unique when payload changes; retain closest observation only.
                if t["source_best"] is None or abs(delta)<abs(t["source_best"]["offset_sec"]):t["source_best"]={**small,"offset_sec":delta}
    for m,items in targets.items():
        for t in items:
            t.pop("source_first")
            t["target"]=fmt(t["target"])
            emit("EVENT_EVIDENCE",dict(mmsi=m,**t))

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--since",required=True)
    ap.add_argument("--api",default="http://127.0.0.1:8766/api/status")
    ap.add_argument("--ais",default="/opt/JAES_SIMULASI_BIMA2/data/01_DATA_SOURCE/AIS/realtime/ais_realtime.csv")
    args=ap.parse_args();since=dt(args.since);day=since.astimezone(WIB).date()
    with urlopen(args.api,timeout=15) as f:status=json.load(f)
    e=status["event_engine"];rows=e["prediction_evaluation"]
    if day!=datetime.now(WIB).date():ap.error("API snapshot audit is for current WIB day only")
    emit("SNAPSHOT",dict(api=args.api,at=datetime.now(WIB).isoformat(),since=fmt(since),model=status.get("models"),engine=e.get("status"),timestamp_field=e.get("timestamp_field"),rows=len(rows)))
    chosen=[r for r in rows if (r.get("D0_utc") or r.get("ATA")) and dt(r.get("D0_utc") or r["ATA"])>=since]
    complete=[r for r in chosen if all(r.get(k) and dt(r[k])>=since for k in ("D0_utc","ATA","etd_real"))]
    for r in chosen:
        out=metric_checks(r)
        if out:emit("CYCLE",out)
        else:emit("PARTIAL_OR_ACTIVE",dict(trip_id=r["trip_id"],mmsi=r["mmsi"],status=r["status"],D0=fmt(r.get("D0_utc")),A=fmt(r.get("ATA")),D1=fmt(r.get("etd_real")),flags=r.get("event_qc_flags"),prediction_status_early=r.get("prediction_status_early"),prediction_status_arrival=r.get("prediction_status_arrival")))
    emit("COHORT",dict(records=len(chosen),complete=len(complete),status_counts=Counter(r["status"] for r in chosen),complete_flags=Counter(flag for r in complete for flag in (r.get("event_qc_flags") or "").split("|") if flag)))
    for r in board_checks(e):emit("BOARD",r)
    print("=== RAW EVIDENCE: nearest observations and repeated source timestamps; not independent ground truth ===")
    raw_evidence(Path(args.ais),day,complete)
    print("AUDIT_FINISHED (read only)")
if __name__=="__main__":main()
