import unittest
from datetime import date,timedelta
from events import dt
from test_events import fix
from live_events import OperationalTracker
from evaluation import record_trip,active_trip_rows,daily_rows,operational_boards,trip_key
from prediction_archive import groups
from live_events import first_stationary
M="525002060"
class IndependentArrival(unittest.TestCase):
 def test_arrival_without_d0_and_return(self):
  tr=OperationalTracker()
  tr.process(fix(10))
  e=tr.process(fix(12,"PAKNING"))
  self.assertEqual([x["phase"] for x in e],["A"])
  v=tr.state["vessels"][M]
  self.assertIsNone(v["voyage"]["D0_utc"])
  self.assertEqual(v["voyage"]["A_utc"],fix(12)["ts"])
  v["predictions"]["A"]=dict(issue_utc=e[0]["issue_utc"],published_at=e[0]["published_at"],etd=fix(42)["ts"])
  record_trip(tr.state,M,v)
  r=active_trip_rows(tr.state)[M]
  self.assertEqual(r["record_type"],"ARRIVAL_ONLY")
  self.assertIsNone(r["D0_utc"])
  self.assertIsNone(r.get("eta_corrected"))
  self.assertEqual(r["etd_arrival"],fix(42)["ts"])
  self.assertEqual(daily_rows(tr.state,date(2026,11,25))[0],r)
  self.assertEqual(len(groups(tr.state)),1)
  b=operational_boards([r],{M:r},{M:{"status":"BERTHED"}})
  self.assertEqual(b["departures"][0]["board_color"],"berthed")
  self.assertEqual(b["departures"][0]["board_time"],fix(42)["ts"])
  self.assertEqual(b["arrivals"][0]["board_time"],fix(12)["ts"])
  self.assertEqual(tr.process(fix(14,"PAKNING")),[])
  self.assertEqual(tr.process(fix(16,"PAKNING")),[])
  from copy import deepcopy
  old=deepcopy(v)
  self.assertEqual([x["phase"] for x in tr.process(fix(18))],["D0"])
  self.assertEqual(len(tr.state["cycles"]),0)
  exit=v["operational_exit"]
  self.assertEqual(exit["trip_id"],trip_key(M,old["voyage"]))
  record_trip(tr.state,M,old,status="COMPLETED_QC_FAIL",observed_exit=exit["D1_utc"])
  self.assertEqual(tr.state["trip_monitor"][r["trip_id"]]["etd_real"],fix(18)["ts"])
 def test_startup_no_false_ata(self):
  tr=OperationalTracker()
  self.assertEqual(tr.process(fix(10,"PAKNING")),[])
  self.assertEqual(tr.process(fix(12,"PAKNING")),[])
  self.assertEqual(tr.process(fix(14,"PAKNING")),[])
  self.assertIsNone(tr.state["vessels"][M]["voyage"])
 def test_recovery_requires_bracket(self):
  p=fix(20,"PAKNING")
  self.assertIsNone(first_stationary([fix(12,"PAKNING"),fix(16,"PAKNING")],p))
  first=first_stationary([fix(8),fix(12,"PAKNING"),fix(16,"PAKNING")],p)
  self.assertEqual(first["ts"],fix(12)["ts"])
  self.assertIsNone(first_stationary([fix(0),fix(12,"PAKNING"),fix(16,"PAKNING")],p))

 def test_stop_outside_berth_not_moving_bracket(self):
  tr=OperationalTracker()
  p=fix(10);p["sog"]=0
  tr.process(p)
  self.assertEqual(tr.process(fix(12,"PAKNING")),[])
  self.assertIsNone(tr.state["vessels"][M]["voyage"])
