import unittest,tempfile
from pathlib import Path
from datetime import datetime,timezone,timedelta
from stockflow import Ledger,WIB
from yolo_publishers import configure,credentials,ingest,status
from fastapi import HTTPException
class PublisherTests(unittest.TestCase):
 def test_handover(self):
  with tempfile.TemporaryDirectory() as d:
   l=Ledger(Path(d)/"ledger.sqlite");now=datetime.now(timezone.utc);local=now.astimezone(WIB)
   day=local.date().isoformat()
   l.arrival("bengkalis",dict(tanggal=day,jam=local.strftime("%H:%M:%S.%f"),jumlah_mobil=10,jumlah_motor=20),now)
   configure(l,"bengkalis","PC1",True,0,0)
   t=credentials(l,"bengkalis")["token"]
   n=datetime.now(timezone.utc)+timedelta(seconds=1)
   def body(device,c,m,n):
    x=n.astimezone(WIB);return {"mode":"OBSERVED","device":device,"state":dict(tanggal=x.date().isoformat(),jam=x.strftime("%H:%M:%S.%f"),jumlah_mobil=c,jumlah_motor=m)}
   x=ingest(l,"bengkalis",body("PC1",2,3,n),"Bearer "+t,n)
   self.assertEqual((x["official_car"],x["official_motor"]),(12,23))
   self.assertEqual(ingest(l,"bengkalis",body("PC1",2,3,n),"Bearer "+t,n),x)
   with self.assertRaises(HTTPException):ingest(l,"pakning",body("PC1",2,3,n),"Bearer "+t,n)
   configure(l,"bengkalis","PC2",True,100,100)
   new=credentials(l,"bengkalis")["token"]
   n+=timedelta(seconds=1)
   with self.assertRaises(HTTPException):ingest(l,"bengkalis",body("PC1",3,4,n),"Bearer "+t,n)
   x=ingest(l,"bengkalis",body("PC2",101,102,n),"Bearer "+new,n)
   self.assertEqual((x["official_car"],x["official_motor"]),(13,25))
