import unittest
from datetime import datetime,timezone,timedelta
from legacy_tracker import Tracker
from events import features,classify,PORTS,clean_cycle
T=datetime(2026,11,25,0,tzinfo=timezone.utc)
def fix(n,port=None,received=None):
    t=T+timedelta(minutes=n);p=port or "BENGKALIS"
    return {"mmsi":"525002060","ts":t.isoformat(),"received":(T+timedelta(minutes=received if received is not None else n)).isoformat(),
            "port":p,"berth":"BKL-01" if p=="BENGKALIS" else "PKN-01","candidate":port is not None,"ambiguous":False,"sog":0 if port else 8,"cog":90,"distance":.02 if port else .5}
class EventTests(unittest.TestCase):
    def test_cycle_and_delay(self):
        tr=Tracker();events=[]
        for n,p in [(0,None),(2,"BENGKALIS"),(4,"BENGKALIS"),(6,"BENGKALIS"),(8,None),(16,None),(24,None),(32,None),(38,"PAKNING"),(40,"PAKNING"),(42,"PAKNING"),(46,"PAKNING"),(48,None)]:
            events+=tr.process(fix(n,p))
        self.assertEqual([e["phase"] for e in events],["D0","A","D0"])
        self.assertEqual(events[1]["issue_utc"],fix(38)["ts"])
        self.assertEqual(events[1]["published_at"],fix(42)["ts"])
        self.assertEqual(len(tr.history),1)
        self.assertEqual(tr.history[0]["sailing"],30)
        self.assertEqual(tr.history[0]["vtt"],10)
        self.assertEqual(events[-1]["features"]["historical_completed_count"],0)
        self.assertEqual(tr.process(fix(48)),[])
    def test_gap(self):
        tr=Tracker()
        for n,p in [(0,None),(2,"BENGKALIS"),(4,"BENGKALIS"),(6,"BENGKALIS")]:tr.process(fix(n,p))
        self.assertEqual(tr.process(fix(30)),[])
        self.assertIsNone(tr.state["vessels"]["525002060"]["voyage"])
    def test_asof_median(self):
        history=[]
        for i in range(35):
            d0=T-timedelta(days=40-i);a=d0+timedelta(minutes=30+i);d1=a+timedelta(minutes=20)
            history.append(clean_cycle({"mmsi":"525002060","origin_port":"BENGKALIS","destination_port":"PAKNING","D0_utc":d0.isoformat(),"A_utc":a.isoformat(),"D1_utc":d1.isoformat()}))
        f=features(history,fix(0),"BENGKALIS","PAKNING")
        self.assertEqual(f["historical_completed_count"],35)
        self.assertEqual(f["hist_pair_n"],30)
        self.assertEqual(f["hist_pair_sailing_median_min"],49.5)
    def test_same_port_gap_12(self):
        tr=Tracker()
        for n,p in [(0,None),(2,"BENGKALIS"),(13,"BENGKALIS"),(15,"BENGKALIS")]:tr.process(fix(n,p))
        self.assertTrue(tr.state["vessels"]["525002060"]["stop"]["confirmed"])
        self.assertEqual(tr.process(fix(17))[0]["phase"],"D0")
    def test_duplicate_and_ambiguous(self):
        tr=Tracker();tr.process(fix(0));p=fix(2,"BENGKALIS");p["ambiguous"]=True
        tr.process(p);tr.process(p)
        self.assertEqual(tr.state["vessels"][p["mmsi"]]["stop"]["n"],1)
    def test_real_geometry_and_freshness(self):
        lat,lon=PORTS["BENGKALIS"]["BKL-01"]
        row={"mmsi":"525002060","latitude":lat,"longitude":lon,"sog":0,"cog":90,"ais_update_at":T.isoformat(),"inference_allowed":"true"}
        p=classify(row,T);self.assertTrue(p["candidate"]);self.assertEqual(p["port"],"BENGKALIS")
        with self.assertRaises(ValueError):classify(row,T+timedelta(minutes=6))
if __name__=="__main__":unittest.main()
