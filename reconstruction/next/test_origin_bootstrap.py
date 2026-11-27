import unittest
from legacy_tracker import Tracker
class Bootstrap(unittest.TestCase):
 def test_origin_without_fabricated_arrival(self):
  t=Tracker()
  def p(minute,candidate=True):
   stamp=f"2026-11-26T01:{minute:02d}:00+00:00"
   return dict(mmsi="525003298",ts=stamp,received=stamp,sog=0 if candidate else 7,cog=180,distance=.05 if candidate else .3,port="BENGKALIS",berth="BKL-02",candidate=candidate,ambiguous=False)
  for minute in (0,2,4): self.assertEqual(t.process(p(minute)),[])
  self.assertEqual(t.state["vessels"]["525003298"]["status"],"BERTHED")
  e=t.process(p(6,False))
  self.assertEqual([x["phase"] for x in e],["D0"])
  self.assertEqual(e[0]["features"]["destination_port"],"PAKNING")
if __name__=="__main__":unittest.main()
