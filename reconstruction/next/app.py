"""Isolated read-only live AIS dashboard and trusted feature-frame inference prototype."""
import csv,json,os,threading,hmac
from pathlib import Path
from datetime import datetime,timezone
from events import dt
from trajectories import daily,WIB
from datetime import date,timedelta
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from engine import load_release,estimate
from live import Live
from stockflow import Ledger
from health import notices
from cctv_manager import router as cctv_router
ROOT=Path(os.getenv("BIMA2_NEXT_ROOT","/opt/BIMA2_NEXT"))
AIS=Path(os.getenv("BIMA2_AIS_CSV","/opt/JAES_SIMULASI_BIMA2/data/01_DATA_SOURCE/AIS/realtime/ais_realtime.csv"))
app=FastAPI(title="BIMA2 Next",docs_url=None,redoc_url=None)
app.include_router(cctv_router)
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
@app.get("/bengkalis")
@app.get("/pakning")
def page(): return FileResponse(Path(__file__).with_name("public.html"))

@app.get("/inspection")
def inspection(): return FileResponse(Path(__file__).with_name("dashboard.html"))
@app.get("/inspection/manager")
def manager(): return FileResponse(Path(__file__).with_name("cctv_manager.html"),headers={"Cache-Control":"no-store"})
@app.get("/map-assets/{name}")
def map_asset(name: str):
    if name not in ("leaflet.js","leaflet.css","maplibre-gl.js","maplibre-gl.css"): raise HTTPException(404)
    p=Path(__file__).with_name("map-assets")/name
    if not p.is_file(): raise HTTPException(404)
    return FileResponse(p, media_type="text/javascript" if name.endswith(".js") else "text/css")

@app.get("/api/inspection/trajectories")
def trajectories(day: str = ""):
    today=datetime.now(WIB).date()
    try: selected=date.fromisoformat(day) if day else today
    except ValueError: raise HTTPException(400,"Expected YYYY-MM-DD")
    if not today-timedelta(days=7)<=selected<=today: raise HTTPException(400,"Local inspection range: last seven days plus today")
    try:return daily(AIS,selected)
    except OSError:raise HTTPException(503,"Local AIS archive unreadable")

@app.get("/api/inspection/monitoring")
def monitoring(day: str = ""):
    today=datetime.now(WIB).date()
    try:selected=date.fromisoformat(day) if day else today
    except ValueError:raise HTTPException(400,"Expected YYYY-MM-DD")
    if not today-timedelta(days=6)<=selected<=today:raise HTTPException(400,"Local monitoring range: seven WIB calendar days including today")
    return {"date":selected.isoformat(),"rows":live.monitoring(selected) if live else []}

@app.get("/api/status")
def status():
    try:
        with AIS.open(encoding="utf-8-sig",newline="") as f: rows=list(csv.DictReader(f))
        age=max(0,datetime.now(timezone.utc).timestamp()-AIS.stat().st_mtime)
        ais_status="STALE" if age>300 else "AVAILABLE"
    except (OSError,csv.Error): rows=[];age=None;ais_status="UNAVAILABLE"
    now=datetime.now(timezone.utc)
    for row in rows:
        try:
            seconds=(now-dt(row["ais_update_at"])).total_seconds()
            row["live_ais_age_seconds"]=round(seconds,1)
            row["live_ais_quality"]="FUTURE" if seconds<0 else "STALE" if seconds>300 else "QC" if str(row.get("inference_allowed","")).lower() not in ("true","1") else "FRESH"
        except (ValueError,KeyError,TypeError):
            row["live_ais_age_seconds"]=None;row["live_ais_quality"]="INVALID_TIMESTAMP"
    vehicles={}
    for port in ("bengkalis","pakning"):
        try:
            p=ROOT/"data"/"vehicles"/(port+".json")
            vehicles[port]={"state":json.loads(p.read_text()),"file_age_seconds":max(0,datetime.now(timezone.utc).timestamp()-p.stat().st_mtime)}
        except (OSError,ValueError): vehicles[port]=None
    if live:
        vehicles={p:live.ledger.snapshot(p) for p in ("bengkalis","pakning")}
    event=live.snapshot(rows,ais_status,now) if live else None
    return {"notifications":notices(ais_status,rows,model_status,event,vehicles,now),"ais_status":ais_status,"ais_file_age_seconds":age,"vessels":rows,"models":{"release":release,"status":model_status,"algorithms":{r:b.get("algorithm",b.get("estimator_name")) for r,b in (models or {}).items()}},"vehicles":vehicles,"prediction_status":"STAGING_UNVALIDATED","event_engine":event}

# Offline/staging prediction helper is intentionally not exposed as a public write API.
def predict_feature_frame(issue,features,phase):
    if models is None: raise RuntimeError("No active model")
    with lock: return estimate(models,issue,features,phase)

@app.post("/api/vehicles/{port}")
def receive_vehicle(port:str,body:dict,authorization:str=Header(default="")):
    token=os.getenv("BIMA2_VEHICLE_TOKEN","")
    if not token or not hmac.compare_digest(authorization,"Bearer "+token):
        raise HTTPException(401,"Unauthorized")
    if body.get("mode")!="OBSERVED":raise HTTPException(422,"Only OBSERVED input accepted")
    if not live:raise HTTPException(503,"Not ready")
    try:live.ledger.arrival(port,body["state"])
    except (ValueError,KeyError,TypeError) as e:raise HTTPException(422,str(e))
    return {"accepted":True}
