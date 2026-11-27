import unittest
from copy import deepcopy
from datetime import timedelta
from events import dt
from test_events import fix
from test_operational import NOW,M as PUBLIC_M,raw,trip
from live_events import OperationalTracker
from evaluation import record_trip,active_trip_rows,trip_key
from operational import publish
from prediction_archive import FIELDS
M="525002060"
class JournalContinuity(unittest.TestCase):
 def test_manoeuvre_keeps_original_trip_and_predictions(self):
    tr=OperationalTracker()
    def tick(p):
        old=deepcopy(tr.state["vessels"].get(M,{}))
        n=len(tr.state["cycles"])
        events=tr.process(p)
        v=tr.state["vessels"][M]
        if old.get("voyage") and trip_key(M,old["voyage"])!=trip_key(M,v["voyage"]):
            exit=v.get("operational_exit") or {}
            if len(tr.state["cycles"])>n:record_trip(tr.state,M,old,tr.state["cycles"][-1])
            elif exit.get("trip_id")==trip_key(M,old["voyage"]):record_trip(tr.state,M,old,status="COMPLETED_QC_FAIL",observed_exit=exit["D1_utc"])
        for e in events:
            t=dt(e["issue_utc"]);phase=e["phase"]
            r=dict(issue_utc=e["issue_utc"],published_at=e["published_at"],status="PROVISIONAL_UNVALIDATED",release="test",vtt_components={"baseline_min":52.7,"duration_min":50})
            if phase=="D0":r.update(eta=(t+timedelta(minutes=40)).isoformat(),etd=(t+timedelta(minutes=90)).isoformat(),eta_components={"baseline_min":42})
            else:r["etd"]=(t+timedelta(minutes=50)).isoformat()
            v["predictions"][phase]=r
        record_trip(tr.state,M,v)
        return [e["phase"] for e in events]
    for n in [0,2,4]:tick(fix(n,"BENGKALIS"))
    self.assertEqual(tick(fix(6)),["D0"])
    for n in [14,22,30]:tick(fix(n))
    self.assertEqual(tick(fix(46,"PAKNING")),["A"])
    before=active_trip_rows(tr.state)[M]
    p=fix(46.4,"PAKNING");p.update(candidate=False,sog=1.0,distance=.04)
    self.assertEqual(tick(p),[])
    self.assertEqual(len(tr.state["trip_monitor"]),1)
    during=active_trip_rows(tr.state)[M]
    self.assertEqual(during["status"],"BERTH_MANEUVER")
    for k in ("trip_id","D0_utc","ATA","eta_corrected","etd_early","etd_arrival"):self.assertEqual(during[k],before[k])
    for n in [48,50,56,64]:self.assertEqual(tick(fix(n,"PAKNING")),[])
    self.assertEqual(tick(fix(70)),["D0"])
    self.assertEqual(len(tr.state["trip_monitor"]),2)
    r=tr.state["trip_monitor"][before["trip_id"]]
    self.assertEqual(r["etd_real"],fix(70)["ts"])
    self.assertEqual(r["vtt_real_min"],24)
    self.assertIsNotNone(r["early_error_min"]);self.assertIsNotNone(r["arrival_error_min"])
    self.assertEqual(r["prediction_status_early"],"PROVISIONAL_UNVALIDATED")
    self.assertEqual(r["prediction_status_arrival"],"PROVISIONAL_UNVALIDATED")
 def test_public_keeps_conventional_while_tracker_reports_manoeuvre(self):
    r=trip();r.update(ATA="2026-11-26T10:05:00+00:00",status="BERTH_MANEUVER",etd_arrival="2026-11-26T10:50:00+00:00",arrival_published_at="2026-11-26T10:06:00+00:00")
    b=publish([raw(1.3801,102.14856,1.0)],"AVAILABLE",NOW,[r],{PUBLIC_M:r},{PUBLIC_M:{"status":"BERTH_MANEUVER","last_fix_utc":NOW.isoformat()}})
    self.assertEqual(len(b["arrivals"]),1);self.assertEqual(len(b["departures"]),1)
    self.assertEqual(b["departures"][0]["board_time"],r["etd_arrival"])
    self.assertEqual(b["departures"][0]["board_color"],"berthed")
 def test_failed_inference_recorded_without_fake_forecast(self):
    q=dict(D0_utc=fix(6)["ts"],origin_port="BENGKALIS",destination_port="PAKNING")
    v=dict(voyage=q,status="SAILING",predictions={"D0":dict(issue_utc=q["D0_utc"],status="FEATURE_OR_MODEL_ERROR",error="missing feature")})
    state={};record_trip(state,M,v);r=next(iter(state["trip_monitor"].values()))
    self.assertIsNone(r.get("eta_corrected"));self.assertEqual(r["prediction_status_early"],"FEATURE_OR_MODEL_ERROR")
    self.assertEqual(r["prediction_error_early"],"missing feature")
    self.assertIn("prediction_error_early",FIELDS)
