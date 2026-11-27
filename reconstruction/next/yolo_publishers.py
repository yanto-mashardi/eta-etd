"""Official per-port YOLO sender authorization and atomic counter reconciliation."""
import secrets,hmac,json
from datetime import datetime,timezone,timedelta,date
from fastapi import HTTPException
from stockflow import PORTS,WIB,stamp,count
def setup(db):
    db.execute("""CREATE TABLE IF NOT EXISTS yolo_publishers(port TEXT PRIMARY KEY, device TEXT NOT NULL, token TEXT NOT NULL, enabled INTEGER NOT NULL, day TEXT NOT NULL, cutoff TEXT NOT NULL, raw_car INTEGER NOT NULL, raw_motor INTEGER NOT NULL, offset_car INTEGER NOT NULL, offset_motor INTEGER NOT NULL, last_ts TEXT, last_received TEXT, last_raw_car INTEGER, last_raw_motor INTEGER)""")
    db.execute("CREATE TABLE IF NOT EXISTS yolo_handover(port TEXT, ts TEXT, device TEXT, enabled INTEGER, raw_car INTEGER, raw_motor INTEGER, official_car INTEGER, official_motor INTEGER)")
def latest(db,p,day):
    row=db.execute("SELECT car,motor,ts FROM arrivals WHERE port=? AND day=? ORDER BY ts DESC LIMIT 1",(p,day)).fetchone()
    op=db.execute("SELECT counter_car,counter_motor,ts FROM opening WHERE port=?",(p,)).fetchone()
    if op and datetime.fromisoformat(op[2]).astimezone(WIB).date().isoformat()==day and (not row or op[2]>row[2]):return tuple(op)
    return tuple(row) if row else (0,0,None)
def status(ledger,p):
    with ledger.connect() as db:
        setup(db);r=db.execute("SELECT * FROM yolo_publishers WHERE port=?",(p,)).fetchone()
        day=datetime.now(WIB).date().isoformat();c,m,_=latest(db,p,day)
        out={"port":p,"device":None,"enabled":False,"status":"NOT_CONFIGURED","official_car":c,"official_motor":m}
        if r:
            age=(datetime.now(timezone.utc)-datetime.fromisoformat(r["last_received"])).total_seconds() if r["last_received"] else None
            out.update(device=r["device"],enabled=bool(r["enabled"]),status="DISABLED" if not r["enabled"] else "ONLINE" if age is not None and age<=30 else "WAITING" if age is None else "OFFLINE",last_received=r["last_received"],last_observation=r["last_ts"],raw_car=r["last_raw_car"],raw_motor=r["last_raw_motor"],cutoff=r["cutoff"])
        return out
def configure(ledger,p,device,enabled,raw_car,raw_motor):
    if p not in PORTS:raise HTTPException(404,"Unknown port")
    if not isinstance(device,str) or not 1<=len(device.strip())<=100:raise ValueError("Invalid device")
    raw_car,raw_motor=count(raw_car),count(raw_motor)
    now=datetime.now(timezone.utc);day=now.astimezone(WIB).date().isoformat();cutoff=stamp(now.isoformat())
    with ledger.connect() as db:
        db.execute("BEGIN IMMEDIATE");setup(db)
        c,m,_=latest(db,p,day)
        db.execute("INSERT INTO yolo_handover VALUES(?,?,?,?,?,?,?,?)",(p,cutoff,device.strip(),int(enabled),raw_car,raw_motor,c,m))
        db.execute("INSERT OR REPLACE INTO yolo_publishers VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(p,device.strip(),secrets.token_hex(32),int(enabled),day,cutoff,raw_car,raw_motor,c-raw_car,m-raw_motor,None,None,None,None))
    return status(ledger,p)
def credentials(ledger,p):
    with ledger.connect() as db:
        setup(db);r=db.execute("SELECT device,token,enabled FROM yolo_publishers WHERE port=?",(p,)).fetchone()
        if not r or not r["enabled"]:raise HTTPException(409,"Publisher not enabled")
        return {"device":r["device"],"token":r["token"]}
def ingest(ledger,p,body,authorization,now=None):
    if p not in PORTS:raise HTTPException(404,"Unknown port")
    now=now or datetime.now(timezone.utc)
    with ledger.connect() as db:
        db.execute("BEGIN IMMEDIATE");setup(db)
        r=db.execute("SELECT * FROM yolo_publishers WHERE port=?",(p,)).fetchone()
        if not r or not r["enabled"] or not hmac.compare_digest(authorization,"Bearer "+r["token"]) or body.get("device")!=r["device"]:raise HTTPException(401,"Unauthorized publisher")
        if body.get("mode")!="OBSERVED":raise ValueError("Only OBSERVED accepted")
        payload=body["state"];day=date.fromisoformat(payload["tanggal"]).isoformat()
        local=datetime.fromisoformat(day+"T"+payload["jam"])
        if local.tzinfo:raise ValueError("Expected WIB local time")
        ts=stamp(local.replace(tzinfo=WIB));car,motor=count(payload["jumlah_mobil"]),count(payload["jumlah_motor"])
        if ts>stamp((now+timedelta(seconds=30)).isoformat()):raise ValueError("Future arrival")
        if ts<r["cutoff"]:raise ValueError("Before publisher cutover")
        if day>now.astimezone(WIB).date().isoformat():raise ValueError("Future day")
        if r["last_ts"] and ts<r["last_ts"]:raise ValueError("Out of order snapshot")
        if r["last_ts"]==ts and (car,motor)!=(r["last_raw_car"],r["last_raw_motor"]):raise ValueError("Conflicting snapshot")
        if r["last_ts"] and datetime.fromisoformat(r["last_ts"]).astimezone(WIB).date().isoformat()==day and (car<r["last_raw_car"] or motor<r["last_raw_motor"]):raise ValueError("Counter decreased; reconcile in Manager")
        if day==r["day"]:
            if car<r["raw_car"] or motor<r["raw_motor"]:raise ValueError("Counter below handover baseline")
            if r["last_ts"] and datetime.fromisoformat(r["last_ts"]).astimezone(WIB).date().isoformat()==day and (car<r["last_raw_car"] or motor<r["last_raw_motor"]):raise ValueError("Counter decreased; reconcile in Manager")
            official=(car+r["offset_car"],motor+r["offset_motor"])
        else:official=(car,motor)
        # Same transaction as authorization and publisher progress: no race on handover.
        ledger.insert_arrival(db,p,day,ts,*official,now)
        db.execute("UPDATE yolo_publishers SET last_ts=?,last_received=?,last_raw_car=?,last_raw_motor=? WHERE port=?",(ts,stamp(now.isoformat()),car,motor,p))
    return {"accepted":True,"official_car":official[0],"official_motor":official[1]}

def resume(ledger,p,device,authorization):
    if p not in PORTS:raise HTTPException(404,"Unknown port")
    with ledger.connect() as db:
        setup(db);r=db.execute("SELECT * FROM yolo_publishers WHERE port=?",(p,)).fetchone()
        if not r or not r["enabled"] or device!=r["device"] or not hmac.compare_digest(authorization,"Bearer "+r["token"]):raise HTTPException(401,"Unauthorized publisher")
        return {"cutoff":r["cutoff"],"last_ts":r["last_ts"]}
