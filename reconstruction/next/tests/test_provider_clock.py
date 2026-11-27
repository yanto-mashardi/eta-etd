import unittest
from datetime import datetime,timezone
from events import classify
from observation_clock import resolve
from operational import publish

class ProviderClockTests(unittest.TestCase):
 def fixture(self):
  now=datetime.fromisoformat("2026-11-26T12:19:21+00:00")
  raw=dict(mmsi="525003298",shipname="KMP MUTIARA PERTIWI2",latitude="1.436963",longitude="102.142487",sog="6.8",cog="167.2",ais_update_at="2026-11-26T12:18:26.770755+00:00",timestamp="2026-11-26 12:19:01.787578+00:00",inference_allowed="True",live_ais_quality="FRESH")
  prev=dict(ts=raw["ais_update_at"],latitude=1.437852,longitude=102.142268,sog=6.7,cog=166.0)
  return now,raw,prev
 def test_actual_mutiara_payload(self):
  now,raw,prev=self.fixture()
  p=resolve(classify(raw,now),raw,prev,now)
  self.assertEqual(p["clock_basis"],"PROVIDER_OBSERVATION")
  self.assertEqual(p["ts"],"2026-11-26T12:19:01.787578+00:00")
  self.assertIsNone(resolve(classify(raw,now),raw,p,now))
 def test_keep_predictions_on_same_fix(self):
  now,raw,prev=self.fixture();m=raw["mmsi"]
  r=dict(mmsi=m,trip_id="x",origin_port="BENGKALIS",destination_port="PAKNING",status="SAILING",D0_utc="2026-11-26T12:12:20.785382+00:00",eta_corrected="2026-11-26T13:07:35.916210+00:00",etd_early="2026-11-26T14:05:27.980944+00:00",early_published_at="2026-11-26T12:12:41.576935+00:00")
  states={m:dict(status="SAILING",last_fix_utc=prev["ts"],last_sog=prev["sog"],last_latitude=prev["latitude"],last_longitude=prev["longitude"])}
  b=publish([raw],"AVAILABLE",now,[r],{m:r},states)
  self.assertEqual(len(b["arrivals"]),1)
  self.assertEqual(len(b["departures"]),2)
  self.assertEqual(b["arrivals"][0]["board_time"],r["eta_corrected"])
  self.assertEqual(next(x for x in b["departures"] if x["board_port"]=="PAKNING")["board_time"],r["etd_early"])
 def test_no_synthetic_clock(self):
  now,raw,prev=self.fixture()
  raw.pop("timestamp")
  self.assertIsNone(resolve(classify(raw,now),raw,prev,now))
