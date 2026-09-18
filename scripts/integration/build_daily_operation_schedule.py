"""Buat jadwal harian replay: satu baris untuk setiap leg, bukan setiap tick."""
from pathlib import Path
import sys
import pandas as pd

PROJECT_ROOT=Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path: sys.path.insert(0,str(PROJECT_ROOT))
from scripts.v3_paths import output_root, processed_root
ML1_PROCESSED=processed_root(PROJECT_ROOT)/"ml1"; ML1_OUT=output_root(PROJECT_ROOT)/"01_ml1_eta"; INTEGRATION_OUT=output_root(PROJECT_ROOT)/"03_eta_etd_integration"; REPLAY_OUT=output_root(PROJECT_ROOT)/"04_replay_dashboard"
def main():
    pred=pd.read_csv(ML1_OUT/"tables"/"test_predictions.csv",parse_dates=["timestamp"])
    # Prediksi paling awal sebuah leg adalah informasi ETA pertama yang tersedia.
    pred=pred.sort_values(["leg_id","timestamp"]).groupby("leg_id",as_index=False).first()
    info=pd.read_csv(ML1_PROCESSED/"ml1_eta_training_dataset.csv",parse_dates=["timestamp"])
    info=(info.sort_values(["leg_id","timestamp"]).groupby("leg_id",as_index=False)
          .first()[["leg_id","mmsi","origin_port","destination_port"]])
    s=pred.merge(info,on=["leg_id","mmsi"],how="left"); s["mmsi"]=s.mmsi.astype(str)
    for model in ["random_forest","xgboost"]:
        col="eta_corrected_"+("Random_Forest" if model=="random_forest" else "XGBoost")
        s[f"estimated_arrival_{model}"]=s.timestamp+pd.to_timedelta(s[col],unit="min")
    multi=pd.read_csv(INTEGRATION_OUT/"simulation_input_5min_multimodel.csv",parse_dates=["simulation_tick"])
    multi["mmsi"]=multi.mmsi.astype(str)
    # State terdekat pada waktu prediksi memasok turnaround untuk empat kombinasi model.
    pieces=[]
    for vessel,g in s.groupby("mmsi"):
        q=multi[multi.mmsi.eq(vessel)].sort_values("simulation_tick")
        pieces.append(pd.merge_asof(g.sort_values("timestamp"),q.sort_values("simulation_tick"),
            left_on="timestamp",right_on="simulation_tick",direction="nearest",suffixes=("","_tick")))
    s=pd.concat(pieces,ignore_index=True)
    for eta in ["random_forest","xgboost"]:
        for turn in ["random_forest","xgboost"]:
            c=f"turnaround_corrected_{eta}_{turn}_min"
            s[f"estimated_departure_{eta}_{turn}"]=s[f"estimated_arrival_{eta}"]+pd.to_timedelta(s[c],unit="min")
    keep=["leg_id","mmsi","origin_port","destination_port","timestamp","eta_baseline_min",
          "eta_corrected_Random_Forest","eta_corrected_XGBoost","estimated_arrival_random_forest",
          "estimated_arrival_xgboost"]+[c for c in s.columns if c.startswith("turnaround_corrected_") or c.startswith("estimated_departure_")]
    s[keep].rename(columns={"timestamp":"prediction_time"}).sort_values("prediction_time").to_csv(
        REPLAY_OUT/"daily_operation_schedule.csv",index=False)
    print(f"OK daily_operation_schedule.csv: {len(s)} leg")
if __name__=="__main__": main()
