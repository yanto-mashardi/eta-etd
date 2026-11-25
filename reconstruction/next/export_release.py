"""Run in the original Local Run Python environment. No training or test-set selection."""
import argparse,csv,json,hashlib,shutil,re,platform
from pathlib import Path
from importlib.metadata import version
import joblib
import pandas as pd
from events import read_seed
ROLES=("eta","vtt_early","vtt_conventional")
def sha(p):
    with Path(p).open("rb") as f:return hashlib.file_digest(f,"sha256").hexdigest()
def write(p,obj):p.write_text(json.dumps(obj,indent=2,allow_nan=False),encoding="utf-8")
def main():
    p=argparse.ArgumentParser()
    p.add_argument("--results",required=True,type=Path)
    p.add_argument("--history",required=True,type=Path)
    p.add_argument("--eta-data",required=True,type=Path)
    p.add_argument("--early-data",required=True,type=Path)
    p.add_argument("--conventional-data",required=True,type=Path)
    p.add_argument("--output",required=True,type=Path)
    p.add_argument("--release",required=True)
    a=p.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+",a.release):raise ValueError("Invalid release ID")
    summary=json.loads((a.results/"ML_V2_VALIDATION_SUMMARY.json").read_text(encoding="utf-8-sig"))
    if summary["status"]!="PASS_ML_V2_VALIDATION_RESEARCH":raise ValueError("Local selection not PASS")
    selected=summary["selected_ML_algorithms"]
    pred=pd.read_csv(a.results/"ML_V2_EACH_MODEL_VALIDATION_PREDICTIONS.csv",dtype={"cycle_id":str})
    history=read_seed(a.history)
    target=a.output/a.release
    target.mkdir(parents=True,exist_ok=False)
    deps={n:version(n) for n in ("joblib","numpy","pandas","scikit-learn","scipy","threadpoolctl")}
    manifest={"release_id":a.release,"python_version":platform.python_version(),"dependencies":deps,"models":{},"history_sha256":sha(a.history),"selection_sha256":sha(a.results/"ML_V2_VALIDATION_SUMMARY.json")}
    cases=[]
    for role,data in zip(ROLES,(a.eta_data,a.early_data,a.conventional_data)):
        alg=selected[role]
        if alg=="catboost":deps["catboost"]=version("catboost")
        if alg=="xgb":deps["xgboost"]=version("xgboost")
        src=a.results/f"ML_V2_{role}_{alg}.joblib"
        if sha(src)!=summary["candidate_models_saved"][role][alg] or sha(data)!=summary["input_sha256"][role]:raise ValueError("Source provenance mismatch "+role)
        b=joblib.load(src)
        if b["role"]!=role or b["algorithm"]!=alg:raise ValueError("Bundle mismatch")
        if b["sklearn_version"]!=deps["scikit-learn"] or b["python_version"]!=manifest["python_version"]:raise ValueError("Use original training environment")
        df=pd.read_csv(data,dtype={"mmsi":str,"cycle_id":str})
        va=df[df.split=="VALIDATION"].set_index("cycle_id",verify_integrity=True)
        ref=pred[(pred.role==role)&(pred.algorithm==alg)].set_index("cycle_id",verify_integrity=True)
        if set(va.index)!=set(ref.index):raise ValueError("Reference coverage mismatch")
        for cid,row in va.iterrows():
            x={k:(None if pd.isna(row[k]) else row[k].item() if hasattr(row[k],"item") else row[k]) for k in b["feature_names"]}
            cases.append({"role":role,"cycle_id":cid,"features":x,"expected_duration_min":float(ref.loc[cid,"predicted_duration_min"])})
        shutil.copyfile(src,target/(role+".joblib"))
        manifest["models"][role]={"sha256":sha(src),"algorithm":alg}
    shutil.copyfile(a.history,target/"historical_cycles.csv")
    write(target/"validation_fixture.json",{"release_id":a.release,"cases":cases})
    manifest["fixture_sha256"]=sha(target/"validation_fixture.json")
    write(target/"manifest.json",manifest)
    (target/"requirements.txt").write_text("\n".join(f"{k}=={v}" for k,v in sorted(deps.items()))+"\n",encoding="utf-8")
    print("EXPORTED",target,len(history),"historical cycles",len(cases),"validation predictions")
if __name__=="__main__":main()
