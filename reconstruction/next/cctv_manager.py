"""Authenticated CCTV administration. No media processing or vehicle ledger writes."""
import os,json,hmac,re,time,tempfile,threading,logging
from pathlib import Path
from datetime import datetime,timezone
from urllib.request import Request,urlopen
from urllib.error import HTTPError,URLError
from fastapi import APIRouter,Header,HTTPException,Response
from pydantic import BaseModel,Field
router=APIRouter(prefix="/api/inspection/cctv")
BASE=Path("/var/lib/bima2-cctv")
CONFIG=BASE/"mediamtx.yml"
META=BASE/"devices.json"
PORTS=("bengkalis","pakning")
HOST="192.236.226.247"
LOCK=threading.RLock()
def admin(authorization):
    token=os.getenv("BIMA2_CCTV_ADMIN_TOKEN","")
    if not token:raise HTTPException(503,"CCTV manager not configured")
    if not hmac.compare_digest(authorization,"Bearer "+token):raise HTTPException(401,"Unauthorized")
def relay(path,method="GET"):
    try:
        with urlopen(Request("http://127.0.0.1:9997"+path,method=method),timeout=3) as r:
            raw=r.read();return json.loads(raw) if raw else {}
    except HTTPError as e:
        if e.code==404:return None
        raise HTTPException(503,"MediaMTX API rejected request")
    except (OSError,ValueError):raise HTTPException(503,"MediaMTX API unavailable")
def read(p):
    try:return json.loads(p.read_text())
    except (OSError,ValueError):raise HTTPException(503,"CCTV configuration unavailable")
def write(p,obj,mode=0o640):
    fd,tmp=tempfile.mkstemp(dir=p.parent)
    try:
        with os.fdopen(fd,"w") as f:
            os.fchmod(f.fileno(),mode);json.dump(obj,f,indent=2);f.flush();os.fsync(f.fileno())
        os.replace(tmp,p)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)
def publisher(config,port):
    return next((u for u in config["authInternalUsers"] if any(x.get("action")=="publish" and x.get("path")==port for x in u.get("permissions",[]))),None)
def view(port,cfg,meta):
    u=publisher(cfg,port);m=meta.get(port,{})
    p=relay("/v3/paths/get/"+port) or {}
    return {"port":port,"device":m.get("device","CCTV "+port.title()),"kind":m.get("kind","CCTV"),"enabled":bool(u),"username":u["user"] if u else m.get("username",port+"_pub"),"ready":bool(p.get("ready")),"ready_time":p.get("readyTime"),"tracks":p.get("tracks",[]),"bytes_received":p.get("bytesReceived"),"readers":len(p.get("readers") or []),"rtmp_url":"rtmp://"+HOST+":1935/"+port,"rtsp_url":"rtsp://"+HOST+":8554/"+port,"updated_at":m.get("updated_at")}
class Change(BaseModel):
    device:str=Field(min_length=1,max_length=100)
    kind:str=Field(pattern="^(Larix|OBS|CCTV)$")
    username:str=Field(pattern="^[A-Za-z0-9_-]{3,64}$")
    password:str=Field(default="",max_length=128)
    enabled:bool=True
@router.get("")
def status(response:Response,authorization:str=Header(default="")):
    admin(authorization);response.headers["Cache-Control"]="no-store"
    with LOCK:
        cfg=read(CONFIG);meta=read(META)
        return {"cameras":[view(p,cfg,meta) for p in PORTS]}
@router.put("/{port}")
def change(port:str,body:Change,response:Response,authorization:str=Header(default="")):
    admin(authorization);response.headers["Cache-Control"]="no-store"
    if port not in PORTS:raise HTTPException(404,"Unknown port")
    if body.username in ("any","campus_reader"):raise HTTPException(422,"Reserved username")
    if body.password and not re.fullmatch(r"[A-Za-z0-9_-]{16,128}",body.password):raise HTTPException(422,"Password: 16–128 letters, digits, underscore or hyphen")
    with LOCK:
        cfg=read(CONFIG);meta=read(META);old=publisher(cfg,port)
        current=relay("/v3/config/global/get")
        if not current:raise HTTPException(503,"Relay configuration unavailable")
        users=[u for u in cfg["authInternalUsers"] if u is not old]
        if any(u["user"]==body.username for u in users):raise HTTPException(422,"Username already used")
        password=body.password or (old or {}).get("pass","")
        if body.enabled and not password:raise HTTPException(422,"Set a new publisher password")
        updated=dict(cfg)
        updated["authInternalUsers"]=users+([{"user":body.username,"pass":password,"permissions":[{"action":"publish","path":port}]}] if body.enabled else [])
        changed=updated!=cfg
        if changed:
            # Disconnect only the previous RTMP publisher before changing access.
            p=relay("/v3/paths/get/"+port) or {}
            src=p.get("source") or {}
            if p.get("ready") and src.get("type")!="rtmpConn":raise HTTPException(409,"Stop the current publisher before changing credentials")
            if p.get("ready") and src.get("id"):
                if not re.fullmatch(r"[a-fA-F0-9-]{36}",src["id"]):raise HTTPException(409,"Unknown publisher ID")
            write(CONFIG,updated)
            try:
                for _ in range(20):
                    time.sleep(.25)
                    active=relay("/v3/config/global/get") or {}
                    # Compare effective permission and credential values, not optional default fields.
                    u=publisher(active,port)
                    if (not body.enabled and u is None) or (body.enabled and u and u.get("user")==body.username and u.get("pass")==password):break
                else:raise HTTPException(503,"Relay did not reload configuration")
                if p.get("ready") and src.get("id"):relay("/v3/rtmpconns/kick/"+src["id"],"POST")
            except Exception:
                write(CONFIG,cfg)
                raise
        meta[port]={"device":body.device,"kind":body.kind,"username":body.username,"updated_at":datetime.now(timezone.utc).isoformat()}
        write(META,meta,0o600)
        logging.info("CCTV configuration changed: port=%s enabled=%s credentials_changed=%s",port,body.enabled,changed)
        return view(port,updated,meta)
