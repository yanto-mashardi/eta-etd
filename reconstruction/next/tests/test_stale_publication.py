import unittest
from datetime import timedelta
from events import classify
from evaluation import publish
from test_operational import NOW,M,raw,trip

def state(r,fix):
    return {M:dict(status="STALE",last_status=r["status"],last_observation=fix,last_fix_utc=fix["ts"],source_fix_utc=fix["ts"],port=fix["port"] if fix["candidate"] else None,nearest_berth=fix["berth"] if fix["candidate"] else None,shipname="Test")}

class StalePublication(unittest.TestCase):
 def test_sailing_keeps_three_rows_and_times(self):
    r=trip();row=raw(1.41,102.14,6);fix=classify(row,NOW)
    before=publish([row],"AVAILABLE",NOW,[r],{M:r},{M:dict(status="SAILING",last_fix_utc=fix["ts"])})
    row["live_ais_quality"]="STALE"
    after=publish([row],"AVAILABLE",NOW+timedelta(minutes=6),[r],{M:r},state(r,fix))
    self.assertEqual(len(after["arrivals"]),1)
    self.assertEqual(len(after["departures"]),2)
    for k in ("arrivals","departures"):
        self.assertEqual([(x["board_port"],x["board_time"],x["board_color"],x["board_status"]) for x in before[k]],[(x["board_port"],x["board_time"],x["board_color"],x["board_status"]) for x in after[k]])
        self.assertTrue(all(x["ais_quality"]=="STALE" for x in after[k]))
    self.assertEqual(after["vessels"][M]["sog"],6)
 def test_missing_snapshot_keeps_sandar(self):
    r=trip();r.update(ATA="2026-11-26T10:05:00+00:00",status="BERTHED",etd_arrival="2026-11-26T10:50:00+00:00")
    fix=classify(raw(1.380001,102.148561,0),NOW)
    after=publish([],"UNAVAILABLE",NOW+timedelta(minutes=6),[r],{M:r},state(r,fix))
    self.assertEqual(len(after["arrivals"]),1)
    self.assertEqual(len(after["departures"]),1)
    self.assertEqual(after["departures"][0]["board_time"],r["etd_arrival"])
    self.assertEqual(after["departures"][0]["board_color"],"berthed")
    self.assertEqual(after["departures"][0]["ais_quality"],"STALE")
    self.assertEqual(after["departures"][0]["board_berth"],"PKN-01")
 def test_fresh_arrival_replaces_stale_departure(self):
    r=trip();fix=classify(raw(1.41,102.14,6),NOW)
    prior=publish([],"UNAVAILABLE",NOW+timedelta(minutes=6),[r],{M:r},state(r,fix))
    self.assertEqual(len(prior["departures"]),2)
    r.update(ATA="2026-11-26T10:05:00+00:00",status="BERTHED",etd_arrival="2026-11-26T10:50:00+00:00")
    current=publish([raw(1.380001,102.148561,0)],"AVAILABLE",NOW,[r],{M:r},{M:dict(status="BERTHED",last_fix_utc=fix["ts"])})
    self.assertEqual(len(current["departures"]),1)
    self.assertEqual(current["departures"][0]["board_port"],"PAKNING")
    self.assertEqual(current["departures"][0]["ais_quality"],"FRESH")
