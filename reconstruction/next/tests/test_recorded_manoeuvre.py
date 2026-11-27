import unittest
from datetime import datetime,timedelta
from events import classify,resolve,dt
from live_events import OperationalTracker
class RecordedManoeuvre(unittest.TestCase):
    def test_real_geometry_and_reported_times_from_27_nov(self):
        # Subset of operator audit log. Receipt simulated +1s because the excerpt
        # reports provider observation and update, not exact receipt time.
        data=[
            ("11:19:09.497101","11:16:08.859439",1.380143,102.148433,0),
            ("11:22:27.637419","11:22:11.824501",1.381043,102.147908,3.7),
            ("11:23:29.454895","11:22:11.824501",1.381715,102.148337,2.7),
            ("11:24:08.857975","11:22:11.824501",1.381615,102.148658,.7),
            ("11:24:29.727975","11:22:11.824501",1.381628,102.148677,1),
            ("11:25:28.451339","11:22:11.824501",1.382490,102.148637,4.2),
            ("11:25:39.056852","11:22:11.824501",1.382647,102.148625,4.2),
        ]
        def iso(t):return "2026-11-27T"+t+"+07:00"
        t=OperationalTracker();prev=None;events=[]
        for obs,src,lat,lon,sog in data:
            row=dict(mmsi="525003298",latitude=lat,longitude=lon,sog=sog,cog=0,ais_update_at=iso(src),timestamp=iso(obs),inference_allowed=True)
            now=dt(iso(obs))+timedelta(seconds=1)
            p=resolve(classify(row,now),row,prev,now)
            if p:events.extend(t.process(p));prev=p
        self.assertEqual([x["phase"] for x in events],["D0"])
        self.assertEqual(dt(events[0]["issue_utc"]),dt(iso(data[-1][0])))
    def test_server_clock_cannot_replace_source(self):
        now=dt("2026-11-27T11:22:00+07:00")
        r=dict(mmsi="525003298",latitude=1.38,longitude=102.14856,sog=0,ais_update_at="2026-11-27T11:19:00+07:00",timestamp=now.isoformat(),inference_allowed=True)
        prev=resolve(classify(r,now),r,None,now)
        r.update(latitude=1.3802,sog=1,provider_observation_basis="SERVER_FALLBACK")
        self.assertIsNone(resolve(classify(r,now),r,prev,now))
