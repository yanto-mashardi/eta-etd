
from __future__ import annotations
import csv, hashlib, json, os, shutil, subprocess, sys, traceback
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
AIS_HISTORY = ROOT / "data" / "01_DATA_SOURCE" / "AIS" / "historical"
VEH_HISTORY = ROOT / "data" / "01_DATA_SOURCE" / "VEHICLE_HISTORICAL"
LEGACY_MANIFEST = ROOT / "data" / "input" / "vehicle" / "manifest"
RUNS = ROOT / "outputs" / "training_runs"
REGISTRY = ROOT / "config" / "registry" / "training_run_registry.csv"
STATUS = ROOT / "outputs" / "inspection" / "training_status.json"
PYTHON = Path(sys.executable)

AIS_ALIASES = {
    "created_at":["created_at","timestamp","time","datetime","date_time","basedatetime","base_datetime","dt"],
    "mmsi":["mmsi","vessel_id","ship_id","imo"],
    "lat":["lat","latitude","y"],
    "lon":["lon","lng","longitude","x"],
    "sog":["sog","speed","speed_over_ground","speed_knots"],
    "cog":["cog","course","course_over_ground","heading"],
}

def stamp():
    return datetime.now().astimezone().isoformat(timespec="seconds")

def write_status(**kw):
    STATUS.parent.mkdir(parents=True,exist_ok=True)
    current={}
    try: current=json.loads(STATUS.read_text(encoding="utf-8"))
    except Exception: pass
    current.update(kw)
    current["updated_at"]=stamp()
    tmp=STATUS.with_suffix(".tmp")
    tmp.write_text(json.dumps(current,indent=2,ensure_ascii=False),encoding="utf-8")
    os.replace(tmp,STATUS)

def sha256(path:Path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""): h.update(chunk)
    return h.hexdigest()

def read_tabular(path:Path):
    s=path.suffix.lower()
    if s==".csv": return pd.read_csv(path)
    if s in {".xlsx",".xls"}: return pd.read_excel(path)
    if s==".parquet": return pd.read_parquet(path)
    return None

def normalize_ais(df:pd.DataFrame):
    norm={str(c).strip().lower().replace(" ","_"):c for c in df.columns}
    out={}
    for target, aliases in AIS_ALIASES.items():
        source=next((norm[a] for a in aliases if a in norm),None)
        if source is None:
            raise ValueError(f"kolom AIS '{target}' tidak ditemukan")
        out[target]=df[source]
    z=pd.DataFrame(out)
    z["created_at"]=pd.to_datetime(z["created_at"],errors="coerce",utc=True)
    for c in ["lat","lon","sog","cog"]: z[c]=pd.to_numeric(z[c],errors="coerce")
    z["mmsi"]=pd.to_numeric(z["mmsi"],errors="coerce").astype("Int64")
    z=z.dropna(subset=["created_at","mmsi","lat","lon","sog"])
    return z

def build_all_ais(run_dir:Path):
    files=[]
    for ext in ("*.csv","*.xlsx","*.xls","*.parquet"):
        files += list(AIS_HISTORY.rglob(ext)) if AIS_HISTORY.exists() else []
    used=[]; skipped=[]; frames=[]
    for f in sorted(set(files)):
        try:
            raw=read_tabular(f)
            if raw is None or raw.empty: raise ValueError("file kosong/tidak didukung")
            z=normalize_ais(raw)
            if z.empty: raise ValueError("tidak ada baris AIS valid")
            z["_source_file"]=str(f.relative_to(ROOT))
            frames.append(z); used.append({"file":str(f.relative_to(ROOT)),"rows":len(z),"sha256":sha256(f)})
        except Exception as e:
            skipped.append({"file":str(f.relative_to(ROOT)),"reason":str(e)})
    if not frames:
        raise RuntimeError(f"Tidak ada file AIS kompatibel di {AIS_HISTORY}")
    all_df=pd.concat(frames,ignore_index=True)
    all_df=all_df.drop_duplicates(subset=["created_at","mmsi","lat","lon","sog","cog"]).sort_values(["mmsi","created_at"])
    path=run_dir/"input"/"ais_history_all.csv"
    path.parent.mkdir(parents=True,exist_ok=True)
    all_df.drop(columns=["_source_file"]).to_csv(path,index=False)
    return path,used,skipped,len(all_df)

def valid_manifest(path:Path):
    try:
        xl=pd.ExcelFile(path)
        return "04_TRIP_3M" in xl.sheet_names and "07_SIM_5MIN" in xl.sheet_names
    except Exception:
        return False

def read_manifest_sheet(path:Path,name:str):
    # Existing workbook uses two descriptive rows before header.
    for skip in (2,0):
        try:
            d=pd.read_excel(path,sheet_name=name,skiprows=skip)
            if len(d.columns)>2 and not d.empty:return d
        except Exception: pass
    raise ValueError(f"sheet {name} tidak terbaca")

def build_all_vehicle(run_dir:Path):
    candidates=[]
    for base in [VEH_HISTORY,LEGACY_MANIFEST]:
        if base.exists():
            candidates += list(base.rglob("*.xlsx"))
    used=[]; skipped=[]; trips=[]; sims=[]
    for f in sorted(set(candidates)):
        if not valid_manifest(f):
            skipped.append({"file":str(f.relative_to(ROOT)),"reason":"sheet 04_TRIP_3M/07_SIM_5MIN tidak lengkap"})
            continue
        try:
            t=read_manifest_sheet(f,"04_TRIP_3M")
            s=read_manifest_sheet(f,"07_SIM_5MIN")
            t["_source_file"]=str(f.relative_to(ROOT))
            s["_source_file"]=str(f.relative_to(ROOT))
            trips.append(t); sims.append(s)
            used.append({"file":str(f.relative_to(ROOT)),"trip_rows":len(t),"sim_rows":len(s),"sha256":sha256(f)})
        except Exception as e:
            skipped.append({"file":str(f.relative_to(ROOT)),"reason":str(e)})
    if not trips:
        raise RuntimeError("Tidak ada workbook histori kendaraan kompatibel untuk ML2.")
    trip=pd.concat(trips,ignore_index=True).drop_duplicates()
    sim=pd.concat(sims,ignore_index=True).drop_duplicates()
    out=run_dir/"input"/"vehicle_history_all.xlsx"
    out.parent.mkdir(parents=True,exist_ok=True)
    with pd.ExcelWriter(out,engine="openpyxl") as w:
        trip.drop(columns=["_source_file"],errors="ignore").to_excel(w,sheet_name="04_TRIP_3M",index=False,startrow=2)
        sim.drop(columns=["_source_file"],errors="ignore").to_excel(w,sheet_name="07_SIM_5MIN",index=False,startrow=2)
    return out,used,skipped,len(trip),len(sim)

def run_cmd(args, env, log):
    with log.open("a",encoding="utf-8") as f:
        f.write("\\n$ "+" ".join(map(str,args))+"\\n")
        f.flush()
        p=subprocess.run(args,cwd=ROOT,env=env,stdout=f,stderr=subprocess.STDOUT,text=True)
    if p.returncode!=0:
        raise RuntimeError(f"Command gagal ({p.returncode}): {' '.join(map(str,args))}")

def read_metrics(path:Path):
    if not path.exists(): return []
    return pd.read_csv(path).to_dict("records")

def metric(row,key):
    for k in [key,key.upper(),f"{key.upper()}_min",f"{key}_min"]:
        if k in row and pd.notna(row[k]):
            try:return float(row[k])
            except Exception: pass
    return None

def append_registry(rows):
    REGISTRY.parent.mkdir(parents=True,exist_ok=True)
    fields=["candidate_id","run_id","scope","algorithm","created_at","mae_min","rmse_min","r2","n_test","artifact_path","source_files","source_rows","source_status","target_source","feature_source","queue_proxy_used","status"]
    exists=REGISTRY.exists()
    with REGISTRY.open("a",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields)
        if not exists:w.writeheader()
        for r in rows:w.writerow({k:r.get(k) for k in fields})

def find_first(base:Path,names):
    for n in names:
        x=list(base.rglob(n))
        if x:return x[0]
    return None

def main():
    run_id=datetime.now().strftime("TRAIN_%Y%m%d_%H%M%S")
    run_dir=RUNS/run_id
    run_dir.mkdir(parents=True,exist_ok=True)
    log=run_dir/"training.log"
    write_status(status="RUNNING",run_id=run_id,stage="scan_history",started_at=stamp(),message="Membaca seluruh data histori")
    manifest={"run_id":run_id,"started_at":stamp()}
    try:
        ais_path,ais_used,ais_skipped,ais_rows=build_all_ais(run_dir)
        cctv_files=[]
        if CCTV_HISTORY.exists():
            for ext in ("*.csv","*.xlsx","*.xls","*.parquet"):
                cctv_files += list(CCTV_HISTORY.rglob(ext))
        cctv_used=[{"file":str(f.relative_to(ROOT)),"sha256":sha256(f)} for f in sorted(set(cctv_files))]
        manifest.update({
            "ais":{"used":ais_used,"skipped":ais_skipped,"rows":ais_rows},
            "cctv_history":{"used":cctv_used,"folder":str(CCTV_HISTORY.relative_to(ROOT))}
        })
        (run_dir/"source_manifest.json").write_text(json.dumps(manifest,indent=2,ensure_ascii=False),encoding="utf-8")

        env=os.environ.copy()
        env["LOCAL_RUN_RUN_ROOT"]=str(run_dir)
        env["BIMA2_ML1_INPUT_FILE"]=str(ais_path)
        env["BIMA2_ML2_AIS_INPUT_FILE"]=str(ais_path)

        write_status(status="RUNNING",run_id=run_id,stage="ml1_dataset",message=f"ML1: {ais_rows} AIS rows dari {len(ais_used)} file")
        run_cmd([str(PYTHON),str(ROOT/"scripts/ml1/build_ml1_dataset.py")],env,log)

        write_status(status="RUNNING",run_id=run_id,stage="ml1_training",message="Melatih ML1 Random Forest dan XGBoost")
        run_cmd([str(PYTHON),str(ROOT/"scripts/ml1/train_ml1.py")],env,log)

        write_status(status="RUNNING",run_id=run_id,stage="ml2_dataset",
                     message=f"ML2: reconstruct turnaround AIS + CCTV 5-min history dari {len(cctv_used)} file")
        run_cmd([str(PYTHON),str(ROOT/"scripts/ml2/build_ml2_history_dataset.py")],env,log)

        ml2_dataset=run_dir/"data_processed"/"ml2"/"turnaround_training_dataset.csv"
        ml2_rows_count=len(pd.read_csv(ml2_dataset)) if ml2_dataset.exists() else 0
        ml2_prov_path=run_dir/"data_processed"/"ml2"/"source_provenance.json"
        ml2_prov=json.loads(ml2_prov_path.read_text(encoding="utf-8")) if ml2_prov_path.exists() else {}
        manifest["ml2"]={
            "paired_rows":ml2_rows_count,
            "source_status":ml2_prov.get("source_status"),
            "target_source":ml2_prov.get("target_source"),
            "feature_source":ml2_prov.get("feature_source"),
            "queue_proxy_used":ml2_prov.get("queue_proxy_used"),
        }
        (run_dir/"source_manifest.json").write_text(json.dumps(manifest,indent=2,ensure_ascii=False),encoding="utf-8")

        write_status(status="RUNNING",run_id=run_id,stage="ml2_training",
                     message=f"Melatih ML2 RF/XGBoost dari {ml2_rows_count} pasangan AIS-turnaround + CCTV 5-min")
        run_cmd([str(PYTHON),str(ROOT/"scripts/ml2/train_ml2_manifest.py")],env,log)

        model_root=run_dir/"model_artifacts"
        ml1_metrics=find_first(model_root,["metrics_comparison.csv","legacy_metrics_comparison.csv"])
        ml2_metrics=find_first(model_root,["ml2_model_metrics.csv"])
        ml1_rows=read_metrics(ml1_metrics) if ml1_metrics else []
        ml2_rows=read_metrics(ml2_metrics) if ml2_metrics else []

        registry=[]
        for scope,rows in [("ML1",ml1_rows),("ML2",ml2_rows)]:
            for row in rows:
                name=str(row.get("model",""))
                key="xgboost" if "xg" in name.lower() else "random_forest" if ("random" in name.lower() or "forest" in name.lower()) else "baseline"
                if key=="baseline": continue
                artifact=find_first(model_root,[f"ml1_{key}.joblib" if scope=="ML1" else f"ml2_{key}.joblib"])
                if not artifact: continue
                cid=f"{run_id}:{scope}:{key}"
                registry.append({
                    "candidate_id":cid,"run_id":run_id,"scope":scope,"algorithm":key,"created_at":stamp(),
                    "mae_min":metric(row,"mae"),"rmse_min":metric(row,"rmse"),"r2":metric(row,"r2"),
                    "n_test":row.get("n_test"),"artifact_path":str(artifact.relative_to(ROOT)),
                    "source_files":len(ais_used) if scope=="ML1" else len(cctv_used)+len(ais_used),
                    "source_rows":ais_rows if scope=="ML1" else ml2_rows_count,
                    "source_status":"AIS_HISTORICAL" if scope=="ML1" else ml2_prov.get("source_status"),
                    "target_source":"AIS_ARRIVAL_RESIDUAL" if scope=="ML1" else ml2_prov.get("target_source"),
                    "feature_source":"AIS_NAVIGATION" if scope=="ML1" else ml2_prov.get("feature_source"),
                    "queue_proxy_used":False if scope=="ML1" else ml2_prov.get("queue_proxy_used"),
                    "status":"CANDIDATE",
                })
        append_registry(registry)
        result={"run_id":run_id,"status":"SUCCESS","finished_at":stamp(),"manifest":manifest,"candidates":registry}
        (run_dir/"result.json").write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding="utf-8")
        write_status(status="SUCCESS",run_id=run_id,stage="done",finished_at=stamp(),message=f"Training selesai; {len(registry)} candidate model tersimpan",candidates=registry)
    except Exception as e:
        tb=traceback.format_exc()
        log.write_text((log.read_text(encoding="utf-8") if log.exists() else "")+"\\n"+tb,encoding="utf-8")
        write_status(status="ERROR",run_id=run_id,stage="error",finished_at=stamp(),message=str(e))
        raise

if __name__=="__main__":
    main()
