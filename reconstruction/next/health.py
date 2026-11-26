"""Derive lightweight health notices from existing status snapshot; no polling or history."""
from datetime import datetime,timezone
from events import dt
def notices(ais_status,rows,model_status,event,vehicles,now=None):
    now=now or datetime.now(timezone.utc)
    out=[]
    def add(code,message,severity="error",port=None):
        out.append(dict(code=code,message=message,severity=severity,port=port))
    if ais_status!="AVAILABLE":add("AIS_STALE" if ais_status=="STALE" else "AIS_ERROR","AIS: file kedaluwarsa" if ais_status=="STALE" else "AIS: file tidak tersedia")
    elif not rows:add("AIS_EMPTY","AIS: tidak ada kapal pada snapshot","warning")
    for r in rows:
        quality=r.get("live_ais_quality")
        if quality!="FRESH":add("AIS_STALE" if quality=="STALE" else "AIS_DATA_ERROR",str(r.get("shipname") or r.get("mmsi"))+": "+str(quality),"warning")
    if model_status!="MODEL_LOADED_UNVALIDATED":add("ML_ERROR","Model: "+model_status)
    if not event or str(event.get("status","")).startswith("ERROR"):add("EVENT_ERROR","Event engine tidak siap atau mengalami gangguan")
    for m,v in (event or {}).get("vessels",{}).items():
        for phase,p in v.get("predictions",{}).items():
            if p.get("status")=="FEATURE_OR_MODEL_ERROR":add("ML_ERROR",str(m)+": inference "+phase+" gagal")
    for port,v in vehicles.items():
        v=v or {};hb=v.get("last_received")
        if not hb:add("CCTV_WAITING",port+": menunggu data CCTV/YOLO","info",port)
        else:
            try:age=(now-dt(hb)).total_seconds()
            except (ValueError,TypeError):age=121
            if age>120:add("CCTV_ERROR",port+": heartbeat pengiriman kendaraan terputus","error",port)
        if v.get("issues"):add("QUEUE_ERROR",port+": "+", ".join(v["issues"]),"warning",port)
    return out
