import unittest,csv,io
from datetime import date
from evaluation import record_trip,with_vtt,daily_rows,active_trip_rows,operational_boards
from prediction_archive import FIELDS
M="525003298"
def t(h,m):return f"2026-11-27T{h:02d}:{m:02d}:00+07:00"
def fixture():
    return dict(mmsi=M,trip_id="x",status="COMPLETED_QC_FAIL",D0_utc=t(9,43),ATA=t(10,23),etd_real=t(10,24),eta_corrected=t(10,42),etd_early=t(11,32),etd_arrival=t(11,15),early_published_at=t(9,44),arrival_published_at=t(10,23),origin_port="BENGKALIS",destination_port="PAKNING",event_qc_flags="DURATION_QC")
class InspectionMetrics(unittest.TestCase):
    def test_historical_failed_qc_evaluation_and_csv(self):
        original=fixture();r=with_vtt(original)
        self.assertEqual(r["early_error_min"],68)
        self.assertEqual(r["arrival_error_min"],51)
        self.assertEqual(r["early_abs_error_min"],68)
        self.assertEqual(r["arrival_abs_error_min"],51)
        self.assertEqual(r["lead_to_departure_min"],40)
        self.assertEqual(r["lead_advantage_min"],39)
        self.assertEqual(r["evaluation_scope"],"OPERATIONAL_QC_FAIL")
        self.assertEqual(r["vtt_real_min"],1)
        self.assertNotIn("early_error_min",original)
        f=io.StringIO();w=csv.DictWriter(f,fieldnames=FIELDS);w.writeheader();w.writerow(r)
        self.assertEqual(next(csv.DictReader(io.StringIO(f.getvalue())))["evaluation_scope"],"OPERATIONAL_QC_FAIL")
    def test_no_future_prediction_or_false_actual(self):
        r=fixture();r["arrival_published_at"]=r["etd_real"]
        self.assertIsNone(with_vtt(r)["arrival_error_min"])
        r["status"]="SAILING"
        self.assertIsNone(with_vtt(r)["early_error_min"])
        r["status"]="COMPLETED_QC_FAIL";r["etd_real"]=t(10,22)
        self.assertEqual(with_vtt(r)["evaluation_scope"],"INVALID_ACTUAL")
        self.assertIsNone(with_vtt(r)["vtt_real_min"])
    def test_arrival_only_has_conventional_error_not_early(self):
        r=fixture();r.update(D0_utc=None,record_type="ARRIVAL_ONLY",etd_early=None,early_published_at=None)
        out=with_vtt(r)
        self.assertIsNone(out["early_error_min"]);self.assertEqual(out["arrival_error_min"],51)
        self.assertIsNone(out["lead_advantage_min"])
    def test_merge_retains_predictions_and_uses_latest_berth(self):
        q=dict(D0_utc=t(9,43),A_utc=t(10,23),origin_port="BENGKALIS",destination_port="PAKNING",qc_flags=["DURATION_QC"])
        p={"D0":dict(issue_utc=q["D0_utc"],published_at=t(9,44),eta=t(10,42),etd=t(11,32)),"A":dict(issue_utc=q["A_utc"],published_at=t(10,23),etd=t(11,15))}
        fix=dict(candidate=True,port="PAKNING",berth="PKN-02",ts=t(10,23),sog=0)
        v=dict(voyage=q,predictions=p,status="BERTHED",stop=dict(port="PAKNING",last=fix,confirmed=False),last=fix)
        state=dict(vessels={M:v});record_trip(state,M,v)
        active=active_trip_rows(state)[M]
        self.assertEqual(active["departure_berth"],"PKN-02");self.assertEqual(active["berth_quality"],"NEAREST")
        self.assertEqual(daily_rows(state,date(2026,11,27))[0],active)
        b=operational_boards([active],{M:active},{M:{"status":"BERTHED"}})
        self.assertEqual(b["departures"][0]["board_time"],active["etd_arrival"])
        self.assertEqual(b["departures"][0]["board_color"],"berthed")
        v["predictions"]={};record_trip(state,M,v,status="COMPLETED_QC_FAIL",observed_exit=t(10,24))
        r=next(iter(state["trip_monitor"].values()))
        self.assertEqual(r["early_error_min"],68);self.assertEqual(r["arrival_error_min"],51)
        self.assertEqual(r["departure_berth"],"PKN-02")
        self.assertEqual(with_vtt(r),r)
