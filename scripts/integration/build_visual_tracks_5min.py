"""Bangun lintasan visual dermaga-ke-dermaga dari AIS mentah untuk replay harian."""
from pathlib import Path
import sys
import numpy as np
import pandas as pd
import yaml

PROJECT_ROOT=Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path: sys.path.insert(0, str(PROJECT_ROOT))
from scripts.v3_paths import output_root, processed_root, model_artifact_root, logs_root
ML1_PROCESSED=processed_root(PROJECT_ROOT)/"ml1"
REPLAY_OUT=output_root(PROJECT_ROOT)/"04_replay_dashboard"
def load_ports():
    cfg=yaml.safe_load((PROJECT_ROOT/"config"/"ports_berths.yaml").read_text(encoding="utf-8"))
    return {port: tuple((np.mean([b["lat"] for b in item["berths"]]), np.mean([b["lon"] for b in item["berths"]])))
            for port,item in cfg["ports"].items()}
PORTS=load_ports()

def nm(lat,lon,pt):
    r=6371.0088; p1,p2=np.radians(lat),np.radians(pt[0]); dp=np.radians(pt[0]-lat); dl=np.radians(pt[1]-lon)
    return 2*r*np.arcsin(np.sqrt(np.sin(dp/2)**2+np.cos(p1)*np.cos(p2)*np.sin(dl/2)**2))/1.852

def interpolate(nodes, start, end, leg):
    ticks=pd.date_range(start.floor("5min"),end.ceil("5min"),freq="5min",tz="UTC")
    t=nodes.timestamp.astype("int64").to_numpy(); q=ticks.astype("int64").to_numpy()
    lat=np.interp(q,t,nodes.latitude); lon=np.interp(q,t,nodes.longitude)
    state=np.where(ticks < leg.model_start,"BERTH_ORIGIN",np.where(ticks >= leg.arrival_time,"BERTH_DESTINATION","AIS_SAILING"))
    return pd.DataFrame({"simulation_tick":ticks,"mmsi":str(leg.mmsi),"latitude":lat,"longitude":lon,
        "origin_port":leg.origin_port,"destination_port":leg.destination_port,"leg_id":leg.leg_id,
        "visual_state":state,"position_source":"AIS mentah + endpoint dermaga jika AIS tidak merekam titik terminal"})

def main():
    d=pd.read_csv(ML1_PROCESSED/"ml1_eta_training_dataset.csv",parse_dates=["timestamp","arrival_time"])
    legs=(d.groupby("leg_id",as_index=False).agg(mmsi=("mmsi","first"),model_start=("timestamp","min"),
        arrival_time=("arrival_time","first"),origin_port=("origin_port","first"),destination_port=("destination_port","first")))
    legs=legs.sort_values("arrival_time").reset_index(drop=True).iloc[int(len(legs)*.8):].copy()
    raw=pd.read_csv(PROJECT_ROOT/"data"/"input"/"ais"/"raw"/"ais_raw_2024.csv",usecols=["mmsi","created_at","lat","lon","sog","cog"])
    raw=raw.rename(columns={"created_at":"timestamp","lat":"latitude","lon":"longitude","sog":"sog_kn","cog":"cog_deg"})
    raw.timestamp=pd.to_datetime(raw.timestamp,utc=True); raw.mmsi=raw.mmsi.astype(str)
    raw=raw.dropna(subset=["timestamp","latitude","longitude"]).sort_values(["mmsi","timestamp"]).drop_duplicates(["mmsi","timestamp"])
    tracks=[]; bounds=[]
    for leg in legs.itertuples(index=False):
        vessel=raw[raw.mmsi.eq(str(leg.mmsi))]
        prior=vessel[(vessel.timestamp.le(leg.model_start))&(vessel.timestamp.ge(leg.arrival_time-pd.Timedelta(hours=3)))].copy()
        prior["origin_distance"]=nm(prior.latitude,prior.longitude,PORTS[leg.origin_port])
        in_origin=prior[prior.origin_distance.le(.20)]
        depart=in_origin.timestamp.max() if len(in_origin) else leg.model_start-pd.Timedelta(minutes=30)
        nodes=vessel[(vessel.timestamp.ge(depart)) & (vessel.timestamp.le(leg.arrival_time))].copy()
        virtual_start=pd.DataFrame([{"timestamp":depart,"latitude":PORTS[leg.origin_port][0],"longitude":PORTS[leg.origin_port][1]}])
        virtual_end=pd.DataFrame([{"timestamp":leg.arrival_time,"latitude":PORTS[leg.destination_port][0],"longitude":PORTS[leg.destination_port][1]}])
        nodes=pd.concat([virtual_start,nodes[["timestamp","latitude","longitude"]],virtual_end],ignore_index=True)
        nodes=nodes.sort_values("timestamp").drop_duplicates("timestamp",keep="last")
        tracks.append(interpolate(nodes,depart,leg.arrival_time,leg))
        bounds.append({"mmsi":str(leg.mmsi),"leg_id":leg.leg_id,"start":depart,"end":leg.arrival_time,
                       "port":leg.destination_port})
    out=pd.concat(tracks,ignore_index=True)
    # Kapal tetap tampak di dermaga setelah tiba hingga perjalanan berikutnya mulai.
    b=pd.DataFrame(bounds).sort_values(["mmsi","end"])
    berth=[]
    for vessel,g in b.groupby("mmsi"):
        for i,row in enumerate(g.itertuples(index=False)):
            nxt=g.iloc[i+1].start if i+1<len(g) else min(row.end.normalize()+pd.Timedelta(hours=23,minutes=55),row.end+pd.Timedelta(hours=8))
            for tick in pd.date_range(row.end.ceil("5min")+pd.Timedelta(minutes=5),nxt.floor("5min"),freq="5min",tz="UTC"):
                berth.append({"simulation_tick":tick,"mmsi":vessel,"latitude":PORTS[row.port][0],"longitude":PORTS[row.port][1],
                  "origin_port":None,"destination_port":row.port,"leg_id":row.leg_id,"visual_state":"BERTH_IDLE",
                  "position_source":"Dermaga dari event kedatangan AIS"})
    if berth: out=pd.concat([out,pd.DataFrame(berth)],ignore_index=True)
    priority={"AIS_SAILING":3,"BERTH_ORIGIN":2,"BERTH_DESTINATION":2,"BERTH_IDLE":1}
    out["priority"]=out.visual_state.map(priority)
    out=out.sort_values(["simulation_tick","mmsi","priority"]).drop_duplicates(["simulation_tick","mmsi"],keep="last").drop(columns="priority")
    out=out.sort_values(["simulation_tick","mmsi"]).reset_index(drop=True)
    out.to_csv(REPLAY_OUT/"visual_track_5min.csv",index=False)
    print(f"OK visual_track_5min.csv: {len(out)} state; {out.mmsi.nunique()} kapal; {len(legs)} leg uji")
if __name__=="__main__": main()
