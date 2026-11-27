import unittest,time
from datetime import datetime,timezone
from evaluation import with_vtt
from health import notices
from trajectories import _cache,expire_cache
class HealthCacheTests(unittest.TestCase):
 def test_vtt_correction(self):
  r=with_vtt(dict(vtt_early_base_min=40,vtt_early_min=45))
  self.assertEqual(r["vtt_early_correction_min"],5)
  self.assertIsNone(r["vtt_conventional_correction_min"])
 def test_cache_expiry(self):
  _cache.clear();_cache["old"]=(time.monotonic()-61,{})
  expire_cache();self.assertFalse(_cache)
 def test_waiting_vs_error(self):
  now=datetime(2026,11,26,1,0,tzinfo=timezone.utc)
  out=notices("AVAILABLE",[],"MODEL_LOADED_UNVALIDATED",{"status":"STAGING_UNVALIDATED"},{"bengkalis":{},"pakning":{"last_received":"2026-11-26T00:55:00+00:00"}},now)
  self.assertIn(("CCTV_WAITING","bengkalis"),[(x["code"],x["port"]) for x in out])
  self.assertIn(("CCTV_ERROR","pakning"),[(x["code"],x["port"]) for x in out])
