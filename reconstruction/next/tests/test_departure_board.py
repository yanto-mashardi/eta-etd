import unittest
from evaluation import operational_boards
class DepartureBoardTest(unittest.TestCase):
 def test_round_trip(self):
  def t(h,m):return f"2026-11-26T{h:02d}:{m:02d}:00+00:00"
  m="525003298"
  r=dict(mmsi=m,trip_id="out",origin_port="BENGKALIS",destination_port="PAKNING",D0_utc=t(1,0),status="SAILING",eta_corrected=t(1,30),etd_early=t(2,15),early_published_at=t(1,1))
  prev=dict(mmsi=m,trip_id="prev",destination_port="BENGKALIS",status="COMPLETED_QC_PASS",etd_real=t(1,0),etd_early=t(1,2),early_published_at=t(0,0),departure_berth="BKL-01")
  def boards():return operational_boards([prev,r],{m:r},{m:{"status":r["status"]}})
  b=boards();self.assertEqual(len(b["departures"]),2)
  self.assertEqual([(x["board_port"],x["board_color"]) for x in b["departures"]],[("BENGKALIS","actual"),("PAKNING","incoming")])
  self.assertEqual(b["arrivals"][0]["board_color"],"incoming")
  r.update(status="BERTHED",ATA=t(1,35),etd_arrival=t(2,0),arrival_published_at=t(1,40))
  b=boards();self.assertEqual(len(b["departures"]),1);self.assertEqual(b["departures"][0]["board_port"],"PAKNING");self.assertEqual(b["departures"][0]["board_color"],"berthed");self.assertEqual(b["arrivals"][0]["board_color"],"late")
  r.update(status="COMPLETED_QC_PASS",etd_real=t(2,5),early_error_min=10,arrival_error_min=-5)
  back=dict(mmsi=m,trip_id="back",origin_port="PAKNING",destination_port="BENGKALIS",D0_utc=t(2,5),status="SAILING",eta_corrected=t(2,50),etd_early=t(3,30),early_published_at=t(2,6))
  b=operational_boards([prev,r,back],{m:back},{m:{"status":"SAILING"}})
  self.assertEqual(len(b["arrivals"]),1);self.assertEqual(b["arrivals"][0]["board_port"],"BENGKALIS")
  self.assertEqual(next(x for x in b["departures"] if x["board_port"]=="PAKNING")["board_color"],"late")
  back.update(status="BERTHED",ATA=t(2,45),etd_arrival=t(3,25))
  b=operational_boards([prev,r,back],{m:back},{m:{"status":"BERTHED"}})
  self.assertEqual(len(b["departures"]),1);self.assertEqual(b["departures"][0]["board_port"],"BENGKALIS");self.assertEqual(b["arrivals"][0]["board_color"],"actual")
 def test_no_prior_and_stale(self):
  r=dict(mmsi="x",trip_id="x",origin_port="PAKNING",destination_port="BENGKALIS",D0_utc="2026-11-26T01:00:00+00:00",status="SAILING")
  b=operational_boards([r],{"x":r},{"x":{"status":"STALE"}})
  self.assertEqual(next(x for x in b["departures"] if x["board_kind"]=="REAL")["board_color"],"unknown")
  self.assertTrue(all(x["ais_quality"]=="STALE" for x in b["departures"]))

 def test_all_four_tables_and_exact_source(self):
  def t(h,m):return f"2026-11-26T{h:02d}:{m:02d}:00+07:00"
  m="525003298"
  prior=dict(mmsi=m,trip_id="prior",destination_port="BENGKALIS",status="COMPLETED_QC_PASS",etd_real=t(8,0),etd_early=t(8,0),etd_arrival=t(8,1),early_published_at=t(6,0),arrival_published_at=t(7,0))
  out=dict(mmsi=m,trip_id="out",origin_port="BENGKALIS",destination_port="PAKNING",D0_utc=t(8,0),status="SAILING",eta_corrected=t(8,30),etd_early=t(9,15),early_published_at=t(8,1))
  def projection(r):
   b=operational_boards([prior,out,r],{m:r},{m:{"status":r["status"]}})
   return {(k,x["board_port"]):(x["board_time"],x["board_color"]) for k,rows in b.items() for x in rows}
  self.assertEqual(projection(out),{("departures","BENGKALIS"):(t(8,0),"actual"),("arrivals","PAKNING"):(t(8,30),"incoming"),("departures","PAKNING"):(t(9,15),"incoming")})
  out.update(status="BERTHED",ATA=t(8,35),etd_arrival=t(9,0),arrival_published_at=t(8,40))
  self.assertEqual(projection(out),{("arrivals","PAKNING"):(t(8,35),"late"),("departures","PAKNING"):(t(9,0),"berthed")})
  out.update(status="COMPLETED_QC_PASS",etd_real=t(9,5))
  back=dict(mmsi=m,trip_id="back",origin_port="PAKNING",destination_port="BENGKALIS",D0_utc=t(9,5),status="SAILING",eta_corrected=t(9,50),etd_early=t(10,30),early_published_at=t(9,6))
  self.assertEqual(projection(back),{("departures","PAKNING"):(t(9,5),"late"),("arrivals","BENGKALIS"):(t(9,50),"incoming"),("departures","BENGKALIS"):(t(10,30),"incoming")})
  back.update(status="BERTHED",ATA=t(9,45),etd_arrival=t(10,25))
  self.assertEqual(projection(back),{("arrivals","BENGKALIS"):(t(9,45),"actual"),("departures","BENGKALIS"):(t(10,25),"berthed")})
