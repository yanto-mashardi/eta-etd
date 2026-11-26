"""Single-process polling adapter, staging only, never writes to AIS source."""
import csv,json,threading
from datetime import datetime,timezone
from pathlib import Path
from collections import Counter
import logging
import time
from prediction_archive import prune_verified
from trajectories import expire_cache
from copy import deepcopy
from evaluation import record_trip,daily_rows,active_trip_rows,WIB
from operational import publish
from live_events import OperationalTracker
from events import Tracker,read_seed,classify,atomic_json,dt
from engine import estimate
from stockflow import Ledger

class Live:
    def __init__(self,root,ais,models,release,timestamp_field="ais_update_at"):
        self.root=Path(root);self.ledger=Ledger(self.root/'data'/'stockflow.sqlite');self.ais=Path(ais);self.models=models;self.release=release
        self.field=timestamp_field;self.lock=threading.Lock();self.stop=threading.Event()
        self.path=self.root/"data"/"events_state.json"
        self.seed_path=self.root/"data"/"historical_cycles.csv"
        seed=read_seed(self.seed_path) if self.seed_path.exists() else []
        state=json.loads(self.path.read_text()) if self.path.exists() else None
        self.tracker=OperationalTracker(state,seed);self.error=None;self.rejected=0;self.rejection_reasons=Counter();self.duplicates=0
        # Import only already stored predictions from an ongoing voyage, never rerun them.
        for m,v in self.tracker.state["vessels"].items():
            record_trip(self.tracker.state,m,v)
        atomic_json(self.path,self.tracker.state)
        self.last_archive_prune=0
    def tick(self):
        now=datetime.now(timezone.utc)
        with self.ais.open(encoding="utf-8-sig",newline="") as f: rows=list(csv.DictReader(f))
        for row in rows:
            try: p=classify(row,now,self.field)
            except (ValueError,KeyError,TypeError) as e: self.rejected+=1;self.rejection_reasons[str(e)[:120]]+=1;continue
            with self.lock:
                previous=self.tracker.state["vessels"].get(p["mmsi"],{}).get("last")
                if previous and dt(p["ts"])<=dt(previous["ts"]): self.duplicates+=1;continue
                old=deepcopy(self.tracker.state["vessels"].get(p["mmsi"],{}))
                ncycles=len(self.tracker.state["cycles"])
                events=self.tracker.process(p)
                current=self.tracker.state["vessels"][p["mmsi"]]
                current["shipname"]=row.get("shipname") or p["mmsi"]
                completed=self.tracker.state["cycles"][ncycles:]
                if old.get("voyage") and (not current.get("voyage") or old["voyage"]["D0_utc"]!=current["voyage"]["D0_utc"]):
                    old["shipname"]=current["shipname"]
                    exit_event=current.get('operational_exit') or {}
                    old_id=p['mmsi']+'|'+dt(old['voyage']['D0_utc']).isoformat()
                    if completed: record_trip(self.tracker.state,p['mmsi'],old,completed[-1])
                    elif exit_event.get('trip_id')==old_id:
                        old['voyage']['qc_flags']=exit_event['qc_flags']
                        record_trip(self.tracker.state,p['mmsi'],old,status='COMPLETED_QC_FAIL',observed_exit=exit_event['D1_utc'])
                    else: record_trip(self.tracker.state,p['mmsi'],old,status='INCOMPLETE_'+current['status'])
                for event in events:
                    if event["phase"]=="D0": self.ledger.departure(event["features"]["origin_port"],p["mmsi"],event["issue_utc"])
                    result={"status":"WAITING_MODEL_OR_HISTORY","issue_utc":event["issue_utc"],"published_at":event["published_at"],"release":self.release}
                    if self.models is not None and self.tracker.seed_count:
                        try:
                            result.update(estimate(self.models,event["issue_utc"],event["features"],event["phase"]))
                            result["status"]="PROVISIONAL_UNVALIDATED"
                            result["published_at"]=datetime.now(timezone.utc).isoformat()
                        except (ValueError,KeyError,TypeError,RuntimeError) as e:
                            result["status"]="FEATURE_OR_MODEL_ERROR";result["error"]=str(e)[:250]
                    self.tracker.state["vessels"][p["mmsi"]]["predictions"][event["phase"]]=result
                record_trip(self.tracker.state,p["mmsi"],current)
                atomic_json(self.path,self.tracker.state)
        if time.monotonic()-self.last_archive_prune>=60:
            with self.lock:
                if prune_verified(self.tracker.state,self.root/"data"/"prediction_archive",datetime.now(WIB).date()):
                    atomic_json(self.path,self.tracker.state)
                self.last_archive_prune=time.monotonic()
        self.error=None
    def run(self):
        while not self.stop.is_set():
            try:
                expire_cache()
                self.tick()
            except Exception as e: self.error=type(e).__name__;logging.exception("Live tick failed")
            self.stop.wait(5)
    def monitoring(self,day):
        with self.lock:
            return daily_rows(self.tracker.state,day)
    def snapshot(self,ais_rows=(),ais_status='UNAVAILABLE',now=None):
        with self.lock:
            now=now or datetime.now(timezone.utc)
            active=active_trip_rows(self.tracker.state)
            rows=daily_rows(self.tracker.state,now.astimezone(WIB).date())
            states=self.tracker.snapshot(now)
            # Include prior day record for an active voyage crossing midnight.
            journal=self.tracker.state.get("trip_monitor",{})
            boards=publish(ais_rows,ais_status,now,journal.values(),active,states)
            return {"arrival_board":boards["arrivals"],"departure_board":boards["departures"],"operational_vessels":boards["vessels"],"publication_issues":boards["issues"],"active_trip_predictions":active,"prediction_evaluation":rows,"vessels":states,"history_seed_count":self.tracker.seed_count,
                    "completed_live_cycles":len(self.tracker.state["cycles"]),"status":"STAGING_UNVALIDATED" if not self.error else "ERROR:"+self.error,"rejected_rows":self.rejected,"rejection_reasons":dict(self.rejection_reasons),"duplicate_polls":self.duplicates,"timestamp_field":self.field}
