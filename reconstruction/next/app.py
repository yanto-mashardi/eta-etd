"""Isolated read-only live AIS dashboard and trusted feature-frame inference prototype."""
import csv,json,os,threading
from pathlib import Path
from datetime import datetime,timezone
from fastapi import FastAPI
from fastapi.responses import FileResponse
from engine import load_release,estimate
from live import Live
ROOT=Path(os.getenv("BIMA2_NEXT_ROOT","/opt/BIMA2_NEXT"))
AIS=Path(os.getenv("BIMA2_AIS_CSV","/opt/JAES_SIMULASI_BIMA2/data/01_DATA_SOURCE/AIS/realtime/ais_realtime.csv"))
app=FastAPI(title="BIMA2 Next",docs_url=None,redoc_url=None)
lock=threading.Lock()
release=None
models=None
model_status="WAITING_MODEL_RELEASE"
live=None
worker=None
@app.on_event("startup")
def init():
    global release,models,model_status,live,worker
    try:
        release,models=load_release(ROOT/"models")
        model_status="MODEL_LOADED_UNVALIDATED"
    except FileNotFoundError: pass
    except Exception as e: model_status="MODEL_LOAD_FAILED:"+type(e).__name__
    live=Live(ROOT,AIS,models,release,os.getenv("BIMA2_AIS_FIX_TIMESTAMP","ais_update_at"))
    worker=threading.Thread(target=live.run,daemon=True);worker.start()

@app.on_event("shutdown")
def shutdown():
    if live: live.stop.set()
    if worker: worker.join(timeout=10)

@app.get("/")
def page(): return FileResponse(Path(__file__).with_name("dashboard.html"))
@app.get("/api/status")
def status():
    try:
        with AIS.open(encoding="utf-8-sig",newline="") as f: rows=list(csv.DictReader(f))
        age=max(0,datetime.now(timezone.utc).timestamp()-AIS.stat().st_mtime)
        ais_status="STALE" if age>300 else "AVAILABLE"
    except (OSError,csv.Error): rows=[];age=None;ais_status="UNAVAILABLE"
    vehicles={}
    for port in ("bengkalis","pakning"):
        try:
            p=ROOT/"data"/"vehicles"/(port+".json")
            vehicles[port]={"state":json.loads(p.read_text()),"file_age_seconds":max(0,datetime.now(timezone.utc).timestamp()-p.stat().st_mtime)}
        except (OSError,ValueError): vehicles[port]=None
    return {"ais_status":ais_status,"ais_file_age_seconds":age,"vessels":rows,"models":{"release":release,"status":model_status,"algorithms":{r:b.get("algorithm",b.get("estimator_name")) for r,b in (models or {}).items()}},"vehicles":vehicles,"prediction_status":"STAGING_UNVALIDATED","event_engine":live.snapshot() if live else None}

# Offline/staging prediction helper is intentionally not exposed as a public write API.
def predict_feature_frame(issue,features,phase):
    if models is None: raise RuntimeError("No active model")
    with lock: return estimate(models,issue,features,phase)
