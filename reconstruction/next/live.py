"""Single-process polling adapter, staging only, never writes to AIS source."""
import csv,json,threading
from datetime import datetime,timezone
from pathlib import Path
from collections import Counter
import logging
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
        self.tracker=Tracker(state,seed);self.error=None;self.rejected=0;self.rejection_reasons=Counter();self.duplicates=0
    def tick(self):
        now=datetime.now(timezone.utc)
        with self.ais.open(encoding="utf-8-sig",newline="") as f: rows=list(csv.DictReader(f))
        for row in rows:
            try: p=classify(row,now,self.field)
            except (ValueError,KeyError,TypeError) as e: self.rejected+=1;self.rejection_reasons[str(e)[:120]]+=1;continue
            with self.lock:
                previous=self.tracker.state["vessels"].get(p["mmsi"],{}).get("last")
                if previous and dt(p["ts"])<=dt(previous["ts"]): self.duplicates+=1;continue
                for event in self.tracker.process(p):
                    if event["phase"]=="D0": self.ledger.departure(event["features"]["origin_port"],p["mmsi"],event["issue_utc"])
                    result={"status":"WAITING_MODEL_OR_HISTORY","issue_utc":event["issue_utc"],"published_at":event["published_at"],"release":self.release}
                    if self.models is not None and self.tracker.seed_count:
                        try:
                            result.update(estimate(self.models,event["issue_utc"],event["features"],event["phase"]))
                            result["status"]="PROVISIONAL_UNVALIDATED"
                        except (ValueError,KeyError,TypeError,RuntimeError) as e:
                            result["status"]="FEATURE_OR_MODEL_ERROR";result["error"]=str(e)[:250]
                    self.tracker.state["vessels"][p["mmsi"]]["predictions"][event["phase"]]=result
                atomic_json(self.path,self.tracker.state)
        self.error=None
    def run(self):
        while not self.stop.is_set():
            try: self.tick()
            except Exception as e: self.error=type(e).__name__;logging.exception("Live tick failed")
            self.stop.wait(5)
    def snapshot(self):
        with self.lock:
            return {"vessels":self.tracker.snapshot(datetime.now(timezone.utc)),"history_seed_count":self.tracker.seed_count,
                    "completed_live_cycles":len(self.tracker.state["cycles"]),"status":"STAGING_UNVALIDATED" if not self.error else "ERROR:"+self.error,"rejected_rows":self.rejected,"rejection_reasons":dict(self.rejection_reasons),"duplicate_polls":self.duplicates,"timestamp_field":self.field}
