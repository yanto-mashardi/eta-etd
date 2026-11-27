"""Persistent stock-flow ledger. Only observed arrivals and declared loads."""
import sqlite3, json, threading
from copy import deepcopy
from datetime import datetime, timezone, date, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
WIB=ZoneInfo("Asia/Jakarta")
PORTS=("bengkalis","pakning")
def stamp(s):
    t=datetime.fromisoformat(str(s).replace("Z","+00:00"))
    if t.tzinfo is None: raise ValueError("Timezone required")
    return t.astimezone(timezone.utc).isoformat(timespec="microseconds")
def count(x):
    if type(x) is not int or x<0: raise ValueError("Expected nonnegative integer")
    return x
def port(p):
    p=p.lower()
    if p not in PORTS: raise ValueError("Invalid port")
    return p
class Ledger:
    def __init__(self,path):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        self._snapshot_lock=threading.RLock();self._snapshot_conn=None;self._snapshots={}
        with self.connect() as db:
            db.executescript("""CREATE TABLE IF NOT EXISTS arrivals(port TEXT, day TEXT, ts TEXT, car INTEGER, motor INTEGER, PRIMARY KEY(port,ts));
            CREATE TABLE IF NOT EXISTS departures(id TEXT PRIMARY KEY, port TEXT, ts TEXT, mmsi TEXT, car INTEGER, motor INTEGER, source TEXT);
            CREATE TABLE IF NOT EXISTS opening(port TEXT PRIMARY KEY, ts TEXT, car INTEGER, motor INTEGER, counter_car INTEGER, counter_motor INTEGER);
            CREATE TABLE IF NOT EXISTS heartbeat(port TEXT PRIMARY KEY, ts TEXT);
            CREATE TABLE IF NOT EXISTS capacity_policy(mmsi TEXT PRIMARY KEY, capacity_units INTEGER, motor_units INTEGER, fill_fraction REAL);
            CREATE TABLE IF NOT EXISTS departure_policy(id TEXT PRIMARY KEY, capacity_units INTEGER, motor_units INTEGER, fill_fraction REAL);""")
    def connect(self):
        db=sqlite3.connect(self.path,timeout=10);db.row_factory=sqlite3.Row;return db
    def arrival(self,p,payload,now=None):
        p=port(p);day=date.fromisoformat(payload["tanggal"]).isoformat()
        local=datetime.fromisoformat(day+"T"+payload["jam"])
        if local.tzinfo: raise ValueError("jam must be WIB local time")
        ts=stamp(local.replace(tzinfo=WIB));now=now or datetime.now(timezone.utc)
        if datetime.fromisoformat(ts)>now+timedelta(seconds=30): raise ValueError("Future arrival")
        car,motor=count(payload["jumlah_mobil"]),count(payload["jumlah_motor"])
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.insert_arrival(db,p,day,ts,car,motor,now)
    def insert_arrival(self,db,p,day,ts,car,motor,now):
        old=db.execute("SELECT car,motor FROM arrivals WHERE port=? AND ts=?",(p,ts)).fetchone()
        if old:
            if tuple(old)!=(car,motor): raise ValueError("Conflicting snapshot")
        else:
            prev=db.execute("SELECT car,motor FROM arrivals WHERE port=? AND day=? AND ts<? ORDER BY ts DESC LIMIT 1",(p,day,ts)).fetchone()
            nxt=db.execute("SELECT car,motor FROM arrivals WHERE port=? AND day=? AND ts>? ORDER BY ts LIMIT 1",(p,day,ts)).fetchone()
            if (prev and (car<prev[0] or motor<prev[1])) or (nxt and (car>nxt[0] or motor>nxt[1])): raise ValueError("Counter decreased within day")
            db.execute("INSERT INTO arrivals VALUES(?,?,?,?,?)",(p,day,ts,car,motor))
        db.execute("INSERT INTO heartbeat VALUES(?,?) ON CONFLICT(port) DO UPDATE SET ts=max(ts,excluded.ts)",(p,stamp(now.isoformat())))
    def configure_capacity(self,mmsi,capacity_pce,motor_pce,fill_fraction):
        from decimal import Decimal
        c=Decimal(str(capacity_pce))*100; m=Decimal(str(motor_pce))*100
        if c!=int(c) or m!=int(m) or c<=0 or not 0<m<=100 or not 0<fill_fraction<=1: raise ValueError("Invalid capacity policy")
        with self.connect() as db:
            db.execute("INSERT INTO capacity_policy VALUES(?,?,?,?) ON CONFLICT(mmsi) DO UPDATE SET capacity_units=excluded.capacity_units,motor_units=excluded.motor_units,fill_fraction=excluded.fill_fraction",(str(mmsi),int(c),int(m),fill_fraction))
    def departure(self,p,mmsi,ts):
        p=port(p);ts=stamp(ts);eid=str(mmsi)+"|"+ts+"|"+p
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            cur=db.execute("INSERT OR IGNORE INTO departures(id,port,ts,mmsi) VALUES(?,?,?,?)",(eid,p,ts,str(mmsi)))
            if cur.rowcount:
                db.execute("INSERT INTO departure_policy SELECT ?,capacity_units,motor_units,fill_fraction FROM capacity_policy WHERE mmsi=?",(eid,str(mmsi)))
        return eid
    def set_opening(self,p,ts,car,motor,counter_car,counter_motor):
        p=port(p);ts=stamp(ts)
        with self.connect() as db:
            db.execute("INSERT INTO opening VALUES(?,?,?,?,?,?)",(p,ts,count(car),count(motor),count(counter_car),count(counter_motor)))
    def set_load(self,eid,car,motor,source):
        if source not in ("ACTUAL","ESTIMATED"): raise ValueError("Explicit source required")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row=db.execute("SELECT car,motor,source FROM departures WHERE id=?",(eid,)).fetchone()
            if not row: raise ValueError("Unknown departure")
            values=(count(car),count(motor),source)
            if row["source"] is not None and tuple(row)!=values: raise ValueError("Load already recorded; correction requires audited reconciliation")
            db.execute("UPDATE departures SET car=?,motor=?,source=? WHERE id=?",(*values,eid))
    def close(self):
        with self._snapshot_lock:
            if self._snapshot_conn is not None:self._snapshot_conn.close()
            self._snapshot_conn=None;self._snapshots.clear()
    def snapshot(self,p):
        p=port(p)
        with self._snapshot_lock:
            if self._snapshot_conn is None:
                self._snapshot_conn=sqlite3.connect(self.path,timeout=10,check_same_thread=False)
            revision=self._snapshot_conn.execute("PRAGMA data_version").fetchone()[0]
            now=datetime.now(timezone.utc);day=now.astimezone(WIB).date()
            prior=self._snapshots.get(p)
            if prior:
                oldrev,oldday,at,data=prior
                hb=data.get("last_received")
                crossing=bool(hb and (at-datetime.fromisoformat(hb)).total_seconds()<=120<(now-datetime.fromisoformat(hb)).total_seconds())
                if revision==oldrev and day==oldday and not crossing and (now-at).total_seconds()<60:return deepcopy(data)
            data=self._calculate_snapshot(p)
            after=self._snapshot_conn.execute("PRAGMA data_version").fetchone()[0]
            if revision==after:self._snapshots[p]=(after,day,now,deepcopy(data))
            else:self._snapshots.pop(p,None)
            return data
    def _calculate_snapshot(self,p):
        p=port(p)
        with self.connect() as db:
            db.execute("BEGIN")
            op=db.execute("SELECT * FROM opening WHERE port=?",(p,)).fetchone()
            latest=db.execute("SELECT * FROM arrivals WHERE port=? ORDER BY ts DESC LIMIT 1",(p,)).fetchone()
            hb=db.execute("SELECT ts FROM heartbeat WHERE port=?",(p,)).fetchone()
            deps=[dict(r) for r in db.execute("SELECT * FROM departures WHERE port=? ORDER BY ts DESC LIMIT 20",(p,))]
            result={"status":"WAITING_OPENING_STOCK","queue_car":None,"queue_motor":None,"latest_counter":dict(latest) if latest else None,"last_received":hb[0] if hb else None,"recent_departures":deps}
            if not op:return result
            arr=list(db.execute("SELECT * FROM arrivals WHERE port=? AND ts>? ORDER BY ts",(p,op["ts"])))
            departures=list(db.execute("SELECT * FROM departures WHERE port=? AND ts>? ORDER BY ts,id",(p,op["ts"])))
            policies={r["id"]:dict(r) for r in db.execute("SELECT * FROM departure_policy")}
        day=datetime.fromisoformat(op["ts"]).astimezone(WIB).date().isoformat()
        prev=(op["counter_car"],op["counter_motor"]);q=[op["car"],op["motor"]];inflow=[0,0];outflow=[0,0];issues=[]
        pending=0;estimated=False
        # Replay chronological ledger; arrivals at identical time precede departure.
        events=sorted([(r["ts"],0,r) for r in arr]+[(r["ts"],1,r) for r in departures],key=lambda x:(x[0],x[1]))
        for _,kind,r in events:
            if kind==0:
                if r["day"]!=day:
                    if date.fromisoformat(r["day"])-date.fromisoformat(day)!=timedelta(days=1): issues.append("MISSING_DAY")
                    day=r["day"];prev=(0,0)
                d=(r["car"]-prev[0],r["motor"]-prev[1])
                if min(d)<0: issues.append("COUNTER_CONFLICT");continue
                prev=(r["car"],r["motor"])
                for i in range(2):q[i]+=d[i];inflow[i]+=d[i]
            elif r["source"] is None:
                policy=policies.get(r["id"])
                if not policy or pending or min(q)<0: pending+=1;continue
                from capacity import allocate
                cars,motors=allocate(q[0],q[1],policy)
                for i,n in enumerate((cars,motors)):q[i]-=n;outflow[i]+=n
                for d in deps:
                    if d["id"]==r["id"]:d.update(car=cars,motor=motors,source="CAPACITY_POLICY")
                estimated=True
            else:
                estimated|=r["source"]=="ESTIMATED"
                for i,k in enumerate(("car","motor")):q[i]-=r[k];outflow[i]+=r[k]
                if min(q)<0:issues.append("NEGATIVE_STOCK")
        stale=not hb or (datetime.now(timezone.utc)-datetime.fromisoformat(hb[0])).total_seconds()>120
        if pending:issues.append("PENDING_OUTFLOW")
        if stale:issues.append("STALE_CCTV_TRANSPORT")
        if not latest:issues.append("WAITING_CCTV")
        elif latest["day"]!=datetime.now(WIB).date().isoformat():issues.append("MISSING_CURRENT_DAY")
        result.update(status="RECONCILIATION_REQUIRED" if issues else "RECONSTRUCTED",
            method="CAPACITY_POLICY_OR_DECLARED_LOAD" if estimated else "DECLARED_LOAD",issues=sorted(set(issues)),pending_departures=pending,inflow_car=inflow[0],inflow_motor=inflow[1],outflow_car=outflow[0],outflow_motor=outflow[1],
            queue_car=q[0] if not issues else None,queue_motor=q[1] if not issues else None,partial_stock_car=q[0],partial_stock_motor=q[1])
        return result
