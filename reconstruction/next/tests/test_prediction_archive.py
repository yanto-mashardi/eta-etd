import unittest,tempfile,json
from pathlib import Path
from datetime import date
from prediction_archive import groups,fingerprint,prune_verified
class ArchiveTest(unittest.TestCase):
 def test_verified_prune(self):
  r={"trip_id":"x","D0_utc":"2026-11-18T01:00:00+00:00","status":"COMPLETED_QC_PASS","etd_real":"2026-11-18T02:00:00+00:00"}
  s={"trip_monitor":{"x":r}}
  with tempfile.TemporaryDirectory() as p:
   p=Path(p)
   self.assertEqual(prune_verified(s,p,date(2026,11,26)),0)
   (p/"2026-11-18.verified.json").write_text(json.dumps({"fingerprint":fingerprint(groups(s)["2026-11-18"])}))
   self.assertEqual(prune_verified(s,p,date(2026,11,26)),1)
   self.assertEqual(s["trip_monitor"],{})
 def test_unfinished_retained(self):
  r={"trip_id":"x","D0_utc":"2026-11-18T01:00:00+00:00","status":"SAILING"}
  s={"trip_monitor":{"x":r}}
  with tempfile.TemporaryDirectory() as p:
   p=Path(p);(p/"2026-11-18.verified.json").write_text(json.dumps({"fingerprint":fingerprint([r])}))
   self.assertEqual(prune_verified(s,p,date(2026,11,26)),0)
