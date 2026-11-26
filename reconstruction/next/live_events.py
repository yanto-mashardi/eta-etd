"""Live AIS operational transitions; research Tracker remains unchanged.
A first valid stationary fix at the expected destination publishes operational A.
Research acceptance still requires the original multi-fix confirmation and QC.
"""
from events import Tracker,PORTS,dt,minutes,features,clean_cycle,cycle_key

class OperationalTracker(Tracker):
    def recover(self,p):
        """Recover only the latest interrupted trip with frozen D0 and matching destination."""
        v=self.state["vessels"].get(p["mmsi"])
        if not v or v.get("voyage") or not p["candidate"]:return
        if v.get("last") and dt(p["ts"])<=dt(v["last"]["ts"]):return
        rows=[r for r in self.state.get("trip_monitor",{}).values() if str(r["mmsi"])==p["mmsi"]]
        if not rows:return
        r=max(rows,key=lambda x:dt(x["D0_utc"]))
        if not str(r.get("status","")).startswith("INCOMPLETE_") or r.get("ATA") or r.get("etd_real") or r["destination_port"]!=p["port"] or not 15<=minutes(r["D0_utc"],p["ts"])<=120:return
        v["voyage"]={k:r[k] for k in ("D0_utc","origin_port","destination_port")}
        v["voyage"]["qc_flags"]=["RECOVERED_AFTER_GAP"]
        # Retain published values from the journal; do not re-run D0.
        v["predictions"]={}
        v["stop"]=None
    def process(self,p):
        self.recover(p)
        v=self.state["vessels"].setdefault(p["mmsi"],{"last":None,"stop":None,"voyage":None,"status":"WAITING_ORIGIN","predictions":{}})
        prev=v.get("last")
        if prev and dt(p["ts"])<=dt(prev["ts"]):return []
        s=v.get("stop");q=v.get("voyage");events=[]
        gap=bool(prev and minutes(prev["ts"],p["ts"])>(12 if prev["candidate"] and p["candidate"] and prev["port"]==p["port"] else 10))
        def flag(reason):
            if q is not None:
                flags=q.setdefault("qc_flags",[])
                if reason not in flags:flags.append(reason)
        if gap:flag("AIS_GAP")
        def emit(phase,origin,dest):
            events.append(dict(phase=phase,issue_utc=p["ts"],published_at=p["received"],features=features(self.history,p,origin,dest)))
        if p["candidate"]:
            if s and s["port"]!=p["port"]:
                flag("PORT_JUMP");s=None
            if q and (p["port"]!=q["destination_port"] or not q.get("A_utc") and not 0<minutes(q["D0_utc"],p["ts"])<=120):
                v.update(voyage=None,predictions={});q=None
            if not s:
                s=dict(port=p["port"],first=p,last=p,n=0,votes={},bracket=prev["ts"] if prev and not prev["candidate"] and not gap else None,confirmed=False)
                v["stop"]=s
            s["n"]+=1;s["last"]=p
            if not p["ambiguous"]:s["votes"][p["berth"]]=s["votes"].get(p["berth"],0)+1
            if not s["confirmed"] and s["n"]>=3 and minutes(s["first"]["ts"],p["ts"])>=4 and (not s["bracket"] or minutes(s["bracket"],s["first"]["ts"])<=10):
                s["confirmed"]=True
            # Operational A uses first observed stationary destination fix, not the confirmation time.
            if q and not q.get("A_utc"):
                q["A_utc"]=p["ts"]
                q["A_confirmed_at"]=None
                q["publication_protocol"]="FIRST_STATIONARY_FIX"
                if not s["bracket"]:flag("ARRIVAL_BRACKET_MISSING")
                if minutes(q["D0_utc"],p["ts"])<15:flag("SAILING_DURATION_QC")
                emit("A",q["origin_port"],q["destination_port"])
            if q and s["confirmed"] and not q.get("A_confirmed_at"):
                q["A_confirmed_at"]=p["received"]
            v["status"]="BERTHED" if q and q.get("A_utc") or s["confirmed"] else "ARRIVAL_CANDIDATE"
        elif p["sog"]>.8 and s:
            origin=s["port"];dest=next(k for k in PORTS if k!=origin)
            # A distant fix after missing AIS cannot establish a departure timestamp.
            if minutes(s["last"]["ts"],p["ts"])>10 and (p["port"]!=origin or p["distance"]>.15):
                v.update(stop=None,voyage=None,status="AIS_GAP",predictions={})
            else:
                origin_flags=[]
                if not s["confirmed"]:origin_flags.append("ORIGIN_STOP_UNCONFIRMED")
                if not s["bracket"]:origin_flags.append("ORIGIN_BRACKET_MISSING")
                if minutes(s["last"]["ts"],p["ts"])>10:origin_flags.append("DEPARTURE_BRACKET_GAP")
                if q and q.get("A_utc") and q["destination_port"]==origin:
                    if not s["confirmed"]:flag("ARRIVAL_STOP_UNCONFIRMED")
                    if minutes(s["last"]["ts"],p["ts"])>10:flag("DEPARTURE_BRACKET_GAP")
                    v["operational_exit"]={"trip_id":p["mmsi"]+"|"+dt(q["D0_utc"]).isoformat(),"D1_utc":p["ts"],"qc_flags":list(q.get("qc_flags",[]))}
                    try:
                        cycle=clean_cycle(dict(q,mmsi=p["mmsi"],D1_utc=p["ts"],known_at=p["received"]))
                        if not q.get("qc_flags") and s["confirmed"] and q.get("A_confirmed_at"):
                            if cycle_key(cycle) not in {cycle_key(x) for x in self.history}:
                                self.history.append(cycle);self.state["cycles"].append(cycle)
                        else: v["operational_exit"]["qc_flags"].append("RESEARCH_QC_NOT_PASSED")
                    except ValueError:v["operational_exit"]["qc_flags"].append("DURATION_QC")
                v.update(stop=None,voyage=dict(origin_port=origin,destination_port=dest,D0_utc=p["ts"],qc_flags=origin_flags,publication_protocol="FIRST_STATIONARY_FIX"),status="SAILING",predictions={})
                emit("D0",origin,dest)
        elif s:
            # Zero SOG outside a berth never creates D0; retain the last known berth until movement.
            v["status"]="DEPARTURE_PENDING"
        elif q:
            if q.get("A_utc") or minutes(q["D0_utc"],p["ts"])>120:
                v.update(voyage=None,status="AIS_GAP",predictions={})
            else:v["status"]="SAILING"
        else:v["status"]="WAITING_ORIGIN"
        v["last"]=p
        return events
