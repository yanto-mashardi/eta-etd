"""Prepare ML2 dataset with explicit provenance guard."""
from pathlib import Path
import sys
import os
import argparse, json
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path: sys.path.insert(0, str(PROJECT_ROOT))
from scripts.v3_paths import output_root, processed_root, model_artifact_root, logs_root
ACTIVE_MANIFEST_DIR = PROJECT_ROOT / "data" / "input" / "vehicle" / "manifest"
QUARANTINE_DIR = PROJECT_ROOT / "data" / "input" / "audit_quarantine"
PROCESSED = processed_root(PROJECT_ROOT) / "ml2"
PROCESSED.mkdir(parents=True, exist_ok=True)

def choose_book(allow_simulated=False):
    override = os.getenv("BIMA2_ML2_MANIFEST_FILE", "").strip()
    if override:
        p = Path(override)
        if not p.exists():
            raise FileNotFoundError(f"BIMA2_ML2_MANIFEST_FILE tidak ditemukan: {p}")
        return p, "OBSERVED_OR_USER_SUPPLIED"
    active = sorted(ACTIVE_MANIFEST_DIR.glob("*.xlsx"))
    if active:
        return active[0], "OBSERVED_OR_USER_SUPPLIED"
    simulated = sorted(QUARANTINE_DIR.glob("SIMULATED*.xlsx"))
    if simulated and allow_simulated:
        return simulated[0], "SIMULATED"
    if simulated:
        raise RuntimeError("Hanya manifest SIMULATED yang tersedia. Jalankan dengan --allow-simulated hanya untuk reproduksi prototype lama, bukan klaim operasional.")
    raise FileNotFoundError("Manifest ML2 tidak ditemukan pada data/input/vehicle/manifest/.")

def main(allow_simulated=False):
    book, source_status = choose_book(allow_simulated)
    def sheet(name): return pd.read_excel(book, sheet_name=name, skiprows=2)
    trip=sheet("04_TRIP_3M"); sim=sheet("07_SIM_5MIN")
    trip["Departure"]=pd.to_datetime(trip["Departure"]); trip["Arrival"]=pd.to_datetime(trip["Arrival"]); trip["MMSI"]=trip["MMSI"].astype(str)
    trip["Split"]="TRAIN"; trip.loc[trip["Date"].ge(pd.Timestamp("2024-03-01")),"Split"]="TEST"
    trip["destination_port"]=trip["Destination"].astype(str); trip["arrival_hour"]=trip["Arrival"].dt.hour; trip["arrival_dow"]=trip["Arrival"].dt.dayofweek
    trip["minute_of_day"]=trip["Arrival"].dt.hour*60+(trip["Arrival"].dt.minute//5)*5
    sim["Timestamp"]=pd.to_datetime(sim["Timestamp"]); sim["arrival_dow"]=sim["Timestamp"].dt.dayofweek; sim["minute_of_day"]=sim["Timestamp"].dt.hour*60+sim["Timestamp"].dt.minute
    profiles=[]
    for terminal,car,motor,pce in [("Bengkalis","Car arrival BKS","Motor arrival BKS","PCE arrival BKS"),("Pakning","Car arrival PKG","Motor arrival PKG","PCE arrival PKG")]:
        z=sim[["arrival_dow","minute_of_day",car,motor,pce]].copy(); z.columns=["arrival_dow","minute_of_day","car_rate_5min","motor_rate_5min","pce_rate_5min"]; z["terminal"]=terminal; profiles.append(z)
    rates=pd.concat(profiles,ignore_index=True); profile=rates.groupby(["terminal","arrival_dow","minute_of_day"],as_index=False).mean()
    trip=trip.merge(profile.rename(columns={"terminal":"destination_port"}),on=["destination_port","arrival_dow","minute_of_day"],how="left")
    keep=["Trip ID","Date","Split","MMSI","destination_port","arrival_hour","arrival_dow","Capacity PCE","Turnaround min","car_rate_5min","motor_rate_5min","pce_rate_5min"]
    out=trip[keep].rename(columns={"Trip ID":"trip_id","Date":"date","Split":"split","MMSI":"mmsi","Capacity PCE":"capacity_pce","Turnaround min":"turnaround_actual_min"})
    out.to_csv(PROCESSED/"turnaround_training_dataset.csv",index=False); profile.to_csv(PROCESSED/"vehicle_rate_5min.csv",index=False)
    capacity=trip.groupby("MMSI",as_index=False)["Capacity PCE"].median().rename(columns={"MMSI":"mmsi","Capacity PCE":"capacity_pce"}); capacity.to_csv(PROCESSED/"vessel_capacity_derived.csv",index=False)
    provenance={"source_file":str(book.relative_to(PROJECT_ROOT)),"source_status":source_status,"operational_claim_allowed":source_status!="SIMULATED"}
    (PROCESSED/"source_provenance.json").write_text(json.dumps(provenance,indent=2),encoding="utf-8")
    print(json.dumps(provenance,indent=2)); print(f"trips={len(out)}; vessels={out.mmsi.nunique()}; profile_rows={len(profile)}")

if __name__=="__main__":
    p=argparse.ArgumentParser(); p.add_argument("--allow-simulated",action="store_true"); a=p.parse_args(); main(a.allow_simulated)
