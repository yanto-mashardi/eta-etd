import unittest,importlib.util,sys
from pathlib import Path
from events import dt
class ReceiverProvenance(unittest.TestCase):
    def test_receiver_schema_and_fallback(self):
        import os
        path=Path(os.environ.get("BIMA2_CANDIDATE_POLLER",str(Path(__file__).resolve().parents[3]/"scripts/data_source/ais/poll_ais_api_realtime.py")))
        spec=importlib.util.spec_from_file_location("candidate_poller_test",path)
        p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)
        fmap=dict(mmsi="mmsi",latitude="lat",longitude="lon",sog="speed",cog="course",timestamp="timestamp",ais_update_at="update_at")
        centers=dict(BENGKALIS=(1.449921,102.136747),PAKNING=(1.380001,102.148561))
        raw=dict(mmsi=525003298,lat=1.38,lon=102.14856,speed=0,course=0,update_at="2026-11-27T11:19:00+07:00")
        def n():return p.normalize_one(raw,fmap,dict(naive_timestamp_timezone="Asia/Jakarta"),centers,2,{525003298})
        self.assertEqual(n()["provider_observation_basis"],"SERVER_FALLBACK")
        raw["timestamp"]="2026-11-27T11:19:03";self.assertEqual(n()["provider_observation_basis"],"PROVIDER_ASSUMED_TZ")
        raw["timestamp"]="2026-11-27T11:19:03+07:00";self.assertEqual(n()["provider_observation_basis"],"PROVIDER_EXPLICIT_OFFSET")
        self.assertEqual(dt(n()["timestamp"]),dt(raw["timestamp"]))
    def test_vps_alias_and_raw_trajectory_identity(self):
        import os
        from datetime import date
        from events import MMSI_ALIAS,canonical_mmsi,classify
        from trajectories import normalize
        path=Path(os.environ.get("BIMA2_CANDIDATE_POLLER",str(Path(__file__).resolve().parents[3]/"scripts/data_source/ais/poll_ais_api_realtime.py")))
        spec=importlib.util.spec_from_file_location("candidate_alias_test",path)
        p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)
        self.assertEqual({str(k):str(v) for k,v in p.MMSI_ALIAS.items()},MMSI_ALIAS)
        fmap=dict(mmsi="mmsi",latitude="lat",longitude="lon",sog="speed",cog="course",timestamp="timestamp",ais_update_at="update_at")
        centers=dict(BENGKALIS=(1.449921,102.136747),PAKNING=(1.380001,102.148561))
        raw=dict(mmsi=50862783,lat=1.38,lon=102.14856,speed=0,course=0,update_at="2026-11-27T11:19:00+07:00",timestamp="2026-11-27T11:19:03+07:00")
        r=p.normalize_one(raw,fmap,{},centers,2,{525100240})
        self.assertEqual(r["mmsi"],525100240)
        self.assertEqual(r["reported_mmsi"],50862783)
        self.assertEqual(p.rejection_reason(raw,fmap,centers,2,{525100240}),(None,50862783))
        rx=dt("2026-11-27T11:19:04+07:00")
        self.assertEqual(classify(r,rx)["mmsi"],"525100240")
        self.assertEqual(classify(r,rx)["reported_mmsi"],"50862783")
        x=normalize(raw,rx.isoformat(),date(2026,11,27))
        self.assertEqual(x["mmsi"],"525100240")
        self.assertEqual(x["reported_mmsi"],"50862783")
        self.assertEqual(canonical_mmsi(525100240),"525100240")
        self.assertEqual(raw["mmsi"],50862783)
        raw["mmsi"]=12345678
        self.assertIsNone(p.normalize_one(raw,fmap,{},centers,2,{525100240}))
