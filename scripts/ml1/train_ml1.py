"""Train ML1 ETA residual correction using project_config.yaml and chronological service-leg split."""
from __future__ import annotations
import json, sys
from pathlib import Path
import joblib, matplotlib.pyplot as plt, numpy as np, pandas as pd, yaml
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder
from xgboost import XGBRegressor

NUM=["distance_to_destination_nm","sog_kn","cog_deg","heading_error_deg","eta_baseline_min","hour","day_of_week"]
CAT=["mmsi","origin_port","destination_port"]
TARGET="eta_residual_min"
def root(): return Path(__file__).resolve().parents[2]
def paths():
    r=root()
    if str(r) not in sys.path: sys.path.insert(0,str(r))
    try:
        from scripts.v3_paths import output_root, processed_root, model_artifact_root
        return output_root(r),processed_root(r),model_artifact_root(r)
    except Exception:
        return r/'outputs',r/'data/processed',r/'models'
def metric(name,truth,pred):
    return {"model":name,"MAE_min":mean_absolute_error(truth,pred),"RMSE_min":mean_squared_error(truth,pred)**0.5,"Bias_min":float(np.mean(pred-truth)),"R2":r2_score(truth,pred),"n_test":len(truth)}
def main():
    proj=yaml.safe_load((root()/"config/project_config.yaml").read_text(encoding="utf-8")) or {}
    cfg=proj["ml1"]; val=proj.get("research",{}).get("validation",{})
    ratio=float(val.get("test_ratio",0.20)); rnd=int(cfg.get("random_state",42))
    outroot,processed,modelroot=paths(); path=processed/'ml1/ml1_eta_training_dataset.csv'
    if not path.exists(): raise FileNotFoundError(path)
    df=pd.read_csv(path,parse_dates=["timestamp","arrival_time"]).sort_values(["arrival_time","timestamp"])
    legs=df[["leg_id","arrival_time"]].drop_duplicates().sort_values("arrival_time").reset_index(drop=True)
    split=max(1,min(len(legs)-1,int(len(legs)*(1-ratio))))
    train_ids=set(legs.iloc[:split].leg_id); train=df[df.leg_id.isin(train_ids)].copy(); test=df[~df.leg_id.isin(train_ids)].copy()
    if train.empty or test.empty: raise ValueError("Leg tidak cukup untuk chronological split")
    prep=ColumnTransformer([("numeric",Pipeline([("imputer",SimpleImputer(strategy="median"))]),NUM),("categorical",Pipeline([("imputer",SimpleImputer(strategy="most_frequent")),("onehot",OneHotEncoder(handle_unknown="ignore"))]),CAT)])
    models={"Random Forest":RandomForestRegressor(n_estimators=500,min_samples_leaf=2,max_features=.8,random_state=rnd,n_jobs=-1),"XGBoost":XGBRegressor(n_estimators=500,max_depth=5,learning_rate=.04,subsample=.85,colsample_bytree=.85,objective="reg:squarederror",random_state=rnd,n_jobs=-1)}
    out=outroot/'01_ml1_eta'; mroot=modelroot/'ML1_ETA_CORRECTION'; mdir=mroot/'06_model_saved'; tdir=out/'tables'; fdir=out/'figures'; vdir=mroot/'05_validation'; metdir=mroot/'07_metrics'; pdir=mroot/'08_prediction'
    for d in [mdir,tdir,fdir,vdir,metdir,pdir]:d.mkdir(parents=True,exist_ok=True)
    rows=[metric("Baseline (jarak/kecepatan)",test.actual_remaining_min,test.eta_baseline_min)]
    preds=test[["leg_id","mmsi","timestamp","arrival_time","arrival_berth","actual_remaining_min","eta_baseline_min","eta_residual_min"]].copy()
    for name,est in models.items():
        pipe=Pipeline([("preprocess",prep),("model",est)]); pipe.fit(train[NUM+CAT],train[TARGET])
        residual=pipe.predict(test[NUM+CAT]); eta=test.eta_baseline_min.to_numpy()+residual
        preds[f"residual_prediction_{name.replace(' ','_')}"]=residual; preds[f"eta_corrected_{name.replace(' ','_')}"]=eta
        rows.append(metric(name+" corrected ETA",test.actual_remaining_min,eta)); joblib.dump(pipe,mdir/f"ml1_{name.lower().replace(' ','_')}.joblib",compress=3)
    metrics=pd.DataFrame(rows); metrics.to_csv(tdir/'metrics_comparison.csv',index=False); metrics.to_csv(metdir/'metrics_comparison.csv',index=False); preds.to_csv(tdir/'test_predictions.csv',index=False); preds.to_csv(pdir/'test_predictions.csv',index=False)
    info={"arrival_definition":"terminal_berth_arrival","split_method":"chronological","test_ratio":ratio,"split_unit":"service_leg","train_legs":int(train.leg_id.nunique()),"test_legs":int(test.leg_id.nunique()),"train_arrival_start":str(train.arrival_time.min()),"train_arrival_end":str(train.arrival_time.max()),"test_arrival_start":str(test.arrival_time.min()),"test_arrival_end":str(test.arrival_time.max()),"features":NUM+CAT,"target":TARGET}
    (tdir/'split_information.json').write_text(json.dumps(info,indent=2),encoding='utf-8'); (vdir/'split_information.json').write_text(json.dumps(info,indent=2),encoding='utf-8')
    plt.figure(figsize=(8,4.5)); plt.bar(metrics.model,metrics.MAE_min); plt.ylabel('MAE (menit)'); plt.xticks(rotation=14,ha='right'); plt.tight_layout(); plt.savefig(fdir/'mae_model_comparison.png',dpi=180); plt.close()
    print(metrics.to_string(index=False))
if __name__=='__main__':main()
