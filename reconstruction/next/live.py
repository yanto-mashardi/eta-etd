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
from evaluation import record_trip,daily_rows,active_trip_rows,WIB,trip_key,publish
from live_events import OperationalTracker,find_arrival
from events import read_seed,classify,atomic_json,dt,resolve,quality
from engine import estimate
from stockflow import Ledger

class Live:
    def __init__(self,root,ais,models,release,timestamp_field="ais_update_at"):
        self.root=Path(root);self.ledger=Ledger(self.root/'data'/'stockflow.sqlite');self.ais=Path(ais);self.models=models;self.release=release
        self.field=timestamp_field;self.lock=threading.RLock();self.stop=threading.Event()
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
        self.raw_rows=[];self.classified={};self.file_mtime=None
    def drain_departures(self):
        pending=self.tracker.state.setdefault('departure_outbox',{})
        if not pending:return
        for key,item in list(pending.items()):
            self.ledger.departure(item['port'],item['mmsi'],item['ts'])
            del pending[key]
        atomic_json(self.path,self.tracker.state)
    def tick(self):
        with self.lock:
            try:
                self.drain_departures()
                self._tick()
            except Exception:
                seed=read_seed(self.seed_path) if self.seed_path.exists() else []
                self.tracker=OperationalTracker(json.loads(self.path.read_text()),seed)
                raise
    def _tick(self):
        now=datetime.now(timezone.utc)
        try:
            with self.ais.open(encoding="utf-8-sig",newline="") as f:
                import os
                mtime=os.fstat(f.fileno()).st_mtime;rows=list(csv.DictReader(f))
        except (OSError,csv.Error):
            self.raw_rows=[];self.classified={};self.file_mtime=None
            raise
        self.raw_rows=rows;self.classified={};self.file_mtime=mtime
        if now.timestamp()-mtime>300:return
        for row in rows:
            try: p=classify(row,now,self.field)
            except (ValueError,KeyError,TypeError) as e: self.rejected+=1;self.rejection_reasons[str(e)[:120]]+=1;continue
            self.classified[p["mmsi"]]=dict(p)
            with self.lock:
                previous=self.tracker.state["vessels"].get(p["mmsi"],{}).get("last")
                raw_fix=p
                p=resolve(p,row,previous,now)
                recovery_only=p is None
                if recovery_only:
                    self.duplicates+=1
                    v=self.tracker.state["vessels"].get(raw_fix["mmsi"],{})
                    stop=v.get("stop")
                    if not (previous and previous.get("candidate") and raw_fix["candidate"] and stop and not v.get("voyage") and not stop.get("arrival_recovery_attempted") and raw_fix["port"]==stop["port"]==previous["port"] and dt(raw_fix["ts"])==dt(previous.get("source_fix_utc",previous["ts"]))):continue
                    p=dict(previous,received=now.isoformat())
                old=deepcopy(self.tracker.state["vessels"].get(p["mmsi"],{}))
                ncycles=len(self.tracker.state["cycles"])
                events=[] if recovery_only else self.tracker.process(p)
                current=self.tracker.state["vessels"][p["mmsi"]]
                current["shipname"]=row.get("shipname") or p["mmsi"]
                # One bounded history lookup per unlinked berth stay, never per poll.
                stop=current.get("stop")
                if p["candidate"] and stop and not current.get("voyage") and not stop.get("arrival_recovery_attempted"):
                    stop["arrival_recovery_attempted"]=True
                    first=find_arrival(self.ais,p)
                    if first:events.append(self.tracker.arrival_only(current,p,first,"RECOVERED_ARRIVAL"))
                completed=self.tracker.state["cycles"][ncycles:]
                if old.get("voyage") and (not current.get("voyage") or trip_key(p["mmsi"],old["voyage"])!=trip_key(p["mmsi"],current["voyage"])):
                    old["shipname"]=current["shipname"]
                    exit_event=current.get('operational_exit') or {}
                    old_id=trip_key(p['mmsi'],old['voyage'])
                    if exit_event.get('trip_id')==old_id and exit_event.get('event_evidence'):
                        old['voyage']['event_evidence']=exit_event['event_evidence']
                    if completed: record_trip(self.tracker.state,p['mmsi'],old,completed[-1])
                    elif exit_event.get('trip_id')==old_id:
                        old['voyage']['qc_flags']=exit_event['qc_flags']
                        record_trip(self.tracker.state,p['mmsi'],old,status='COMPLETED_QC_FAIL',observed_exit=exit_event['D1_utc'])
                    else: record_trip(self.tracker.state,p['mmsi'],old,status='INCOMPLETE_'+current['status'])
                for event in events:
                    if event["phase"]=="D0":
                        key=trip_key(p["mmsi"],current["voyage"])
                        self.tracker.state.setdefault("departure_outbox",{})[key]=dict(port=event["features"]["origin_port"],mmsi=p["mmsi"],ts=event["issue_utc"])
                    result={"status":"WAITING_MODEL_OR_HISTORY","issue_utc":event["issue_utc"],"published_at":event["published_at"],"release":self.release,"features":event["features"]}
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
        self.drain_departures()
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
            boards=publish(ais_rows,ais_status,now,journal.values(),active,states,self.classified)
            return {"arrival_board":boards["arrivals"],"departure_board":boards["departures"],"operational_vessels":boards["vessels"],"publication_issues":boards["issues"],"active_trip_predictions":active,"prediction_evaluation":rows,"vessels":states,"history_seed_count":self.tracker.seed_count,
                    "completed_live_cycles":len(self.tracker.state["cycles"]),"status":"STAGING_UNVALIDATED" if not self.error else "ERROR:"+self.error,"rejected_rows":self.rejected,"rejection_reasons":dict(self.rejection_reasons),"duplicate_polls":self.duplicates,"timestamp_field":self.field}

    def status_snapshot(self,now=None):
        with self.lock:
            now=now or datetime.now(timezone.utc)
            age=max(0,now.timestamp()-self.file_mtime) if self.file_mtime is not None else None
            status="UNAVAILABLE" if age is None else "STALE" if age>300 else "AVAILABLE"
            rows=[quality(r,now) for r in self.raw_rows]
            seen={str(r.get("mmsi")) for r in rows}
            for m,v in self.tracker.state["vessels"].items():
                p=v.get("last") or {}
                if m not in seen and p.get("latitude") is not None and p.get("longitude") is not None:
                    rows.append(dict(mmsi=m,shipname=v.get("shipname") or m,latitude=p["latitude"],longitude=p["longitude"],sog=p["sog"],ais_update_at=p.get("source_fix_utc",p["ts"]),live_ais_quality="STALE",live_ais_age_seconds=max(0,(now-dt(p.get("source_fix_utc",p["ts"]))).total_seconds())))
            if status!="AVAILABLE":
                for r in rows:
                    if r.get("live_ais_quality")=="FRESH":r["live_ais_quality"]="STALE"
            return rows,age,status,self.snapshot(rows,status,now)
