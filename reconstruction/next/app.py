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
from cctv_manager import router as cctv_router,admin
import yolo_publishers as yp
from fastapi import Response
from pydantic import BaseModel,StrictInt
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
    try:return daily(AIS,selected,live.monitoring(selected) if live else ())
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
    now=datetime.now(timezone.utc)
    rows,age,ais_status,event=live.status_snapshot(now) if live else ([],None,"UNAVAILABLE",None)
    vehicles={p:live.ledger.snapshot(p) for p in ("bengkalis","pakning")} if live else {}
    return {"notifications":notices(ais_status,rows,model_status,event,vehicles,now),"ais_status":ais_status,"ais_file_age_seconds":age,"vessels":rows,"models":{"release":release,"status":model_status,"algorithms":{r:b.get("algorithm",b.get("estimator_name")) for r,b in (models or {}).items()}},"vehicles":vehicles,"prediction_status":"STAGING_UNVALIDATED","event_engine":event}

# Offline/staging prediction helper is intentionally not exposed as a public write API.
def predict_feature_frame(issue,features,phase):
    if models is None: raise RuntimeError("No active model")
    with lock: return estimate(models,issue,features,phase)

class PublisherConfig(BaseModel):
    device:str
    enabled:bool=True
    raw_car:StrictInt
    raw_motor:StrictInt

@app.get("/api/inspection/yolo")
def yolo_status(response:Response,authorization:str=Header(default="")):
    admin(authorization);response.headers["Cache-Control"]="no-store"
    if not live:raise HTTPException(503,"Not ready")
    return {"publishers":[yp.status(live.ledger,p) for p in yp.PORTS]}

@app.put("/api/inspection/yolo/{port}")
def yolo_config(port:str,body:PublisherConfig,response:Response,authorization:str=Header(default="")):
    admin(authorization);response.headers["Cache-Control"]="no-store"
    if not live:raise HTTPException(503,"Not ready")
    try:return yp.configure(live.ledger,port,body.device,body.enabled,body.raw_car,body.raw_motor)
    except ValueError as e:raise HTTPException(422,str(e))

@app.post("/api/inspection/yolo/{port}/connection")
def yolo_connection(port:str,response:Response,authorization:str=Header(default="")):
    admin(authorization);response.headers["Cache-Control"]="no-store"
    if not live:raise HTTPException(503,"Not ready")
    return yp.credentials(live.ledger,port)

@app.get("/api/vehicles/{port}/resume")
def yolo_resume(port:str,device:str,authorization:str=Header(default="")):
    if not live:raise HTTPException(503,"Not ready")
    return yp.resume(live.ledger,port,device,authorization)

@app.post("/api/vehicles/{port}")
def receive_vehicle(port:str,body:dict,authorization:str=Header(default="")):
    if not live:raise HTTPException(503,"Not ready")
    try:return yp.ingest(live.ledger,port,body,authorization)
    except (ValueError,KeyError,TypeError) as e:raise HTTPException(422,str(e))
