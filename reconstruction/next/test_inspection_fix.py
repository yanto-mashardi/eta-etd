import unittest
from trajectories import split_trips
from legacy_tracker import Tracker
from events import dt
class InspectionFix(unittest.TestCase):
 def test_stationary_visible(self):
  p=dict(mmsi="525100240",shipname="Test",ts="2026-11-26T01:00:00+00:00",received="2026-11-26T01:00:00+00:00",lat=1.38,lon=102.1485,sog=0,cog=None,distance=.01,port="PAKNING",berth="PKN-01",candidate=True,ambiguous=True)
  r=split_trips([p])
  self.assertEqual(len(r),1)
  self.assertEqual(r[0]["status"],"AT_BERTH")
  self.assertEqual(r[0]["point_count"],1)
 def test_nearest_not_confirmed(self):
  t=Tracker()
  p=dict(mmsi="525100240",ts="2026-11-26T01:00:00+00:00",received="2026-11-26T01:00:00+00:00",sog=0,cog=None,distance=.01,port="PAKNING",berth="PKN-01",candidate=True,ambiguous=True)
  t.process(p)
  v=t.snapshot(dt(p["ts"]))[p["mmsi"]]
  self.assertIsNone(v["berth"])
  self.assertEqual(v["nearest_berth"],"PKN-01")
  self.assertEqual(v["berth_confidence"],"NEAREST_ONLY")
