import unittest,tempfile,json,sqlite3
from pathlib import Path
from datetime import datetime,timezone
from trajectories import split_trips
from events import atomic_json
from test_events import fix
from live_events import OperationalTracker
from stockflow import Ledger
from live import Live
class IntegrationContract(unittest.TestCase):
    def test_trajectory_uses_journal_interval(self):
        p=fix(8);p.update(lat=1.42,lon=102.14,shipname="Test")
        q=dict(p,ts=fix(10)["ts"])
        row=dict(trip_id="journal-1",D0_utc=fix(6)["ts"],ATA=fix(40)["ts"],origin_port="BENGKALIS",destination_port="PAKNING",status="BERTHED")
        a=split_trips([p,q],[row])
        self.assertEqual(len(a),1)
        self.assertEqual(a[0]["journal_trip_id"],"journal-1")
        self.assertIsNone(split_trips([p,q])[0]["journal_trip_id"])
    def test_event_evidence(self):
        t=OperationalTracker()
        for n,p in [(0,None),(2,"BENGKALIS"),(4,"BENGKALIS"),(6,"BENGKALIS"),(8,None),(16,None),(24,None),(32,None),(38,"PAKNING"),(40,"PAKNING"),(42,"PAKNING"),(46,"PAKNING"),(48,None)]:t.process(fix(n,p))
        x=t.state["vessels"]["525002060"]["operational_exit"]["event_evidence"]
        self.assertEqual(x["D0"]["ts"],fix(8)["ts"])
        self.assertEqual(x["A"]["ts"],fix(38)["ts"])
        self.assertEqual(x["D1"]["ts"],fix(48)["ts"])
    def test_outbox_is_idempotent_on_restart(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);l=Live(root,root/"ais.csv",None,None)
            x=dict(port="BENGKALIS",mmsi="525002060",ts=fix(8)["ts"])
            l.tracker.state["departure_outbox"]={"trip":x}
            atomic_json(l.path,l.tracker.state)
            l.ledger.departure(x["port"],x["mmsi"],x["ts"])
            l.ledger.close()
            r=Live(root,root/"ais.csv",None,None);r.drain_departures()
            self.assertEqual(json.loads(r.path.read_text())["departure_outbox"],{})
            with r.ledger.connect() as db:self.assertEqual(db.execute("SELECT count(*) FROM departures").fetchone()[0],1)
            r.ledger.close()
    def test_cache_invalidates_on_external_transaction(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"ledger.sqlite";l=Ledger(path);other=Ledger(path)
            self.assertEqual(l.snapshot("bengkalis")["recent_departures"],[])
            other.departure("bengkalis","525002060",fix(8)["ts"])
            self.assertEqual(len(l.snapshot("bengkalis")["recent_departures"]),1)
            l.close();other.close()
