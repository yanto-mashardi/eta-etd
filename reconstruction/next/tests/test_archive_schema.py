import unittest
from datetime import date
from trajectories import normalize,split_trips
class ArchiveSchema(unittest.TestCase):
 def test_real_schema(self):
  r={"mmsi":"525003298","timestamp":"2026-11-24T10:00:05+07:00","update_at":"2026-11-24T09:59:00.147016","lat":"1.449358","lon":"102.138487","sog":"","raw_json":'{"speed":0,"course":0}'}
  p=normalize(r,"2026-11-24T03:00:06+00:00",date(2026,11,24))
  self.assertIsNotNone(p);self.assertEqual(p["sog"],0);self.assertEqual(p["ts"],"2026-11-24T03:00:05+00:00")
  r.update(timestamp="2026-11-24T10:00:15+07:00",lat="1.449360")
  q=normalize(r,"2026-11-24T03:00:16+00:00",date(2026,11,24))
  self.assertNotEqual(p["ts"],q["ts"])
 def test_raw_schema(self):
  p=normalize({"mmsi":525003298,"timestamp":"2026-11-24T10:00:05+07:00","update_at":"2026-11-24T09:59:00","lat":1.449358,"lon":102.138487,"speed":0},"2026-11-24T03:00:06+00:00",date(2026,11,24))
  self.assertIsNotNone(p)
