"""Build ML1 ETA-correction training data using terminal berth arrival as the target event."""
from __future__ import annotations

import argparse, json, os, sys
from pathlib import Path
import numpy as np
import pandas as pd
import yaml

ALIASES = {
    "timestamp": ["timestamp","time","datetime","date_time","basedatetime","base_datetime","dt","created_at"],
    "mmsi": ["mmsi","vessel_id","ship_id","imo"],
    "latitude": ["lat","latitude","y"],
    "longitude": ["lon","lng","longitude","x"],
    "sog": ["sog","speed","speed_over_ground","speed_knots"],
    "cog": ["cog","course","course_over_ground","heading"],
}

def project_root(): return Path(__file__).resolve().parents[2]

def runtime_processed_root(root: Path) -> Path:
    if str(root) not in sys.path: sys.path.insert(0, str(root))
    try:
        from scripts.v3_paths import processed_root
        return processed_root(root)
    except Exception:
        return root / "data" / "processed"

def load_project(path: Path) -> dict:
    d=yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if "ml1" not in d or "ports" not in d:
        raise ValueError("project_config.yaml harus memiliki bagian ml1 dan ports")
    return d

def resolve_column(frame, logical, configured=None):
    if configured and configured in frame.columns: return configured
    norm={str(c).strip().lower().replace(" ","_"):c for c in frame.columns}
    for n in ALIASES[logical]:
        if n in norm:return norm[n]
    raise ValueError(f"Kolom {logical} tidak ditemukan")

def haversine_nm(lat1,lon1,lat2,lon2):
    r=6371.0088
    p1,p2=np.radians(lat1),np.radians(lat2)
    dp,dl=np.radians(lat2-lat1),np.radians(lon2-lon1)
    a=np.sin(dp/2)**2+np.cos(p1)*np.cos(p2)*np.sin(dl/2)**2
    return 2*r*np.arcsin(np.sqrt(a))/1.852

def bearing_deg(lat1,lon1,lat2,lon2):
    p1,p2,dl=np.radians(lat1),np.radians(lat2),np.radians(lon2-lon1)
    y=np.sin(dl)*np.cos(p2); x=np.cos(p1)*np.sin(p2)-np.sin(p1)*np.cos(p2)*np.cos(dl)
    return (np.degrees(np.arctan2(y,x))+360)%360

def angular_difference(a,b): return np.abs((a-b+180)%360-180)

def minutes_of_day(ts): return ts.hour*60+ts.minute

def in_service_window(ts_local, start_s, end_s):
    sh,sm=map(int,start_s.split(":")); eh,em=map(int,end_s.split(":"))
    v=minutes_of_day(ts_local); return (sh*60+sm)<=v<=(eh*60+em)

def build_dataset(project: dict, root: Path):
    cfg=project["ml1"]
    ports=project["ports"]
    rel=project.get("research",{}).get("reliability_indicator",{})
    validation=project.get("research",{}).get("operational_holdout",{})
    target=cfg.get("target_event",{})
    radius=float(target.get("berth_radius_nm",0.15))
    berth_max_sog=float(target.get("max_sog_kn",0.8))
    sail_min=float(rel.get("sailing_speed_min_kn",3.0)); sail_max=float(rel.get("sailing_speed_max_kn",15.0))
    start_window=str(validation.get("service_window_start","07:00")); end_window=str(validation.get("service_window_end","23:55"))
    tz=project.get("timezone","Asia/Jakarta")

    raw_path=Path(os.getenv("BIMA2_ML1_INPUT_FILE",str(root/cfg["input_file"])))
    if not raw_path.exists(): raise FileNotFoundError(raw_path)
    raw=pd.read_csv(raw_path)
    configured=cfg.get("columns",{})
    cols={k:resolve_column(raw,k,configured.get(k)) for k in ALIASES}
    df=raw.rename(columns={v:k for k,v in cols.items()})[[*ALIASES]].copy()
    df["timestamp"]=pd.to_datetime(df.timestamp,errors="coerce",utc=True)
    for c in ["latitude","longitude","sog","cog"]:df[c]=pd.to_numeric(df[c],errors="coerce")
    df["mmsi"]=pd.to_numeric(df.mmsi,errors="coerce").astype("Int64")
    df=df.dropna(subset=["timestamp","mmsi","latitude","longitude","sog"])
    df=df[df.latitude.between(-90,90)&df.longitude.between(-180,180)].copy()
    df["mmsi"]=df.mmsi.astype("int64").astype(str)
    df=df.sort_values(["mmsi","timestamp"]).reset_index(drop=True)

    port_names=list(ports)
    berth_defs=[]
    for p,item in ports.items():
        for b in item["berths"]: berth_defs.append((p,b["id"],float(b["lat"]),float(b["lon"])))
    corridor_nm=min(float(haversine_nm(a[2],a[3],b[2],b[3])) for a in berth_defs if a[0]==port_names[0] for b in berth_defs if b[0]==port_names[1])

    # Distance to every berth and nearest berth/terminal.
    berth_dist_cols=[]
    for p,bid,lat,lon in berth_defs:
        col=f"distance_to_{bid}_nm"; berth_dist_cols.append((p,bid,col,lat,lon))
        df[col]=haversine_nm(df.latitude,df.longitude,lat,lon)
    mat=df[[x[2] for x in berth_dist_cols]].to_numpy()
    arg=np.argmin(mat,axis=1)
    df["nearest_berth"]=[berth_dist_cols[i][1] for i in arg]
    df["nearest_port"]=[berth_dist_cols[i][0] for i in arg]
    df["nearest_berth_distance_nm"]=mat[np.arange(len(df)),arg]
    for p in port_names:
        cols_p=[x[2] for x in berth_dist_cols if x[0]==p]
        df[f"distance_to_{p}_nm"]=df[cols_p].min(axis=1)

    # YEAR-2 target: actual arrival is the first AIS observation at a berth with low SOG.
    df["in_berth_arrival_state"]=(df.nearest_berth_distance_nm<=radius)&(df.sog<=berth_max_sog)
    events=[]
    for mmsi,g in df.groupby("mmsi",sort=False):
        g=g.copy()
        entered=g.in_berth_arrival_state & ~g.in_berth_arrival_state.shift(fill_value=False)
        for idx in g.index[entered]:
            r=df.loc[idx]; local=r.timestamp.tz_convert(tz)
            if not in_service_window(local,start_window,end_window): continue
            events.append({"mmsi":mmsi,"arrival_time":r.timestamp,"destination_port":r.nearest_port,"arrival_berth":r.nearest_berth,"arrival_row":int(idx),"arrival_sog_kn":float(r.sog),"berth_distance_nm":float(r.nearest_berth_distance_nm)})
    arrivals=pd.DataFrame(events)
    if arrivals.empty: raise ValueError("Tidak ada terminal berth arrival yang memenuhi radius/SOG/service window")
    arrivals=arrivals.sort_values(["mmsi","arrival_time"]).reset_index(drop=True)
    min_gap=pd.Timedelta(minutes=float(cfg.get("min_arrival_separation_minutes",45)))
    arrivals["prev"]=arrivals.groupby("mmsi").arrival_time.shift()
    arrivals=arrivals[arrivals.prev.isna()|((arrivals.arrival_time-arrivals.prev)>=min_gap)].drop(columns="prev").reset_index(drop=True)

    # Berth-exit events are used only to identify the origin of the next service leg.
    vessel_groups={m:g for m,g in df.groupby("mmsi",sort=False)}
    berth_exits={}
    for m,g in vessel_groups.items():
        exited=g.in_berth_arrival_state & ~g.in_berth_arrival_state.shift(-1,fill_value=False)
        berth_exits[m]=g.loc[exited,["timestamp","nearest_port","nearest_berth"]].reset_index(drop=True)

    max_h=pd.Timedelta(hours=float(cfg.get("max_approach_hours",3)))
    max_leg=pd.Timedelta(minutes=float(cfg.get("max_service_leg_minutes",90)))
    interval=int(cfg.get("sample_every_minutes",5))
    max_factor=float(cfg.get("max_corridor_distance_factor",1.5))
    samples=[]; previous_destination={}
    for leg_id,event in arrivals.iterrows():
        m=str(event.mmsi); g=vessel_groups[m]; exits=berth_exits[m]
        prior=exits[exits.timestamp<event.arrival_time]
        last=prior.iloc[-1] if not prior.empty else None
        if last is not None and (event.arrival_time-last.timestamp)>max_leg: continue
        leg_start=max(event.arrival_time-max_h,last.timestamp) if last is not None else event.arrival_time-max_h
        dest=event.destination_port
        approach=g[(g.timestamp<event.arrival_time)&(g.timestamp>=leg_start)].copy()
        approach=approach[(approach.sog.between(sail_min,sail_max)) & (approach[f"distance_to_{dest}_nm"]>radius) & (approach[f"distance_to_{dest}_nm"]<=corridor_nm*max_factor)]
        if approach.empty: continue
        approach["sample_bin"]=approach.timestamp.dt.floor(f"{interval}min")
        approach=approach.drop_duplicates("sample_bin",keep="last")
        origin=last.nearest_port if last is not None else previous_destination.get(m,"unknown")
        berth=next(b for b in berth_defs if b[1]==event.arrival_berth)
        for _,r in approach.iterrows():
            actual=(event.arrival_time-r.timestamp).total_seconds()/60
            baseline=float(r[f"distance_to_{dest}_nm"])/float(r.sog)*60
            tb=bearing_deg(r.latitude,r.longitude,berth[2],berth[3])
            he=angular_difference(r.cog,tb) if pd.notna(r.cog) else np.nan
            samples.append({"leg_id":leg_id,"mmsi":r.mmsi,"timestamp":r.timestamp,"arrival_time":event.arrival_time,"arrival_berth":event.arrival_berth,"origin_port":origin,"destination_port":dest,"distance_to_destination_nm":r[f"distance_to_{dest}_nm"],"sog_kn":r.sog,"cog_deg":r.cog,"heading_error_deg":he,"eta_baseline_min":baseline,"actual_remaining_min":actual,"eta_residual_min":actual-baseline,"hour":r.timestamp.tz_convert(tz).hour,"day_of_week":r.timestamp.tz_convert(tz).dayofweek})
        previous_destination[m]=dest
    dataset=pd.DataFrame(samples)
    if dataset.empty: raise ValueError("Tidak ada sampel ML1 setelah filter")
    dataset=dataset.replace([np.inf,-np.inf],np.nan).dropna(subset=["eta_residual_min","eta_baseline_min"]).sort_values(["arrival_time","timestamp"]).reset_index(drop=True)
    out=runtime_processed_root(root)/"ml1"; out.mkdir(parents=True,exist_ok=True)
    dataset.to_csv(out/"ml1_eta_training_dataset.csv",index=False)
    arrivals.to_csv(out/"detected_arrival_events.csv",index=False)
    quality={"arrival_definition":"terminal_berth_arrival","berth_radius_nm":radius,"berth_max_sog_kn":berth_max_sog,"service_window":f"{start_window}-{end_window}","raw_rows":len(raw),"clean_ais_rows":len(df),"detected_arrivals":len(arrivals),"ml1_samples":len(dataset),"legs":int(dataset.leg_id.nunique()),"corridor_reference_nm":round(corridor_nm,3)}
    (out/"data_quality.json").write_text(json.dumps(quality,indent=2,default=str),encoding="utf-8")
    return out/"ml1_eta_training_dataset.csv"

if __name__=="__main__":
    ap=argparse.ArgumentParser(); ap.add_argument("--config",default="config/project_config.yaml"); a=ap.parse_args()
    root=project_root(); print(build_dataset(load_project(root/a.config),root))
