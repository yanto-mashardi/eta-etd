import unittest
from datetime import date
from collections import Counter
from trajectories import normalize
from evaluation import with_vtt
class InspectionVtt(unittest.TestCase):
 def test_vtt(self):
  row={"ATA":"2026-11-26T01:00:00+00:00","etd_arrival":"2026-11-26T01:30:00+00:00","etd_real":"2026-11-26T01:40:00+00:00","status":"COMPLETED_QC_PASS"}
  self.assertEqual(with_vtt(row)["vtt_conventional_min"],30)
  self.assertEqual(with_vtt(row)["vtt_real_min"],40)
  row["status"]="INCOMPLETE_AIS_GAP"
  self.assertIsNone(with_vtt(row)["vtt_real_min"])
 def test_diagnostic(self):
  c=Counter()
  self.assertIsNone(normalize({"mmsi":"525100240"},"2026-11-26T01:00:00+00:00",date(2026,11,26),c))
  self.assertEqual(c["MISSING_TIMESTAMP"],1)
