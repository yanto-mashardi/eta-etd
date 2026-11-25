import unittest
from datetime import date
from trajectories import normalize,split_trips
class TestTrajectory(unittest.TestCase):
 def fix(self,t,lat,lon,sog):
  return normalize({"mmsi":"525003298","update_at":"2026-11-25T"+t+"+00:00","lat":lat,"lon":lon,"sog":sog},"2026-11-25T10:00:00+00:00",date(2026,11,25))
 def test_gap(self):
  p=[self.fix("01:00:00",1.42,102.14,7),self.fix("01:02:00",1.41,102.14,7),self.fix("01:30:00",1.40,102.14,7)]
  t=split_trips(p);self.assertEqual([x["point_count"] for x in t],[2,1]);self.assertEqual(t[0]["status"],"AIS_GAP")
 def test_day(self):
  self.assertIsNone(normalize({"mmsi":"525003298","update_at":"2026-11-24T16:00:00+00:00","lat":1.42,"lon":102.14,"sog":7},"2026-11-25T10:00:00+00:00",date(2026,11,25)))
if __name__=="__main__":unittest.main()
