from __future__ import annotations
import json, math, time
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import joblib
import numpy as np
import pandas as pd
import yaml

TZ=ZoneInfo("Asia/Jakarta")
ROOT=Path(__file__).resolve().parents[2]
CONFIG_PATH=ROOT/"config/project_config.yaml"
CFG=yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}

AIS_JSON=ROOT/((CFG.get("ais") or {}).get("realtime_storage") or {}).get("current_state","data/01_DATA_SOURCE/AIS/realtime/ais_current_state.json")
AIS_CSV=ROOT/((CFG.get("ais") or {}).get("api") or {}).get("output_file","data/01_DATA_SOURCE/AIS/realtime/ais_realtime.csv")
CCTV_BENGKALIS=ROOT/((((CFG.get("cctv") or {}).get("terminals") or {}).get("BENGKALIS") or {}).get("state_file","data/01_DATA_SOURCE/CCTV/output/vehicle_state.json"))
CCTV_PAKNING=ROOT/((((CFG.get("cctv") or {}).get("terminals") or {}).get("PAKNING") or {}).get("state_file","data/01_DATA_SOURCE/CCTV/output/pakning/vehicle_state.json"))
OUT=ROOT/"outputs/realtime"
OUT.mkdir(parents=True,exist_ok=True)
HISTORY_5MIN=ROOT/((CFG.get("integration") or {}).get("research_history_5min","outputs/history/operation_state_5min.csv"))
HISTORY_TICK_MIN=int((CFG.get("integration") or {}).get("research_history_tick_minutes",5))
HIST_DEMAND_PROFILE=ROOT/((CFG.get("integration") or {}).get("historical_demand_profile","outputs/history/historical_demand_profile_5min.csv"))

ACTIVE_CFG=ROOT/((CFG.get("models") or {}).get("active_registry","config/registry/active_model_config.yaml"))
CAPACITY_CSV=ROOT/((CFG.get("vessels") or {}).get("capacity_master","config/vessel_capacity_realtime_v4.csv"))
ML1_DIR=ROOT/"models/ML1_ETA_CORRECTION/06_model_saved"
ML2_DIR=ROOT/"models/ML2_TURNAROUND_CORRECTION/06_model_saved"

QUEUE_LEDGER=ROOT/((CFG.get("queue") or {}).get("ledger","outputs/realtime/queue_service_state.json"))
QUEUE_EVENTS=ROOT/((CFG.get("queue") or {}).get("event_log","outputs/realtime/queue_service_events.jsonl"))
CAR_PCE_FACTOR=float((CFG.get("queue") or {}).get("car_pce",1.0))
MOTOR_PCE_FACTOR=float((CFG.get("queue") or {}).get("motorcycle_pce",0.25))
ML1_TARGET=(CFG.get("ml1") or {}).get("target_event") or {}
BERTH_RADIUS_NM=float(ML1_TARGET.get("berth_radius_nm",0.15))
BERTH_MAX_SOG=float(ML1_TARGET.get("max_sog_kn",0.8))
AIS_QC=(CFG.get("ais") or {}).get("quality_control") or {}
MAX_DATA_AGE_SECONDS=float(AIS_QC.get("max_data_age_seconds",300))
ALLOW_STALE_INFERENCE=bool(AIS_QC.get("allow_stale_for_inference",False))
RELIABILITY=(CFG.get("research") or {}).get("reliability_indicator") or {}
RELIABLE_SPEED_MIN=float(RELIABILITY.get("reliable_speed_min_kn",7.0))
RELIABLE_SPEED_MAX=float(RELIABILITY.get("reliable_speed_max_kn",9.0))
LOW_DEMAND_THRESHOLD=float((((CFG.get("ml2") or {}).get("behavioral_rule") or {}).get("low_demand_ratio_threshold",0.35)))

BERTHS={}
for port,item in (CFG.get("ports") or {}).items():
    for b in item.get("berths",[]):
        BERTHS[str(b["id"])]=(float(b["lat"]),float(b["lon"]))


def load_target_mmsi():
    """Operational MMSI whitelist from the single project_config.yaml."""
    try:
        values=(((CFG.get("ais") or {}).get("vessel_filter") or {}).get("mmsi_whitelist") or [])
        return {int(x) for x in values}
    except Exception:
        return set()

_MODEL_CACHE={}
CAPACITY={}

def now(): return datetime.now(TZ)
def iso(d): return d.isoformat(timespec="seconds")

def hav(a,b,c,d):
    R=3440.065
    p1,p2=math.radians(a),math.radians(c)
    dp,dl=math.radians(c-a),math.radians(d-b)
    x=math.sin(dp/2)**2+math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2*R*math.asin(math.sqrt(x))

def bearing(lat1,lon1,lat2,lon2):
    p1,p2=math.radians(lat1),math.radians(lat2)
    dl=math.radians(lon2-lon1)
    y=math.sin(dl)*math.cos(p2)
    x=math.cos(p1)*math.sin(p2)-math.sin(p1)*math.cos(p2)*math.cos(dl)
    return (math.degrees(math.atan2(y,x))+360)%360

def angle_error(a,b):
    return abs((float(a)-float(b)+180)%360-180)

def readj(path,default):
    try:return json.loads(path.read_text(encoding="utf-8"))
    except Exception:return default

def _int(v,default=0):
    try:return int(float(v or 0))
    except Exception:return default

def default_queue_ledger():
    return {
        "version":1,
        "updated_at":None,
        "ports":{
            "BENGKALIS":{"loaded_car_total":0,"loaded_motor_total":0,"departure_count":0,"last_departure_at":None,"last_departure_mmsi":None},
            "PAKNING":{"loaded_car_total":0,"loaded_motor_total":0,"departure_count":0,"last_departure_at":None,"last_departure_mmsi":None},
        },
        "vessels":{},
        "last_event":None,
    }

def load_queue_ledger():
    d=readj(QUEUE_LEDGER,{})
    base=default_queue_ledger()
    if isinstance(d,dict):
        base.update({k:v for k,v in d.items() if k not in ("ports","vessels")})
        if isinstance(d.get("ports"),dict):
            for port in ("BENGKALIS","PAKNING"):
                if isinstance(d["ports"].get(port),dict):
                    base["ports"][port].update(d["ports"][port])
        if isinstance(d.get("vessels"),dict):
            base["vessels"].update(d["vessels"])
    return base

def save_queue_ledger(ledger):
    ledger["updated_at"]=iso(now())
    tmp=QUEUE_LEDGER.with_suffix(".tmp")
    tmp.write_text(json.dumps(ledger,indent=2),encoding="utf-8")
    tmp.replace(QUEUE_LEDGER)

def effective_vehicle_state(raw,port,ledger):
    s=dict(raw or {})
    lp=(ledger.get("ports") or {}).get(port,{})
    loaded_car=_int(lp.get("loaded_car_total"))
    loaded_motor=_int(lp.get("loaded_motor_total"))
    car_in=_int(s.get("car_in_total"))
    motor_in=_int(s.get("motor_in_total"))
    s["loaded_car_total"]=loaded_car
    s["loaded_motor_total"]=loaded_motor
    s["car_queue_current"]=max(0,car_in-loaded_car)
    s["motor_queue_current"]=max(0,motor_in-loaded_motor)
    s["total_queue_current"]=s["car_queue_current"]+s["motor_queue_current"]
    s["service_departure_count"]=_int(lp.get("departure_count"))
    s["last_service_departure_at"]=lp.get("last_departure_at")
    s["last_service_departure_mmsi"]=lp.get("last_departure_mmsi")
    return s

def allocate_loading(car_queue,motor_queue,capacity_pce):
    car_queue=max(0,_int(car_queue)); motor_queue=max(0,_int(motor_queue))
    try:capacity=max(0.0,float(capacity_pce or 0))
    except Exception:capacity=0.0
    queue_pce=CAR_PCE_FACTOR*car_queue+MOTOR_PCE_FACTOR*motor_queue
    if capacity<=0 or queue_pce<=0:
        return 0,0,0.0
    if queue_pce<=capacity+1e-9:
        return car_queue,motor_queue,round(queue_pce,3)
    # proportional allocation by PCE contribution, then fill remaining capacity without exceeding queue/capacity
    service_pce=min(capacity,queue_pce)
    car_target=service_pce*((CAR_PCE_FACTOR*car_queue)/queue_pce)/CAR_PCE_FACTOR
    loaded_car=min(car_queue,int(math.floor(car_target+1e-9)))
    remaining=max(0.0,service_pce-loaded_car)
    loaded_motor=min(motor_queue,int(math.floor((remaining/MOTOR_PCE_FACTOR)+1e-9)))
    used=CAR_PCE_FACTOR*loaded_car+MOTOR_PCE_FACTOR*loaded_motor
    while loaded_car<car_queue and used+CAR_PCE_FACTOR<=service_pce+1e-9:
        loaded_car+=1; used+=CAR_PCE_FACTOR
    while loaded_motor<motor_queue and used+MOTOR_PCE_FACTOR<=service_pce+1e-9:
        loaded_motor+=1; used+=MOTOR_PCE_FACTOR
    return loaded_car,loaded_motor,round(used,3)

def append_queue_event(event):
    with QUEUE_EVENTS.open("a",encoding="utf-8") as f:
        f.write(json.dumps(event,separators=(",",":"))+"\n")

def apply_departure_service(vessels,raw_by_port,ledger):
    """Persist berth visits and subtract queue once a vessel has *clearly* left.

    V10 only detected departure when the very first sample after BERTHED already had
    SOG >= 1 kn AND distance > 0.15 nm. A slow manoeuvring sample could therefore
    overwrite BERTHED and the service event was lost forever. V11 keeps a berth-visit
    latch until departure is confirmed, so queue reduction cannot be skipped by an
    intermediate APPROACHING/UNDERWAY sample.
    """
    events=[]
    capacities=load_capacity()
    prev_map=ledger.setdefault("vessels",{})
    processed=ledger.setdefault("processed_departures",{})
    for v in vessels:
        m=str(v.get("mmsi"))
        rec=prev_map.get(m) if isinstance(prev_map.get(m),dict) else {}
        state=str(v.get("operational_state") or "")
        port=str(v.get("current_port") or "").upper()
        sog=float(v.get("sog") or 0)
        dist=float(v.get("berth_distance_nm") or 0)

        # Start/refresh a berth visit. The latch survives slow manoeuvring after unberthing.
        if state=="BERTHED" and port in ("BENGKALIS","PAKNING"):
            if not rec.get("berth_visit_active"):
                rec["berth_visit_id"]=f"{m}:{port}:{v.get('source_timestamp') or iso(now())}"
                rec["berth_entered_at"]=iso(now())
            rec["berth_visit_active"]=True
            rec["berth_port"]=port
            rec["berth_name"]=v.get("nearest_berth")

        departed=False
        origin=str(rec.get("berth_port") or "").upper()
        if rec.get("berth_visit_active") and origin in ("BENGKALIS","PAKNING") and state!="BERTHED":
            # Confirm departure when vessel is physically clear of the berth. SOG is
            # supportive, but not mandatory once distance is safely outside the berth zone.
            departed=(dist>0.18 and (sog>=0.7 or state in ("SAILING","UNDERWAY"))) or dist>0.24

        if departed:
            visit_id=str(rec.get("berth_visit_id") or f"{m}:{origin}:{rec.get('berth_entered_at') or ''}")
            event_id=f"DEPARTURE:{visit_id}"
            if not processed.get(event_id):
                effective=effective_vehicle_state(raw_by_port.get(origin,{}),origin,ledger)
                capacity=float(capacities.get(int(v["mmsi"]),0) or 0)
                lc,lm,used=allocate_loading(effective.get("car_queue_current",0),effective.get("motor_queue_current",0),capacity)
                lp=ledger["ports"][origin]
                lp["loaded_car_total"]=_int(lp.get("loaded_car_total"))+lc
                lp["loaded_motor_total"]=_int(lp.get("loaded_motor_total"))+lm
                lp["departure_count"]=_int(lp.get("departure_count"))+1
                lp["last_departure_at"]=iso(now())
                lp["last_departure_mmsi"]=int(v["mmsi"])
                event={
                    "event_id":event_id,"event_type":"DEPARTURE_LOADING","occurred_at":iso(now()),
                    "port":origin,"mmsi":int(v["mmsi"]),"shipname":v.get("shipname"),
                    "berth":rec.get("berth_name"),"capacity_pce":capacity,
                    "queue_car_before":_int(effective.get("car_queue_current")),
                    "queue_motor_before":_int(effective.get("motor_queue_current")),
                    "loaded_car":lc,"loaded_motor":lm,"loaded_pce":used,
                    "queue_car_after":max(0,_int(effective.get("car_queue_current"))-lc),
                    "queue_motor_after":max(0,_int(effective.get("motor_queue_current"))-lm),
                }
                append_queue_event(event)
                ledger["last_event"]=event
                processed[event_id]=event["occurred_at"]
                # Keep the dedup dictionary bounded.
                if len(processed)>300:
                    for key in list(processed)[:-200]: processed.pop(key,None)
                events.append(event)
            rec["berth_visit_active"]=False
            rec["last_departure_event_id"]=event_id
            rec["last_departure_at"]=iso(now())

        rec.update({
            "operational_state":state,
            "current_port":port,
            "nearest_berth":v.get("nearest_berth"),
            "source_timestamp":v.get("source_timestamp"),
            "sog":v.get("sog"),
            "berth_distance_nm":v.get("berth_distance_nm"),
        })
        prev_map[m]=rec
    save_queue_ledger(ledger)
    return events

def load_ais():
    o=readj(AIS_JSON,None)
    if o is not None:
        r=o.get("vessels",o) if isinstance(o,dict) else o
        return r if isinstance(r,list) else []
    if AIS_CSV.exists():
        try:return pd.read_csv(AIS_CSV).to_dict("records")
        except Exception:return []
    return []

def load_capacity():
    global CAPACITY
    if CAPACITY:return CAPACITY
    try:
        df=pd.read_csv(CAPACITY_CSV)
        CAPACITY={int(r.mmsi):float(r.capacity_pce) for _,r in df.iterrows()}
    except Exception:
        CAPACITY={}
    return CAPACITY

def active_models():
    result={"ml1_eta":"random_forest","ml2_turnaround":"xgboost"}
    try:
        d=yaml.safe_load(ACTIVE_CFG.read_text(encoding="utf-8")) or {}
        result["ml1_eta"]=str((d.get("ml1_eta") or {}).get("active") or result["ml1_eta"])
        result["ml2_turnaround"]=str((d.get("ml2_turnaround") or {}).get("active") or result["ml2_turnaround"])
    except Exception:
        pass
    return result

def load_joblib(path):
    key=str(path)
    try:
        mt=path.stat().st_mtime
    except Exception:
        return None
    cached=_MODEL_CACHE.get(key)
    if cached and cached[0]==mt:return cached[1]
    try:
        obj=joblib.load(path)
        _MODEL_CACHE[key]=(mt,obj)
        return obj
    except Exception:
        return None

def model_path_ml1(name):
    return ML1_DIR/f"ml1_{name}.joblib"

def model_path_ml2(name):
    return ML2_DIR/f"ml2_{name}.joblib"

def nearest(lat,lon):
    return sorted((hav(lat,lon,*xy),k) for k,xy in BERTHS.items())[0]

def destination_position(dest):
    pts=[xy for k,xy in BERTHS.items() if dest in k]
    return (
        sum(x[0] for x in pts)/len(pts),
        sum(x[1] for x in pts)/len(pts)
    )

def cctv_rates(veh):
    """Return explicit YOLO rolling 5-minute arrival rates only.

    Queue length is intentionally NOT used as a substitute for arrival rate.
    Zero is a valid observed rate when the fields exist.
    """
    if not isinstance(veh,dict):
        return None,None,None,"WAITING_5MIN_RATE"
    required=("car_rate_5min","motor_rate_5min")
    if not all(k in veh for k in required):
        return None,None,None,"WAITING_5MIN_RATE"
    try:
        car=float(veh.get("car_rate_5min") or 0)
        motor=float(veh.get("motor_rate_5min") or 0)
        pce=float(veh.get("pce_rate_5min")) if veh.get("pce_rate_5min") is not None else car+0.25*motor
        return car,motor,pce,"CCTV_ROLLING_5MIN"
    except Exception:
        return None,None,None,"INVALID_5MIN_RATE"

def historical_demand(terminal, when_dt):
    """Return historical 5-minute predicted demand for ML2."""
    try:
        if not HIST_DEMAND_PROFILE.exists():
            return None,None,None,"MISSING_HISTORICAL_PROFILE"
        d=pd.read_csv(HIST_DEMAND_PROFILE)
        if d.empty:return None,None,None,"EMPTY_HISTORICAL_PROFILE"
        d['terminal']=d['terminal'].astype(str).str.upper()
        dow=int(when_dt.weekday()); minute=int(when_dt.hour*60+(when_dt.minute//5)*5)
        q=d[(d.terminal==str(terminal).upper()) & (pd.to_numeric(d.arrival_dow,errors='coerce')==dow) & (pd.to_numeric(d.minute_of_day,errors='coerce')==minute)]
        if q.empty:return None,None,None,"NO_PROFILE_BIN"
        r=q.iloc[0]
        return float(r.predicted_car_5min),float(r.predicted_motor_5min),float(r.predicted_pce_5min),"HISTORICAL_VEHICLE_PROFILE"
    except Exception:
        return None,None,None,"INVALID_HISTORICAL_PROFILE"

def ml1_predict(model_name, row):
    path=model_path_ml1(model_name)
    model=load_joblib(path)
    if model is None:return None,f"MISSING:{path.name}"
    try:
        residual=float(model.predict(pd.DataFrame([row]))[0])
        return residual,f"ACTIVE:{model_name}"
    except Exception as e:
        return None,f"ERROR:{model_name}:{type(e).__name__}"

def ml2_base_payload():
    obj=load_joblib(ML2_DIR/"ml2_turnaround_selected.joblib")
    return obj if isinstance(obj,dict) else {}

def base_turnaround(mmsi,dest):
    payload=ml2_base_payload()
    base=payload.get("base_by_vessel_terminal",{}) if isinstance(payload,dict) else {}
    candidates=[(str(mmsi),dest),(mmsi,dest),f"({mmsi}, '{dest}')"]
    for k in candidates:
        try:
            if k in base:return float(base[k])
        except Exception:pass
    vals=[]
    try:vals=[float(v) for v in base.values()]
    except Exception:pass
    return float(np.median(vals)) if vals else 20.0

def ml2_predict(model_name,row):
    path=model_path_ml2(model_name)
    model=load_joblib(path)
    if model is None:
        payload=ml2_base_payload()
        if isinstance(payload,dict) and str(payload.get("winner","")).lower().replace(" ","_")==model_name:
            model=payload.get("model")
    if model is None:return None,f"MISSING:{path.name}"
    try:
        correction=float(model.predict(pd.DataFrame([row]))[0])
        return correction,f"ACTIVE:{model_name}"
    except Exception as e:
        return None,f"ERROR:{model_name}:{type(e).__name__}"

def normalize(v,vehicles_by_port,active,target_mmsi):
    try:m=int(float(v.get("mmsi",0) or 0))
    except Exception:return None
    if m not in target_mmsi:return None

    lat=float(v.get("latitude",v.get("lat",0)) or 0)
    lon=float(v.get("longitude",v.get("lon",0)) or 0)
    sog=float(v.get("sog",v.get("speed",0)) or 0)
    cog=float(v.get("cog",v.get("course",0)) or 0)
    heading=v.get("heading")
    dist,bid=nearest(lat,lon)

    state="BERTHED" if dist<=BERTH_RADIUS_NM and sog<=BERTH_MAX_SOG else "APPROACHING" if dist<=max(0.30,BERTH_RADIUS_NM*2) else "SAILING" if sog>=1 else "UNDERWAY"
    port="BENGKALIS" if "BENGKALIS" in bid else "PAKNING"
    dest="PAKNING" if port=="BENGKALIS" else "BENGKALIS"
    d=min(hav(lat,lon,*xy) for k,xy in BERTHS.items() if dest in k)
    ts=v.get("update_at") or v.get("timestamp")
    data_age=v.get("data_age_seconds")
    try:data_age=float(data_age) if data_age is not None else None
    except Exception:data_age=None
    stale=bool((data_age is not None and data_age>MAX_DATA_AGE_SECONDS) or str(v.get("data_quality") or "").upper()=="STALE")

    eta_base=None
    eta_corr=None
    eta_correction=None
    eta_arrival=None
    ml1_status="NOT_APPLICABLE"

    if state!="BERTHED" and sog>BERTH_MAX_SOG and (ALLOW_STALE_INFERENCE or not stale):
        eta_base=d/sog*60.0
        dest_lat,dest_lon=destination_position(dest)
        target_bearing=bearing(lat,lon,dest_lat,dest_lon)
        hdg=float(heading) if heading not in (None,"") else cog
        row={
            "distance_to_destination_nm":d,
            "sog_kn":sog,
            "cog_deg":cog,
            "heading_error_deg":angle_error(hdg,target_bearing),
            "eta_baseline_min":eta_base,
            "hour":now().hour,
            "day_of_week":now().weekday(),
            "mmsi":m,
            "origin_port":port,
            "destination_port":dest,
        }
        pred,ml1_status=ml1_predict(active["ml1_eta"],row)
        eta_correction=pred
        eta_corr=max(0,eta_base+(pred or 0))
        eta_arrival=now()+timedelta(minutes=eta_corr)
    elif stale and state!="BERTHED":
        ml1_status="STALE_DATA_INFERENCE_DISABLED"

    turnaround_port=port if state=="BERTHED" else dest
    veh=(vehicles_by_port or {}).get(turnaround_port,{})
    observed_car,observed_motor,observed_pce,rate_mode=cctv_rates(veh)
    arrival_ref=eta_arrival or now()
    predicted_car,predicted_motor,predicted_pce,pred_mode=historical_demand(turnaround_port,arrival_ref)
    capacity=load_capacity().get(m,np.nan)
    ta_base=base_turnaround(m,turnaround_port)
    demand_ratio=(predicted_pce/float(capacity)) if predicted_pce is not None and capacity not in (None,0) and not pd.isna(capacity) else np.nan
    low_demand=int(not pd.isna(demand_ratio) and demand_ratio<LOW_DEMAND_THRESHOLD)
    ml2_row={
        "mmsi":str(m),
        "terminal":turnaround_port,
        "destination_port":turnaround_port,
        "arrival_hour":arrival_ref.hour,
        "arrival_dow":arrival_ref.weekday(),
        "capacity_pce":capacity,
        "turnaround_base_min":ta_base,
        "predicted_car_5min":predicted_car,
        "predicted_motor_5min":predicted_motor,
        "predicted_pce_5min":predicted_pce,
        "observed_car_5min":observed_car,
        "observed_motor_5min":observed_motor,
        "observed_pce_5min":observed_pce,
        "demand_capacity_ratio":demand_ratio,
        "low_demand_flag":low_demand,
        # compatibility aliases for older ML2 artifacts until retraining completes
        "car_rate_5min":observed_car,
        "motor_rate_5min":observed_motor,
        "pce_rate_5min":observed_pce,
    }
    if stale and state!="BERTHED":
        correction=None
        ml2_status="STALE_DATA_INFERENCE_DISABLED"
    elif predicted_pce is None:
        correction=None
        ml2_status=f"WAITING_HISTORICAL_DEMAND:{turnaround_port}"
    elif observed_pce is None:
        correction=None
        ml2_status=f"WAITING_CCTV_RATE:{turnaround_port}"
    else:
        correction,ml2_status=ml2_predict(active["ml2_turnaround"],ml2_row)
    ta_corr=max(0,ta_base+(correction or 0))

    if state=="BERTHED":
        etd=now()+timedelta(minutes=ta_corr)
    elif eta_arrival is not None:
        etd=eta_arrival+timedelta(minutes=ta_corr)
    else:
        etd=None

    return {
        "mmsi":m,
        "shipname":v.get("shipname",v.get("name",str(m))),
        "latitude":lat,"longitude":lon,"sog":sog,"cog":cog,"heading":heading,
        "data_quality":v.get("data_quality"),
        "data_age_seconds":data_age,"stale_for_inference":stale,
        "speed_reliability_status":"RELIABLE_7_9_KN" if RELIABLE_SPEED_MIN<=sog<=RELIABLE_SPEED_MAX else "OUTSIDE_RELIABLE_7_9_KN",
        "nearest_berth":bid,"berth_distance_nm":round(dist,4),
        "operational_state":state,"current_port":port,"destination_port":dest,
        "capacity_pce":load_capacity().get(m),
        "eta_baseline_min":None if eta_base is None else round(eta_base,2),
        "eta_correction_ml1_min":None if eta_correction is None else round(eta_correction,2),
        "eta_corrected_min":None if eta_corr is None else round(eta_corr,2),
        "eta_timestamp":None if eta_arrival is None else iso(eta_arrival),
        "turnaround_base_min":round(ta_base,2),
        "turnaround_correction_ml2_min":None if correction is None else round(correction,2),
        "turnaround_corrected_min":round(ta_corr,2),
        "etd_timestamp":None if etd is None else iso(etd),
        "ml1_model_id":active["ml1_eta"],
        "ml2_model_id":active["ml2_turnaround"],
        "ml1_inference_status":ml1_status,
        "ml2_inference_status":ml2_status,
        "ml2_input_mode":rate_mode,
        "historical_demand_mode":pred_mode,
        "predicted_car_5min":predicted_car,"predicted_motor_5min":predicted_motor,"predicted_pce_5min":predicted_pce,
        "observed_car_5min":observed_car,"observed_motor_5min":observed_motor,"observed_pce_5min":observed_pce,
        "demand_capacity_ratio":None if pd.isna(demand_ratio) else round(float(demand_ratio),4),
        "low_demand_flag":low_demand,
        # Optional timetable fields. They are passed through only when supplied by the
        # upstream source/config; V11 never invents ON TIME/DELAY without a reference.
        "scheduled_arrival_timestamp":v.get("scheduled_arrival_timestamp") or v.get("planned_arrival_timestamp") or v.get("schedule_arrival_timestamp"),
        "scheduled_departure_timestamp":v.get("scheduled_departure_timestamp") or v.get("planned_departure_timestamp") or v.get("schedule_departure_timestamp"),
        "source_timestamp":ts,
    }

def persist_research_snapshot(state):
    """Persist one synchronized research snapshot per 5-minute bin.

    Realtime JSON is the serving contract; this CSV is the immutable analysis/audit contract.
    One row is stored per vessel per tick with synchronized queue and berth context.
    """
    try:
        generated=pd.Timestamp(state['generated_at'])
        tick=generated.floor(f'{HISTORY_TICK_MIN}min')
        marker=HISTORY_5MIN.with_suffix('.last_tick')
        if marker.exists() and marker.read_text(encoding='utf-8').strip()==tick.isoformat():
            return
        HISTORY_5MIN.parent.mkdir(parents=True,exist_ok=True)
        b=state.get('vehicle_bengkalis') or {};p=state.get('vehicle_pakning') or {}
        rows=[]
        for v in state.get('vessels') or []:
            rows.append({
                'simulation_tick':tick.isoformat(),'generated_at':state.get('generated_at'),
                'mmsi':v.get('mmsi'),'shipname':v.get('shipname'),'latitude':v.get('latitude'),'longitude':v.get('longitude'),
                'sog':v.get('sog'),'cog':v.get('cog'),'operational_state':v.get('operational_state'),
                'current_port':v.get('current_port'),'destination_port':v.get('destination_port'),'nearest_berth':v.get('nearest_berth'),
                'eta_baseline_min':v.get('eta_baseline_min'),'eta_correction_ml1_min':v.get('eta_correction_ml1_min'),
                'eta_corrected_min':v.get('eta_corrected_min'),'eta_timestamp':v.get('eta_timestamp'),
                'turnaround_base_min':v.get('turnaround_base_min'),'turnaround_correction_ml2_min':v.get('turnaround_correction_ml2_min'),
                'turnaround_corrected_min':v.get('turnaround_corrected_min'),'etd_timestamp':v.get('etd_timestamp'),
                'ml1_model_id':v.get('ml1_model_id'),'ml2_model_id':v.get('ml2_model_id'),
                'predicted_pce_5min':v.get('predicted_pce_5min'),'observed_pce_5min':v.get('observed_pce_5min'),
                'low_demand_flag':v.get('low_demand_flag'),'data_age_seconds':v.get('data_age_seconds'),
                'bengkalis_car_queue':b.get('car_queue_current'),'bengkalis_motor_queue':b.get('motor_queue_current'),
                'pakning_car_queue':p.get('car_queue_current'),'pakning_motor_queue':p.get('motor_queue_current'),
                'arrival_definition':'TERMINAL_BERTH_ARRIVAL','method_version':'BIMA2_YEAR2_METHOD_ALIGNED_V12',
            })
        if not rows:
            rows=[{'simulation_tick':tick.isoformat(),'generated_at':state.get('generated_at'),'arrival_definition':'TERMINAL_BERTH_ARRIVAL','method_version':'BIMA2_YEAR2_METHOD_ALIGNED_V12'}]
        pd.DataFrame(rows).to_csv(HISTORY_5MIN,mode='a',index=False,header=not HISTORY_5MIN.exists())
        marker.write_text(tick.isoformat(),encoding='utf-8')
    except Exception as exc:
        print(f'RESEARCH_HISTORY_WARNING: {exc}',flush=True)

def build():
    target_mmsi=load_target_mmsi()
    active=active_models()
    raw_bengkalis=readj(CCTV_BENGKALIS,{})
    raw_pakning=readj(CCTV_PAKNING,{})
    raw_by_port={"BENGKALIS":raw_bengkalis,"PAKNING":raw_pakning}
    vs=[x for x in (normalize(v,raw_by_port,active,target_mmsi) for v in load_ais()) if x]
    queue_ledger=load_queue_ledger()
    service_events=apply_departure_service(vs,raw_by_port,queue_ledger)
    veh_bengkalis=effective_vehicle_state(raw_bengkalis,"BENGKALIS",queue_ledger)
    veh_pakning=effective_vehicle_state(raw_pakning,"PAKNING",queue_ledger)

    berths={k:{"status":"AVAILABLE"} for k in BERTHS}
    for v in vs:
        if v["operational_state"]=="BERTHED":
            berths[v["nearest_berth"]]={"status":"OCCUPIED","mmsi":v["mmsi"],"shipname":v["shipname"]}

    ml1_states=[v["ml1_inference_status"] for v in vs if v["ml1_inference_status"]!="NOT_APPLICABLE"]
    ml2_states=[v["ml2_inference_status"] for v in vs]
    ml1_ok=bool(ml1_states) and all(x.startswith("ACTIVE:") for x in ml1_states)
    ml2_active=[x for x in ml2_states if x.startswith("ACTIVE:")]
    ml2_wait=[x for x in ml2_states if x.startswith("WAITING_CCTV_RATE:")]
    if ml2_states and len(ml2_active)==len(ml2_states):
        ml2_system_status=f"ACTIVE:{active['ml2_turnaround']}"
    elif ml2_active:
        ml2_system_status=f"PARTIAL:{active['ml2_turnaround']}"
    elif ml2_wait:
        ml2_system_status=f"WAITING_CCTV:{active['ml2_turnaround']}"
    else:
        ml2_system_status=f"FALLBACK:{active['ml2_turnaround']}"

    cctv_times=[x.get("updated_at") for x in (veh_bengkalis,veh_pakning) if isinstance(x,dict) and x.get("updated_at")]
    s={
        "generated_at":iso(now()),
        "ais_updated_at":max([v.get("source_timestamp") or "" for v in vs],default=""),
        "cctv_updated_at":max(cctv_times,default=None),
        "ml1_status":f"ACTIVE:{active['ml1_eta']}" if ml1_ok else f"FALLBACK:{active['ml1_eta']}",
        "ml2_status":ml2_system_status,
        "ml1_model_id":active["ml1_eta"],
        "ml2_model_id":active["ml2_turnaround"],
        "vessels":vs,
        "berths":berths,
        "vehicle_bengkalis":veh_bengkalis,
        "vehicle_pakning":veh_pakning,
        "diagnostics":{
            "dashboard_mode":"realtime_serving_plus_5min_research_history",
            "method_version":"BIMA2_YEAR2_METHOD_ALIGNED_V12",
            "arrival_definition":"TERMINAL_BERTH_ARRIVAL",
            "etd_formula":"ETA_corrected + turnaround_base + turnaround_correction_ML2",
            "queue_module_role":"OPERATIONAL_SIMULATION_NOT_ML2",
            "ais_source":"data/01_DATA_SOURCE/AIS/realtime/ais_current_state.json",
            "ais_vessel_count":len(vs),
            "target_mmsi":sorted(target_mmsi),
            "ml1_artifact":str(model_path_ml1(active["ml1_eta"]).relative_to(ROOT)),
            "ml2_artifact":str(model_path_ml2(active["ml2_turnaround"]).relative_to(ROOT)),
            "ml1_inference":ml1_states,
            "ml2_inference":ml2_states,
            "queue_service_ledger":"outputs/realtime/queue_service_state.json",
            "service_events_this_tick":service_events,
        },
    }

    (OUT/"current_operation_state.json").write_text(json.dumps(s,indent=2),encoding="utf-8")
    for port in ("BENGKALIS","PAKNING"):
        z=dict(s)
        z["vessels"]=[v for v in vs if v["current_port"]==port or v["destination_port"]==port]
        z["berths"]={k:v for k,v in berths.items() if port in k}
        z["vehicle_current"]=veh_bengkalis if port=="BENGKALIS" else veh_pakning
        (OUT/f"current_{port.lower()}_state.json").write_text(json.dumps(z,indent=2),encoding="utf-8")
    persist_research_snapshot(s)
    return s

if __name__=="__main__":
    import argparse
    ap=argparse.ArgumentParser()
    ap.add_argument("--loop",action="store_true")
    ap.add_argument("--seconds",type=int,default=5)
    args=ap.parse_args()
    while True:
        s=build()
        print(f"[{s['generated_at']}] vessels={len(s['vessels'])} ml1={s['ml1_status']} ml2={s['ml2_status']}")
        if not args.loop:break
        time.sleep(max(1,args.seconds))
