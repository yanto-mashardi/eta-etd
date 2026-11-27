"""Historical research comparator for regression tests only."""
from events import *
class Tracker(TrackerState):
    def process(self,p):
        v=self.state["vessels"].setdefault(p["mmsi"],{"last":None,"stop":None,"voyage":None,"status":"WAITING_ORIGIN","predictions":{}})
        prev=v["last"]
        if prev and dt(p["ts"])<=dt(prev["ts"]): return []
        events=[]
        # Never infer exit from missing observations or from a direct jump to another berth.
        if prev and minutes(prev["ts"],p["ts"])>(12 if prev["candidate"] and p["candidate"] and prev["port"]==p["port"] else 10):
            v.update(stop=None,voyage=None,status="AIS_GAP",predictions={})
            prev=None
        s=v["stop"]
        if p["candidate"]:
            if s and p["port"]!=s["port"]:
                v.update(stop=None,voyage=None,status="PORT_JUMP",predictions={});s=None;prev=None
            if not s:
                s={"port":p["port"],"first":p,"last":p,"n":0,"votes":{},"bracket":prev["ts"] if prev and not prev["candidate"] else None,"confirmed":False}
                v["stop"]=s
                q=v["voyage"]
                if q and q["destination_port"]==p["port"] and 15<=minutes(q["D0_utc"],p["ts"])<=120 and s["bracket"]:
                    s["arrival_features"]=features(self.history,p,q["origin_port"],q["destination_port"])
            s["n"]+=1;s["last"]=p
            if not p["ambiguous"]: s["votes"][p["berth"]]=s["votes"].get(p["berth"],0)+1
            if not s["confirmed"] and s["n"]>=3 and minutes(s["first"]["ts"],p["ts"])>=4 and (not s["bracket"] or minutes(s["bracket"],s["first"]["ts"])<=10):
                s["confirmed"]=True;v["status"]="BERTHED"
                # A stationary observation window establishes origin occupancy, not an actual arrival.
                s["arrival_observed"]=bool(s["bracket"])
                q=v["voyage"]
                if q and "arrival_features" in s and q["destination_port"]==p["port"]:
                    q["A_utc"]=s["first"]["ts"]
                    q["A_confirmed_at"]=p["received"]
                    events.append({"phase":"A","issue_utc":q["A_utc"],"published_at":p["received"],"features":s["arrival_features"]})
                elif q:
                    v["voyage"]=None;v["predictions"]={}
            elif not s["confirmed"]: v["status"]="ARRIVAL_CANDIDATE"
            elif self.require_moving_exit and v["status"]=="DEPARTURE_PENDING": v["status"]="BERTHED"
        else:
            if s:
                if self.require_moving_exit and s["confirmed"] and p["sog"]<=.8:
                    # A stationary fix outside the berth radius is not proof of departure.
                    v["status"]="DEPARTURE_PENDING";v["last"]=p
                    return events
                if s["confirmed"] and minutes(s["last"]["ts"],p["ts"])<=10:
                    q=v["voyage"]
                    if q and q.get("A_utc")==s["first"]["ts"] and q["destination_port"]==s["port"]:
                        try:
                            c=clean_cycle(dict(q,mmsi=p["mmsi"],D1_utc=p["ts"],known_at=p["received"]))
                            if cycle_key(c) not in {cycle_key(x) for x in self.history}:
                                self.history.append(c);self.state["cycles"].append(c)
                            v["last_completed_cycle"]=c
                        except ValueError: v["last_cycle_status"]="EXCLUDED_DURATION_QC"
                    origin=s["port"];dest=next(k for k in PORTS if k!=origin)
                    v["voyage"]={"origin_port":origin,"destination_port":dest,"D0_utc":p["ts"]}
                    v["predictions"]={};v["status"]="SAILING"
                    events.append({"phase":"D0","issue_utc":p["ts"],"published_at":p["received"],"features":features(self.history,p,origin,dest)})
                else:
                    v.update(voyage=None,predictions={},status="UNCONFIRMED_STOP_EXIT")
                v["stop"]=None
            elif v["voyage"] and minutes(v["voyage"]["D0_utc"],p["ts"])>120:
                v.update(voyage=None,predictions={},status="VOYAGE_EXPIRED")
            elif not v["voyage"]: v["status"]="WAITING_ORIGIN"
        v["last"]=p
        return events
