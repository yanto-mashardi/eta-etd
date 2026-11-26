import unittest
from datetime import datetime,timezone
from events import Tracker
from test_events import fix
from operational import publish
T="2026-11-26T10:40:00+00:00"
NOW=datetime.fromisoformat(T)
M="525003298"
def raw(lat,lon,sog):
 return dict(mmsi=M,shipname="Test",latitude=lat,longitude=lon,sog=sog,ais_update_at=T,inference_allowed="true",live_ais_quality="FRESH")
def trip():
 return dict(mmsi=M,trip_id="x",origin_port="BENGKALIS",destination_port="PAKNING",D0_utc="2026-11-26T09:30:00+00:00",eta_corrected="2026-11-26T10:00:00+00:00",etd_early="2026-11-26T10:45:00+00:00",early_published_at="2026-11-26T09:31:00+00:00",status="SAILING")
class PublicationTests(unittest.TestCase):
 def test_moving_ais_overrides_old_berth(self):
  r=trip();r.update(ATA="2026-11-26T10:05:00+00:00",status="BERTHED",etd_arrival="2026-11-26T10:50:00+00:00")
  b=publish([raw(1.382,102.15,6.2)],"AVAILABLE",NOW,[r],{M:r},{M:dict(status="BERTHED",last_fix_utc=T)})
  self.assertFalse(b["arrivals"]);self.assertIsNone(b["departures"][0]["board_time"]);self.assertEqual(b["vessels"][M]["status"],"BERGERAK")
 def test_sailing_then_arrival(self):
  r=trip();s={M:dict(status="SAILING",last_fix_utc=T)}
  b=publish([raw(1.41,102.14,6)],"AVAILABLE",NOW,[r],{M:r},s)
  self.assertEqual(len(b["departures"]),2);self.assertEqual(b["arrivals"][0]["board_time"],r["eta_corrected"])
  r.update(ATA="2026-11-26T10:05:00+00:00",status="BERTHED",etd_arrival="2026-11-26T10:50:00+00:00")
  s[M]["status"]="BERTHED"
  b=publish([raw(1.380001,102.148561,0)],"AVAILABLE",NOW,[r],{M:r},s)
  self.assertEqual(len(b["departures"]),1);self.assertEqual(b["departures"][0]["board_time"],r["etd_arrival"]);self.assertEqual(b["arrivals"][0]["board_time"],r["ATA"])
 def test_stationary_origin_conflict(self):
  r=trip()
  b=publish([raw(1.449921,102.136747,0)],"AVAILABLE",NOW,[r],{M:r},{M:dict(status="SAILING",last_fix_utc=T)})
  self.assertFalse(b["arrivals"]);self.assertIsNone(b["departures"][0]["board_time"])
 def test_stationary_outside_not_departure(self):
  tr=Tracker(require_moving_exit=True)
  for n,p in [(0,None),(2,"BENGKALIS"),(4,"BENGKALIS"),(6,"BENGKALIS")]:tr.process(fix(n,p))
  q=fix(8);q["sog"]=0
  self.assertEqual(tr.process(q),[])
  self.assertEqual(tr.process(fix(9))[0]["phase"],"D0")

 def test_stationary_return_restores_berth(self):
  tr=Tracker(require_moving_exit=True)
  for n,p in [(0,None),(2,"BENGKALIS"),(4,"BENGKALIS"),(6,"BENGKALIS")]:tr.process(fix(n,p))
  q=fix(8);q["sog"]=0
  self.assertEqual(tr.process(q),[])
  self.assertEqual(tr.process(fix(9,"BENGKALIS")),[])
  self.assertEqual(tr.state["vessels"]["525002060"]["status"],"BERTHED")
