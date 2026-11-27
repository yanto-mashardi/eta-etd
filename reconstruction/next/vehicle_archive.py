"""Verified daily vehicle ledger CSV. No credentials and no deletion of uncheckpointed queue history."""
import csv,io,hashlib,json,sqlite3,subprocess
from datetime import datetime,date,timedelta,timezone
from pathlib import Path
from zoneinfo import ZoneInfo
WIB=ZoneInfo("Asia/Jakarta")
FIELDS="kind port ts day mmsi car motor source event_id capacity_units motor_units fill_fraction device enabled raw_car raw_motor official_car official_motor".split()
def bounds(day):
    d=date.fromisoformat(day)
    from datetime import time
    a=datetime.combine(d,time.min,tzinfo=WIB).astimezone(timezone.utc)
    return tuple(x.isoformat(timespec="microseconds") for x in (a,a+timedelta(days=1)))
def tables(db):
    return {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
def days(db):
    names=tables(db)
    return sorted({r[0] for t in ("arrivals","departures","yolo_handover") if t in names for r in db.execute("SELECT DISTINCT date(ts,'+7 hours') FROM "+t) if r[0]})
def rows(db,day):
    lo,hi=bounds(day);out=[];names=tables(db)
    for name in ("arrivals","departures","yolo_handover"):
        if name not in names:continue
        if name=="departures":
            sql="SELECT d.*,p.capacity_units,p.motor_units,p.fill_fraction FROM departures d LEFT JOIN departure_policy p ON d.id=p.id WHERE d.ts>=? AND d.ts<? ORDER BY d.ts,d.id"
        else:sql="SELECT * FROM "+name+" WHERE ts>=? AND ts<? ORDER BY ts,port"
        for r in db.execute(sql,(lo,hi)):
            x=dict(r)
            if name=="departures":x["event_id"]=x.pop("id")
            out.append(dict(kind=name,day=day,**{k:x[k] for k in FIELDS if k in x and k not in ("kind","day")}))
    return sorted(out,key=lambda x:(x["ts"],x["kind"],x.get("port",""),x.get("event_id","")))
def encode(data):
    f=io.StringIO(newline="");w=csv.DictWriter(f,fieldnames=FIELDS,lineterminator="\n");w.writeheader();w.writerows(data);return f.getvalue().encode("utf-8")
def digest(data):return hashlib.sha256(data).hexdigest()
def safe_to_prune(db,day):
    # A later operator-approved opening checkpoint is the only deletion boundary.
    # Do not discard unreconciled historical arrivals/departures.
    _,hi=bounds(day)
    for table in ("arrivals","departures"):
        if db.execute("SELECT 1 FROM "+table+" t LEFT JOIN opening o ON t.port=o.port WHERE t.ts>=? AND t.ts<? AND (o.ts IS NULL OR t.ts>o.ts) LIMIT 1",(bounds(day)[0],hi)).fetchone():return False
    return True
def sync(root,atomic_file):
    path=root/"data"/"stockflow.sqlite"
    if not path.is_file():return
    folder=root/"data"/"prediction_archive"/"vehicles";folder.mkdir(mode=0o750,exist_ok=True)
    today=datetime.now(WIB).date();cutoff=(today-timedelta(days=6)).isoformat()
    cmd=["rclone","--config","/root/.config/rclone/rclone.conf"]
    with sqlite3.connect(path.resolve().as_uri()+"?mode=ro",uri=True,timeout=10) as db:
        db.row_factory=sqlite3.Row
        for day in days(db):
            if day>today.isoformat():continue
            db.execute("BEGIN")
            data=rows(db,day)
            sealed="vehicle_archive_sealed" in tables(db) and db.execute("SELECT 1 FROM vehicle_archive_sealed WHERE day=?",(day,)).fetchone()
            db.commit()
            if sealed:raise RuntimeError("Unexpected rows in sealed vehicle day "+day)
            if not data:continue
            encoded=encode(data);sha=digest(encoded)
            csvpath=folder/("VEHICLE_LEDGER_"+day+".csv");receipt=folder/(day+".verified.json")
            try:old=json.loads(receipt.read_text())
            except (OSError,ValueError):old={}
            if day>=cutoff or old.get("sha256")!=sha:
                if not csvpath.exists() or digest(csvpath.read_bytes())!=sha:
                    atomic_file(csvpath,lambda f:f.write(encoded.decode("utf-8")))
            if day>=today.isoformat():continue
            remote="aisdrive:CCTV_YOLO/"+csvpath.name
            if old.get("sha256")!=sha:
                subprocess.run(cmd+["copyto",str(csvpath),remote,"--ignore-times"],check=True,timeout=180)
                if digest(subprocess.check_output(cmd+["cat",remote],timeout=180))!=sha:raise RuntimeError("Vehicle Drive verification failed "+day)
                atomic_file(receipt,lambda f:json.dump(dict(sha256=sha,remote=remote),f))
            if day<cutoff and csvpath.exists() and digest(csvpath.read_bytes())==sha:csvpath.unlink()

def prune_verified(ledger,folder,today):
    """Service-owned transaction; old data cannot be appended after sealing."""
    cutoff=(today-timedelta(days=6)).isoformat()
    removed=0
    with ledger.connect() as db:
        candidates=[day for day in days(db) if day<cutoff]
    for day in candidates:
        try:receipt=json.loads((folder/(day+".verified.json")).read_text())
        except (OSError,ValueError):continue
        with ledger.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            data=rows(db,day)
            if not data or digest(encode(data))!=receipt.get("sha256") or not safe_to_prune(db,day):continue
            lo,hi=bounds(day)
            db.execute("INSERT OR IGNORE INTO vehicle_archive_sealed(day) VALUES(?)",(day,))
            db.execute("DELETE FROM departure_policy WHERE id IN (SELECT id FROM departures WHERE ts>=? AND ts<?)",(lo,hi))
            for t in ("arrivals","departures","yolo_handover"):
                if t in tables(db):db.execute("DELETE FROM "+t+" WHERE ts>=? AND ts<?",(lo,hi))
            removed+=len(data)
    return removed
