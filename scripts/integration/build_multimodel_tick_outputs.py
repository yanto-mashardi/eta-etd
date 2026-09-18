"""Publikasikan keluaran RF dan XGBoost pada setiap tick replay lima menit.

Jika xgboost terpasang, inferensi dilakukan langsung dari artefak model. Fallback
dipakai hanya untuk replay historis pada lingkungan tanpa xgboost: prediksi XGB
tersimpan pada titik AIS sumber diinterpolasi ke grid lima menit.
"""
from pathlib import Path
import sys
import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path: sys.path.insert(0, str(PROJECT_ROOT))
from scripts.v3_paths import output_root, processed_root, model_artifact_root, logs_root
ML1_PROCESSED = processed_root(PROJECT_ROOT)/"ml1"
ML1_MODELS = model_artifact_root(PROJECT_ROOT)/"ML1_ETA_CORRECTION"/"06_model_saved"
ML2_PROCESSED = processed_root(PROJECT_ROOT)/"ml2"
ML2_MODELS = model_artifact_root(PROJECT_ROOT)/"ML2_TURNAROUND_CORRECTION"/"06_model_saved"
INTEGRATION_OUT = output_root(PROJECT_ROOT)/"03_eta_etd_integration"
LEGACY_OUT = output_root(PROJECT_ROOT)/"04_replay_dashboard"
INTEGRATION_OUT.mkdir(parents=True, exist_ok=True)
F1 = ["distance_to_destination_nm","sog_kn","cog_deg","heading_error_deg","eta_baseline_min","hour","day_of_week","mmsi","origin_port","destination_port"]
F2 = ["mmsi","destination_port","arrival_hour","arrival_dow","capacity_pce","car_rate_5min","motor_rate_5min","pce_rate_5min"]

def key(name): return name.lower().replace(" ", "_")

def xgb_from_saved_points(x):
    """Interpolasi prediksi XGB pada dua observasi AIS yang mengapit satu tick."""
    p = pd.read_csv(model_artifact_root(PROJECT_ROOT)/"ML1_ETA_CORRECTION"/"08_prediction"/"test_predictions.csv", parse_dates=["timestamp"])
    p["mmsi"] = p.mmsi.astype(str)
    p = p[["mmsi","timestamp","residual_prediction_XGBoost"]]
    a = x.copy()
    a["source_time_before"] = pd.to_datetime(a["source_time_before"], utc=True)
    a["source_time_after"] = pd.to_datetime(a["source_time_after"], utc=True)
    a = a.merge(p, left_on=["mmsi","source_time_before"], right_on=["mmsi","timestamp"], how="left")
    b = a.merge(p, left_on=["mmsi","source_time_after"], right_on=["mmsi","timestamp"], how="left", suffixes=("_before","_after"))
    c0, c1 = b["residual_prediction_XGBoost_before"], b["residual_prediction_XGBoost_after"]
    return (c0 + b.interpolation_weight * (c1-c0)).fillna(b.eta_correction_min).to_numpy()

def rf_ml2_bundle():
    """Latih ulang RF ML2 dari 80% historis bila bundle dua-model belum tersedia."""
    d = pd.read_csv(ML2_PROCESSED/"turnaround_training_dataset.csv", parse_dates=["date"])
    d["mmsi"] = d.mmsi.astype(str)
    train = d[d.date.lt("2024-03-01")].copy()
    base = train.groupby(["mmsi","destination_port"]).turnaround_actual_min.median()
    train["turnaround_base_min"] = train.set_index(["mmsi","destination_port"]).index.map(base)
    train["correction_target_min"] = train.turnaround_actual_min-train.turnaround_base_min
    prep = ColumnTransformer([("cat",OneHotEncoder(handle_unknown="ignore"),["mmsi","destination_port"]),
        ("num",SimpleImputer(strategy="median"),[c for c in F2 if c not in ["mmsi","destination_port"]])])
    pipe = Pipeline([("prep",prep),("model",RandomForestRegressor(n_estimators=500,min_samples_leaf=3,random_state=42,n_jobs=-1))])
    pipe.fit(train[F2],train.correction_target_min)
    return {"models":{"Random Forest":pipe},"features":F2,"base_by_vessel_terminal":base.to_dict(),"mode":"retrained_rf_fallback"}

def main():
    x = pd.read_csv(ML1_PROCESSED/"replay_20pct"/"eta_state_rf_source.csv",parse_dates=["simulation_tick"])
    x["mmsi"] = x.mmsi.astype(str); x = x.sort_values(["mmsi","simulation_tick"]).reset_index(drop=True)
    gap=x.groupby("mmsi").simulation_tick.diff().dt.total_seconds().div(60).fillna(999)
    x["journey_id"]=x.mmsi+"_J"+gap.gt(35).groupby(x.mmsi).cumsum().astype(str)
    rf = joblib.load(ML1_MODELS/"ml1_random_forest.joblib")
    x["eta_correction_random_forest_min"]=rf.predict(x[F1])
    try:
        xgb=joblib.load(ML1_MODELS/"ml1_xgboost.joblib")
        x["eta_correction_xgboost_min"]=xgb.predict(x[F1]); xgb_mode="direct_model"
    except (ImportError, ModuleNotFoundError):
        x["eta_correction_xgboost_min"]=xgb_from_saved_points(x); xgb_mode="interpolated_saved_model_output"
    for m in ["random_forest","xgboost"]:
        x[f"eta_corrected_{m}_min"]=(x.eta_baseline_min+x[f"eta_correction_{m}_min"]).clip(lower=0)
        x[f"estimated_arrival_{m}"]=x.simulation_tick+pd.to_timedelta(x[f"eta_corrected_{m}_min"],unit="min")

    cap_path=PROJECT_ROOT/"data"/"reference"/"vessel_master"/"vessel_capacity.csv"
    cap=pd.read_csv(cap_path if cap_path.exists() else ML2_PROCESSED/"vessel_capacity_derived.csv"); cap["mmsi"]=cap.mmsi.astype(str)
    x=x.merge(cap,on="mmsi",how="left"); x["capacity_pce"]=x.capacity_pce.fillna(cap.capacity_pce.median())
    try:
        bundle=joblib.load(ML2_MODELS/"ml2_turnaround_models.joblib")
        ml2_mode="direct_models"
    except (FileNotFoundError, ImportError, ModuleNotFoundError):
        bundle=rf_ml2_bundle(); ml2_mode="rf_direct_xgb_saved_output"
    base=bundle["base_by_vessel_terminal"]
    x["turnaround_base_min"]=[base.get((str(r.mmsi),r.destination_port),np.nan) for _,r in x.iterrows()]
    x["turnaround_base_min"]=x.turnaround_base_min.fillna(np.median(list(base.values())))
    profile=pd.read_csv(INTEGRATION_OUT/"vehicle_rate_5min.csv")
    legacy=pd.read_csv(LEGACY_OUT/"legacy_simulation_input_5min.csv",parse_dates=["simulation_tick"])
    legacy["mmsi"]=legacy.mmsi.astype(str)
    saved_xgb=legacy[legacy.state_type.eq("AIS_SAILING")][["simulation_tick","mmsi","turnaround_correction_ml2_min"]].drop_duplicates(["simulation_tick","mmsi"])
    for em in ["random_forest","xgboost"]:
        arrival=x[f"estimated_arrival_{em}"]
        z=pd.DataFrame({"mmsi":x.mmsi,"destination_port":x.destination_port,"arrival_hour":arrival.dt.hour,
            "arrival_dow":arrival.dt.dayofweek,"capacity_pce":x.capacity_pce,
            "minute_of_day":arrival.dt.hour*60+(arrival.dt.minute//5)*5})
        z=z.merge(profile.rename(columns={"terminal":"destination_port"}),on=["destination_port","arrival_dow","minute_of_day"],how="left")
        for c in ["car_rate_5min","motor_rate_5min","pce_rate_5min"]: z[c]=z[c].fillna(profile[c].median())
        for model,pipe in bundle["models"].items():
            mk=key(model); corr=pipe.predict(z[bundle["features"]]); pref=f"{em}_{mk}"
            x[f"turnaround_correction_{pref}_min"]=corr
            x[f"turnaround_corrected_{pref}_min"]=(x.turnaround_base_min+corr).clip(lower=0)
            x[f"etd_{pref}"]=arrival+pd.to_timedelta(x[f"turnaround_corrected_{pref}_min"],unit="min")
        # XGB fallback is the previously evaluated XGB output; direct bundle replaces it.
        if "XGBoost" in bundle["models"]:
            pipe=bundle["models"]["XGBoost"]; corr=pipe.predict(z[bundle["features"]])
        else:
            corr=x[["simulation_tick","mmsi"]].merge(saved_xgb,on=["simulation_tick","mmsi"],how="left").turnaround_correction_ml2_min.fillna(0).to_numpy()
        pref=f"{em}_xgboost"; x[f"turnaround_correction_{pref}_min"]=corr
        x[f"turnaround_corrected_{pref}_min"]=(x.turnaround_base_min+corr).clip(lower=0)
        x[f"etd_{pref}"]=arrival+pd.to_timedelta(x[f"turnaround_corrected_{pref}_min"],unit="min")
    x["state_type"]="AIS_SAILING"; x["source_ais"]="AIS historis; interpolasi grid 5-menit"
    x["source_vehicle"]="Profil manifest 5-menit; belum CCTV aktual"
    x["ml1_xgboost_inference"]=xgb_mode; x["ml2_inference"]=ml2_mode
    out=INTEGRATION_OUT/"simulation_input_5min_multimodel.csv"; x.sort_values(["simulation_tick","mmsi"]).to_csv(out,index=False)
    print(f"OK {out}: {len(x)} state; ETA RF/XGB; ETD empat kombinasi; ML1-XGB={xgb_mode}; ML2={ml2_mode}")
if __name__=="__main__": main()
