import unittest
from evaluation import evaluate
class EvaluationTest(unittest.TestCase):
 def test_completed(self):
  def t(h,m):return f"2026-11-26T{h:02d}:{m:02d}:00+00:00"
  v=dict(D0_utc=t(1,0),A_utc=t(1,40),origin_port="BENGKALIS",destination_port="PAKNING")
  p={"D0":dict(issue_utc=t(1,0),published_at=t(1,1),eta=t(1,42),etd=t(2,5),eta_components={"baseline_min":45}),"A":dict(issue_utc=t(1,40),published_at=t(1,45),etd=t(2,0))}
  r=evaluate("525003298",v,p,{"D1_utc":t(2,2)})
  self.assertEqual(r["eta_correction_min"],-3)
  self.assertEqual(r["early_error_min"],3)
  self.assertEqual(r["arrival_error_min"],-2)
  self.assertEqual(r["lead_advantage_min"],44)
  self.assertEqual(r["lead_to_departure_min"],61)
  self.assertIsNone(evaluate("525003298",v,p)["early_error_min"])

 def test_retention(self):
  from evaluation import record_trip,daily_rows
  from datetime import date
  state={}
  v={"voyage":{"D0_utc":"2026-11-26T01:00:00+00:00","A_utc":"2026-11-26T01:40:00+00:00","origin_port":"BENGKALIS","destination_port":"PAKNING"},"stop":{"confirmed":True,"port":"PAKNING","votes":{"PKN-01":3},"n":3},"last":{"ts":"2026-11-26T01:44:00+00:00","sog":0},"predictions":{}}
  record_trip(state,"525003298",v)
  record_trip(state,"525003298",v,{"D1_utc":"2026-11-26T02:00:00+00:00"})
  v["voyage"]={"D0_utc":"2026-11-26T02:00:00+00:00","origin_port":"PAKNING","destination_port":"BENGKALIS"}
  record_trip(state,"525003298",v)
  rows=daily_rows(state,date(2026,11,26))
  self.assertEqual(len(rows),2)
  self.assertEqual(rows[0]["departure_berth"],"PKN-01")
  self.assertEqual(rows[0]["status"],"COMPLETED_QC_PASS")
