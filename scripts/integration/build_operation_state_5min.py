"""Satukan seluruh keluaran replay menjadi satu kontrak operation_state_5min."""
from pathlib import Path
import sys
import os
import numpy as np
import pandas as pd
import yaml

PROJECT_ROOT=Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path: sys.path.insert(0,str(PROJECT_ROOT))
from scripts.v3_paths import output_root
INTEGRATION_OUT=output_root(PROJECT_ROOT)/"03_eta_etd_integration"; REPLAY_OUT=output_root(PROJECT_ROOT)/"04_replay_dashboard"; PUBLISHED=output_root(PROJECT_ROOT)/"published"
def load_config():
    ports=yaml.safe_load((PROJECT_ROOT/"config"/"ports_berths.yaml").read_text())
    project=yaml.safe_load((PROJECT_ROOT/"config"/"project_config.yaml").read_text())
    return ports["ports"],project
def nearest_berth(lat,lon,ports):
    best=(None,1e9)
    for terminal,item in ports.items():
        for b in item["berths"]:
            d=(lat-b["lat"])**2+(lon-b["lon"])**2
            if d<best[1]: best=(b["id"],d)
    return best[0]
def main():
    PUBLISHED.mkdir(parents=True, exist_ok=True)
    ports,cfg=load_config()
    visual=pd.read_csv(REPLAY_OUT/"visual_track_5min.csv",parse_dates=["simulation_tick"])
    visual["mmsi"]=visual.mmsi.astype(str)
    multi=pd.read_csv(INTEGRATION_OUT/"simulation_input_5min_multimodel.csv",parse_dates=["simulation_tick"])
    multi["mmsi"]=multi.mmsi.astype(str)
    # Prediksi hanya ditempel pada kapal/tick yang memiliki observasi ML1.
    model_cols=[c for c in multi.columns if c not in {"latitude","longitude","origin_port","destination_port","state_type","source_ais","source_vehicle","leg_id"}]
    model=multi[model_cols].drop_duplicates(["simulation_tick","mmsi"])
    vessel=visual.merge(model,on=["simulation_tick","mmsi"],how="left")
    vessel["record_type"]="VESSEL_STATE"; vessel["vessel_state"]=vessel.visual_state
    vessel["berth_id"]=[nearest_berth(a,b,ports) if str(s).startswith("BERTH") else None
                        for a,b,s in zip(vessel.latitude,vessel.longitude,vessel.vessel_state)]
    sched=pd.read_csv(REPLAY_OUT/"daily_operation_schedule.csv",parse_dates=["prediction_time"])
    sched_cols=[c for c in sched.columns if c=="leg_id" or c.startswith("estimated_") or c=="prediction_time"]
    vessel=vessel.merge(sched[sched_cols],on="leg_id",how="left",suffixes=("","_schedule"))

    rates=pd.read_csv(INTEGRATION_OUT/"vehicle_rate_5min.csv")
    departures=(multi.sort_values("simulation_tick").groupby("journey_id",as_index=False).first()
                [["simulation_tick","origin_port","capacity_pce"]])
    terminal_rows=[]
    for date in sorted(vessel.simulation_tick.dt.date.unique()):
        day=pd.Timestamp(date,tz="UTC"); queue={"Bengkalis":0.,"Pakning":0.}
        for tick in pd.date_range(day+pd.Timedelta(hours=7),day+pd.Timedelta(hours=23,minutes=55),freq="5min"):
            minute=tick.hour*60+tick.minute
            for terminal in ports:
                r=rates[(rates.terminal.eq(terminal))&(rates.arrival_dow.eq(day.dayofweek))&(rates.minute_of_day.eq(minute))]
                car=float(r.car_rate_5min.iloc[0]) if len(r) else 0.; motor=float(r.motor_rate_5min.iloc[0]) if len(r) else 0.
                pce=float(r.pce_rate_5min.iloc[0]) if len(r) else 0.
                cap=float(departures[(departures.simulation_tick.eq(tick))&(departures.origin_port.eq(terminal))].capacity_pce.sum())
                queue[terminal]=max(0.,queue[terminal]+pce-cap)
                terminal_rows.append({"record_type":"TERMINAL_STATE","simulation_tick":tick,"terminal":terminal,
                  "queue_estimated_pce":queue[terminal],"car_arrival_5min":car,"motor_arrival_5min":motor,
                  "pce_arrival_5min":pce,"service_capacity_pce":cap,"data_source_vehicle":"profil_manifest_5menit"})
    terminal=pd.DataFrame(terminal_rows)
    active_run_id=os.environ.get("LOCAL_RUN_RUN_ID") or cfg.get("run_id","UNSPECIFIED")
    vessel["run_id"]=active_run_id; terminal["run_id"]=active_run_id
    vessel["data_source_position"]="AIS_historis_interpolasi_5menit"
    out=pd.concat([vessel,terminal],ignore_index=True,sort=False).sort_values(["simulation_tick","record_type","mmsi"]).reset_index(drop=True)
    for c in [x for x in out.columns if str(x).startswith("dta_")]:
        etd_col=c.replace("dta_","etd_",1)
        if etd_col not in out.columns:
            out[etd_col] = out[c]
    provenance=cfg.get("provenance",{})
    vehicle_status=str(provenance.get("vehicle_manifest_current","UNKNOWN"))
    operational=bool(provenance.get("operational_claim_allowed",False))
    out["bima2_snapshot_status"] = (
        "BIMA2_OPERATIONAL" if operational else f"LEGACY_PROTOTYPE_{vehicle_status}"
    )
    out["operational_claim_allowed"] = operational
    out.to_csv(PUBLISHED/"operation_state_5min.csv",index=False)
    print(f"OK operation_state_5min.csv: {len(out)} records; vessel={len(vessel)}; terminal={len(terminal)}; run_id={active_run_id}")
if __name__=="__main__": main()
