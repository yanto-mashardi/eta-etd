import unittest,tempfile
from pathlib import Path
from datetime import datetime,timezone,timedelta
from zoneinfo import ZoneInfo
from stockflow import Ledger
class StockTests(unittest.TestCase):
 def setUp(self):
    self.tmp=tempfile.TemporaryDirectory();self.l=Ledger(Path(self.tmp.name)/"stock.sqlite")
    self.now=datetime.now(timezone.utc)
    self.today=self.now.astimezone(ZoneInfo("Asia/Jakarta")).date()
    self.yesterday=self.today-timedelta(days=1)
    self.l.set_opening("bengkalis",str(self.yesterday)+"T23:50:00+07:00",10,20,100,200)
 def tearDown(self):self.tmp.cleanup()
 def add(self,d,t,c,m):
    self.l.arrival("bengkalis",dict(tanggal=d,jam=t,jumlah_mobil=c,jumlah_motor=m),self.now)
 def test_rollover_and_departure(self):
    self.add(str(self.yesterday),"23:55:00",105,207)
    eid=self.l.departure("bengkalis","525002060",str(self.yesterday)+"T23:56:00+07:00")
    self.l.departure("bengkalis","525002060",str(self.yesterday)+"T23:56:00+07:00")
    self.l.set_load(eid,8,12,"ACTUAL")
    self.add(str(self.today),"00:00:00",0,0)
    self.add(str(self.today),"00:00:01",3,4)
    self.add(str(self.today),"00:05:00",3,4)
    x=self.l.snapshot("bengkalis")
    self.assertEqual((x["queue_car"],x["queue_motor"]),(10,19))
    self.assertEqual(x["outflow_car"],8)
 def test_unknown_load(self):
    self.add(str(self.yesterday),"23:55:00",105,207)
    self.l.departure("bengkalis","525002060",str(self.yesterday)+"T23:56:00+07:00")
    self.assertIsNone(self.l.snapshot("bengkalis")["queue_car"])
 def test_late_snapshot_and_conflict(self):
    self.add(str(self.yesterday),"23:59:00",105,207)
    self.add(str(self.yesterday),"23:55:00",103,205)
    with self.assertRaises(ValueError):self.add(str(self.yesterday),"23:56:00",102,206)
    self.assertEqual(self.l.snapshot("bengkalis")["inflow_car"],5)
 def test_estimated(self):
    self.add(str(self.yesterday),"23:55:00",105,207)
    eid=self.l.departure("bengkalis","525002060",str(self.yesterday)+"T23:56:00+07:00")
    self.l.set_load(eid,8,12,"ESTIMATED")
    self.add(str(self.today),"00:00:00",0,0)
    self.assertEqual(self.l.snapshot("bengkalis")["status"],"RECONSTRUCTED")
if __name__=="__main__":unittest.main()
