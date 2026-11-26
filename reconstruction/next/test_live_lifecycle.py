import unittest
from events import dt
from test_events import fix
from live_events import OperationalTracker
from evaluation import record_trip,active_trip_rows,operational_boards
M="525002060"
class LiveLifecycle(unittest.TestCase):
 def test_round_trip_with_gap(self):
  tr=OperationalTracker()
  def tick(n,port):
   p=fix(n,port);old=tr.state["vessels"].get(M,{}).get("voyage")
   events=tr.process(p)
   v=tr.state["vessels"][M]
   for e in events:
    phase=e["phase"];t=dt(e["issue_utc"])
    from datetime import timedelta
    if phase=="D0":
     v["predictions"][phase]=dict(issue_utc=e["issue_utc"],published_at=e["published_at"],eta=(t+timedelta(minutes=30)).isoformat(),etd=(t+timedelta(minutes=75)).isoformat())
    else:v["predictions"][phase]=dict(issue_utc=e["issue_utc"],published_at=e["published_at"],etd=(t+timedelta(minutes=25)).isoformat())
   record_trip(tr.state,M,v)
   return events,operational_boards(tr.state.get("trip_monitor",{}).values(),active_trip_rows(tr.state),{M:{"status":v["status"]}})
  tick(0,"BENGKALIS")
  tick(2,"BENGKALIS")
  tick(4,"BENGKALIS")
  e,b=tick(6,None);self.assertEqual([x["phase"] for x in e],["D0"]);self.assertEqual(len(b["departures"]),2)
  e,b=tick(36,"PAKNING");self.assertEqual([x["phase"] for x in e],["A"]);self.assertEqual(len(b["departures"]),1);self.assertEqual(b["arrivals"][0]["board_color"],"actual");self.assertEqual(b["departures"][0]["board_color"],"berthed")
  tick(38,"PAKNING");tick(40,"PAKNING")
  e,b=tick(60,None);self.assertEqual(e,[]) # too large a departure bracket, no fabricated D0
 def test_normal_return_and_qc(self):
  tr=OperationalTracker()
  phases=[]
  for n,p in [(0,None),(2,"BENGKALIS"),(4,"BENGKALIS"),(6,"BENGKALIS"),(8,None),(16,None),(24,None),(32,None),(38,"PAKNING"),(40,"PAKNING"),(42,"PAKNING"),(46,"PAKNING"),(48,None)]:
   phases.extend(x["phase"] for x in tr.process(fix(n,p)))
  self.assertEqual(phases,["D0","A","D0"])
  self.assertEqual(len(tr.state["cycles"]),1)
  self.assertEqual(tr.state["vessels"][M]["voyage"]["origin_port"],"PAKNING")
