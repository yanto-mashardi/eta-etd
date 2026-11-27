"""Authenticated CCTV administration. No media processing or vehicle ledger writes."""
import os,json,hmac,re,time,tempfile,threading,logging
from pathlib import Path
from datetime import datetime,timezone
from urllib.request import Request,urlopen
from urllib.parse import urlencode,quote
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
    return next((u for u in config["authInternalUsers"] if any(x.get("action")=="publish" and x.get("path")=="live/"+port for x in u.get("permissions",[]))),None)
def view(port,cfg,meta):
    u=publisher(cfg,port);m=meta.get(port,{})
    p=relay("/v3/paths/get/live/"+port) or {}
    return {"port":port,"device":m.get("device","CCTV "+port.title()),"kind":m.get("kind","CCTV"),"enabled":bool(u),"username":u["user"] if u else m.get("username",port+"_pub"),"ready":bool(p.get("ready")),"ready_time":p.get("readyTime"),"tracks":p.get("tracks",[]),"bytes_received":p.get("bytesReceived"),"readers":len(p.get("readers") or []),"rtmp_url":"rtmp://"+HOST+":1935/live/"+port,"rtsp_url":"rtsp://"+HOST+":8554/live/"+port,"updated_at":m.get("updated_at")}
def connection_fields(port,user,password):
    if port not in PORTS:raise ValueError("Unknown port")
    server="rtmp://"+HOST+":1935/live"
    key=port+"?"+urlencode({"user":user,"pass":password})
    return {"url":server+"/"+key,"server":server,"stream_key":key,"rtsp_url":"rtsp://"+HOST+":8554/live/"+port}

@router.post("/{port}/connection")
def connection(port:str,response:Response,authorization:str=Header(default="")):
    admin(authorization)
    response.headers["Cache-Control"]="no-store"
    if port not in PORTS:raise HTTPException(404,"Unknown port")
    with LOCK:
        u=publisher(read(CONFIG),port)
        if not u:raise HTTPException(409,"Publisher disabled")
        return connection_fields(port,u["user"],u["pass"])

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
    if body.username in ("any","campus_reader","campus_validation","validation_relay"):raise HTTPException(422,"Reserved username")
    if body.password and not re.fullmatch(r"[A-Za-z0-9_-]{6,128}",body.password):raise HTTPException(422,"Password: 6–128 letters, digits, underscore or hyphen")
    with LOCK:
        cfg=read(CONFIG);meta=read(META);old=publisher(cfg,port)
        current=relay("/v3/config/global/get")
        if not current:raise HTTPException(503,"Relay configuration unavailable")
        users=[u for u in cfg["authInternalUsers"] if u is not old]
        if any(u["user"]==body.username for u in users):raise HTTPException(422,"Username already used")
        password=body.password or (old or {}).get("pass","")
        if body.enabled and not password:raise HTTPException(422,"Set a new publisher password")
        updated=dict(cfg)
        updated["authInternalUsers"]=users+([{"user":body.username,"pass":password,"permissions":[{"action":"publish","path":"live/"+port}]}] if body.enabled else [])
        changed=(bool(old)!=body.enabled or (body.enabled and (old.get("user")!=body.username or old.get("pass")!=password)))
        if changed:
            # Disconnect only the previous RTMP publisher before changing access.
            p=relay("/v3/paths/get/live/"+port) or {}
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

# Reader permissions never grant publish or API access.
READER_NAMES=("campus_reader","campus_validation")
def reader_prefix(name):
    return "validation/" if name=="campus_validation" else "live/"

def reader_account(cfg,name):
    if name not in READER_NAMES:raise HTTPException(404,"Unknown reader")
    u=next((u for u in cfg["authInternalUsers"] if u["user"]==name),None)
    if u and (not u.get("permissions") or any(p.get("action")!="read" or p.get("path") not in [reader_prefix(name)+x for x in PORTS] for p in u["permissions"])):
        raise HTTPException(409,"Unexpected reader permissions")
    return u
def reader_view(cfg,name):
    u=reader_account(cfg,name)
    return {"username":name,"enabled":bool(u),"ports":[p["path"].split("/")[-1] for p in u["permissions"]] if u else []}
class ReaderChange(BaseModel):
    password:str=Field(default="",max_length=128)
    enabled:bool=True
    ports:list[str]=Field(default_factory=lambda:list(PORTS))
def reader_users(cfg,name,body):
    old=reader_account(cfg,name)
    if body.password and not re.fullmatch(r"[A-Za-z0-9_-]{6,128}",body.password):raise HTTPException(422,"Password: 6–128 URL-safe characters")
    if not set(body.ports)<=set(PORTS) or (body.enabled and not body.ports):raise HTTPException(422,"Select valid ports")
    password=body.password or (old or {}).get("pass","")
    if body.enabled and not password:raise HTTPException(422,"Set a password for new reader")
    users=[u for u in cfg["authInternalUsers"] if u is not old]
    if body.enabled:users.append({"user":name,"pass":password,"permissions":[{"action":"read","path":reader_prefix(name)+port} for port in PORTS if port in body.ports]})
    return users
@router.get("/readers/accounts")
def readers(response:Response,authorization:str=Header(default="")):
    admin(authorization);response.headers["Cache-Control"]="no-store"
    with LOCK:return {"accounts":[reader_view(read(CONFIG),name) for name in READER_NAMES]}
@router.put("/readers/accounts/{name}")
def update_reader(name:str,body:ReaderChange,response:Response,authorization:str=Header(default="")):
    admin(authorization);response.headers["Cache-Control"]="no-store"
    with LOCK:
        cfg=read(CONFIG);updated=dict(cfg);updated["authInternalUsers"]=reader_users(cfg,name,body)
        before=reader_account(cfg,name);after=reader_account(updated,name)
        if before!=after:
            write(CONFIG,updated)
            try:
                for _ in range(24):
                    time.sleep(.25)
                    active=relay("/v3/config/global/get") or {}
                    if "authInternalUsers" not in active:continue
                    u=reader_account(active,name)
                    if after is None and u is None:break
                    if after and u and u.get("pass")==after["pass"] and {(p["action"],p["path"]) for p in u["permissions"]}=={(p["action"],p["path"]) for p in after["permissions"]}:break
                else:raise HTTPException(503,"Reader configuration not applied")
            except Exception:
                write(CONFIG,cfg)
                raise
            logging.info("RTSP reader configuration changed: %s",name)
        result=reader_view(updated,name)
        if name=="campus_validation" and before!=after:
            result["disconnected"]=disconnect_validation()
        return result
@router.post("/readers/accounts/{name}/connection")
def reader_connection(name:str,response:Response,authorization:str=Header(default="")):
    admin(authorization);response.headers["Cache-Control"]="no-store"
    with LOCK:
        u=reader_account(read(CONFIG),name)
        if not u:raise HTTPException(409,"Reader disabled")
        return {"urls":{p["path"].split("/")[-1]:"rtsp://"+quote(name,safe="")+":"+quote(u["pass"],safe="")+"@"+HOST+":8554/"+p["path"] for p in u["permissions"]}}

def validation_ids():
    ids=[];page=0
    while True:
        data=relay("/v3/rtspsessions/list?itemsPerPage=100&page="+str(page))
        if not isinstance(data,dict):raise HTTPException(503,"Session list unavailable")
        for s in data.get("items",[]):
            if s.get("state")=="read" and s.get("path") in {"validation/"+p for p in PORTS}:
                sid=s.get("id","")
                if not re.fullmatch(r"[a-fA-F0-9-]{36}",sid):raise HTTPException(503,"Invalid session ID")
                ids.append(sid)
        page+=1
        if page>=data.get("pageCount",1):return ids
        if page>100:raise HTTPException(503,"Session list too large")
def disconnect_validation():
    ids=validation_ids()
    for sid in ids:relay("/v3/rtspsessions/kick/"+sid,"POST")
    return len(ids)
@router.post("/readers/validation/disconnect")
def kick_validation(response:Response,authorization:str=Header(default="")):
    admin(authorization);response.headers["Cache-Control"]="no-store"
    with LOCK:return {"disconnected":disconnect_validation()}
