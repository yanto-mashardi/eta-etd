"""Train ML2 turnaround correction with baseline turnaround + historical/observed demand features."""
from __future__ import annotations
import json, sys
from pathlib import Path
import joblib, numpy as np, pandas as pd, yaml
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder
from xgboost import XGBRegressor
ROOT=Path(__file__).resolve().parents[2]
PROJ=yaml.safe_load((ROOT/'config/project_config.yaml').read_text(encoding='utf-8')) or {}; CFG=PROJ['ml2']; rnd=int(PROJ.get('ml1',{}).get('random_state',42)); ratio=float(PROJ.get('research',{}).get('validation',{}).get('test_ratio',.20))
_run=''
try:
    import os;_run=os.getenv('LOCAL_RUN_RUN_ROOT','').strip()
except:pass
PROCESSED=(Path(_run)/'data_processed' if _run else ROOT/'data/processed')/'ml2'
OUT=(Path(_run)/'outputs' if _run else ROOT/'outputs')/'02_ml2_turnaround'
MODEL=ROOT/'models/ML2_TURNAROUND_CORRECTION/06_model_saved'
FEATURES=list(CFG['features']); CAT=['mmsi','terminal']; NUM=[x for x in FEATURES if x not in CAT]
def metrics(name,y,p):return {'model':name,'MAE_min':mean_absolute_error(y,p),'RMSE_min':mean_squared_error(y,p)**.5,'n_test':len(y)}
def main():
    path=PROCESSED/'turnaround_training_dataset.csv';d=pd.read_csv(path,parse_dates=['arrival_timestamp']).sort_values('arrival_timestamp').reset_index(drop=True)
    req=set([x for x in FEATURES if x!='turnaround_base_min']+['turnaround_actual_min']);missing=req-set(d.columns)
    if missing:raise ValueError('ML2 columns missing: '+','.join(sorted(missing)))
    split=max(1,min(len(d)-1,int(len(d)*(1-ratio))));train=d.iloc[:split].copy();test=d.iloc[split:].copy();keys=['mmsi','terminal']
    # Baseline is derived from training data only, avoiding test leakage.
    base=train.groupby(keys).turnaround_actual_min.median();fallback=float(train.turnaround_actual_min.median())
    def attach(x):
        x=x.copy();x['turnaround_base_min']=[float(base.get((r.mmsi,r.terminal),fallback)) for r in x.itertuples()];x['correction_target_min']=x.turnaround_actual_min-x.turnaround_base_min;return x
    train=attach(train);test=attach(test)
    prep=ColumnTransformer([('num',Pipeline([('imp',SimpleImputer(strategy='median'))]),NUM),('cat',Pipeline([('imp',SimpleImputer(strategy='most_frequent')),('onehot',OneHotEncoder(handle_unknown='ignore'))]),CAT)])
    models={'Random Forest':RandomForestRegressor(n_estimators=500,min_samples_leaf=2,max_features=.8,random_state=rnd,n_jobs=-1),'XGBoost':XGBRegressor(n_estimators=500,max_depth=5,learning_rate=.04,subsample=.85,colsample_bytree=.85,objective='reg:squarederror',random_state=rnd,n_jobs=-1)}
    OUT.mkdir(parents=True,exist_ok=True);(OUT/'tables').mkdir(exist_ok=True);MODEL.mkdir(parents=True,exist_ok=True)
    rows=[];pred=test[['trip_id','arrival_timestamp','mmsi','terminal','turnaround_actual_min','turnaround_base_min']].copy();trained={}
    for name,est in models.items():
        pipe=Pipeline([('preprocess',prep),('model',est)]);pipe.fit(train[FEATURES],train.correction_target_min);corr=pipe.predict(test[FEATURES]);corrected=np.maximum(0,test.turnaround_base_min.to_numpy()+corr);rows.append(metrics(name,test.turnaround_actual_min,corrected));pred[f'correction_{name.replace(" ","_")}']=corr;pred[f'turnaround_corrected_{name.replace(" ","_")}']=corrected;fname='random_forest' if name.startswith('Random') else 'xgboost';joblib.dump(pipe,MODEL/f'ml2_{fname}.joblib',compress=3);trained[name]=(pipe,rows[-1]['MAE_min'])
    met=pd.DataFrame(rows).sort_values('MAE_min');winner=str(met.iloc[0].model);pipe=trained[winner][0]
    base_map={f"{k[0]}|{k[1]}":float(v) for k,v in base.items()}
    payload={'winner':winner.lower().replace(' ','_'),'model':pipe,'features':FEATURES,'base_by_vessel_terminal':base_map,'fallback_turnaround_base_min':fallback,'arrival_definition':'terminal_berth_arrival','method':'ETA_corrected + turnaround_base + turnaround_correction_ML2'}
    joblib.dump(payload,MODEL/'ml2_turnaround_selected.joblib',compress=3);met.to_csv(OUT/'tables/ml2_model_metrics.csv',index=False);pred.to_csv(OUT/'tables/ml2_test_predictions.csv',index=False)
    info={'split_method':'chronological','test_ratio':ratio,'features':FEATURES,'target':'turnaround_actual_min - turnaround_base_min','turnaround_base_source':'training_only_median_by_vessel_terminal','winner':winner};(OUT/'tables/ml2_split_information.json').write_text(json.dumps(info,indent=2),encoding='utf-8');print(met.to_string(index=False))
if __name__=='__main__':main()
